import { Paper, Stack, Table, Text, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useApi } from "../api/context";
import { allocationQuery } from "../api/queries";
import type { AllocationData } from "../api/types";
import { useToday } from "../clock";
import { AllocationBars } from "../components/AllocationBars";
import { EmptyState, Warning } from "../components/Notice";
import { QueryView } from "../components/QueryView";
import { dayLabel, money, percent, points } from "../format/display";
import { localDay } from "../format/time";
import { useProfile } from "../profile";
import { QUIET_PERIOD } from "./OverviewPage";
import { classLabels, Page } from "./Page";

function Allocation({ data }: { data: AllocationData }) {
  const today = useToday();
  const { report } = data;
  const label = classLabels(data.class_names);
  const skipped = report.allocation_skipped ?? [];
  return (
    <Stack gap="md">
      <Text c="dimmed">Değerleme günü {dayLabel(report.logical_date, { today })}</Text>
      {skipped.length > 0 ? (
        <Warning>
          <strong>Dağılım hesaplanmadı; fiyatı eksik: {skipped.join(", ")}.</strong> Fiyat gelince
          kendiliğinden hesaplanır.
        </Warning>
      ) : report.allocation.length > 0 ? (
        <>
          <AllocationBars lines={report.allocation} alerts={report.alerts} label={label} />
          <Table.ScrollContainer minWidth={480}>
            <Table>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Sınıf</Table.Th>
                  <Table.Th ta="right">Değer</Table.Th>
                  <Table.Th ta="right">Ağırlık</Table.Th>
                  <Table.Th ta="right">Hedef</Table.Th>
                  <Table.Th ta="right">Sapma</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {report.allocation.map((line) => (
                  <Table.Tr key={line.asset_class}>
                    <Table.Td fw={700}>{label(line.asset_class)}</Table.Td>
                    <Table.Td ta="right" className="ft-num">
                      {money(line.value)}
                    </Table.Td>
                    <Table.Td ta="right" className="ft-num">
                      {percent(line.weight, { places: 1 })}
                    </Table.Td>
                    <Table.Td ta="right" className="ft-num">
                      {percent(line.target, { places: 1 })}
                    </Table.Td>
                    <Table.Td ta="right" className="ft-num">
                      {points(line.deviation)}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </>
      ) : (
        <EmptyState>Henüz dağılım yok; dağılım içi bir fona işlem girilince hesaplanır.</EmptyState>
      )}
      {report.quiet_period && (
        <Text size="sm" c="dimmed">
          {QUIET_PERIOD}
        </Text>
      )}

      <Title order={2} mt="md">
        Açık alarmlar
      </Title>
      {report.alerts.length > 0 ? (
        <ul className="ft-cards" aria-label="Açık alarmlar">
          {report.alerts.map((alert) => (
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
      ) : (
        <Text>Açık alarm yok.</Text>
      )}
    </Stack>
  );
}

export function AllocationPage() {
  const query = useQuery(allocationQuery(useApi(), useProfile()));
  return (
    <Page title="Dağılım">
      <QueryView query={query}>{(data) => <Allocation data={data} />}</QueryView>
    </Page>
  );
}
