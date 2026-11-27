import { describe, expect, it } from "vitest";
import parity from "./format/parity.json";
import { PROFILE_LABELS, PROFILES, SANAL_NOTICE } from "./profile";

// Etiketler ve bant metni Python'dakilerle aynı olmalı (sunum/profiles.py, contracts/report.py).
describe("profil metinleri", () => {
  it("profil etiketleri sunucudakilerle aynıdır", () => {
    expect(PROFILE_LABELS).toEqual(parity.labels.profiles);
    expect([...PROFILES].sort()).toEqual(Object.keys(parity.labels.profiles).sort());
  });

  it("sanal bant metni rapordakiyle aynıdır", () => {
    expect(SANAL_NOTICE).toBe(parity.labels.sanal_notice);
  });
});
