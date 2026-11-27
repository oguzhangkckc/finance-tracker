import type { ReactNode } from "react";

// Grafik koordinatı ve eksen etiketi yaklaşıktır; gösterilen kesin değerler metinden biçimlenir
// (K-139: Number() yalnız grafik koordinatı için).
export function coordinate(value: string | null): number | null {
  return value === null ? null : Number(value);
}

const COMPACT = new Intl.NumberFormat("tr-TR", { notation: "compact", maximumFractionDigits: 1 });

export function compact(value: number): string {
  return COMPACT.format(value);
}

type KeyKind = "value" | "invested" | "adjusted" | "planned" | "actual";

export function ChartKey({ kind }: { kind: KeyKind }) {
  return (
    <svg className="ft-key" viewBox="0 0 28 8" aria-hidden="true" focusable="false">
      {kind === "planned" || kind === "actual" ? (
        <rect className={`ft-key-${kind}`} x="1" y="1" width="26" height="6" />
      ) : (
        <line className={`ft-key-${kind}`} x1="1" y1="4" x2="27" y2="4" />
      )}
    </svg>
  );
}

// Her grafiğin tablo karşılığı vardır (K-129).
export function TableToggle({ children }: { children: ReactNode }) {
  return (
    <details className="ft-details">
      <summary>Tablo olarak göster</summary>
      {children}
    </details>
  );
}
