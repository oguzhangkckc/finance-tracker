import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AllocationData } from "../api/types";
import { allocationPage, report } from "../test/pages";
import { pageRoutes, renderApp } from "../test/render";
import { QUIET_PERIOD } from "./OverviewPage";

const LINES = [
  { asset_class: "hisse", value: "60000", weight: "0.6667", target: "0.6", deviation: "0.0667" },
  { asset_class: "altin", value: "30000", weight: "0.3333", target: "0.4", deviation: "-0.0667" },
];

function open(data: AllocationData) {
  return renderApp("/gercek/dagilim", pageRoutes("/api/gercek/dagilim", data));
}

describe("dağılım", () => {
  it("sınıfları değer, ağırlık, hedef ve puanla tabloya döker", async () => {
    open(allocationPage({ report: report({ allocation: LINES }) }));

    const table = await screen.findByRole("table");
    const rows = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((row) =>
        within(row)
          .getAllByRole("cell")
          .map((cell) => cell.textContent),
      );
    expect(rows).toEqual([
      ["Hisse", "60.000,00 TL", "%66,7", "%60,0", "+6,7 puan"],
      ["Altın", "30.000,00 TL", "%33,3", "%40,0", "-6,7 puan"],
    ]);
    expect(screen.getByText("Değerleme günü 25 Kasım")).toBeInTheDocument();
  });

  it("fiyatı eksikse dağılımı hesaplamaz ve nedenini söyler", async () => {
    open(allocationPage({ report: report({ allocation: LINES, allocation_skipped: ["XAC"] }) }));

    expect(await screen.findByText("Dağılım hesaplanmadı; fiyatı eksik: XAC.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("dağılım yoksa yapılacak işi söyler", async () => {
    open(allocationPage({ report: report({ quiet_period: true }) }));

    expect(
      await screen.findByText(
        "Henüz dağılım yok; dağılım içi bir fona işlem girilince hesaplanır.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(QUIET_PERIOD)).toBeInTheDocument();
  });

  it("açık alarmları yönü ve açıldığı günle listeler", async () => {
    open(
      allocationPage({
        report: report({
          allocation: LINES,
          alerts: [
            {
              asset_class: "altin",
              direction: "below",
              deviation: "-0.0667",
              opened_at: "2026-11-19T22:30:00Z",
            },
            {
              asset_class: "hisse",
              direction: "above",
              deviation: null,
              opened_at: "2025-12-02T06:00:00Z",
            },
          ],
        }),
      }),
    );

    const alarms = within(await screen.findByRole("list", { name: "Açık alarmlar" })).getAllByRole(
      "listitem",
    );
    expect(alarms[0]).toHaveTextContent("Altın · -6,7 puanhedefin altında · açıldı 20 Kasım");
    expect(alarms[1]).toHaveTextContent("Hissehedefin üstünde · açıldı 2 Aralık 2025");
  });

  it("açık alarm yoksa bunu söyler", async () => {
    open(allocationPage());

    expect(await screen.findByText("Açık alarm yok.")).toBeInTheDocument();
  });
});
