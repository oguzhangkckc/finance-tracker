import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { OverviewData } from "../api/types";
import { json, SESSION } from "../test/fetch";
import { holding, overview, report } from "../test/pages";
import { pageRoutes, renderApp } from "../test/render";
import { QUIET_PERIOD } from "./OverviewPage";

function open(data: OverviewData, profile = "gercek") {
  return renderApp(`/${profile}`, pageRoutes(`/api/${profile}/ozet`, data));
}

function summary(overrides: Partial<OverviewData["report"]["summary"]>) {
  return { ...report().summary, ...overrides };
}

describe("özet", () => {
  it("toplam değeri, değişimi ve dağılım içi tutarı gösterir", async () => {
    open(
      overview({
        report: report({
          summary: summary({
            values: { in_allocation: "88500", out_of_allocation: "0", total: "90000" },
            realized_pnl: "250.5",
          }),
        }),
      }),
    );

    expect(await screen.findByText("90.000,00 TL", { selector: ".ft-hero" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Özet" })).toBeInTheDocument();
    expect(screen.getByText("Toplam değer · Değerleme günü 25 Kasım")).toBeInTheDocument();
    expect(screen.getByText("+%2,27").closest(".ft-delta")).toHaveTextContent("▲+%2,27 artış");
    expect(screen.getByText("18 Kasım sonrasında")).toBeInTheDocument();
    expect(screen.getByText("88.500,00 TL")).toBeInTheDocument();
    expect(screen.queryByText("Dağılım dışı")).not.toBeInTheDocument();
    expect(screen.getByText("+%12,50")).toBeInTheDocument();
    expect(screen.getByText("250,50 TL")).toBeInTheDocument();
  });

  it("düşüşü okla ve sözcükle, dağılım dışı tutarı ayrıca gösterir", async () => {
    open(
      overview({
        report: report({
          summary: summary({
            values: { in_allocation: "88500", out_of_allocation: "1500", total: "90000" },
            change: "-0.01",
          }),
        }),
      }),
    );

    expect(await screen.findByText("-%1,00")).toBeInTheDocument();
    expect(screen.getByText("-%1,00").closest(".ft-delta")).toHaveTextContent("▼-%1,00 azalış");
    expect(screen.getByText("Dağılım dışı")).toBeInTheDocument();
    expect(screen.getByText("1.500,00 TL")).toBeInTheDocument();
  });

  it("bayat fiyat, eksik fiyat ve açık alarm uyarılarını gösterir", async () => {
    open(
      overview({
        stale_all: ["XPP fiyatı 4 gündür güncellenmedi"],
        report: report({
          missing_prices: ["XAC"],
          alerts: [
            {
              asset_class: "altin",
              direction: "below",
              deviation: "-0.061",
              opened_at: "2026-11-20T05:00:00Z",
            },
          ],
        }),
      }),
    );

    expect(
      await screen.findByText("Fiyatlar bayat: XPP fiyatı 4 gündür güncellenmedi."),
    ).toBeInTheDocument();
    expect(screen.getByText("Fiyatı eksik: XAC.")).toBeInTheDocument();
    expect(screen.getByText("Açık sapma alarmı: 1.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dağılımı gör" })).toHaveAttribute(
      "href",
      "/gercek/dagilim",
    );
  });

  it("dağılımı sınıf adlarıyla, hedefe uzaklığı sözcükle gösterir; alarmı işaretler", async () => {
    open(
      overview({
        report: report({
          quiet_period: true,
          allocation: [
            {
              asset_class: "hisse",
              value: "60000",
              weight: "0.6667",
              target: "0.6",
              deviation: "0.0667",
            },
            {
              asset_class: "altin",
              value: "30000",
              weight: "0.3333",
              target: "0.4",
              deviation: "-0.0667",
            },
          ],
          alerts: [
            {
              asset_class: "altin",
              direction: "below",
              deviation: "-0.0667",
              opened_at: "2026-11-20T05:00:00Z",
            },
          ],
        }),
      }),
    );

    expect(await screen.findByText("Hisse")).toBeInTheDocument();
    expect(screen.getByText("· hedef %60,0 · 6,7 puan fazla")).toBeInTheDocument();
    expect(screen.getByText("· hedef %40,0 · 6,7 puan eksik")).toBeInTheDocument();
    expect(screen.getAllByText("Alarm eşiği aşıldı")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Ayrıntı ›" })).toHaveAttribute(
      "href",
      "/gercek/dagilim",
    );
    expect(screen.getByText(QUIET_PERIOD)).toBeInTheDocument();
  });

  it("varlıkları fiyat günüyle, elle girilen ve bayat fiyatı işaretleyerek listeler", async () => {
    open(
      overview({
        stale: { XHT: "3 gündür eski" },
        report: report({
          holdings: [
            holding({ source: "manual" }),
            holding({
              instrument: "XAC",
              asset_class: "nakit",
              allocation: false,
              value: null,
              price: null,
              price_date: null,
            }),
          ],
        }),
      }),
    );

    const cards = within(await screen.findByRole("list", { name: "Varlıklar" })).getAllByRole(
      "listitem",
    );
    expect(cards[0]).toHaveTextContent("XHT1.283,83 TL");
    expect(cards[0]).toHaveTextContent(
      "son fiyat: 12,83827 TL (24 Kasım) elle bayat: 3 gündür eski",
    );
    expect(cards[1]).toHaveTextContent("Nakit · dağılım dışı");
    expect(cards[1]).toHaveTextContent("fiyat yok");
    expect(screen.getByRole("link", { name: "Tümü ›" })).toHaveAttribute(
      "href",
      "/gercek/varliklar",
    );
  });

  it("pozisyon yoksa yapılacak işi söyler", async () => {
    open(overview());

    expect(
      await screen.findByText("Henüz pozisyon yok. İşlemler girildiğinde fonlar burada görünür."),
    ).toBeInTheDocument();
  });

  it("son fiyat güncellemesini İstanbul saatiyle, kapalıysa nedenini gösterir", async () => {
    open(
      overview({
        refresh: {
          allowed: false,
          reason: "bugün zaten güncellendi",
          earliest: "2026-11-26T15:00:00Z",
          last_sync: "2026-11-25T06:30:00Z",
        },
      }),
    );

    expect(await screen.findByText("Son fiyat güncellemesi: 25 Kasım 09:30")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Elle güncelleme şu an kapalı: bugün zaten güncellendi. En erken 26 Kasım 18:00.",
      ),
    ).toBeInTheDocument();
  });

  it("son iki günde güncelleme yoksa bunu söyler", async () => {
    open(overview({ refresh: { allowed: true, reason: null, earliest: null, last_sync: null } }));

    expect(
      await screen.findByText("Son fiyat güncellemesi: son iki günde yok"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Elle güncelleme şu an kapalı/)).not.toBeInTheDocument();
  });

  it("sanal profilde sanalın verisini ister", async () => {
    const { fetch } = open(overview(), "sanal");

    await screen.findByText("90.000,00 TL", { selector: ".ft-hero" });
    const asked = fetch.mock.calls.map(([request]) => new URL(request.url).pathname);
    expect(asked).toContain("/api/sanal/ozet");
    expect(asked).not.toContain("/api/gercek/ozet");
  });

  it("veri yüklenemezse nedeni ve yeniden deneme düğmesi çıkar", async () => {
    let calls = 0;
    const { user } = renderApp("/gercek", {
      "GET /api/oturum": () => json(SESSION),
      "GET /api/gercek/ozet": () => {
        calls += 1;
        return calls === 1 ? json({ error: "Portföy dosyası okunamadı." }, 503) : json(overview());
      },
    });

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Portföy dosyası okunamadı.")).toBeInTheDocument();
    await user.click(within(alert).getByRole("button", { name: "Yeniden dene" }));

    await waitFor(() =>
      expect(screen.getByText("90.000,00 TL", { selector: ".ft-hero" })).toBeInTheDocument(),
    );
  });
});
