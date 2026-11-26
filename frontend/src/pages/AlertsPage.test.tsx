import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AlertEventItem, AlertsData } from "../api/types";
import { CLASS_NAMES } from "../test/pages";
import { pageRoutes, renderApp } from "../test/render";
import { tableState } from "../test/tables";
import { QUIET_PERIOD } from "./OverviewPage";

const EVENT: AlertEventItem = {
  id: 7,
  occurred_at: "2026-11-20T06:00:00Z",
  day: "2026-11-20",
  kind: "opened",
  direction: "below",
  deviation: "-0.0615",
  asset_class: "altin",
  class_name: "Altın",
  notified_at: "2026-11-20T06:05:00Z",
};

function page(overrides: Partial<AlertsData> = {}): AlertsData {
  return {
    table: tableState([
      EVENT,
      {
        ...EVENT,
        id: 8,
        kind: "resolved",
        direction: "above",
        deviation: "0.01",
        notified_at: null,
      },
    ]),
    alerts: [],
    quiet_ended: "2026-09-01",
    class_names: CLASS_NAMES,
    ...overrides,
  };
}

describe("alarmlar", () => {
  it("sessiz dönemin bittiği günü ve alarm geçmişini İstanbul saatiyle gösterir", async () => {
    renderApp("/gercek/alarmlar", pageRoutes("/api/gercek/alarmlar", page()));

    expect(
      await screen.findByText("Sessiz dönem 1 Eylül'de bitti; sapma alarmları açık."),
    ).toBeInTheDocument();
    expect(screen.getByText("Açık alarm yok.")).toBeInTheDocument();
    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(
      within(rows[0] as HTMLElement)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual([
      "20 Kasım 09:00",
      "Altın",
      "açıldı · hedefin altında",
      "-6,2 puan",
      "20 Kasım 09:05",
    ]);
    expect(rows[1]).toHaveTextContent("kapandı · hedefin üstünde");
    expect(rows[1]).toHaveTextContent("bekliyor");
  });

  it("sessiz dönem sürüyorsa bunu söyler ve açık alarmları listeler", async () => {
    renderApp(
      "/gercek/alarmlar",
      pageRoutes(
        "/api/gercek/alarmlar",
        page({
          quiet_ended: null,
          alerts: [
            {
              asset_class: "hisse",
              direction: "above",
              deviation: "0.07",
              opened_at: "2026-11-24T08:00:00Z",
            },
          ],
          table: tableState<AlertEventItem>([]),
        }),
      ),
    );

    expect(await screen.findByText(QUIET_PERIOD)).toBeInTheDocument();
    expect(
      within(screen.getByRole("list", { name: "Açık alarmlar" })).getByRole("listitem"),
    ).toHaveTextContent("Hisse · +7,0 puanhedefin üstünde · açıldı 24 Kasım");
    expect(screen.getByText("Henüz alarm olayı yok.")).toBeInTheDocument();
  });
});
