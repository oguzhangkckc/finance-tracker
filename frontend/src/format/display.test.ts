import { describe, expect, it } from "vitest";
import {
  type Case,
  dayLabel,
  exact,
  gapText,
  money,
  monthLabel,
  percent,
  points,
  samePlaces,
} from "./display";
import parity from "./parity.json";

const CASES: readonly string[] = ["", "in", "de", "den"] satisfies Case[];

function asCase(value: string): Case {
  if (!CASES.includes(value)) {
    throw new Error(`Fikstürde bilinmeyen hâl: ${value}`);
  }
  return value as Case;
}

// Her satırın beklenen metni contracts/display'den üretildi (make bicim).
describe("contracts/display ile eşlik", () => {
  it.each(parity.money)("para $value → $text", ({ value, text }) => {
    expect(money(value)).toBe(text);
  });

  it.each(parity.percent)(
    "yüzde $value ($places basamak, işaretli: $signed) → $text",
    ({ value, places, signed, text }) => {
      expect(percent(value, { places, signed })).toBe(text);
    },
  );

  it.each(parity.points)("puan $value → $text", ({ value, text }) => {
    expect(points(value)).toBe(text);
  });

  it.each(parity.gap)("hedefe uzaklık $value → $text", ({ value, text }) => {
    expect(gapText(value)).toBe(text);
  });

  it.each(parity.exact)("kesin değer $value → $text", ({ value, text }) => {
    expect(exact(value)).toBe(text);
  });

  it.each(parity.same_places)("aynı basamak $values → $texts", ({ values, texts }) => {
    expect(samePlaces(...values)).toEqual(texts);
  });

  it.each(parity.day)("gün $day ($case, yıl: $year) → $text", (row) => {
    expect(dayLabel(row.day, { today: row.today, case: asCase(row.case), year: row.year })).toBe(
      row.text,
    );
  });

  it.each(parity.month)("ay $period ($case) → $text", ({ period, case: grammaticalCase, text }) => {
    expect(monthLabel(period, asCase(grammaticalCase))).toBe(text);
  });
});

describe("biçimlendiricinin girdisi", () => {
  it.each(["1e5", "1E+2", "1.", ".5", "1,5", "", " 1", "+1", "--1", "NaN", "Infinity"])(
    "%j ondalık metin değildir",
    (text) => {
      expect(() => money(text)).toThrow("Ondalık metin bekleniyordu");
    },
  );

  it("Number'ın kaybedeceği basamakları korur", () => {
    expect(exact("12345678901234567890.123456789")).toBe("12345678901234567890,123456789");
    expect(money("90071992547409931.005")).toBe("90.071.992.547.409.931,00 TL");
  });

  it.each(["2026-1-05", "26-11-25", "2026-13-01"])("%s geçerli bir gün değildir", (day) => {
    expect(() => dayLabel(day, { today: "2026-11-26" })).toThrow();
  });
});
