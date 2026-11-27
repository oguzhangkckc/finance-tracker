import type { ReactNode } from "react";

// Web'deki simgelerin aynısı (src/finans/web/icons.py); renk currentColor'dan gelir.
const PATHS = {
  ozet: (
    <>
      <path d="M4 12a8 8 0 1 0 8-8v8z" />
      <path d="M15 3.5a8 8 0 0 1 5.5 5.5H15z" />
    </>
  ),
  varliklar: (
    <>
      <path d="M12 3 3 8l9 5 9-5z" />
      <path d="m3 13 9 5 9-5" />
    </>
  ),
  islemler: <path d="M7 4v14M4 15l3 3 3-3M17 20V6M14 9l3-3 3 3" />,
  dagilim: <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />,
  getiri: (
    <>
      <path d="M3 17l6-6 4 4 8-8" />
      <path d="M15 7h6v6" />
    </>
  ),
  raporlar: (
    <>
      <path d="M7 3h7l5 5v13H7z" />
      <path d="M14 3v5h5M10 13h6M10 17h6" />
    </>
  ),
  alarmlar: (
    <>
      <path d="M6 16V11a6 6 0 1 1 12 0v5l2 2H4z" />
      <path d="M10 21h4" />
    </>
  ),
  sistem: (
    <>
      <rect x="3" y="4" width="18" height="12" rx="2" />
      <path d="M8 20h8M12 16v4" />
    </>
  ),
  ayarlar: (
    <>
      <path d="M4 7h10M18 7h2M4 17h4M12 17h8" />
      <circle cx="16" cy="7" r="2" />
      <circle cx="10" cy="17" r="2" />
    </>
  ),
  daha: (
    <>
      <circle cx="5" cy="12" r="1.6" />
      <circle cx="12" cy="12" r="1.6" />
      <circle cx="19" cy="12" r="1.6" />
    </>
  ),
  uyari: (
    <>
      <path d="M12 3 2 20h20z" />
      <path d="M12 10v4M12 17h.01" />
    </>
  ),
  bilgi: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5M12 8h.01" />
    </>
  ),
  tamam: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m8 12 3 3 5-6" />
    </>
  ),
  hata: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v6M12 16h.01" />
    </>
  ),
  bos: (
    <>
      <rect x="4" y="4" width="16" height="16" rx="3" />
      <path d="M8 9h8M8 13h5" />
    </>
  ),
  hedef: (
    <>
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="4" />
    </>
  ),
} satisfies Record<string, ReactNode>;

export type IconName = keyof typeof PATHS;

const FILLED: ReadonlySet<IconName> = new Set(["daha"]);

export function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  const paint = FILLED.has(name)
    ? { fill: "currentColor" }
    : {
        fill: "none",
        stroke: "currentColor",
        strokeWidth: 1.8,
        strokeLinecap: "round" as const,
        strokeLinejoin: "round" as const,
      };
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      aria-hidden="true"
      focusable="false"
      {...paint}
    >
      {PATHS[name]}
    </svg>
  );
}
