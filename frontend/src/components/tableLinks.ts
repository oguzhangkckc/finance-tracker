// Tablo durumu adres parametrelerindedir (K-129); adlar sunum/table.py'dekilerle aynı.
export const SORT = "sirala";
export const DIRECTION = "yon";
export const PAGE = "sayfa";
export const SEARCH = "ara";
export const FROM = "bas";
export const TO = "bit";

export type Changes = Readonly<Record<string, string | null>>;

// Bağlantılar sunucunun anladığı parametrelerden kurulur; sayfa yalnız açıkça verilirse taşınır.
export function search(params: Readonly<Record<string, string>>, changes: Changes = {}): string {
  const next = new URLSearchParams(params);
  for (const [key, value] of Object.entries(changes)) {
    if (value === null || value === "") {
      next.delete(key);
    } else {
      next.set(key, value);
    }
  }
  const text = next.toString();
  return text === "" ? "" : `?${text}`;
}

export interface SortState {
  sort: string;
  descending: boolean;
  default_sort: string;
  default_descending: boolean;
  params: Readonly<Record<string, string>>;
}

// Seçili sütun tersine döner; başka sütun artan başlar, varsayılan sütun varsayılan yönüyle.
export function sortLink(table: SortState, key: string): string {
  const descending =
    key === table.sort ? !table.descending : key === table.default_sort && table.default_descending;
  return search(table.params, {
    [SORT]: key,
    [DIRECTION]: descending ? "azalan" : "artan",
    [PAGE]: null,
  });
}

export function ariaSort(table: SortState, key: string): "ascending" | "descending" | "none" {
  if (key !== table.sort) {
    return "none";
  }
  return table.descending ? "descending" : "ascending";
}
