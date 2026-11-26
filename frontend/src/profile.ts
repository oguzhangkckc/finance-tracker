import { useParams } from "react-router";
import type { components } from "./api/schema";

export type ProfileSlug = components["schemas"]["ProfileSlug"];

export const PROFILES = ["gercek", "sanal"] as const satisfies readonly ProfileSlug[];

export const PROFILE_LABELS: Record<ProfileSlug, string> = { gercek: "Gerçek", sanal: "Sanal" };

export const SANAL_NOTICE = "SANAL — gerçek alım değil";

export function isProfileSlug(value: string | undefined): value is ProfileSlug {
  return PROFILES.some((profile) => profile === value);
}

// Profil sayfaları yalnız doğrulanmış profil altında açılır; varsayılana düşmek iki profili
// karıştırabilirdi (K-125).
export function useProfile(): ProfileSlug {
  const { profil } = useParams();
  if (!isProfileSlug(profil)) {
    throw new Error("Profil sayfası profil adresinin dışında açıldı.");
  }
  return profil;
}
