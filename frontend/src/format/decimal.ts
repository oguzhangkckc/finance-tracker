// Para ve oran istemcide Number'a çevrilmez (K-139): değer = units / 10^scale.
export interface Decimal {
  readonly units: bigint;
  readonly scale: number;
}

// API Decimal'i üstel gösterimsiz metin olarak gönderir (K-138); başka biçim hatadır.
const PATTERN = /^(-)?(\d+)(?:\.(\d+))?$/;

export function parseDecimal(text: string): Decimal {
  const match = PATTERN.exec(text);
  if (match === null) {
    throw new Error(`Ondalık metin bekleniyordu: ${JSON.stringify(text)}`);
  }
  const [, minus, whole = "", fraction = ""] = match;
  const units = BigInt(whole + fraction);
  return { units: minus === undefined ? units : -units, scale: fraction.length };
}

function pow10(exponent: number): bigint {
  return 10n ** BigInt(exponent);
}

export function abs(value: Decimal): Decimal {
  return value.units < 0n ? { units: -value.units, scale: value.scale } : value;
}

export function scaleBy(value: Decimal, exponent: number): Decimal {
  const scale = value.scale - exponent;
  return scale >= 0
    ? { units: value.units, scale }
    : { units: value.units * pow10(-scale), scale: 0 };
}

// Banker yuvarlaması; Python'daki quantize(..., ROUND_HALF_EVEN) ile aynı sonuç.
export function roundHalfEven(value: Decimal, places: number): Decimal {
  if (value.scale <= places) {
    return { units: value.units * pow10(places - value.scale), scale: places };
  }
  const factor = pow10(value.scale - places);
  const quotient = value.units / factor;
  const remainder = value.units % factor;
  const twice = (remainder < 0n ? -remainder : remainder) * 2n;
  const away = twice > factor || (twice === factor && quotient % 2n !== 0n);
  const step = value.units < 0n ? -1n : 1n;
  return { units: away ? quotient + step : quotient, scale: places };
}

// K-52: sondaki sıfırlar atılır, -0 yoktur.
export function canonical(value: Decimal): Decimal {
  let { units, scale } = value;
  while (scale > 0 && units % 10n === 0n) {
    units /= 10n;
    scale -= 1;
  }
  return { units, scale: units === 0n ? 0 : scale };
}

export function plainText(value: Decimal): string {
  const negative = value.units < 0n;
  const digits = (negative ? -value.units : value.units).toString().padStart(value.scale + 1, "0");
  const cut = digits.length - value.scale;
  const fraction = value.scale > 0 ? `,${digits.slice(cut)}` : "";
  return `${negative ? "-" : ""}${digits.slice(0, cut)}${fraction}`;
}
