import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { SettingItem } from "../api/types";
import { json, SESSION } from "../test/fetch";
import { CLASS_NAMES } from "../test/pages";
import { renderApp } from "../test/render";
import { tableState } from "../test/tables";
import { CONFIRMATION, recorded } from "../test/writes";

const ITEM: SettingItem = {
  id: 3,
  recorded_at: "2026-11-01T07:00:00Z",
  source: "web",
  source_label: "web",
  effective_from: "2026-12-01",
  initial: false,
  values: { payday: 15, monthly_contribution: "6000", targets: {} },
  state: "planned",
  state_label: "planlandı",
  cancelled_at: null,
  cancel_reason: null,
  changes: [{ setting: "Aylık katkı", change: "5.000,00 TL → 6.000,00 TL" }],
};

function cancelPreview(overrides = {}) {
  return {
    profile: "gercek",
    target: ITEM,
    reason: "plan değişti",
    confirmation: CONFIRMATION,
    changed: false,
    ...overrides,
  };
}

function routes(extra = {}) {
  return {
    "GET /api/oturum": () => json(SESSION),
    "GET /api/gercek/ayarlar/3/vazgec": () => json(ITEM),
    "GET /api/gercek/ayarlar": () =>
      json({
        table: tableState([]),
        current: ITEM.values,
        current_id: 2,
        current_from: null,
        planned: [],
        classes: [],
        class_names: CLASS_NAMES,
      }),
    ...extra,
  };
}

describe("ayar sürümünden vazgeçme", () => {
  it("gerekçeyle önizler, GERÇEK kutusunu gösterir, kaydeder ve ayarlara döner", async () => {
    const onizle = recorded(() => json(cancelPreview()));
    const kaydet = recorded(() => json({ number: 3, duplicate: false }));
    const { user, router } = renderApp(
      "/gercek/ayarlar/3/vazgec",
      routes({
        "POST /api/gercek/ayarlar/3/vazgec/onizle": onizle,
        "POST /api/gercek/ayarlar/3/vazgec/kaydet": kaydet,
      }),
    );

    expect(
      await screen.findByRole("heading", { level: 1, name: "Ayar sürümü #3: vazgeç" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Yürürlük").nextElementSibling).toHaveTextContent(
      "1 Aralık'tan itibaren",
    );
    expect(screen.getByText("Aylık katkı").nextElementSibling).toHaveTextContent(
      "5.000,00 TL → 6.000,00 TL",
    );
    await user.type(screen.getByLabelText("Gerekçe"), "plan değişti");
    await user.click(screen.getByRole("button", { name: "Önizle" }));

    expect(await screen.findByText(/portföye kaydedilecek/)).toHaveTextContent(
      "GERÇEK portföye kaydedilecek.",
    );
    expect(onizle.bodies).toEqual([{ reason: "plan değişti" }]);
    await user.click(screen.getByRole("button", { name: "Vazgeçmeyi kaydet" }));

    expect(await screen.findByText("Ayar sürümü #3 için vazgeçildi.")).toBeInTheDocument();
    expect(kaydet.bodies).toEqual([{ confirmation: CONFIRMATION }]);
    expect(router.state.location.pathname).toBe("/gercek/ayarlar");
  });

  it("yürürlükteki sürümden vazgeçilemeyeceğini söyler", async () => {
    renderApp(
      "/gercek/ayarlar/3/vazgec",
      routes({
        "GET /api/gercek/ayarlar/3/vazgec": () =>
          json({ error: "Yürürlükteki sürümden vazgeçilemez." }, 422),
      }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Yürürlükteki sürümden vazgeçilemez.",
    );
  });

  it("sonuç değiştiyse yeni önizlemeyi uyarıyla gösterir; tekrar onayda bunu söyler", async () => {
    const { user } = renderApp(
      "/gercek/ayarlar/3/vazgec",
      routes({
        "POST /api/gercek/ayarlar/3/vazgec/onizle": () => json(cancelPreview()),
        "POST /api/gercek/ayarlar/3/vazgec/kaydet": recorded(
          () => json(cancelPreview({ changed: true }), 409),
          () => json({ number: 3, duplicate: true }),
        ),
      }),
    );
    await user.type(await screen.findByLabelText("Gerekçe"), "plan değişti");
    await user.click(screen.getByRole("button", { name: "Önizle" }));
    await user.click(await screen.findByRole("button", { name: "Vazgeçmeyi kaydet" }));

    expect(
      await screen.findByText("Önizlemeden sonra veriler değişti; kayıt yapılmadı."),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Vazgeçmeyi kaydet" }));
    expect(
      await screen.findByText("Bu onay zaten kullanıldı; ayar sürümü #3 için vazgeçildi."),
    ).toBeInTheDocument();
  });

  it("numara geçersizse bulunamadı sayfasıdır", async () => {
    renderApp("/gercek/ayarlar/x/vazgec", routes());

    expect(await screen.findByRole("heading", { name: "Sayfa bulunamadı" })).toBeInTheDocument();
  });
});
