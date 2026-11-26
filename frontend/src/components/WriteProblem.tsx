import { Alert, Button, Stack, Text } from "@mantine/core";
import type { ApiError } from "../api/client";
import { retriable } from "../api/writes";
import { Icon } from "../layout/icons";

// Alan hatası alanın altında gösterilir; burada yalnız ne yapılacağı söylenir.
export function WriteProblem({ problem, onRetry }: { problem: ApiError; onRetry?: () => void }) {
  const fieldsOnly = Object.keys(problem.fields).length > 0;
  return (
    <Alert color="kiremit" variant="light" icon={<Icon name="hata" />} role="alert">
      <Stack gap="xs" align="flex-start">
        <Text size="sm">
          {fieldsOnly ? (
            <>
              <strong>Bir alan düzeltilmeli.</strong> Aşağıda işaretli.
            </>
          ) : (
            problem.message
          )}
        </Text>
        {problem.retryAfter != null && (
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
