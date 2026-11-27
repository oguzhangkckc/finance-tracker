import {
  type CSSVariablesResolver,
  createTheme,
  type MantineColorsTuple,
  type MantineThemeOverride,
} from "@mantine/core";
import type { ProfileSlug } from "./profile";

type Hex = `#${string}`;

interface Tone {
  light: Hex;
  softLight: Hex;
  dark: Hex;
  softDark: Hex;
}

type Scheme = "light" | "dark";

// K-128. Mantine metni açık temada birincil tondan (7), koyu temada 4. tondan alır;
// belirteçler bu iki tona oturur.
export const TONES = {
  petrol: { light: "#0A6763", softLight: "#E2F0EE", dark: "#5CC3BC", softDark: "#123330" },
  murdum: { light: "#6B3FA0", softLight: "#F0E8F8", dark: "#C4A7F5", softDark: "#2A2140" },
  yaprak: { light: "#1B7340", softLight: "#E4F1E8", dark: "#6FCF91", softDark: "#14291C" },
  kiremit: { light: "#B03A2E", softLight: "#F7E6E3", dark: "#F2927F", softDark: "#3A1E1A" },
  kehribar: { light: "#855800", softLight: "#FAEFD7", dark: "#E6B450", softDark: "#31270F" },
} as const satisfies Record<string, Tone>;

export type ToneName = keyof typeof TONES;

export const SURFACES = {
  light: {
    paper: "#F6F5F1",
    surface: "#FFFFFF",
    ink: "#1B2228",
    inkSoft: "#5A636D",
    line: "#DCD9D1",
    field: "#868E97",
  },
  dark: {
    paper: "#0F1316",
    surface: "#171C20",
    ink: "#E7E9EC",
    inkSoft: "#A1AAB3",
    line: "#2A3137",
    field: "#6E7882",
  },
} as const satisfies Record<Scheme, Record<string, Hex>>;

export const ON_ACCENT = { light: "#FFFFFF", dark: "#0F1316" } as const satisfies Record<
  Scheme,
  Hex
>;

export const ACCENT: Record<ProfileSlug, ToneName> = { gercek: "petrol", sanal: "murdum" };

export const SEMANTIC = { gain: "yaprak", loss: "kiremit", warn: "kehribar" } as const;

export const PRIMARY_SHADE = { light: 7, dark: 4 } as const;

export const LUMINANCE_THRESHOLD = 0.3;

const FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

function channels(hex: Hex): [number, number, number] {
  const value = Number.parseInt(hex.slice(1), 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

export function mix(from: Hex, to: Hex, share: number): Hex {
  const target = channels(to);
  const parts = channels(from).map((channel, index) => {
    const end = target[index] ?? channel;
    return Math.round(channel + (end - channel) * share)
      .toString(16)
      .padStart(2, "0");
  });
  return `#${parts.join("").toUpperCase()}`;
}

export function ramp(tone: Tone): MantineColorsTuple {
  return [
    mix(tone.softLight, "#FFFFFF", 0.5),
    tone.softLight,
    mix(tone.softLight, tone.dark, 1 / 3),
    mix(tone.softLight, tone.dark, 2 / 3),
    tone.dark,
    mix(tone.dark, tone.light, 1 / 3),
    mix(tone.dark, tone.light, 2 / 3),
    tone.light,
    mix(tone.light, "#000000", 0.2),
    mix(tone.light, "#000000", 0.4),
  ];
}

const dark = SURFACES.dark;

// Mantine koyu temada bileşen zeminlerini ve çizgilerini `dark` paletinden alır.
const DARK_PALETTE: MantineColorsTuple = [
  dark.ink,
  mix(dark.ink, dark.inkSoft, 0.5),
  dark.inkSoft,
  dark.field,
  dark.line,
  mix(dark.line, dark.surface, 0.5),
  dark.surface,
  dark.paper,
  mix(dark.paper, "#000000", 0.3),
  mix(dark.paper, "#000000", 0.6),
];

const COLORS = {
  ...Object.fromEntries(Object.entries(TONES).map(([name, tone]) => [name, ramp(tone)])),
  dark: DARK_PALETTE,
};

function themeFor(profile: ProfileSlug): MantineThemeOverride {
  return createTheme({
    primaryColor: ACCENT[profile],
    primaryShade: PRIMARY_SHADE,
    colors: COLORS,
    white: ON_ACCENT.light,
    black: ON_ACCENT.dark,
    autoContrast: true,
    luminanceThreshold: LUMINANCE_THRESHOLD,
    fontFamily: FONT,
    headings: { fontFamily: FONT },
    respectReducedMotion: true,
    cursorType: "pointer",
    defaultRadius: "md",
  });
}

export const THEMES: Record<ProfileSlug, MantineThemeOverride> = {
  gercek: themeFor("gercek"),
  sanal: themeFor("sanal"),
};

function schemeVariables(scheme: Scheme): Record<string, string> {
  const surface = SURFACES[scheme];
  const variables: Record<string, string> = {
    "--mantine-color-body": surface.paper,
    "--mantine-color-text": surface.ink,
    "--mantine-color-dimmed": surface.inkSoft,
    "--mantine-color-default-border": surface.line,
    "--ft-surface": surface.surface,
    "--ft-line": surface.line,
    "--ft-field": surface.field,
  };
  for (const [name, tone] of Object.entries(TONES)) {
    variables[`--mantine-color-${name}-light`] =
      scheme === "light" ? tone.softLight : tone.softDark;
    variables[`--mantine-color-${name}-light-color`] = scheme === "light" ? tone.light : tone.dark;
  }
  for (const [meaning, name] of Object.entries(SEMANTIC)) {
    const tone = TONES[name];
    variables[`--ft-${meaning}`] = scheme === "light" ? tone.light : tone.dark;
    variables[`--ft-${meaning}-soft`] = scheme === "light" ? tone.softLight : tone.softDark;
  }
  return variables;
}

export const cssVariablesResolver: CSSVariablesResolver = () => ({
  variables: {},
  light: schemeVariables("light"),
  dark: schemeVariables("dark"),
});
