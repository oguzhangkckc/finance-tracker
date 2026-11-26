import { Text, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useApi } from "../api/context";
import { alertsQuery } from "../api/queries";
import type { AlertEventItem, AlertsData } from "../api/types";
import { useToday } from "../clock";
import { type DataColumn, DataTable, useTableQuery } from "../components/DataTable";
import { OpenAlerts } from "../components/OpenAlerts";
import { QueryView } from "../components/QueryView";
import { dayLabel, points } from "../format/display";
import { localTime } from "../format/time";
import { useProfile } from "../profile";
import { QUIET_PERIOD } from "./OverviewPage";
import { classLabels, Page } from "./Page";

function Alerts({ data }: { data: AlertsData }) {
  const today = useToday();
  const columns: DataColumn<AlertEventItem>[] = [
    { key: "tarih", label: "Tarih", cell: (row) => localTime(row.occurred_at, today) },
    { key: "sinif", label: "Sınıf", cell: (row) => row.class_name },
    {
      key: "olay",
      label: "Olay",
      cell: (row) =>
        `${row.kind === "opened" ? "açıldı" : "kapandı"} · ${row.direction === "above" ? "hedefin üstünde" : "hedefin altında"}`,
    },
    { key: "sapma", label: "Sapma", numeric: true, cell: (row) => points(row.deviation) },
    {
      key: "bildirim",
      label: "Bildirim",
      cell: (row) => (row.notified_at === null ? "bekliyor" : localTime(row.notified_at, today)),
    },
  ];
  return (
    <>
      {data.quiet_ended === null ? (
        <Text size="sm" c="dimmed">
          {QUIET_PERIOD}
        </Text>
      ) : (
        <Text c="dimmed">
          Sessiz dönem {dayLabel(data.quiet_ended, { today, case: "de" })} bitti; sapma alarmları
          açık.
        </Text>
      )}
      <OpenAlerts alerts={data.alerts} label={classLabels(data.class_names)} />
      <Title order={2} mt="md">
        Alarm geçmişi
      </Title>
      <DataTable
        table={data.table}
        columns={columns}
        rowKey={(row) => row.id}
        noun="alarm olayı"
        empty="Henüz alarm olayı yok."
      />
    </>
  );
}

export function AlertsPage() {
  const query = useQuery(alertsQuery(useApi(), useProfile(), useTableQuery()));
  return (
    <Page title="Alarmlar">
      <QueryView query={query}>{(data) => <Alerts data={data} />}</QueryView>
    </Page>
  );
}
