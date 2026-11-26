import { LineChart } from "@mantine/charts";
import { Paper, Stack, Table, Text } from "@mantine/core";
import { useId } from "react";
import type { ValueChartData, ValuePoint } from "../api/types";
import { useToday } from "../clock";
import { parseDecimal } from "../format/decimal";
import { dayLabel, money, monthLabel } from "../format/display";
import { ChartKey, compact, coordinate, TableToggle } from "./chart";

function Verdict({ gap }: { gap: string }) {
  const { units } = parseDecimal(gap);
  if (units > 0n) {
    return <>Değer, enflasyona göre güncellenmiş yatırımın {money(gap)} üstünde: reel kazanç.</>;
  }
  if (units < 0n) {
    return (
      <>Değer, enflasyona göre güncellenmiş yatırımın {money(gap.slice(1))} altında: reel kayıp.</>
    );
  }
  return <>Değer, enflasyona göre güncellenmiş yatırıma eşit: reel kazanç ya da kayıp yok.</>;
}

function Tooltip({ point, today }: { point: ValuePoint | undefined; today: string }) {
  if (point === undefined) {
    return null;
  }
  return (
    <Paper withBorder shadow="sm" p="xs" className="ft-surface">
      <Text size="sm" fw={600}>
        {dayLabel(point.day, { today })}
      </Text>
      <Text size="sm">Değer: {point.value === null ? "fiyat eksik" : money(point.value)}</Text>
      <Text size="sm">Yatırılan: {money(point.invested)}</Text>
      <Text size="sm">
        Güncellenmiş: {point.adjusted === null ? "TÜFE yok" : money(point.adjusted)}
      </Text>
    </Paper>
  );
}

// K-129: değer dolu çizgi, yatırılan para kesikli basamak, güncellenmiş yatırım noktalı.
export function ValueChart({ chart }: { chart: ValueChartData }) {
  const today = useToday();
  const captionId = useId();
  const { points } = chart;
  const first = points[0];
  const last = points.at(-1);
  if (first === undefined || last === undefined) {
    return null;
  }
  const description = `Haftalık portföy değeri, yatırılan para ve enflasyona göre güncellenmiş yatırım; ${dayLabel(first.day, { today })} ile ${dayLabel(last.day, { today })} arası.`;
  const data = points.map((point) => ({
    day: point.day,
    value: coordinate(point.value),
    invested: coordinate(point.invested),
    adjusted: coordinate(point.adjusted),
  }));
  return (
    <Paper
      component="figure"
      withBorder
      p="md"
      m={0}
      className="ft-surface"
      aria-labelledby={captionId}
    >
      <Stack gap="sm">
        <Text component="figcaption" fw={600} id={captionId}>
          Değerin seyri
        </Text>
        <LineChart
          h={220}
          data={data}
          dataKey="day"
          role="img"
          aria-label={description}
          withDots={false}
          connectNulls={false}
          valueFormatter={compact}
          xAxisProps={{ tickFormatter: (day: string) => dayLabel(day, { today }) }}
          tooltipProps={{
            content: ({ label }) => (
              <Tooltip point={points.find((point) => point.day === label)} today={today} />
            ),
          }}
          series={[
            {
              name: "value",
              label: "Portföy değeri",
              color: "var(--mantine-primary-color-filled)",
            },
            {
              name: "invested",
              label: "Yatırılan para (net katkı)",
              color: "var(--mantine-color-dimmed)",
              strokeDasharray: "6 4",
              curveType: "stepAfter",
            },
            {
              name: "adjusted",
              label: "Enflasyona göre güncellenmiş yatırım",
              color: "var(--mantine-color-text)",
              strokeDasharray: "1 4",
            },
          ]}
        />
        <ul className="ft-legend" aria-label="Çizgiler">
          <li>
            <ChartKey kind="value" />
            Portföy değeri
          </li>
          <li>
            <ChartKey kind="invested" />
            Yatırılan para (net katkı)
          </li>
          <li>
            <ChartKey kind="adjusted" />
            Enflasyona göre güncellenmiş yatırım
          </li>
        </ul>
        {chart.real_gap !== null && (
          <Text size="sm">
            <Verdict gap={chart.real_gap} />
          </Text>
        )}
        {chart.estimated_period !== null && (
          <Text size="sm" c="dimmed">
            TÜFE'si henüz açıklanmamış haftalarda (tabloda *) son açıklanan dönem,{" "}
            {monthLabel(chart.estimated_period)}, kullanıldı.
          </Text>
        )}
        <TableToggle>
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Hafta</Table.Th>
                <Table.Th ta="right">Değer</Table.Th>
                <Table.Th ta="right">Yatırılan para</Table.Th>
                <Table.Th ta="right">Enflasyona göre güncellenmiş</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {points.map((point) => (
                <Table.Tr key={point.day}>
                  <Table.Td>{dayLabel(point.day, { today })}</Table.Td>
                  <Table.Td ta="right" className="ft-num">
                    {point.value === null ? "fiyat eksik" : money(point.value)}
                  </Table.Td>
                  <Table.Td ta="right" className="ft-num">
                    {money(point.invested)}
                  </Table.Td>
                  <Table.Td ta="right" className="ft-num">
                    {point.adjusted === null
                      ? "TÜFE yok"
                      : `${money(point.adjusted)}${point.estimated ? " *" : ""}`}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </TableToggle>
      </Stack>
    </Paper>
  );
}
