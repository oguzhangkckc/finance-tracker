import { QueryClient, queryOptions } from "@tanstack/react-query";
import { type Api, unwrap } from "./client";

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 30_000 },
    },
  });
}

export function sessionQuery(api: Api) {
  return queryOptions({
    queryKey: ["oturum"],
    queryFn: () => unwrap(api.GET("/api/oturum")),
    staleTime: Number.POSITIVE_INFINITY,
  });
}
