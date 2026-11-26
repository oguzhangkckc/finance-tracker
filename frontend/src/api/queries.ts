import { QueryClient, queryOptions } from "@tanstack/react-query";
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

export function sessionQuery(api: Api) {
  return queryOptions({
    queryKey: ["oturum"],
    queryFn: () => unwrap(api.GET("/api/oturum")),
    staleTime: Number.POSITIVE_INFINITY,
  });
}
