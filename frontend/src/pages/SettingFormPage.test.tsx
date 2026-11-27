import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { SettingsData } from "../api/types";
import type { ProfileProposal, SettingPreview } from "../api/writes";
import { json, SESSION } from "../test/fetch";
import { CLASS_NAMES } from "../test/pages";
import { renderApp } from "../test/render";
import { tableState } from "../test/tables";
import { CONFIRMATION, recorded } from "../test/writes";

const VALUES = {
  payday: 15,
  monthly_contribution: "5000",
  targets: { hisse: "0.625", altin: "0.375" },
};

function settings(overrides: Partial<SettingsData> = {}): SettingsData {
  return {
    table: tableState([]),
    current: VALUES,
    current_id: 2,
    current_from: "2026-10-01",
    planned: [],
    classes: ["hisse", "altin"],
    class_names: CLASS_NAMES,
    ...overrides,
  };
}

function proposal(overrides: Partial<ProfileProposal> = {}): ProfileProposal {
  return {
    profile: "gercek",
    problem: null,
    version: null,
    base: null,
    changed_fields: ["monthly_contribution"],
    changes: [{ setting: "Aylık katkı", change: "5.000,00 TL → 6.000,00 TL" }],
    issues: [],
    later: [],
    ready: true,
    ...overrides,
  };
}

function preview(overrides: Partial<SettingPreview> = {}): SettingPreview {
  return {
    day: "2026-12-01",
    plans: [proposal()],
    carry_option: false,
    carry: false,
    confirmation: CONFIRMATION,
    changed: false,
    ...overrides,
  };
}

const LATER = {
  id: 5,
  effective_from: "2027-01-01",
  fields: ["monthly_contribution" as const],
  kept: "aylık katkı 4.000,00 TL",
  carried: [{ setting: "Aylık katkı", change: "6.000,00 TL" }],
};

function open(profile: "gercek" | "sanal", extra = {}, data = settings()) {
  return renderApp(`/${profile}/ayarlar/yeni`, {
    "GET /api/oturum": () => json(SESSION),
    [`GET /api/${profile}/ayarlar`]: () => json(data),
    ...extra,
  });
}

