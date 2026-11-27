import type { components } from "../api/schema";

// Bütün tablo yanıtları satır tipi dışında aynı biçimdedir (api/tables.py Table).
export type TableData<R> = Omit<components["schemas"]["Table_RunItem_"], "rows"> & { rows: R[] };

const DIRECTIONS = ["artan", "azalan"];

export function tableState<R>(rows: R[], overrides: Partial<TableData<R>> = {}): TableData<R> {
  return {
    rows,
    total: rows.length,
    page: 1,
    pages: 1,
    page_size: 25,
    sort: "tarih",
    descending: true,
    default_sort: "tarih",
    default_descending: true,
    params: {},
    active: [],
    ignored: "",
    columns: [
      { key: "tarih", label: "Tarih", directions: DIRECTIONS },
      { key: "fon", label: "Fon", directions: DIRECTIONS },
      { key: "tutar", label: "Tutar", directions: DIRECTIONS },
      { key: "no", label: "#", directions: DIRECTIONS },
    ],
    choices: [],
    day_filter: false,
    search: false,
    ...overrides,
  };
}
