import { Anchor, Button, Code, Group, Paper, Text, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { useApi } from "../api/context";
import { settingsQuery } from "../api/queries";
import type { SettingItem, SettingsData } from "../api/types";
import { useToday } from "../clock";
import { type DataColumn, DataTable, useTableQuery } from "../components/DataTable";
import { QueryView } from "../components/QueryView";
import { dayLabel, money, ratioPercent } from "../format/display";
import { localTime } from "../format/time";
import { href } from "../layout/nav";
import { type ProfileSlug, useProfile } from "../profile";
import { classLabels, Page } from "./Page";

const INITIAL = "Başlangıç (portfolio.toml)";

function Changes({ item }: { item: SettingItem }) {
  if (item.changes.length === 0) {
    return <>değişiklik yok</>;
  }
  return (
    <>
      {item.changes.map((change) => (
        <div key={change.setting}>
          {change.setting}: {change.change}
        </div>
      ))}
    </>
  );
}

function Current({ data, today }: { data: SettingsData; today: string }) {
  const label = classLabels(data.class_names);
  const { current } = data;
  return (
    <>
      {data.current_id === null ? (
        <Text size="sm" c="dimmed">
          Ayar sürümü yok; portfolio.toml kullanılıyor. Başlangıç sürümünü{" "}
          <Code>ft config apply</Code> yazar.
        </Text>
      ) : data.current_from === null ? (
        <Text c="dimmed">{INITIAL}</Text>
      ) : (
        <Text c="dimmed">
          {dayLabel(data.current_from, { today, case: "den" })} beri geçerli · #{data.current_id}
        </Text>
      )}
      <Paper withBorder p="md" className="ft-surface">
        <dl className="ft-summary">
          <div className="ft-summary-row">
            <dt>Maaş günü</dt>
            <dd>{current.payday === null ? "tanımlı değil" : `ayın ${current.payday}. günü`}</dd>
          </div>
          <div className="ft-summary-row">
            <dt>Aylık katkı</dt>
            <dd className="ft-num">
              {current.monthly_contribution === null
                ? "tanımlı değil"
                : money(current.monthly_contribution)}
            </dd>
          </div>
          {data.classes.map((code) => (
            <div key={code} className="ft-summary-row">
              <dt>{label(code)}</dt>
              <dd className="ft-num">%{ratioPercent(current.targets[code] ?? "0")}</dd>
            </div>
          ))}
        </dl>
      </Paper>
    </>
  );
}

function CancelLink({ profile, id }: { profile: ProfileSlug; id: number }) {
  return (
    <Anchor component={Link} to={href(profile, `ayarlar/${id}/vazgec`)}>
      Vazgeç <span className="ft-sr">(#{id})</span>
    </Anchor>
  );
}

function Settings({ data, profile }: { data: SettingsData; profile: ProfileSlug }) {
  const today = useToday();
  const effective = (item: SettingItem) =>
    item.initial ? INITIAL : `${dayLabel(item.effective_from, { today, case: "den" })} itibaren`;
  const columns: DataColumn<SettingItem>[] = [
    { key: "no", label: "#", cell: (row) => row.id },
    { key: "kayit", label: "Kayıt", cell: (row) => localTime(row.recorded_at, today) },
    { key: "yururluk", label: "Yürürlük", cell: effective },
    { key: "degisiklik", label: "Değişiklik", cell: (row) => <Changes item={row} /> },
    {
      key: "durum",
      label: "Durum",
      cell: (row) => (
        <>
          {row.state_label}
          {row.cancel_reason === null ? "" : `: ${row.cancel_reason}`}
          {row.state === "planned" && (
            <>
              {" · "}
              <CancelLink profile={profile} id={row.id} />
            </>
          )}
        </>
      ),
    },
    { key: "kaynak", label: "Kaynak", cell: (row) => row.source_label },
  ];
  return (
    <>
      <Text c="dimmed">
        Maaş günü, aylık katkı ve hedef dağılım yürürlük tarihli sürümlerdir; geçmiş raporlar o
        dönemin ayarıyla üretilir. Sınıflar ve fonlar portfolio.toml'dadır.
      </Text>
      <Group>
        <Button component={Link} to={href(profile, "ayarlar/yeni")}>
          Yeni ayar sürümü
        </Button>
      </Group>
      <Title order={2} mt="md">
        Geçerli ayar
      </Title>
      <Current data={data} today={today} />
      {data.planned.length > 0 && (
        <>
          <Title order={2} mt="md">
            Planlanan
          </Title>
          <ul className="ft-cards" aria-label="Planlanan">
            {data.planned.map((item) => (
              <li key={item.id}>
                <Paper withBorder p="sm" className="ft-surface">
                  <Group justify="space-between" wrap="nowrap">
                    <Text fw={700}>{effective(item)}</Text>
                    <Text c="dimmed">#{item.id}</Text>
                  </Group>
                  <Changes item={item} />
                  <CancelLink profile={profile} id={item.id} />
                </Paper>
              </li>
            ))}
          </ul>
        </>
      )}
      <Title order={2} mt="md">
        Geçmiş
      </Title>
      <DataTable
        table={data.table}
        columns={columns}
        rowKey={(row) => row.id}
        rowVoided={(row) => row.cancelled_at !== null}
        noun="ayar sürümü"
        empty="Henüz ayar sürümü yok."
      />
    </>
  );
}

export function SettingsPage() {
  const profile = useProfile();
  const query = useQuery(settingsQuery(useApi(), profile, useTableQuery()));
  return (
    <Page title="Ayarlar">
      <QueryView query={query}>{(data) => <Settings data={data} profile={profile} />}</QueryView>
    </Page>
  );
}
