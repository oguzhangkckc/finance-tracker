import type { ProfileSlug } from "../profile";
import type { IconName } from "./icons";

export interface NavItem {
  path: string;
  label: string;
  icon: IconName;
}

export const NAV: readonly NavItem[] = [
  { path: "", label: "Özet", icon: "ozet" },
  { path: "varliklar", label: "Varlıklar", icon: "varliklar" },
  { path: "islemler", label: "İşlemler", icon: "islemler" },
  { path: "dagilim", label: "Dağılım", icon: "dagilim" },
  { path: "getiri", label: "Getiri", icon: "getiri" },
  { path: "raporlar", label: "Raporlar", icon: "raporlar" },
  { path: "alarmlar", label: "Alarmlar", icon: "alarmlar" },
  { path: "ayarlar", label: "Ayarlar", icon: "ayarlar" },
  { path: "sistem", label: "Sistem", icon: "sistem" },
];

const MORE_TAB: NavItem = { path: "daha", label: "Daha fazla", icon: "daha" };

function pick(path: string): NavItem {
  const item = NAV.find((candidate) => candidate.path === path);
  if (item === undefined) {
    throw new Error(`Menüde ${path} yok.`);
  }
  return item;
}

// Telefonda dört sekme ve "Daha fazla"; geri kalanlar o sayfada (K-128).
export const TABS: readonly NavItem[] = [
  pick(""),
  pick("varliklar"),
  pick("islemler"),
  pick("raporlar"),
  MORE_TAB,
];

export const MORE: readonly NavItem[] = NAV.filter((item) => !TABS.includes(item));

export function href(profile: ProfileSlug, path: string): string {
  return path === "" ? `/${profile}` : `/${profile}/${path}`;
}

export function subpath(pathname: string, profile: ProfileSlug): string {
  return pathname.slice(profile.length + 1).replace(/^\/+|\/+$/g, "");
}

// Alt sayfa (ör. varliklar/lotlar) üst menü öğesini de seçili yapar.
export function isCurrent(path: string, rest: string): boolean {
  return path === rest || (path !== "" && rest.startsWith(`${path}/`));
}

export function isTabCurrent(path: string, rest: string): boolean {
  if (path === MORE_TAB.path) {
    return rest === MORE_TAB.path || MORE.some((item) => isCurrent(item.path, rest));
  }
  return isCurrent(path, rest);
}
