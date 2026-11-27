import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TransactionItem } from "../api/types";
import type { TableState } from "../components/DataTable";
import { json, SESSION } from "../test/fetch";
import { renderApp } from "../test/render";
import { tableState } from "../test/tables";

function tx(overrides: Partial<TransactionItem> = {}): TransactionItem {
  return {
    id: 1,
    instrument: "XHT",
    trade_date: "2026-11-20",
    side: "BUY",
    units: "100",
    unit_price: "12.5",
    fee: "0",
    amount: "1250",
    asset_class: "hisse",
    class_name: "Hisse",
    external_ref: null,
    note: null,
    created_at: "2026-11-20T09:00:00Z",
    voided_at: null,
    void_reason: null,
    ...overrides,
  };
}

function open(path: string, table: TableState<TransactionItem>) {
  return renderApp(path, {
    "GET /api/oturum": () => json(SESSION),
    "GET /api/gercek/islemler": () => json({ table }),
  });
}

function asked(fetch: ReturnType<typeof open>["fetch"]): string[] {
  return fetch.mock.calls
    .map(([request]) => new URL(request.url))
    .filter((url) => url.pathname === "/api/gercek/islemler")
    .map((url) => url.search);
}

describe("işlem tablosu", () => {
  it("adresteki parametreler olduğu gibi gider; sunucunun durumu gösterilir", async () => {
    const { fetch } = open(
      "/gercek/islemler?fon=XHT&yok=1",
      tableState([tx()], {
        params: { fon: "XHT" },
        active: [{ key: "fon", name: "Fon", value: "XHT", day: false }],
        ignored: "yok=1",
      }),
    );

    await screen.findByRole("table");
    expect(asked(fetch)).toEqual(["?fon=XHT&yok=1"]);
    const chips = within(screen.getByRole("list", { name: "Etkin filtreler" }));
    expect(chips.getByRole("link", { name: "Fon: XHT filtresini kaldır" })).toHaveAttribute(
      "href",
      "/gercek/islemler",
    );
    expect(chips.getByRole("link", { name: "Hepsini temizle" })).toHaveAttribute(
      "href",
      "/gercek/islemler",
    );
    expect(screen.getByText("Filtre anlaşılmadı: yok=1. Yok sayıldı.")).toBeInTheDocument();
  });

  it("gün filtresi çipte gün adıyla yazılır", async () => {
    open(
      "/gercek/islemler?bas=2026-11-01",
      tableState([tx()], {
        params: { bas: "2026-11-01" },
        active: [{ key: "bas", name: "Başlangıç", value: "2026-11-01", day: true }],
      }),
    );

    expect(
      await screen.findByRole("link", { name: "Başlangıç: 1 Kasım filtresini kaldır" }),
    ).toBeInTheDocument();
  });

  it("satırları web'deki gibi yazar; iptal edilen satırı işaretler", async () => {
    open(
      "/gercek/islemler",
      tableState([
        tx({ note: "maaş", external_ref: "D-12" }),
        tx({
          id: 2,
          side: "SELL",
          voided_at: "2026-11-21T10:00:00Z",
          void_reason: "yanlış adet",
          fee: "1.25",
        }),
      ]),
    );

    const rows = within(await screen.findByRole("table"))
      .getAllByRole("row")
      .slice(1);
    expect(
      within(rows[0] as HTMLElement)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual([
      "1",
      "20 Kasım",
      "XHT Hisse",
      "alış",
      "100",
      "12,5",
      "1.250,00 TL",
      "0",
      "maaş D-12",
      "İptal et (#1)",
    ]);
    expect(rows[1]).toHaveClass("ft-voided");
    expect(rows[1]).toHaveTextContent("satış");
    expect(rows[1]).toHaveTextContent("İptal: yanlış adet");
    expect(within(rows[1] as HTMLElement).queryByRole("link", { name: /İptal et/ })).toBeNull();
    expect(screen.getByRole("link", { name: "İptal et (#1)" })).toHaveAttribute(
      "href",
      "/gercek/islemler/1/iptal",
    );
  });

  it("sıralanabilir başlık bağlantıdır ve yönünü söyler", async () => {
    const { router, fetch } = open(
      "/gercek/islemler?fon=XHT",
      tableState([tx()], { params: { fon: "XHT" } }),
    );

    const date = await screen.findByRole("columnheader", { name: "Tarih" });
    expect(date).toHaveAttribute("aria-sort", "descending");
    expect(screen.getByRole("columnheader", { name: "Fiyat" })).not.toHaveAttribute("aria-sort");
    const amount = screen.getByRole("link", { name: "Tutar" });
    expect(amount).toHaveAttribute("href", "/gercek/islemler?fon=XHT&sirala=tutar&yon=artan");

    fireEvent.click(amount);

    await waitFor(() =>
      expect(router.state.location.search).toBe("?fon=XHT&sirala=tutar&yon=artan"),
    );
    await waitFor(() => expect(asked(fetch)).toContain("?fon=XHT&sirala=tutar&yon=artan"));
  });

  it("sıralama seçimi sütunu ve yönü birlikte değiştirir, sayfayı bırakır", async () => {
    const { router, user } = open(
      "/gercek/islemler?fon=XHT&sayfa=2",
      tableState([tx()], { params: { fon: "XHT", sayfa: "2" }, page: 2, pages: 2, total: 30 }),
    );

    await user.selectOptions(await screen.findByLabelText("Sırala"), "tutar.azalan");

    await waitFor(() =>
      expect(router.state.location.search).toBe("?fon=XHT&sirala=tutar&yon=azalan"),
    );
  });

  it("arama tüm kayıtlarda yapılır ve ilk sayfaya döner", async () => {
    const { router, user } = open(
      "/gercek/islemler?sayfa=3",
      tableState([tx()], { params: { sayfa: "3" }, search: true, page: 3, pages: 3, total: 60 }),
    );

    await user.type(await screen.findByLabelText("Ara"), "dekont");
    await user.click(screen.getByRole("button", { name: "Ara" }));

    await waitFor(() => expect(router.state.location.search).toBe("?ara=dekont"));
  });

  it("filtreler uygulanır; varsayılan seçenek adrese yazılmaz", async () => {
    const { router, user } = open(
      "/gercek/islemler",
      tableState([tx()], {
        day_filter: true,
        choices: [
          {
            key: "tur",
            label: "Tür",
            options: [
              { value: "alis", label: "alış" },
              { value: "satis", label: "satış" },
            ],
            default: null,
          },
          {
            key: "iptal",
            label: "İptal edilenler",
            options: [
              { value: "goster", label: "göster" },
              { value: "gizle", label: "gizle" },
            ],
            default: "goster",
          },
        ],
      }),
    );

    await user.click(await screen.findByText("Filtreler"));
    expect(
      within(screen.getByLabelText("Tür"))
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Hepsi", "alış", "satış"]);
    expect(screen.getByLabelText("İptal edilenler")).toHaveValue("goster");
    await user.selectOptions(screen.getByLabelText("Tür"), "satis");
    fireEvent.change(screen.getByLabelText("Başlangıç"), { target: { value: "2026-11-01" } });
    await user.click(screen.getByRole("button", { name: "Uygula" }));

    await waitFor(() => expect(router.state.location.search).toBe("?tur=satis&bas=2026-11-01"));
  });

  it("sayfalar arasında geçiş bağlantı ile yapılır", async () => {
    open(
      "/gercek/islemler?sayfa=2",
      tableState([tx()], { params: { sayfa: "2" }, page: 2, pages: 3, total: 60 }),
    );

    const pager = within(await screen.findByRole("navigation", { name: "Tablo sayfaları" }));
    expect(pager.getByRole("link", { name: "Önceki" })).toHaveAttribute(
      "href",
      "/gercek/islemler?sayfa=1",
    );
    expect(pager.getByRole("link", { name: "Sonraki" })).toHaveAttribute(
      "href",
      "/gercek/islemler?sayfa=3",
    );
    expect(pager.getByText("Sayfa 2 / 3 · 60 satır")).toBeInTheDocument();
  });

  it("filtreyle boş kalan tablo filtreleri temizlemeyi önerir", async () => {
    open(
      "/gercek/islemler?fon=XPP",
      tableState<TransactionItem>([], {
        params: { fon: "XPP" },
        active: [{ key: "fon", name: "Fon", value: "XPP", day: false }],
      }),
    );

    expect(await screen.findByText(/Bu filtrelerle işlem yok\./)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Filtreleri temizle" })).toHaveAttribute(
      "href",
      "/gercek/islemler",
    );
  });

  it("profile göre işlem ekleme bağlantılarını verir", async () => {
    const { unmount } = open("/gercek/islemler", tableState<TransactionItem>([]));
    expect(await screen.findByRole("link", { name: "Alım ekle" })).toHaveAttribute(
      "href",
      "/gercek/islemler/yeni/alis",
    );
    expect(screen.getByRole("link", { name: "Satış ekle" })).toHaveAttribute(
      "href",
      "/gercek/islemler/yeni/satis",
    );
    expect(screen.queryByRole("link", { name: "Maaş günü planı" })).not.toBeInTheDocument();
    unmount();

    renderApp("/sanal/islemler", {
      "GET /api/oturum": () => json(SESSION),
      "GET /api/sanal/islemler": () => json({ table: tableState<TransactionItem>([]) }),
    });
    expect(await screen.findByRole("link", { name: "Sanal alım" })).toHaveAttribute(
      "href",
      "/sanal/islemler/yeni/alis",
    );
    expect(screen.getByRole("link", { name: "Sanal satış" })).toHaveAttribute(
      "href",
      "/sanal/islemler/yeni/satis",
    );
    expect(screen.getByRole("link", { name: "Maaş günü planı" })).toHaveAttribute(
      "href",
      "/sanal/maas-gunu",
    );
  });

  it("hiç işlem yoksa bunu söyler", async () => {
    open("/gercek/islemler", tableState<TransactionItem>([]));

    expect(await screen.findByText("Kayıtlı işlem yok.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
