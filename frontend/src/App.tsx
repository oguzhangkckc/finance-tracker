import { type QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { DataRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import type { Api } from "./api/client";
import { ApiProvider } from "./api/context";
import { ClockProvider } from "./clock";

function systemNow(): Date {
  return new Date();
}

export function App({
  api,
  queryClient,
  router,
  now = systemNow,
}: {
  api: Api;
  queryClient: QueryClient;
  router: DataRouter;
  now?: () => Date;
}) {
  return (
    <ClockProvider now={now}>
      <ApiProvider api={api}>
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </ApiProvider>
    </ClockProvider>
  );
}
