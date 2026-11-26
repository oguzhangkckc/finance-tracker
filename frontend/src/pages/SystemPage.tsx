import { Group, Paper, Text, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useApi } from "../api/context";
import { systemQuery } from "../api/queries";
import type { RunItem, SystemData } from "../api/types";
import { useToday } from "../clock";
import { type DataColumn, DataTable, useTableQuery } from "../components/DataTable";
import { QueryView } from "../components/QueryView";
import { dayLabel } from "../format/display";
import { localTime } from "../format/time";
import { useProfile } from "../profile";
import { Page } from "./Page";

const CHECK_MARKS = { ok: "✓", warn: "!", fail: "✗" } as const;
const CHECK_WORDS = { ok: "geçti", warn: "uyarı", fail: "başarısız" } as const;

function System({ data }: { data: SystemData }) {
  const today = useToday();
  const columns: DataColumn<RunItem>[] = [
    { key: "no", label: "#", cell: (row) => row.id },
    { key: "is", label: "İş", cell: (row) => row.job },
    { key: "gun", label: "Gün", cell: (row) => dayLabel(row.logical_date, { today }) },
    {
      key: "durum",
      label: "Durum",
      cell: (row) => (
        <span
          className={row.status === "failed" || row.status === "partial" ? "ft-warn" : undefined}
        >
          {row.status_label}
        </span>
      ),
    },
    { key: "baslangic", label: "Başladı", cell: (row) => localTime(row.started_at, today) },
  ];
  return (
    <>
      <Title order={2}>Doctor</Title>
      <ul className="ft-cards" aria-label="Doctor">
        {data.checks.map((check) => (
          <li key={check.name}>
            <Paper withBorder p="sm" className="ft-surface">
              <Group justify="space-between" wrap="nowrap">
                <Text fw={700}>{check.name}</Text>
                <Text className={check.status === "ok" ? undefined : "ft-warn"}>
                  <span aria-hidden="true">{CHECK_MARKS[check.status]}</span>
                  <span className="ft-sr">{CHECK_WORDS[check.status]}</span>
                </Text>
              </Group>
              <Text size="sm" c="dimmed">
                {check.detail}
              </Text>
            </Paper>
          </li>
        ))}
      </ul>
      <Title order={2} mt="md">
        İş geçmişi
      </Title>
      <DataTable
        table={data.table}
        columns={columns}
        rowKey={(row) => row.id}
        noun="iş kaydı"
        empty="Henüz iş kaydı yok."
      />
      <Title order={2} mt="md">
        Yedek özetleri
      </Title>
      {data.backups.length > 0 ? (
        <ul className="ft-cards" aria-label="Yedek özetleri">
          {data.backups.map((backup) => (
            <li key={backup.name}>
              <Paper withBorder p="sm" className="ft-surface">
                <Group justify="space-between" wrap="wrap">
                  <Text size="sm">{backup.name}</Text>
                  <Text size="sm" className={backup.ok ? undefined : "ft-warn"}>
                    {backup.message}
                  </Text>
                </Group>
              </Paper>
            </li>
          ))}
        </ul>
      ) : (
        <Text>Yedek bulunamadı ya da yedek dizini tanımlı değil.</Text>
      )}
    </>
  );
}

export function SystemPage() {
  const query = useQuery(systemQuery(useApi(), useProfile(), useTableQuery()));
  return (
    <Page title="Sistem">
      <QueryView query={query}>{(data) => <System data={data} />}</QueryView>
    </Page>
  );
}
