import { type QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { DataRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import type { Api } from "./api/client";
import { ApiProvider } from "./api/context";

export function App({
  api,
  queryClient,
  router,
}: {
  api: Api;
  queryClient: QueryClient;
  router: DataRouter;
}) {
  return (
    <ApiProvider api={api}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </ApiProvider>
  );
}
