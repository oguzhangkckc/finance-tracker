import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { HoldingItem, LotItem } from "../api/types";
import { holding } from "../test/pages";
import { pageRoutes, renderApp } from "../test/render";
import { tableState } from "../test/tables";

function item(overrides: Partial<HoldingItem> = {}): HoldingItem {
  return { ...holding(), class_name: "Hisse", ...overrides };
}

function cells(row: HTMLElement): (string | null)[] {
  return within(row)
    .getAllByRole("cell")
    .map((cell) => cell.textContent);
}

describe("varlıklar", () => {
  it("fonları değer, getiri ve günüyle fiyatla listeler; lotlara bağlar", async () => {
    renderApp(
      "/sanal/varliklar",
      pageRoutes("/api/sanal/varliklar", {
        logical_date: "2026-11-25",
        stale: { XPP: "3 gündür eski" },
        table: tableState([
          item(),
          item({
            instrument: "XPP",
            class_name: "Nakit",
            allocation: false,
            value: null,
            simple_return: null,
          }),
        ]),
      }),
    );

    const rows = within(await screen.findByRole("table"))
      .getAllByRole("row")
      .slice(1);
    expect(cells(rows[0] as HTMLElement)).toEqual([
      "XHT",
      "Hisse",
      "100",
      "1.000,00 TL",
      "1.283,83 TL",
      "%28,38",
      "son fiyat: 12,83827 TL (24 Kasım)",
      "Lotlar (XHT)",
    ]);
    expect(cells(rows[1] as HTMLElement).slice(1, 7)).toEqual([
      "Nakit · dağılım dışı",
      "100",
      "1.000,00 TL",
      "—",
      "—",
      "son fiyat: 12,83827 TL (24 Kasım) bayat: 3 gündür eski",
    ]);
    expect(screen.getByRole("link", { name: "Lotlar (XHT)" })).toHaveAttribute(
      "href",
      "/sanal/varliklar/lotlar?fon=XHT",
    );
    expect(screen.getByText(/Değerleme günü 25 Kasım/)).toBeInTheDocument();
  });

  it("pozisyon yoksa bunu söyler", async () => {
    renderApp(
      "/gercek/varliklar",
      pageRoutes("/api/gercek/varliklar", {
        logical_date: "2026-11-25",
        stale: {},
        table: tableState<HoldingItem>([]),
      }),
    );

    expect(await screen.findByText("Henüz pozisyon yok.")).toBeInTheDocument();
  });
});

describe("lotlar", () => {
  it("lotları alış günü ve kâr/zararla listeler; eksik değer çizgiyle yazılır", async () => {
    const lot: LotItem = {
      instrument: "XHT",
      acquired: "2025-12-02",
      units: "40",
      cost: "400",
      value: null,
      real_return: null,
      cpi_period: null,
      gain: null,
    };
    renderApp(
      "/gercek/varliklar/lotlar?fon=XHT",
      pageRoutes("/api/gercek/varliklar/lotlar", {
        logical_date: "2026-11-25",
        table: tableState([lot, { ...lot, value: "520", gain: "120", real_return: "0.05" }]),
      }),
    );

    const rows = within(await screen.findByRole("table"))
      .getAllByRole("row")
      .slice(1);
    expect(cells(rows[0] as HTMLElement)).toEqual([
      "XHT",
      "2 Aralık 2025",
      "40",
      "400,00 TL",
      "—",
      "—",
      "—",
    ]);
    expect(cells(rows[1] as HTMLElement).slice(4)).toEqual(["520,00 TL", "120,00 TL", "%5,00"]);
    expect(
      within(screen.getByRole("main")).getByRole("link", { name: "Varlıklar" }),
    ).toHaveAttribute("href", "/gercek/varliklar");
  });
});
