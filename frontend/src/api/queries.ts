import { keepPreviousData, QueryClient, queryOptions } from "@tanstack/react-query";
import type { ProfileSlug } from "../profile";
import { type Api, unwrap } from "./client";

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 30_000 },
    },
  });
}

export type ReportSlug = "haftalik" | "aylik" | "maas-gunu";

function path(profil: ProfileSlug) {
  return { params: { path: { profil } } };
}

export function overviewQuery(api: Api, profil: ProfileSlug) {
  return queryOptions({
    queryKey: ["sayfa", profil, "ozet"],
    queryFn: () => unwrap(api.GET("/api/{profil}/ozet", path(profil))),
  });
}

export function allocationQuery(api: Api, profil: ProfileSlug) {
  return queryOptions({
    queryKey: ["sayfa", profil, "dagilim"],
    queryFn: () => unwrap(api.GET("/api/{profil}/dagilim", path(profil))),
  });
}

export function returnsQuery(api: Api, profil: ProfileSlug) {
  return queryOptions({
    queryKey: ["sayfa", profil, "getiri"],
    queryFn: () => unwrap(api.GET("/api/{profil}/getiri", path(profil))),
  });
}

export function reportTextQuery(api: Api, profil: ProfileSlug, tur: ReportSlug) {
  return queryOptions({
    queryKey: ["sayfa", profil, "rapor", tur],
    queryFn: () =>
      unwrap(api.GET("/api/{profil}/raporlar/{tur}", { params: { path: { profil, tur } } })),
  });
}

// K-129: adresteki parametreler olduğu gibi gider; anlaşılmayanı API yok sayar ve adıyla bildirir.
function tableRequest(profil: ProfileSlug, query: string) {
  return { params: { path: { profil } }, querySerializer: () => query };
}

export function holdingsQuery(api: Api, profil: ProfileSlug, query: string) {
  return queryOptions({
    queryKey: ["sayfa", profil, "varliklar", query],
    queryFn: () => unwrap(api.GET("/api/{profil}/varliklar", tableRequest(profil, query))),
    placeholderData: keepPreviousData,
  });
}

export function lotsQuery(api: Api, profil: ProfileSlug, query: string) {
  return queryOptions({
    queryKey: ["sayfa", profil, "lotlar", query],
    queryFn: () => unwrap(api.GET("/api/{profil}/varliklar/lotlar", tableRequest(profil, query))),
    placeholderData: keepPreviousData,
  });
}

export function transactionsQuery(api: Api, profil: ProfileSlug, query: string) {
  return queryOptions({
    queryKey: ["sayfa", profil, "islemler", query],
    queryFn: () => unwrap(api.GET("/api/{profil}/islemler", tableRequest(profil, query))),
    placeholderData: keepPreviousData,
  });
}

export function alertsQuery(api: Api, profil: ProfileSlug, query: string) {
  return queryOptions({
    queryKey: ["sayfa", profil, "alarmlar", query],
    queryFn: () => unwrap(api.GET("/api/{profil}/alarmlar", tableRequest(profil, query))),
    placeholderData: keepPreviousData,
  });
}

export function systemQuery(api: Api, profil: ProfileSlug, query: string) {
  return queryOptions({
    queryKey: ["sayfa", profil, "sistem", query],
    queryFn: () => unwrap(api.GET("/api/{profil}/sistem", tableRequest(profil, query))),
    placeholderData: keepPreviousData,
  });
}

export function settingsQuery(api: Api, profil: ProfileSlug, query: string) {
  return queryOptions({
    queryKey: ["sayfa", profil, "ayarlar", query],
    queryFn: () => unwrap(api.GET("/api/{profil}/ayarlar", tableRequest(profil, query))),
    placeholderData: keepPreviousData,
  });
}

export function sessionQuery(api: Api) {
  return queryOptions({
    queryKey: ["oturum"],
    queryFn: () => unwrap(api.GET("/api/oturum")),
    staleTime: Number.POSITIVE_INFINITY,
  });
}
