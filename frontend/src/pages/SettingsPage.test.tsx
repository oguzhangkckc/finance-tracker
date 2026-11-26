import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { SettingItem, SettingsData } from "../api/types";
import { CLASS_NAMES } from "../test/pages";
import { pageRoutes, renderApp } from "../test/render";
import { tableState } from "../test/tables";

const VALUES = {
  payday: 15,
  monthly_contribution: "5000",
  targets: { hisse: "0.625", altin: "0.375" },
};

function version(overrides: Partial<SettingItem> = {}): SettingItem {
  return {
    id: 3,
    recorded_at: "2026-11-01T07:00:00Z",
    source: "web",
    source_label: "web",
    effective_from: "2026-12-01",
    initial: false,
    values: VALUES,
    state: "planned",
    state_label: "planlandı",
    cancelled_at: null,
    cancel_reason: null,
    changes: [{ setting: "Aylık katkı", change: "4.000,00 TL → 5.000,00 TL" }],
    ...overrides,
  };
}

function page(overrides: Partial<SettingsData> = {}): SettingsData {
  return {
    table: tableState<SettingItem>([]),
    current: VALUES,
    current_id: 2,
    current_from: "2026-10-01",
    planned: [],
    classes: ["hisse", "altin"],
    class_names: CLASS_NAMES,
    ...overrides,
  };
}

function open(data: SettingsData) {
  return renderApp("/gercek/ayarlar", pageRoutes("/api/gercek/ayarlar", data));
}

function summary(): string[] {
  return screen
    .getAllByRole("definition")
    .map((item) => `${item.previousElementSibling?.textContent}=${item.textContent}`);
}

describe("ayarlar", () => {
  it("geçerli ayarı yürürlük günüyle, hedefleri yuvarlamadan yüzdeyle gösterir", async () => {
    open(page());

    expect(await screen.findByText("1 Ekim'den beri geçerli · #2")).toBeInTheDocument();
    expect(summary()).toEqual([
      "Maaş günü=ayın 15. günü",
      "Aylık katkı=5.000,00 TL",
      "Hisse=%62,5",
      "Altın=%37,5",
    ]);
  });

  it("başlangıç sürümünü ve sürüm yokluğunu ayırır; tanımsız değerleri söyler", async () => {
    const { unmount } = open(page({ current_from: null }));
    expect(await screen.findByText("Başlangıç (portfolio.toml)")).toBeInTheDocument();
    unmount();

    open(
      page({
        current_id: null,
        current_from: null,
        current: { payday: null, monthly_contribution: null, targets: {} },
      }),
    );
    expect(
      await screen.findByText(/Ayar sürümü yok; portfolio.toml kullanılıyor/),
    ).toBeInTheDocument();
    expect(summary()).toEqual([
      "Maaş günü=tanımlı değil",
      "Aylık katkı=tanımlı değil",
      "Hisse=%0",
      "Altın=%0",
    ]);
  });

  it("planlanan sürümü değişiklik satırlarıyla, geçmişi durum ve kaynakla listeler", async () => {
    open(
      page({
        planned: [version()],
        table: tableState([
          version(),
          version({
            id: 1,
            initial: true,
            state: "past",
            state_label: "geçmiş",
            source: "cli",
            source_label: "komut satırı",
            changes: [],
          }),
          version({
            id: 4,
            state: "cancelled",
            state_label: "vazgeçildi",
            cancelled_at: "2026-11-02T08:00:00Z",
            cancel_reason: "erken girildi",
          }),
        ]),
      }),
    );

    const planned = within(await screen.findByRole("list", { name: "Planlanan" })).getByRole(
      "listitem",
    );
    expect(planned).toHaveTextContent(
      "1 Aralık'tan itibaren#3Aylık katkı: 4.000,00 TL → 5.000,00 TL",
    );
    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(
      within(rows[0] as HTMLElement)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual([
      "3",
      "1 Kasım 10:00",
      "1 Aralık'tan itibaren",
      "Aylık katkı: 4.000,00 TL → 5.000,00 TL",
      "planlandı",
      "web",
    ]);
    expect(rows[1]).toHaveTextContent("Başlangıç (portfolio.toml)");
    expect(rows[1]).toHaveTextContent("değişiklik yok");
    expect(rows[1]).toHaveTextContent("komut satırı");
    expect(rows[2]).toHaveClass("ft-voided");
    expect(rows[2]).toHaveTextContent("vazgeçildi: erken girildi");
  });
});
