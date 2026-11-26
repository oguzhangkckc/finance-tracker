import { vi } from "vitest";
import type { components } from "../api/schema";

export type Handler = (request: Request) => Response | Promise<Response>;

export function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

export const SESSION = {
  email: "kullanici@example.com",
  profiles: [
    { slug: "gercek", label: "Gerçek" },
    { slug: "sanal", label: "Sanal" },
  ],
  default_profile: "gercek",
} satisfies components["schemas"]["Session"];

export function fakeFetch(routes: Record<string, Handler>) {
  return vi.fn(async (request: Request) => {
    const handler = routes[`${request.method} ${new URL(request.url).pathname}`];
    return handler === undefined ? json({ error: "Bulunamadı." }, 404) : handler(request);
  });
}
