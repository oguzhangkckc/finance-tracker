import { Stack, Title } from "@mantine/core";
import type { ReactNode } from "react";
import { PROFILE_LABELS, useProfile } from "../profile";

export function Page({ title, children }: { title: string; children?: ReactNode }) {
  const profile = useProfile();
  return (
    <Stack gap="md">
      <title>{[title, PROFILE_LABELS[profile], "finans-takip"].join(" · ")}</title>
      <Title order={1}>{title}</Title>
      {children}
    </Stack>
  );
}
