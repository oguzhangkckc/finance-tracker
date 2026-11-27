import { Center, Loader } from "@mantine/core";
import type { UseQueryResult } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { ErrorView } from "./ErrorView";

export function Loading() {
  return (
    <Center py="xl" role="status" aria-label="Yükleniyor">
      <Loader />
    </Center>
  );
}

// Veri gelmişse arka plandaki yenileme hatası sayfayı silmez.
export function QueryView<T>({
  query,
  children,
}: {
  query: UseQueryResult<T>;
  children: (data: T) => ReactNode;
}) {
  if (query.data !== undefined) {
    return children(query.data);
  }
  if (query.isError) {
    return <ErrorView error={query.error} onRetry={() => void query.refetch()} />;
  }
  return <Loading />;
}
