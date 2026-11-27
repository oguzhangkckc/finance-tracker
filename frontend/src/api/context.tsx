import { createContext, type ReactNode, use } from "react";
import type { Api } from "./client";

const ApiContext = createContext<Api | null>(null);

export function ApiProvider({ api, children }: { api: Api; children: ReactNode }) {
  return <ApiContext value={api}>{children}</ApiContext>;
}

export function useApi(): Api {
  const api = use(ApiContext);
  if (api === null) {
    throw new Error("useApi, ApiProvider'ın içinde çağrılmalı.");
  }
  return api;
}
