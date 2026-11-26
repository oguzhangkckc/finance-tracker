import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { json } from "../test/fetch";
import { renderApp } from "../test/render";
import { baseRoutes, CONFIRMATION, recorded, tradePreview } from "../test/writes";

const PREVIEW = "POST /api/gercek/islemler/alis/onizle";
const SAVE = "POST /api/gercek/islemler/kaydet";

function summary(): string[] {
  return screen
    .getAllByRole("definition")
    .map((item) => `${item.previousElementSibling?.textContent}=${item.textContent}`);
}

async function fillRealBuy(user: ReturnType<typeof renderApp>["user"]) {
  await screen.findByRole("option", { name: "XHT · Hisse Fonu" });
  await user.selectOptions(screen.getByLabelText("Fon"), "XHT");
  await user.type(screen.getByLabelText("Adet"), "100");
  await user.type(screen.getByLabelText("Birim fiyat"), "12,5");
  await user.type(screen.getByLabelText(/Dekont no/), "D-1");
  await user.click(screen.getByRole("button", { name: "Önizle" }));
}

describe("gerçek alım", () => {
  it("önizler, GERÇEK kutusunu gösterir, kaydeder ve listeye bildirimle döner", async () => {
    const preview = recorded(() =>
      json(tradePreview({ warnings: ["Girdiğin fiyat yayımlanandan %2 farklı."] })),
    );
    const save = recorded(() => json({ number: 12, duplicate: false }));
    const { user, router } = renderApp("/gercek/islemler/yeni/alis", {
      ...baseRoutes("gercek"),
      [PREVIEW]: preview,
      [SAVE]: save,
    });

    expect(await screen.findByRole("heading", { level: 1, name: "Alım ekle" })).toBeInTheDocument();
    expect(screen.getByText("Dekonttaki adet ve fiyatla.")).toBeInTheDocument();
    expect(screen.getByText("Bilgiler")).toHaveAttribute("aria-current", "step");
    expect(screen.getByLabelText("İşlem günü")).toHaveValue("2026-11-26");
    await fillRealBuy(user);

    expect(
      await screen.findByRole("heading", { level: 1, name: "Alımı kontrol et" }),
    ).toBeInTheDocument();
    expect(preview.bodies).toEqual([
      {
        fund: "XHT",
        day: "2026-11-26",
        units: "100",
        price: "12,5",
        fee: "",
        amount: "",
        ref: "D-1",
        all: false,
      },
    ]);
    expect(screen.getByText("Önizleme")).toHaveAttribute("aria-current", "step");
    expect(screen.getByText("Henüz bir şey kaydedilmedi.")).toBeInTheDocument();
    expect(screen.getByText(/portföye kaydedilecek/)).toHaveTextContent(
      "GERÇEK portföye kaydedilecek.",
    );
    expect(summary()).toEqual([
      "Fon=XHT · Hisse Fonu",
      "İşlem günü=20 Kasım",
      "Adet=100 pay",
      "Birim fiyat=12,5 TL",
      "Komisyon=0,00 TL",
      "Dekont no=D-1",
      "Tutar=1.250,00 TL",
      "XHT payın=0 → 100",
    ]);
    expect(screen.getByText(/Girdiğin fiyat yayımlanandan %2 farklı\./)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Gerçek alımı kaydet" }));

    expect(await screen.findByText("Alım #12 kaydedildi.")).toBeInTheDocument();
    expect(save.bodies).toEqual([{ confirmation: CONFIRMATION }]);
    expect(router.state.location.pathname).toBe("/gercek/islemler");
  });

  it("sonuç değiştiyse kaydetmez, yeni önizlemeyi uyarıyla gösterir", async () => {
    const changed = { ...CONFIRMATION, nonce: "n-2" };
    const save = recorded(
      () => json(tradePreview({ units: "90", confirmation: changed, changed: true }), 409),
      () => json({ number: 13, duplicate: false }),
    );
    const { user } = renderApp("/gercek/islemler/yeni/alis", {
      ...baseRoutes("gercek"),
      [PREVIEW]: () => json(tradePreview()),
      [SAVE]: save,
    });
    await fillRealBuy(user);
    await user.click(await screen.findByRole("button", { name: "Gerçek alımı kaydet" }));

    expect(
      await screen.findByText("Önizlemeden sonra veriler değişti; kayıt yapılmadı."),
    ).toBeInTheDocument();
    expect(summary()).toContain("Adet=90 pay");
    await user.click(screen.getByRole("button", { name: "Gerçek alımı kaydet" }));

    expect(await screen.findByText("Alım #13 kaydedildi.")).toBeInTheDocument();
    expect(save.bodies).toEqual([{ confirmation: CONFIRMATION }, { confirmation: changed }]);
  });

  it("aynı onay ikinci kez gelirse zaten kaydedildiğini söyler", async () => {
    const { user } = renderApp("/gercek/islemler/yeni/alis", {
      ...baseRoutes("gercek"),
      [PREVIEW]: () => json(tradePreview()),
      [SAVE]: () => json({ number: 12, duplicate: true }),
    });
    await fillRealBuy(user);
    await user.click(await screen.findByRole("button", { name: "Gerçek alımı kaydet" }));

    expect(
      await screen.findByText("Bu onay zaten kullanıldı; işlem #12 olarak kaydedildi."),
    ).toBeInTheDocument();
  });

  it("veritabanı meşgulse bekleme süresini söyler ve aynı onayla yeniden dener", async () => {
    const busy = "Şu an zamanlanmış bir iş çalışıyor; hiçbir şey kaydedilmedi.";
    const save = recorded(
      () => json({ error: busy }, 503, { "Retry-After": "5" }),
      () => json({ number: 12, duplicate: false }),
    );
    const { user, router } = renderApp("/gercek/islemler/yeni/alis", {
      ...baseRoutes("gercek"),
      [PREVIEW]: () => json(tradePreview()),
      [SAVE]: save,
    });
    await fillRealBuy(user);
    await user.click(await screen.findByRole("button", { name: "Gerçek alımı kaydet" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(busy);
    expect(alert).toHaveTextContent("5 saniye sonra yeniden deneyebilirsin.");
    await user.click(within(alert).getByRole("button", { name: "Yeniden dene" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/gercek/islemler"));
    expect(save.bodies).toEqual([{ confirmation: CONFIRMATION }, { confirmation: CONFIRMATION }]);
  });

  it("alan hatalarını alanların altında gösterir", async () => {
    const { user } = renderApp("/gercek/islemler/yeni/alis", {
      ...baseRoutes("gercek"),
      [PREVIEW]: () =>
        json(
          { error: "Girdi geçersiz.", fields: { units: "Adet sayı olmalı.", fund: "Fon seç." } },
          422,
        ),
    });
    await fillRealBuy(user);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Bir alan düzeltilmeli. Aşağıda işaretli.",
    );
    expect(screen.getByLabelText("Adet")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("Adet sayı olmalı.")).toBeInTheDocument();
    expect(screen.getByText("Fon seç.")).toBeInTheDocument();
    expect(screen.getByLabelText("Birim fiyat")).toHaveValue("12,5");
  });

  it("onayın süresi dolduysa nedenini söyler, yeniden deneme önermez", async () => {
    const expired = "Önizleme 10 dakikadan eski; onay süresi doldu, hiçbir şey kaydedilmedi.";
    const { user } = renderApp("/gercek/islemler/yeni/alis", {
      ...baseRoutes("gercek"),
      [PREVIEW]: () => json(tradePreview()),
      [SAVE]: () => json({ error: expired }, 422),
    });
    await fillRealBuy(user);
    await user.click(await screen.findByRole("button", { name: "Gerçek alımı kaydet" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(expired);
    expect(screen.queryByRole("button", { name: "Yeniden dene" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Düzenle" }));
    expect(screen.getByLabelText("Adet")).toHaveValue("100");
  });

  it("bilinmeyen işlem türü bulunamadı sayfasıdır", async () => {
    renderApp("/gercek/islemler/yeni/takas", baseRoutes("gercek"));

    expect(await screen.findByRole("heading", { name: "Sayfa bulunamadı" })).toBeInTheDocument();
  });
});

describe("sanal işlem", () => {
  const SANAL_PREVIEW = "POST /api/sanal/islemler/alis/onizle";

  it("tutarla alır; fiyatsız günde en yakın fiyatlı günleri önerir ve SANAL kutusunu gösterir", async () => {
    const preview = recorded(
      () =>
        json(
          {
            error: "XHT için 22 Kasım'da kayıtlı fiyat yok.",
            fields: {},
            price_days: ["2026-11-20", "2026-11-23"],
          },
          422,
        ),
      () =>
        json(
          tradePreview({
            profile: "sanal",
            trade_date: "2026-11-23",
            units: "79",
            gross: "987.5",
            leftover: "12.5",
            ref: null,
          }),
        ),
    );
    const { user } = renderApp("/sanal/islemler/yeni/alis", {
      ...baseRoutes("sanal"),
      [SANAL_PREVIEW]: preview,
    });

    expect(
      await screen.findByRole("heading", { level: 1, name: "Sanal alım" }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Birim fiyat")).not.toBeInTheDocument();
    await screen.findByRole("option", { name: "XHT · Hisse Fonu" });
    await user.selectOptions(screen.getByLabelText("Fon"), "XHT");
    await user.clear(screen.getByLabelText("Fiyat günü"));
    await user.type(screen.getByLabelText("Fiyat günü"), "2026-11-22");
    await user.type(screen.getByLabelText("Tutar"), "1000");
    await user.click(screen.getByRole("button", { name: "Önizle" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("XHT için 22 Kasım'da kayıtlı fiyat yok.");
    expect(alert).toHaveTextContent("gün kendiliğinden kaydırılmaz");
    await user.click(within(alert).getByRole("button", { name: "23 Kasım gününü kullan" }));

    expect(
      await screen.findByRole("heading", { level: 1, name: "Alımı kontrol et" }),
    ).toBeInTheDocument();
    expect(preview.bodies.map((body) => (body as { day: string }).day)).toEqual([
      "2026-11-22",
      "2026-11-23",
    ]);
    expect(screen.getByText(/portföye kaydedilecek/)).toHaveTextContent(
      "SANAL portföye kaydedilecek. Gerçek alım değil.",
    );
    expect(summary()).toContain("Fiyat günü=23 Kasım");
    expect(summary()).toContain("Artan tutar=12,50 TL (fona girmez)");
    expect(screen.getByRole("button", { name: "Sanal alımı kaydet" })).toBeInTheDocument();
  });

  it("satışta eldeki payın tümü işaretlenebilir", async () => {
    const preview = recorded(() =>
      json(tradePreview({ profile: "sanal", kind: "satis", side: "SELL" })),
    );
    const { user } = renderApp("/sanal/islemler/yeni/satis", {
      ...baseRoutes("sanal"),
      "POST /api/sanal/islemler/satis/onizle": preview,
    });

    await screen.findByRole("option", { name: "XHT · Hisse Fonu" });
    expect(screen.queryByRole("option", { name: "XAC" })).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Fon"), "XHT");
    await user.click(screen.getByLabelText("Eldeki payın tümünü sat"));
    await user.click(screen.getByRole("button", { name: "Önizle" }));

    expect(
      await screen.findByRole("heading", { level: 1, name: "Satışı kontrol et" }),
    ).toBeInTheDocument();
    expect(preview.bodies).toEqual([
      expect.objectContaining({ fund: "XHT", units: "", all: true }),
    ]);
    expect(screen.getByRole("button", { name: "Sanal satışı kaydet" })).toBeInTheDocument();
  });
});
