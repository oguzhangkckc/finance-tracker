import { Alert, Group, Paper, Text } from "@mantine/core";
import type { ReactNode } from "react";
import { Icon } from "../layout/icons";

export function Warning({ children }: { children: ReactNode }) {
  return (
    <Alert color="kehribar" variant="light" icon={<Icon name="uyari" />} role="status">
      {children}
    </Alert>
  );
}

// K-128: boş sayfa yapılacak işi söyler.
export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <Paper withBorder p="md" className="ft-surface">
      <Group gap="sm" wrap="nowrap" c="dimmed">
        <Icon name="bos" />
        <Text size="sm">{children}</Text>
      </Group>
    </Paper>
  );
}
