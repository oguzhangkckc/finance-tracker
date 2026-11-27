import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { VoidTarget } from "../api/writes";
import { json } from "../test/fetch";
import { renderApp } from "../test/render";
import { baseRoutes, CONFIRMATION, recorded } from "../test/writes";

const TARGET: VoidTarget = {
  id: 3,
  instrument: "XHT",
  trade_date: "2026-11-20",
  side: "BUY",
  units: "100",
  unit_price: "12.5",
  fee: "0",
  external_ref: "D-1",
  note: null,
};

function voidPreview(reason: string, overrides = {}) {
  return {
    profile: "gercek",
    target: TARGET,
    reason,
    confirmation: CONFIRMATION,
    changed: false,
    ...overrides,
  };
}

const BLOCKED = {
  error: "Bu alım iptal edilemez.",
  fields: {},
  blocking: [{ id: 5, instrument: "XHT", trade_date: "2026-11-22", units: "40" }],
};

describe("işlem iptali", () => {
  it("gerekçeyle önizler, GERÇEK kutusunu gösterir, kaydeder ve listeye döner", async () => {
    const preview = recorded(() => json(voidPreview("yanlış adet")));
    const save = recorded(() => json({ number: 3, duplicate: false }));
    const { user, router } = renderApp("/gercek/islemler/3/iptal", {
      ...baseRoutes("gercek"),
      "GET /api/gercek/islemler/3/iptal": () => json(TARGET),
      "POST /api/gercek/islemler/3/iptal/onizle": preview,
      "POST /api/gercek/islemler/3/iptal/kaydet": save,
    });

    expect(
      await screen.findByRole("heading", { level: 1, name: "İşlem #3 iptali" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Dekont no").nextElementSibling).toHaveTextContent("D-1");
    await user.type(screen.getByLabelText("Gerekçe"), "yanlış adet");
    await user.click(screen.getByRole("button", { name: "Önizle" }));

    expect(await screen.findByText(/portföye kaydedilecek/)).toHaveTextContent(
      "GERÇEK portföye kaydedilecek.",
    );
    expect(preview.bodies).toEqual([{ reason: "yanlış adet" }]);
    expect(screen.getByText("Gerekçe").nextElementSibling).toHaveTextContent("yanlış adet");
    await user.click(screen.getByRole("button", { name: "İptali kaydet" }));

    expect(await screen.findByText("#3 numaralı işlem iptal edildi.")).toBeInTheDocument();
    expect(save.bodies).toEqual([{ confirmation: CONFIRMATION }]);
    expect(router.state.location.pathname).toBe("/gercek/islemler");
  });

  it("sonraki satışlar engelliyorsa önce onları iptal etmeyi önerir", async () => {
    renderApp("/gercek/islemler/3/iptal", {
      ...baseRoutes("gercek"),
      "GET /api/gercek/islemler/3/iptal": () => json(BLOCKED, 422),
    });

    expect(await screen.findByText("Bu işlem şimdi iptal edilemez.")).toBeInTheDocument();
    const sales = within(screen.getByRole("list", { name: "Önce iptal edilecek satışlar" }));
    expect(sales.getByRole("listitem")).toHaveTextContent("#5 · 22 Kasım · XHT · 40 pay");
    expect(sales.getByRole("link", { name: "#5" })).toHaveAttribute(
      "href",
      "/gercek/islemler/5/iptal",
    );
    expect(screen.getByRole("link", { name: "İşlemlere dön" })).toHaveAttribute(
      "href",
      "/gercek/islemler",
    );
  });

  it("sonuç değiştiyse yeni önizlemeyi uyarıyla gösterir; aynı onay tekrarlanırsa söyler", async () => {
    const save = recorded(
      () => json(voidPreview("yanlış adet", { changed: true }), 409),
      () => json({ number: 3, duplicate: true }),
    );
    const { user } = renderApp("/gercek/islemler/3/iptal", {
      ...baseRoutes("gercek"),
      "GET /api/gercek/islemler/3/iptal": () => json(TARGET),
      "POST /api/gercek/islemler/3/iptal/onizle": () => json(voidPreview("yanlış adet")),
      "POST /api/gercek/islemler/3/iptal/kaydet": save,
    });
    await user.type(await screen.findByLabelText("Gerekçe"), "yanlış adet");
    await user.click(screen.getByRole("button", { name: "Önizle" }));
    await user.click(await screen.findByRole("button", { name: "İptali kaydet" }));

    expect(
      await screen.findByText("Önizlemeden sonra veriler değişti; kayıt yapılmadı."),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "İptali kaydet" }));
    expect(
      await screen.findByText("Bu onay zaten kullanıldı; #3 numaralı işlem iptal edildi."),
    ).toBeInTheDocument();
  });

  it("kayıtta engelleyen satış çıkarsa engel ekranına geçer", async () => {
    const { user } = renderApp("/gercek/islemler/3/iptal", {
      ...baseRoutes("gercek"),
      "GET /api/gercek/islemler/3/iptal": () => json(TARGET),
      "POST /api/gercek/islemler/3/iptal/onizle": () => json(voidPreview("yanlış adet")),
      "POST /api/gercek/islemler/3/iptal/kaydet": () => json(BLOCKED, 422),
    });
    await user.type(await screen.findByLabelText("Gerekçe"), "yanlış adet");
    await user.click(screen.getByRole("button", { name: "Önizle" }));
    await user.click(await screen.findByRole("button", { name: "İptali kaydet" }));

    expect(await screen.findByText("Bu işlem şimdi iptal edilemez.")).toBeInTheDocument();
  });

  it("gerekçe hatasını alanın altında gösterir", async () => {
    const { user } = renderApp("/gercek/islemler/3/iptal", {
      ...baseRoutes("gercek"),
      "GET /api/gercek/islemler/3/iptal": () => json(TARGET),
      "POST /api/gercek/islemler/3/iptal/onizle": () =>
        json({ error: "Girdi geçersiz.", fields: { reason: "Gerekçe boş olamaz." } }, 422),
    });
    await user.click(await screen.findByRole("button", { name: "Önizle" }));

    expect(await screen.findByText("Gerekçe boş olamaz.")).toBeInTheDocument();
    expect(screen.getByLabelText("Gerekçe")).toHaveAttribute("aria-invalid", "true");
  });

  it("numara geçersizse bulunamadı, işlem yoksa nedeni gösterilir", async () => {
    const { unmount } = renderApp("/gercek/islemler/abc/iptal", baseRoutes("gercek"));
    expect(await screen.findByRole("heading", { name: "Sayfa bulunamadı" })).toBeInTheDocument();
    unmount();

    renderApp("/gercek/islemler/99/iptal", baseRoutes("gercek"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Bulunamadı.");
  });
});
