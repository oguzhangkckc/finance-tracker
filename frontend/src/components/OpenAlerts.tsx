import { Paper, Text } from "@mantine/core";
import type { AlertLine } from "../api/types";
import { useToday } from "../clock";
import { points } from "../format/display";
import { localDay } from "../format/time";

export function OpenAlerts({
  alerts,
  label,
}: {
  alerts: readonly AlertLine[];
  label: (code: string) => string;
}) {
  const today = useToday();
  if (alerts.length === 0) {
    return <Text>Açık alarm yok.</Text>;
  }
  return (
    <ul className="ft-cards" aria-label="Açık alarmlar">
      {alerts.map((alert) => (
        <li key={alert.asset_class}>
          <Paper withBorder p="sm" className="ft-surface">
            <Text fw={700}>
              {label(alert.asset_class)}
              {alert.deviation !== null && (
                <Text span className="ft-num" fw={400}>
                  {" "}
                  · {points(alert.deviation)}
                </Text>
              )}
            </Text>
            <Text size="sm" c="dimmed">
              {alert.direction === "above" ? "hedefin üstünde" : "hedefin altında"} · açıldı{" "}
              {localDay(alert.opened_at, today)}
            </Text>
          </Paper>
        </li>
      ))}
    </ul>
  );
}
