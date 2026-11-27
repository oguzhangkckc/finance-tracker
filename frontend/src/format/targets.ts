import { canonical, plainText } from "./decimal";

// K-127, K-139: yüzdeler virgüllü yazılır; toplam ölçekli tamsayıyla hesaplanır, kayan nokta
// yuvarlaması karışmaz. Metinler web'deki app.js'tekilerle aynı; asıl denetim sunucudadır.
const PERCENT = /^(\d+)(?:,(\d+))?$/;
const UNREADABLE = "Toplam hesaplanamadı: her alan virgüllü bir sayı olmalı (ör. 17,5).";

export interface TargetTotal {
  text: string;
  exact: boolean;
}

function percentText(units: bigint, scale: number): string {
  return plainText(canonical({ units, scale }));
}

export function targetTotal(values: readonly string[]): TargetTotal {
  const parts: { whole: string; fraction: string }[] = [];
  for (const value of values) {
    const match = PERCENT.exec(value.trim());
    if (match === null) {
      return { text: UNREADABLE, exact: false };
    }
    parts.push({ whole: match[1] ?? "", fraction: match[2] ?? "" });
  }
  const places = Math.max(0, ...parts.map((part) => part.fraction.length));
  const total = parts.reduce(
    (sum, part) => sum + BigInt(part.whole + part.fraction.padEnd(places, "0")),
    0n,
  );
  const hundred = 100n * 10n ** BigInt(places);
  if (total === hundred) {
    return { text: "Toplam %100", exact: true };
  }
  const gap = total < hundred ? hundred - total : total - hundred;
  const word = total < hundred ? "eksik" : "fazla";
  return {
    text: `Toplam %${percentText(total, places)} · %${percentText(gap, places)} ${word}`,
    exact: false,
  };
}
