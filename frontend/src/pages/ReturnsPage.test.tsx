import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ReturnFigure, ReturnsData } from "../api/types";
import { holding, report, returnsPage } from "../test/pages";
import { pageRoutes, renderApp } from "../test/render";
import { figureText } from "./ReturnsPage";

function open(data: ReturnsData) {
  return renderApp("/gercek/getiri", pageRoutes("/api/gercek/getiri", data));
}

function stat(term: string): string | null | undefined {
  return screen.getByText(term, { selector: "dt" }).nextElementSibling?.textContent;
}

describe("getiri", () => {
  it("getiri ölçülerini ve yıllık enflasyonu ay adıyla gösterir", async () => {
    const base = report();
    open(
      returnsPage({
        report: report({
          summary: {
            ...base.summary,
            money_weighted: { status: "ok", rate: "0.1834", annualized: true },
            real_money_weighted: { status: "ok", rate: "0.05", annualized: false },
            real_same_as_nominal: true,
          },
          inflation: {
            cpi_series: "TP.TUKFIY2025.GENEL",
            valuation_period: "2026-10",
            annual_inflation: "0.325",
          },
        }),
      }),
    );

    await screen.findByText("Basit getiri", { selector: "dt" });
    expect(stat("Basit getiri")).toBe("%12,50");
    expect(stat("Para ağırlıklı getiri")).toBe("%18,34 (yıllık)");
    expect(stat("Reel para ağırlıklı getiri")).toBe("%5,00 (dönemlik)");
    expect(stat("Yıllık enflasyon (Ekim 2026)")).toBe("%32,50");
    expect(
      screen.getByText(
        "Alımlar ve değerleme aynı TÜFE dönemine düştüğü için reel getiri henüz nominalle aynı.",
      ),
    ).toBeInTheDocument();
  });

  it.each<[ReturnFigure | null | undefined, string]>([
    [null, "—"],
    [undefined, "—"],
    [{ status: "out_of_range", rate: null, annualized: null }, "anlamlı değil"],
    [{ status: "missing_price", rate: null, annualized: null }, "fiyat eksik"],
    [{ status: "undefined", rate: null, annualized: null }, "hesaplanamadı"],
    [{ status: "ok", rate: null, annualized: null }, "hesaplanamadı"],
  ])("%j getirisi %s olarak yazılır", (figure, text) => {
    expect(figureText(figure)).toBe(text);
  });

  it("fon bazında basit ve reel getiriyi listeler", async () => {
    open(
      returnsPage({
        report: report({
          holdings: [
            holding(),
            holding({ instrument: "XPP", simple_return: null, real_return: null }),
          ],
        }),
      }),
    );

    const table = within(
      await screen
        .findByRole("heading", { name: "Fon bazında" })
        .then((heading) => heading.nextElementSibling as HTMLElement),
    );
    const rows = table
      .getAllByRole("row")
      .slice(1)
      .map((row) =>
        within(row)
          .getAllByRole("cell")
          .map((cell) => cell.textContent),
      );
    expect(rows).toEqual([
      ["XHT", "%28,38", "%10,00"],
      ["XPP", "—", "—"],
    ]);
  });

  it("pozisyon yoksa fon tablosu bunu söyler", async () => {
    open(returnsPage());

    expect(await screen.findByText("Henüz pozisyon yok.")).toBeInTheDocument();
  });

  it("katkı geçmişini çizer ve tablosunu verir", async () => {
    open(returnsPage({ contributions: [{ month: "2026-11", invested: "4500", planned: "5000" }] }));

    expect(await screen.findByRole("figure", { name: "Katkı geçmişi" })).toBeInTheDocument();
    expect(screen.getByRole("figure", { name: "Değerin seyri" })).toBeInTheDocument();
  });
});
