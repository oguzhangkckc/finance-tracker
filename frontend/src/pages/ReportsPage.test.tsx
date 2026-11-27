import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { json, SESSION } from "../test/fetch";
import { pageRoutes, renderApp } from "../test/render";

describe("raporlar", () => {
  it("üç raporun bağlantısını verir", async () => {
    renderApp("/sanal/raporlar");

    const kinds = within(await screen.findByRole("navigation", { name: "Rapor türleri" }));
    expect(
      kinds.getAllByRole("link").map((link) => [link.textContent, link.getAttribute("href")]),
    ).toEqual([
      ["Haftalık rapor", "/sanal/raporlar/haftalik"],
      ["Aylık rapor", "/sanal/raporlar/aylik"],
      ["Maaş günü", "/sanal/raporlar/maas-gunu"],
    ]);
  });

  it("raporu Telegram'daki metniyle gösterir", async () => {
    const text = "Haftalık özet\nToplam: 90.000,00 TL";
    renderApp(
      "/gercek/raporlar/haftalik",
      pageRoutes("/api/gercek/raporlar/haftalik", { title: "Haftalık rapor", text }),
    );

    expect(await screen.findByText(/Toplam: 90\.000,00 TL/)).toHaveTextContent(
      "Haftalık özet Toplam: 90.000,00 TL",
    );
    expect(screen.getByRole("heading", { level: 1, name: "Haftalık rapor" })).toBeInTheDocument();
    expect(
      within(screen.getByRole("main")).getByRole("link", { name: "Raporlar" }),
    ).toHaveAttribute("href", "/gercek/raporlar");
  });

  it("bilinmeyen rapor türü bulunamadı sayfasıdır", async () => {
    renderApp("/gercek/raporlar/yillik");

    expect(await screen.findByRole("heading", { name: "Sayfa bulunamadı" })).toBeInTheDocument();
  });

  it("rapor üretilemezse nedenini gösterir", async () => {
    renderApp("/gercek/raporlar/aylik", {
      "GET /api/oturum": () => json(SESSION),
      "GET /api/gercek/raporlar/aylik": () => json({ error: "Portföy dosyası okunamadı." }, 503),
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("Portföy dosyası okunamadı.");
    expect(screen.getByRole("heading", { level: 1, name: "Aylık rapor" })).toBeInTheDocument();
  });
});
