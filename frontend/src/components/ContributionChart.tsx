import { BarChart } from "@mantine/charts";
import { Paper, Stack, Table, Text } from "@mantine/core";
import { useId } from "react";
import type { ContributionItem } from "../api/types";
import { money, monthLabel } from "../format/display";
import { ChartKey, compact, coordinate, TableToggle } from "./chart";

export function ContributionChart({ months }: { months: readonly ContributionItem[] }) {
  const captionId = useId();
  const first = months[0];
  const last = months.at(-1);
  if (first === undefined || last === undefined) {
    return null;
  }
  const description = `Son ${months.length} ayın net katkısı ve planlanan aylık katkı; ${monthLabel(first.month)} ile ${monthLabel(last.month)} arası.`;
  const data = months.map((month) => ({
    month: month.month,
    planned: coordinate(month.planned),
    invested: coordinate(month.invested),
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
          Katkı geçmişi
        </Text>
        <BarChart
          h={200}
          data={data}
          dataKey="month"
          role="img"
          aria-label={description}
          withTooltip={false}
          valueFormatter={compact}
          xAxisProps={{ tickFormatter: (month: string) => monthLabel(month) }}
          series={[
            { name: "planned", label: "Planlanan katkı", color: "var(--mantine-color-dimmed)" },
            {
              name: "invested",
              label: "Gerçekleşen net katkı",
              color: "var(--mantine-primary-color-filled)",
            },
          ]}
          barProps={(series) =>
            series.name === "planned"
              ? { fill: "none", stroke: "var(--mantine-color-dimmed)", strokeWidth: 1.5 }
              : {}
          }
        />
        <ul className="ft-legend" aria-label="Çubuklar">
          <li>
            <ChartKey kind="planned" />
            Planlanan katkı
          </li>
          <li>
            <ChartKey kind="actual" />
            Gerçekleşen net katkı
          </li>
        </ul>
        <TableToggle>
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Ay</Table.Th>
                <Table.Th ta="right">Planlanan</Table.Th>
                <Table.Th ta="right">Gerçekleşen</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {months.map((month) => (
                <Table.Tr key={month.month}>
                  <Table.Td>{monthLabel(month.month)}</Table.Td>
                  <Table.Td ta="right" className="ft-num">
                    {month.planned === null ? "tanımlı değil" : money(month.planned)}
                  </Table.Td>
                  <Table.Td ta="right" className="ft-num">
                    {money(month.invested)}
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
