import { describe, expect, it } from "vitest";
import { targetTotal } from "./targets";

const UNREADABLE = "Toplam hesaplanamadı: her alan virgüllü bir sayı olmalı (ör. 17,5).";

describe("hedef toplamı", () => {
  it.each([
    [["62,5", "37,5"], "Toplam %100", true],
    [["40", "60,00"], "Toplam %100", true],
    [[" 50 ", "50"], "Toplam %100", true],
    [["0,05", "99,95"], "Toplam %100", true],
    [["33,333333333333333333", "66,666666666666666667"], "Toplam %100", true],
    [["33,3", "33,3", "33,3"], "Toplam %99,9 · %0,1 eksik", false],
    [["60", "50"], "Toplam %110 · %10 fazla", false],
    [["17,50", "17,5"], "Toplam %35 · %65 eksik", false],
    [[], "Toplam %0 · %100 eksik", false],
  ])("%j → %s", (values, text, exact) => {
    expect(targetTotal(values)).toEqual({ text, exact });
  });

  it.each([[["17,5", "abc"]], [["", "100"]], [["17.5", "82,5"]], [["-10", "110"]]])(
    "%j okunamaz",
    (values) => {
      expect(targetTotal(values)).toEqual({ text: UNREADABLE, exact: false });
    },
  );
});
