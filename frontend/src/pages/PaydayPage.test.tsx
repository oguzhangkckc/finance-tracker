import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { PaydayLine, PaydayPlan } from "../api/writes";
import { json } from "../test/fetch";
import { renderApp } from "../test/render";
import { baseRoutes, CONFIRMATION, recorded } from "../test/writes";

function line(overrides: Partial<PaydayLine>): PaydayLine {
  return {
    asset_class: "hisse",
    class_name: "Hisse",
    instrument: "XHT",
    amount: "3000",
    status: "ready",
    price_day: "2026-11-17",
    price: "12.5",
    units: "239",
    spent: "2987.5",
    leftover: "12.5",
    reason: null,
    ...overrides,
  };
}

function plan(overrides: Partial<PaydayPlan> = {}): PaydayPlan {
  return {
    profile: "sanal",
    payday: "2026-11-15",
    reapply_voided: false,
    window_end: "2026-11-22",
    retry_after: "2026-11-18",
    missing_prices: [],
    lines: [
      line({}),
      line({ instrument: "XAC", asset_class: "altin", class_name: "Altın", status: "pending" }),
      line({ instrument: "XPP", status: "skipped", reason: "fon kapalı" }),
    ],
    ready: 1,
    confirmation: CONFIRMATION,
    changed: false,
    ...overrides,
  };
}

function routes(initial: PaydayPlan, extra = {}) {
  return { ...baseRoutes("sanal"), "GET /api/sanal/maas-gunu": () => json(initial), ...extra };
}

describe("maaş günü planı", () => {
  it("gerçek profilde yoktur ve sunucuya sorulmaz", async () => {
    const { fetch } = renderApp("/gercek/maas-gunu", baseRoutes("gercek"));

    expect(await screen.findByRole("heading", { name: "Sayfa bulunamadı" })).toBeInTheDocument();
    const asked = fetch.mock.calls.map(([request]) => new URL(request.url).pathname);
    expect(asked.some((path) => path.includes("maas-gunu"))).toBe(false);
  });

  it("planı satır durumlarıyla gösterir, SANAL kutusuyla uygular ve listeye döner", async () => {
    const save = recorded(() => json({ number: 1, duplicate: false }));
    const { user, router } = renderApp(
      "/sanal/maas-gunu",
      routes(plan(), { "POST /api/sanal/maas-gunu/kaydet": save }),
    );

    expect(
      await screen.findByRole("heading", { level: 2, name: "15 Kasım planı" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Fiyat penceresi 22 Kasım'da biter.")).toBeInTheDocument();
    const lines = within(screen.getByRole("list", { name: "Plan" })).getAllByRole("listitem");
    expect(lines[0]).toHaveTextContent(
      "XHT Hisse3.000,00 TL17 Kasım fiyatıyla 239 pay × 12,5 TL = 2.987,50 TL; artan 12,50 TL.",
    );
    expect(lines[1]).toHaveTextContent(
      "Fiyat henüz açıklanmadı; 18 Kasım tarihinden sonra tekrar bak.",
    );
    expect(lines[2]).toHaveTextContent("İşlem yapılmadı: fon kapalı");
    expect(screen.getByText(/portföye kaydedilecek/)).toHaveTextContent(
      "SANAL portföye kaydedilecek. Gerçek alım değil.",
    );

    await user.click(screen.getByRole("button", { name: "Planı uygula (1 alım)" }));

    expect(await screen.findByText("Maaş günü planı uygulandı: 1 sanal alım.")).toBeInTheDocument();
    expect(save.bodies).toEqual([{ confirmation: CONFIRMATION }]);
    expect(router.state.location.pathname).toBe("/sanal/islemler");
  });

  it("başka bir maaş günü ve iptal edilenlerle yeniden planlar", async () => {
    const preview = recorded(() =>
      json(
        plan({ payday: "2026-10-15", reapply_voided: true, lines: [line({ status: "voided" })] }),
      ),
    );
    const { user } = renderApp(
      "/sanal/maas-gunu",
      routes(plan(), { "POST /api/sanal/maas-gunu/onizle": preview }),
    );

    const date = await screen.findByLabelText("Maaş günü");
    expect(date).toHaveValue("2026-11-15");
    await user.clear(date);
    await user.type(date, "2026-10-15");
    await user.click(screen.getByLabelText("İptal ettiğim maaş günü alımlarını da yeniden öner"));
    await user.click(screen.getByRole("button", { name: "Planı göster" }));

    expect(
      await screen.findByRole("heading", { level: 2, name: "15 Ekim planı" }),
    ).toBeInTheDocument();
    expect(preview.bodies).toEqual([{ payday: "2026-10-15", reapply_voided: true }]);
    expect(screen.getByText(/İptal edilmiş bir alımı var/)).toBeInTheDocument();
  });

  it("fiyat eksikse planı hesaplamaz; uygulanacak alım yoksa bunu söyler", async () => {
    const { unmount } = renderApp(
      "/sanal/maas-gunu",
      routes(plan({ missing_prices: ["XAC"], confirmation: null })),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Plan hesaplanmadı: XAC için maaş gününde fiyat yok. Hiçbir işlem yapılmadı.",
    );
    expect(screen.queryByRole("button", { name: /Planı uygula/ })).not.toBeInTheDocument();
    unmount();

    renderApp(
      "/sanal/maas-gunu",
      routes(plan({ confirmation: null, ready: 0, lines: [line({ status: "applied" })] })),
    );
    expect(await screen.findByText("Uygulanacak alım yok.")).toBeInTheDocument();
    expect(screen.getByText("Zaten uygulandı.")).toBeInTheDocument();
    expect(screen.queryByText(/portföye kaydedilecek/)).not.toBeInTheDocument();
  });

  it("sonuç değiştiyse yeni planı uyarıyla gösterir", async () => {
    const { user } = renderApp(
      "/sanal/maas-gunu",
      routes(plan(), {
        "POST /api/sanal/maas-gunu/kaydet": () => json(plan({ ready: 2, changed: true }), 409),
      }),
    );
    await user.click(await screen.findByRole("button", { name: "Planı uygula (1 alım)" }));

    expect(
      await screen.findByText("Önizlemeden sonra veriler değişti; kayıt yapılmadı."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Planı uygula (2 alım)" })).toBeInTheDocument();
  });
});
