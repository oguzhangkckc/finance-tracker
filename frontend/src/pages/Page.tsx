import { Stack, Title } from "@mantine/core";
import type { ReactNode } from "react";
import { PROFILE_LABELS, useProfile } from "../profile";

export function Page({
  title,
  hideTitle = false,
  children,
}: {
  title: string;
  hideTitle?: boolean;
  children?: ReactNode;
}) {
  const profile = useProfile();
  return (
    <Stack gap="md">
      <title>{[title, PROFILE_LABELS[profile], "finans-takip"].join(" · ")}</title>
      <Title order={1} className={hideTitle ? "ft-sr" : undefined}>
        {title}
      </Title>
      {children}
    </Stack>
  );
}

export function classLabels(names: Readonly<Record<string, string>>): (code: string) => string {
  return (code) => names[code] ?? code;
}
