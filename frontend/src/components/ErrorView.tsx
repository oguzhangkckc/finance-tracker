import { Alert, Button, Stack, Text } from "@mantine/core";
import { ApiError, NETWORK_STATUS } from "../api/client";
import { Icon } from "../layout/icons";

function retriable(problem: ApiError | null): boolean {
  return problem === null || problem.status === NETWORK_STATUS || problem.status >= 500;
}

export function ErrorView({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const problem = error instanceof ApiError ? error : null;
  return (
    <Alert
      color="kiremit"
      variant="light"
      icon={<Icon name="hata" />}
      title="Sayfa yüklenemedi"
      role="alert"
    >
      <Stack gap="sm" align="flex-start">
        <Text size="sm">{problem?.message ?? "Beklenmeyen bir hata oluştu."}</Text>
        {problem?.retryAfter != null && (
          <Text size="sm">{`${problem.retryAfter} saniye sonra yeniden deneyebilirsin.`}</Text>
        )}
        {onRetry !== undefined && retriable(problem) && (
          <Button variant="default" onClick={onRetry}>
            Yeniden dene
          </Button>
        )}
      </Stack>
    </Alert>
  );
}
