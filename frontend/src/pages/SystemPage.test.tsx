import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { RunItem, SystemData } from "../api/types";
import { pageRoutes, renderApp } from "../test/render";
import { tableState } from "../test/tables";

const RUN: RunItem = {
  id: 41,
  job: "sync-prices",
  logical_date: "2026-11-25",
  started_at: "2026-11-25T06:30:00Z",
  finished_at: "2026-11-25T06:31:00Z",
  status: "ok",
  status_label: "başarılı",
};

function page(overrides: Partial<SystemData> = {}): SystemData {
  return {
    table: tableState([RUN, { ...RUN, id: 42, status: "failed", status_label: "başarısız" }]),
    checks: [
      { name: "Veritabanı", status: "ok", detail: "şema güncel" },
      { name: "Fiyatlar", status: "warn", detail: "XPP 3 gündür eski" },
      { name: "Yedek", status: "fail", detail: "son yedek 3 gün önce" },
    ],
    backups: [
      { name: "gece-2026-11-25.age", ok: true, message: "doğrulandı" },
      { name: "gece-2026-11-24.age", ok: false, message: "açılamadı" },
    ],
    ...overrides,
  };
}

describe("sistem", () => {
  it("doctor sonuçlarını işaret ve sözcükle gösterir", async () => {
    renderApp("/gercek/sistem", pageRoutes("/api/gercek/sistem", page()));

    const checks = within(await screen.findByRole("list", { name: "Doctor" })).getAllByRole(
      "listitem",
    );
    expect(checks.map((check) => check.textContent)).toEqual([
      "Veritabanı✓geçtişema güncel",
      "Fiyatlar!uyarıXPP 3 gündür eski",
      "Yedek✗başarısızson yedek 3 gün önce",
    ]);
  });

  it("iş geçmişini durum adıyla ve başarısızı işaretleyerek listeler", async () => {
    renderApp("/gercek/sistem", pageRoutes("/api/gercek/sistem", page()));

    const rows = within(await screen.findByRole("table"))
      .getAllByRole("row")
      .slice(1);
    expect(
      within(rows[0] as HTMLElement)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual(["41", "sync-prices", "25 Kasım", "başarılı", "25 Kasım 09:30"]);
    expect(within(rows[1] as HTMLElement).getByText("başarısız")).toHaveClass("ft-warn");
  });

  it("yedek özetlerini, yoksa nedenini gösterir", async () => {
    const { unmount } = renderApp("/gercek/sistem", pageRoutes("/api/gercek/sistem", page()));

    const backups = within(await screen.findByRole("list", { name: "Yedek özetleri" }));
    expect(backups.getByText("açılamadı")).toHaveClass("ft-warn");
    unmount();

    renderApp("/gercek/sistem", pageRoutes("/api/gercek/sistem", page({ backups: [] })));
    expect(
      await screen.findByText("Yedek bulunamadı ya da yedek dizini tanımlı değil."),
    ).toBeInTheDocument();
  });
});
