import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter } from "react-router";
import { App } from "../App";
import { createApi } from "../api/client";
import { createQueryClient } from "../api/queries";
import { routes } from "../routes";
import { fakeFetch, type Handler, json, SESSION } from "./fetch";

export function renderApp(
  path: string,
  handlers: Record<string, Handler> = { "GET /api/oturum": () => json(SESSION) },
) {
  const fetch = fakeFetch(handlers);
  const api = createApi({ fetch, onSessionExpired: () => false });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const view = render(<App api={api} queryClient={createQueryClient()} router={router} />);
  return { ...view, router, fetch, user: userEvent.setup() };
}