describe("yeni ayar sürümü", () => {
  it("bugünkü ayarla dolar; hedef toplamı canlı hesaplanır, tam %100 değilse önizlenmez", async () => {
    const { user } = open("gercek");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Yeni ayar sürümü" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Yürürlük günü")).toHaveValue("2026-11-26");
    expect(screen.getByLabelText("Maaş günü")).toHaveValue("15");
    expect(screen.getByLabelText("Aylık katkı")).toHaveValue("5000");
    expect(screen.getByLabelText("Hisse")).toHaveValue("62,5");
    expect(screen.getByLabelText("Altın")).toHaveValue("37,5");
    expect(screen.getByText("Toplam %100")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Önizle" })).toBeEnabled();

    await user.clear(screen.getByLabelText("Hisse"));
    await user.type(screen.getByLabelText("Hisse"), "60");
    expect(screen.getByText("Toplam %97,5 · %2,5 eksik")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Önizle" })).toBeDisabled();

    await user.clear(screen.getByLabelText("Hisse"));
    await user.type(screen.getByLabelText("Hisse"), "abc");
    expect(
      screen.getByText("Toplam hesaplanamadı: her alan virgüllü bir sayı olmalı (ör. 17,5)."),
    ).toBeInTheDocument();
  });

  it("sanala da uygulanınca iki portföyün planını gösterir, taşıma seçimiyle yeniden önizler", async () => {
    const onizle = recorded(
      () =>
        json(
          preview({
            plans: [proposal({ later: [LATER] }), proposal({ profile: "sanal" })],
            carry_option: true,
          }),
        ),
      () =>
        json(
          preview({
            plans: [proposal({ later: [LATER] }), proposal({ profile: "sanal" })],
            carry_option: true,
            carry: true,
          }),
        ),
    );
    const { user } = open("gercek", { "POST /api/gercek/ayarlar/onizle": onizle });

    await user.clear(await screen.findByLabelText("Aylık katkı"));
    await user.type(screen.getByLabelText("Aylık katkı"), "6000");
    await user.click(screen.getByLabelText("Sanal portföye de uygula"));
    await user.click(screen.getByRole("button", { name: "Önizle" }));

    expect(
      await screen.findByRole("heading", { level: 1, name: "Ayar sürümünü kontrol et" }),
    ).toBeInTheDocument();
    expect(onizle.bodies[0]).toEqual({
      day: "2026-11-26",
      payday: "15",
      contribution: "6000",
      targets: { hisse: "62,5", altin: "37,5" },
      also_sanal: true,
      carry: false,
    });
    expect(screen.getByText(/Yürürlük: 1 Aralık'tan itibaren\./)).toBeInTheDocument();
    const real = within(screen.getByRole("region", { name: "Gerçek portföy" }));
    expect(real.getByText(/portföye kaydedilecek/)).toHaveTextContent(
      "GERÇEK portföye kaydedilecek.",
    );
    expect(real.getByText("Aylık katkı").nextElementSibling).toHaveTextContent(
      "5.000,00 TL → 6.000,00 TL",
    );
    expect(
      real.getByText(
        "Yürürlüğü 1 Ocak 2027 olan planlanan sürüm (#5) bu değişikliği taşımıyor; o günden itibaren aylık katkı 4.000,00 TL olur.",
      ),
    ).toBeInTheDocument();
    const sanal = within(screen.getByRole("region", { name: "Sanal portföy" }));
    expect(sanal.getByText(/portföye kaydedilecek/)).toHaveTextContent(
      "SANAL portföye kaydedilecek. Gerçek alım değil.",
    );
    expect(
      within(screen.getByRole("list", { name: "Sonraki planlanan sürümler" })).getByRole(
        "listitem",
      ),
    ).toHaveTextContent("Gerçek #5 · 1 Ocak 2027'den itibaren: Aylık katkı 6.000,00 TL");

    await user.click(screen.getByLabelText("Sonraki planlanan sürümlere de uygula"));

    expect(
      await screen.findByText(
        "Yürürlüğü 1 Ocak 2027 olan planlanan sürüm (#5) bu değişikliği taşımıyordu; kaydedilince ona da taşınacak.",
      ),
    ).toBeInTheDocument();
    expect(onizle.bodies[1]).toEqual(expect.objectContaining({ carry: true, also_sanal: true }));
    expect(screen.getByRole("button", { name: "İki portföye de kaydet" })).toBeInTheDocument();
  });

  it("her portföyün sonucunu ayrı gösterir; sanal meşgulse aynı onayla yeniden dener", async () => {
    const kaydet = recorded(
      () =>
        json({
          outcomes: [
            {
              profile: "gercek",
              status: "saved",
              setting_id: 7,
              rewritten: [{ cancelled: 5, written: 8 }],
              message: "",
            },
            { profile: "sanal", status: "busy", setting_id: null, rewritten: [], message: "" },
          ],
        }),
      () =>
        json({
          outcomes: [
            { profile: "gercek", status: "duplicate", setting_id: 7, rewritten: [], message: "" },
            { profile: "sanal", status: "saved", setting_id: 4, rewritten: [], message: "" },
          ],
        }),
    );
    const { user } = open("gercek", {
      "POST /api/gercek/ayarlar/onizle": () =>
        json(preview({ plans: [proposal(), proposal({ profile: "sanal" })] })),
      "POST /api/gercek/ayarlar/kaydet": kaydet,
    });
    await user.click(await screen.findByRole("button", { name: "Önizle" }));
    await user.click(await screen.findByRole("button", { name: "İki portföye de kaydet" }));

    expect(
      await screen.findByRole("heading", { level: 1, name: "Ayar sürümü sonucu" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/ayar sürümü #7 kaydedildi\./)).toHaveTextContent(
      "Gerçek: ayar sürümü #7 kaydedildi.",
    );
    expect(screen.getByText("Sonraki sürüme taşındı: #5 yerine #8.")).toBeInTheDocument();
    expect(screen.getByText(/Şu an zamanlanmış bir iş çalışıyor/)).toHaveTextContent(
      "Sanal: yazılmadı. Şu an zamanlanmış bir iş çalışıyor.",
    );
    await user.click(screen.getByRole("button", { name: "Yeniden dene" }));

    await waitFor(() =>
      expect(screen.getByText(/bu onay zaten kullanılmıştı/)).toHaveTextContent(
        "Gerçek: bu onay zaten kullanılmıştı; ayar sürümü #7 olarak kayıtlı.",
      ),
    );
    expect(screen.getByText(/ayar sürümü #4 kaydedildi\./)).toHaveTextContent(
      "Sanal: ayar sürümü #4 kaydedildi.",
    );
    expect(screen.queryByRole("button", { name: "Yeniden dene" })).not.toBeInTheDocument();
    expect(kaydet.bodies).toEqual([{ confirmation: CONFIRMATION }, { confirmation: CONFIRMATION }]);
    expect(screen.getByRole("link", { name: "Ayarlara dön" })).toHaveAttribute(
      "href",
      "/gercek/ayarlar",
    );
  });

  it("sonuç değiştiyse yeni önizlemeyi uyarıyla gösterir", async () => {
    const { user } = open("gercek", {
      "POST /api/gercek/ayarlar/onizle": () => json(preview()),
      "POST /api/gercek/ayarlar/kaydet": () => json(preview({ changed: true }), 409),
    });
    await user.click(await screen.findByRole("button", { name: "Önizle" }));
    await user.click(await screen.findByRole("button", { name: "Gerçek ayarı kaydet" }));

    expect(
      await screen.findByText("Önizlemeden sonra veriler değişti; kayıt yapılmadı."),
    ).toBeInTheDocument();
  });

  it("alan hatalarını alanların altında gösterir", async () => {
    const { user } = open("gercek", {
      "POST /api/gercek/ayarlar/onizle": () =>
        json(
          {
            error: "Girdi geçersiz.",
            fields: {
              payday: "Maaş günü 1 ile 31 arasında olmalı.",
              "targets.hisse": "Sayı olmalı.",
            },
          },
          422,
        ),
    });
    await user.click(await screen.findByRole("button", { name: "Önizle" }));

    expect(await screen.findByText("Maaş günü 1 ile 31 arasında olmalı.")).toBeInTheDocument();
    expect(screen.getByLabelText("Maaş günü")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("Hisse")).toHaveAttribute("aria-invalid", "true");
  });

  it("sanal profilde sanala da seçeneği yoktur; yazılamayan portföyde kayıt önerilmez", async () => {
    const { user } = open(
      "sanal",
      {
        "POST /api/sanal/ayarlar/onizle": () =>
          json(
            preview({
              plans: [
                proposal({ profile: "sanal", problem: "Başlangıç sürümü yok.", ready: false }),
              ],
              confirmation: null,
            }),
          ),
      },
      settings({ current: { payday: null, monthly_contribution: null, targets: {} } }),
    );

    expect(await screen.findByLabelText(/Maaş günü/)).toHaveValue("");
    expect(screen.getByLabelText(/Maaş günü \(isteğe bağlı\)/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Sanal portföye de uygula")).not.toBeInTheDocument();
    await user.clear(screen.getByLabelText("Hisse"));
    await user.type(screen.getByLabelText("Hisse"), "100");
    await user.click(screen.getByRole("button", { name: "Önizle" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Bu portföye yazılamaz. Başlangıç sürümü yok.",
    );
    expect(screen.queryByRole("button", { name: /kaydet/ })).not.toBeInTheDocument();
  });
});
