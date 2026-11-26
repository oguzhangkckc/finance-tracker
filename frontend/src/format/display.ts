// contracts/display'in karşılığı; ikisinin ayrışmasını parity.json yakalar (K-138, K-139).
import {
  abs,
  canonical,
  type Decimal,
  parseDecimal,
  plainText,
  roundHalfEven,
  scaleBy,
} from "./decimal";

// Yalın, ilgi (Kasım'ın), bulunma (Kasım'da) ve ayrılma (Kasım'dan) hâli.
export type Case = "" | "in" | "de" | "den";

type Sign = "-" | "+" | "";

function group(whole: string): string {
  return whole.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

// Binlik ayırıcı nokta, ondalık ayırıcı virgül; işaret yuvarlanmış değerden.
function digits(value: Decimal, places: number): { sign: Sign; text: string } {
  const rounded = roundHalfEven(value, places);
  const sign: Sign = rounded.units < 0n ? "-" : rounded.units > 0n ? "+" : "";
  const [whole = "", fraction] = plainText(abs(rounded)).split(",");
  return { sign, text: fraction === undefined ? group(whole) : `${group(whole)},${fraction}` };
}

export function money(value: string): string {
  const { sign, text } = digits(parseDecimal(value), 2);
  return `${sign === "-" ? "-" : ""}${text} TL`;
}

export function percent(
  rate: string,
  { places = 2, signed = false }: { places?: number; signed?: boolean } = {},
): string {
  const { sign, text } = digits(scaleBy(parseDecimal(rate), 2), places);
  return `${signed || sign === "-" ? sign : ""}%${text}`;
}

export function points(deviation: string): string {
  const { sign, text } = digits(scaleBy(parseDecimal(deviation), 2), 1);
  return `${sign}${text} puan`;
}

// Hedefe uzaklık işaretsiz ve renksiz söylenir; fazla olmak kazanç değildir (K-129).
export function gapText(deviation: string): string {
  const value = parseDecimal(deviation);
  const { text } = digits(scaleBy(abs(value), 2), 1);
  if (text === "0,0") {
    return "hedefte";
  }
  return `${text} puan ${value.units > 0n ? "fazla" : "eksik"}`;
}

export function exact(value: string): string {
  return plainText(canonical(parseDecimal(value)));
}

// Oran yüzde olarak, yuvarlamadan (sunum/setting_writes.percent_text): 0.175 → "17,5".
export function ratioPercent(ratio: string): string {
  return plainText(canonical(scaleBy(parseDecimal(ratio), 2)));
}

// Karşılaştırılan fiyatlar aynı basamak sayısıyla, en uzunun basamağıyla (K-128).
export function samePlaces(...values: (string | null)[]): (string | null)[] {
  const parsed = values.map((value) => (value === null ? null : parseDecimal(value)));
  const places = Math.max(0, ...parsed.map((value) => value?.scale ?? 0));
  return parsed.map((value) => (value === null ? null : plainText(roundHalfEven(value, places))));
}

export const MONTHS = [
  "Ocak",
  "Şubat",
  "Mart",
  "Nisan",
  "Mayıs",
  "Haziran",
  "Temmuz",
  "Ağustos",
  "Eylül",
  "Ekim",
  "Kasım",
  "Aralık",
] as const;

const VOWELS = "aıoueiöü";
const BACK_VOWELS = "aıou";
const VOICELESS = "fstkçşhp";
const GENITIVE_VOWEL: Readonly<Record<string, string>> = {
  a: "ı",
  ı: "ı",
  o: "u",
  u: "u",
  e: "i",
  i: "i",
  ö: "ü",
  ü: "ü",
};
const ONES = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"];
const TENS = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"];

// Ek, sayının okunuşundaki son kelimeye uyar (2026 → "altı", 2030 → "otuz").
function spokenTail(number: number): string {
  if (number % 10) {
    return ONES[number % 10] ?? "";
  }
  if (number % 100) {
    return TENS[Math.floor(number / 10) % 10] ?? "";
  }
  return number % 1000 ? "yüz" : "bin";
}

function suffix(word: string, grammaticalCase: Case): string {
  if (grammaticalCase === "") {
    return "";
  }
  const letters = [...word.toLowerCase()];
  const last = letters.at(-1) ?? "";
  const vowel = letters.findLast((letter) => VOWELS.includes(letter));
  if (vowel === undefined || last === "") {
    throw new Error(`Ünlüsü olmayan sözcüğe ek getirilemez: ${word}`);
  }
  if (grammaticalCase === "in") {
    return `'${VOWELS.includes(last) ? "n" : ""}${GENITIVE_VOWEL[vowel]}n`;
  }
  const consonant = VOICELESS.includes(last) ? "t" : "d";
  return `'${consonant}${BACK_VOWELS.includes(vowel) ? "a" : "e"}${grammaticalCase === "den" ? "n" : ""}`;
}

function isoParts(text: string, pattern: RegExp): number[] {
  const match = pattern.exec(text);
  if (match === null) {
    throw new Error(`ISO tarih bekleniyordu: ${JSON.stringify(text)}`);
  }
  return match.slice(1).map((part) => Number.parseInt(part, 10));
}

function monthName(month: number): string {
  const name = MONTHS[month - 1];
  if (name === undefined) {
    throw new Error(`Geçersiz ay: ${month}`);
  }
  return name;
}

// "25 Kasım"; yıl bugünkünden farklıysa ya da istenirse "25 Kasım 2026" (K-128).
export function dayLabel(
  day: string,
  {
    today,
    case: grammaticalCase = "",
    year,
  }: { today: string; case?: Case; year?: boolean | null },
): string {
  const [dayYear = 0, month = 0, dayOfMonth = 0] = isoParts(day, /^(\d{4})-(\d{2})-(\d{2})$/);
  const [todayYear] = isoParts(today, /^(\d{4})-\d{2}-\d{2}$/);
  const name = monthName(month);
  if (year ?? dayYear !== todayYear) {
    return `${dayOfMonth} ${name} ${dayYear}${suffix(spokenTail(dayYear), grammaticalCase)}`;
  }
  return `${dayOfMonth} ${name}${suffix(name, grammaticalCase)}`;
}

export function monthLabel(period: string, grammaticalCase: Case = ""): string {
  const [year = 0, month = 0] = isoParts(period, /^(\d{4})-(\d{2})$/);
  return `${monthName(month)} ${year}${suffix(spokenTail(year), grammaticalCase)}`;
}
