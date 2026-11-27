import { Center, Container, Loader } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { Navigate } from "react-router";
import { useApi } from "../api/context";
import { sessionQuery } from "../api/queries";
import { ErrorView } from "../components/ErrorView";
import { href } from "../layout/nav";

export function OpenDefaultProfile() {
  const session = useQuery(sessionQuery(useApi()));
  if (session.data) {
    return <Navigate to={href(session.data.default_profile, "")} replace />;
  }
  if (session.isError) {
    return (
      <Container size="sm" py="xl">
        <ErrorView error={session.error} onRetry={() => void session.refetch()} />
      </Container>
    );
  }
  return (
    <Center py="xl" role="status" aria-label="Yükleniyor">
      <Loader />
    </Center>
  );
}
