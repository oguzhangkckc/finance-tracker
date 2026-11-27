import { describe, expect, it } from "vitest";
import { ariaSort, search, sortLink } from "./tableLinks";

const STATE = {
  sort: "tarih",
  descending: true,
  default_sort: "tarih",
  default_descending: true,
  params: { fon: "XHT", sayfa: "2" },
};

describe("tablo bağlantıları", () => {
  it("parametreyi değiştirir, boş ya da null değeri çıkarır, sırayı korur", () => {
    expect(search({ fon: "XHT", ara: "x" }, { fon: "XPP", ara: null, bas: "2026-11-01" })).toBe(
      "?fon=XPP&bas=2026-11-01",
    );
    expect(search({ fon: "XHT" }, { fon: "" })).toBe("");
    expect(search({ ara: "dekont 12" })).toBe("?ara=dekont+12");
  });

  it("seçili sütunu tersine çevirir ve sayfayı bırakır", () => {
    expect(sortLink(STATE, "tarih")).toBe("?fon=XHT&sirala=tarih&yon=artan");
  });

  it("başka sütun artan başlar", () => {
    expect(sortLink(STATE, "tutar")).toBe("?fon=XHT&sirala=tutar&yon=artan");
  });

  it("varsayılan sütuna dönüş varsayılan yönle olur", () => {
    const byFund = { ...STATE, sort: "fon", descending: false };
    expect(sortLink(byFund, "tarih")).toBe("?fon=XHT&sirala=tarih&yon=azalan");
  });

  it("yalnız seçili sütun sıralı sayılır", () => {
    expect(ariaSort(STATE, "tarih")).toBe("descending");
    expect(ariaSort({ ...STATE, descending: false }, "tarih")).toBe("ascending");
    expect(ariaSort(STATE, "fon")).toBe("none");
  });
});
