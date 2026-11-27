import { isLightColor } from "@mantine/core";
import { describe, expect, it } from "vitest";
import { PROFILES, type ProfileSlug } from "./profile";
import {
  ACCENT,
  LUMINANCE_THRESHOLD,
  ON_ACCENT,
  PRIMARY_SHADE,
  ramp,
  SEMANTIC,
  SURFACES,
  THEMES,
  TONES,
} from "./theme";

const AA = 4.5;
const NON_TEXT = 3;
const SCHEMES = ["light", "dark"] as const;
type Scheme = (typeof SCHEMES)[number];

function luminance(hex: string): number {
  const [r = 0, g = 0, b = 0] = [1, 3, 5].map((start) => {
    const channel = Number.parseInt(hex.slice(start, start + 2), 16) / 255;
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function ratio(first: string, second: string): number {
  const [high, low] = [luminance(first), luminance(second)].sort((a, b) => b - a);
  return ((high ?? 0) + 0.05) / ((low ?? 0) + 0.05);
}

function tokens(scheme: Scheme, profile: ProfileSlug): Record<string, string> {
  const tone = (name: keyof typeof TONES) => TONES[name][scheme];
  const soft = (name: keyof typeof TONES) =>
    scheme === "light" ? TONES[name].softLight : TONES[name].softDark;
  const surface = SURFACES[scheme];
  return {
    paper: surface.paper,
    surface: surface.surface,
    ink: surface.ink,
    "ink-2": surface.inkSoft,
    field: surface.field,
    accent: tone(ACCENT[profile]),
    "accent-soft": soft(ACCENT[profile]),
    "on-accent": ON_ACCENT[scheme],
    gain: tone(SEMANTIC.gain),
    "gain-soft": soft(SEMANTIC.gain),
    loss: tone(SEMANTIC.loss),
    "loss-soft": soft(SEMANTIC.loss),
    warn: tone(SEMANTIC.warn),
    "warn-soft": soft(SEMANTIC.warn),
  };
}

const CASES = SCHEMES.flatMap((scheme) => PROFILES.map((profile) => [scheme, profile] as const));

describe("K-128 renkleri", () => {
  it.each(CASES)("%s temada %s profilde WCAG AA sağlanır", (scheme, profile) => {
    const t = tokens(scheme, profile);
    const pairs: [string, string, number][] = [];
    for (const text of ["ink", "ink-2", "accent", "gain", "loss", "warn"]) {
      for (const back of ["paper", "surface"]) {
        pairs.push([text, back, AA]);
      }
    }
    pairs.push(["on-accent", "accent", AA]);
    for (const tone of ["accent", "gain", "loss", "warn"]) {
      pairs.push(["ink", `${tone}-soft`, AA], [tone, `${tone}-soft`, AA]);
    }
    // Form çerçevesi ve odak halkası metin değil, ama 3:1 gerekir (WCAG 1.4.11).
    pairs.push(["field", "surface", NON_TEXT], ["field", "paper", NON_TEXT]);
    pairs.push(["accent", "paper", NON_TEXT]);

    const weak = pairs
      .filter(([a, b, floor]) => ratio(t[a] ?? "", t[b] ?? "") < floor)
      .map(([a, b]) => `${a}/${b} ${ratio(t[a] ?? "", t[b] ?? "").toFixed(2)}`);

    expect(weak).toEqual([]);
  });

  it.each(SCHEMES)("%s temada sanal vurgu gerçeğinkinden ve uyarıdan ayrıdır", (scheme) => {
    expect(tokens(scheme, "sanal").accent).not.toBe(tokens(scheme, "gercek").accent);
    expect(tokens(scheme, "sanal").accent).not.toBe(tokens(scheme, "gercek").warn);
  });
});

describe("Mantine teması", () => {
  it.each(Object.entries(TONES))(
    "%s paletinde belirteçler Mantine'in okuduğu tonlardadır",
    (_, tone) => {
      const shades = ramp(tone);
      expect(shades).toHaveLength(10);
      expect(shades[1]).toBe(tone.softLight);
      expect(shades[PRIMARY_SHADE.light]).toBe(tone.light);
      expect(shades[PRIMARY_SHADE.dark]).toBe(tone.dark);
    },
  );

  it.each(CASES)("%s temada %s profilin düğme yazısı K-128'in rengidir", (scheme, profile) => {
    const theme = THEMES[profile];
    const accent = TONES[ACCENT[profile]][scheme];
    const chosen = isLightColor(accent, LUMINANCE_THRESHOLD) ? theme.black : theme.white;

    expect(theme.primaryColor).toBe(ACCENT[profile]);
    expect(chosen).toBe(ON_ACCENT[scheme]);
  });
});
