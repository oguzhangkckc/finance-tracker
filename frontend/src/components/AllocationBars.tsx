import { Group, Paper, Stack, Text } from "@mantine/core";
import type { AlertLine, AllocationLine } from "../api/types";
import { gapText, percent } from "../format/display";
import { Icon } from "../layout/icons";

// Çubuk yalnız koordinattır (K-139); anlamı yanındaki metin taşır.
function share(rate: string): string {
  return `${Math.min(Math.max(Number(rate), 0), 1) * 100}%`;
}

// K-129: sapma yeşil ya da kırmızıyla gösterilmez; açık alarmı olan sınıf Kehribar ve ⚠ alır.
export function AllocationBars({
  lines,
  alerts,
  label,
}: {
  lines: readonly AllocationLine[];
  alerts: readonly AlertLine[];
  label: (code: string) => string;
}) {
  const alerted = new Set(alerts.map((alert) => alert.asset_class));
  return (
    <Paper withBorder p="md" className="ft-surface">
      <Stack gap="md">
        {lines.map((line) => {
          const alarm = alerted.has(line.asset_class);
          return (
            <div key={line.asset_class}>
              <Group justify="space-between" wrap="nowrap" gap="xs" align="baseline">
                <Text fw={600}>{label(line.asset_class)}</Text>
                <Text className="ft-num" ta="right">
                  {percent(line.weight, { places: 1 })}{" "}
                  <Text span c="dimmed" size="sm">
                    · hedef {percent(line.target, { places: 1 })} · {gapText(line.deviation)}
                  </Text>
                </Text>
              </Group>
              <div className="ft-bar" aria-hidden="true">
                <div
                  className="ft-bar-fill"
                  data-alarm={alarm || undefined}
                  style={{ width: share(line.weight) }}
                />
                <div className="ft-bar-target" style={{ left: share(line.target) }} />
              </div>
              {alarm && (
                <Group gap={4} className="ft-warn">
                  <Icon name="uyari" size={16} />
                  <Text size="sm">Alarm eşiği aşıldı</Text>
                </Group>
              )}
            </div>
          );
        })}
      </Stack>
    </Paper>
  );
}
