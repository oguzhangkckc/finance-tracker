import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SANAL_NOTICE } from "../profile";
import { SESSION } from "../test/fetch";
import { renderApp } from "../test/render";
import { MORE, NAV, TABS } from "./nav";

const PAGES = [
  ...NAV.map((item) => (item.path === "" ? "" : `/${item.path}`)),
  "/varliklar/lotlar",
  "/daha",
];

function sidebar() {
  return within(screen.getByRole("navigation", { name: "Sayfalar" }));
}

// jsdom medya sorgusunu değerlendirmez; Mantine'in hiddenFrom kuralını her genişlikte uygular.
function tabbar() {
  return within(screen.getByRole("navigation", { name: "Sayfalar (kısa)", hidden: true }));
}

describe("kabuk", () => {
  it("sanal profilde her sayfada bant gösterir", async () => {
    renderApp("/sanal/islemler");

    expect(await screen.findByText(SANAL_NOTICE)).toHaveAttribute("role", "status");
  });

  it("gerçek profilde bant göstermez", async () => {
    renderApp("/gercek/islemler");

    await screen.findByRole("heading", { level: 1, name: "İşlemler" });
    expect(screen.queryByText(SANAL_NOTICE)).not.toBeInTheDocument();
  });

  it("profil geçişi aynı sayfada kalır ve bulunulan profili işaretler", async () => {
    renderApp("/sanal/varliklar/lotlar");

    const switcher = within(await screen.findByRole("navigation", { name: "Portföy" }));
    expect(switcher.getByRole("link", { name: "Gerçek" })).toHaveAttribute(
      "href",
      "/gercek/varliklar/lotlar",
    );
    expect(switcher.getByRole("link", { name: "Sanal" })).toHaveAttribute("aria-current", "page");
    expect(switcher.getByRole("link", { name: "Gerçek" })).not.toHaveAttribute("aria-current");
  });

  it("alt sayfada üst menü öğesini seçili gösterir", async () => {
    renderApp("/gercek/varliklar/lotlar");

    await screen.findByRole("heading", { level: 1, name: "Lotlar" });
    const current = sidebar()
      .getAllByRole("link")
      .filter((link) => link.getAttribute("aria-current") === "page");
    expect(current.map((link) => link.textContent)).toEqual(["Varlıklar"]);
  });

  it("sekmelerde olmayan bir sayfada Daha fazla sekmesini seçili gösterir", async () => {
    renderApp("/gercek/alarmlar");

    await screen.findByRole("heading", { level: 1, name: "Alarmlar" });
    expect(tabbar().getByRole("link", { name: "Daha fazla", hidden: true })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(TABS.some((tab) => tab.path === "alarmlar")).toBe(false);
  });

  it.each(PAGES)("%s sayfasında tek h1 vardır", async (page) => {
    renderApp(`/gercek${page}`);

    await screen.findByRole("heading", { level: 1 });
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("içeriğe geçiş bağlantısı ana bölgeye gider", async () => {
    renderApp("/gercek");

    await screen.findByRole("heading", { level: 1, name: "Özet" });
    expect(screen.getByRole("link", { name: "İçeriğe geç" })).toHaveAttribute("href", "#icerik");
    expect(screen.getByRole("main")).toHaveAttribute("id", "icerik");
  });

  it("oturumdaki e-postayı gösterir", async () => {
    renderApp("/gercek");

    expect(await screen.findByText(SESSION.email)).toBeInTheDocument();
  });

  it("Daha fazla sayfası sekmelerde olmayan her sayfayı listeler", async () => {
    renderApp("/gercek/daha");

    const list = within(await screen.findByRole("navigation", { name: "Diğer sayfalar" }));
    const listed = list.getAllByRole("link").map((link) => link.getAttribute("href"));
    expect(listed).toEqual(MORE.map((item) => `/gercek/${item.path}`));
    const everywhere = new Set([...TABS.map((tab) => tab.path), ...MORE.map((item) => item.path)]);
    expect(NAV.every((item) => everywhere.has(item.path))).toBe(true);
  });
});
