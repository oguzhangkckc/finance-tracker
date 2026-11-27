import { MantineProvider } from "@mantine/core";
import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { createMemoryRouter } from "react-router";
import { App } from "../App";
import { createApi } from "../api/client";
import { createQueryClient } from "../api/queries";
import { ClockProvider } from "../clock";
import { routes } from "../routes";
import { cssVariablesResolver, THEMES } from "../theme";
import { fakeFetch, type Handler, json, SESSION } from "./fetch";

// İstanbul'da 26 Kasım 2026, 12:00.
export const NOW = new Date("2026-11-26T09:00:00Z");

export function renderApp(
  path: string,
  handlers: Record<string, Handler> = { "GET /api/oturum": () => json(SESSION) },
) {
  const fetch = fakeFetch(handlers);
  const api = createApi({ fetch, onSessionExpired: () => false });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const view = render(
    <App api={api} queryClient={createQueryClient()} router={router} now={() => NOW} />,
  );
  return { ...view, router, fetch, user: userEvent.setup() };
}

export function renderPart(ui: ReactNode) {
  return render(
    <ClockProvider now={() => NOW}>
      <MantineProvider theme={THEMES.gercek} cssVariablesResolver={cssVariablesResolver}>
        {ui}
      </MantineProvider>
    </ClockProvider>,
  );
}

export function pageRoutes(path: string, body: unknown, status = 200): Record<string, Handler> {
  return { "GET /api/oturum": () => json(SESSION), [`GET ${path}`]: () => json(body, status) };
}
