import { Anchor, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { useApi } from "../api/context";
import { holdingsQuery, lotsQuery } from "../api/queries";
import type { HoldingItem, HoldingsData, LotItem, LotsData } from "../api/types";
import { useToday } from "../clock";
import { type DataColumn, DataTable, useTableQuery } from "../components/DataTable";
import { PriceLine } from "../components/PriceLine";
import { QueryView } from "../components/QueryView";
import { dayLabel, exact, money, percent } from "../format/display";
import { href } from "../layout/nav";
import { type ProfileSlug, useProfile } from "../profile";
import { Page } from "./Page";

function moneyOrDash(value: string | null): string {
  return value === null ? "—" : money(value);
}

function percentOrDash(value: string | null | undefined): string {
  return value === null || value === undefined ? "—" : percent(value);
}

function Holdings({ data, profile }: { data: HoldingsData; profile: ProfileSlug }) {
  const today = useToday();
  const columns: DataColumn<HoldingItem>[] = [
    { key: "fon", label: "Fon", cell: (row) => <strong>{row.instrument}</strong> },
    {
      key: "sinif",
      label: "Sınıf",
      cell: (row) => `${row.class_name}${row.allocation ? "" : " · dağılım dışı"}`,
    },
    { key: "adet", label: "Adet", numeric: true, cell: (row) => exact(row.units) },
    { key: "maliyet", label: "Maliyet", numeric: true, cell: (row) => money(row.cost) },
    { key: "deger", label: "Değer", numeric: true, cell: (row) => moneyOrDash(row.value) },
    {
      key: "getiri",
      label: "Basit getiri",
      numeric: true,
      cell: (row) => percentOrDash(row.simple_return),
    },
    { key: "fiyat", label: "Fiyat", cell: (row) => <PriceLine holding={row} stale={data.stale} /> },
    {
      key: "lotlar",
      label: "Lotlar",
      quietLabel: true,
      cell: (row) => (
        <Anchor
          component={Link}
          to={`${href(profile, "varliklar/lotlar")}?fon=${encodeURIComponent(row.instrument)}`}
        >
          Lotlar <span className="ft-sr">({row.instrument})</span>
        </Anchor>
      ),
    },
  ];
  return (
    <>
      <Text c="dimmed">
        Değerleme günü {dayLabel(data.logical_date, { today })} ·{" "}
        <Anchor component={Link} to={href(profile, "varliklar/lotlar")}>
          Lotlar
        </Anchor>
      </Text>
      <DataTable
        table={data.table}
        columns={columns}
        rowKey={(row) => row.instrument}
        searchHint="Fon kodu"
        noun="varlık"
        empty="Henüz pozisyon yok."
      />
    </>
  );
}

export function HoldingsPage() {
  const profile = useProfile();
  const query = useQuery(holdingsQuery(useApi(), profile, useTableQuery()));
  return (
    <Page title="Varlıklar">
      <QueryView query={query}>{(data) => <Holdings data={data} profile={profile} />}</QueryView>
    </Page>
  );
}

function Lots({ data, profile }: { data: LotsData; profile: ProfileSlug }) {
  const today = useToday();
  const columns: DataColumn<LotItem>[] = [
    { key: "fon", label: "Fon", cell: (row) => <strong>{row.instrument}</strong> },
    { key: "alis", label: "Alış günü", cell: (row) => dayLabel(row.acquired, { today }) },
    { key: "adet", label: "Adet", numeric: true, cell: (row) => exact(row.units) },
    { key: "maliyet", label: "Maliyet", numeric: true, cell: (row) => money(row.cost) },
    { key: "deger", label: "Değer", numeric: true, cell: (row) => moneyOrDash(row.value) },
    { key: "kar", label: "Kâr/zarar", numeric: true, cell: (row) => moneyOrDash(row.gain) },
    {
      key: "reel",
      label: "Reel getiri",
      numeric: true,
      cell: (row) => percentOrDash(row.real_return),
    },
  ];
  return (
    <>
      <Text c="dimmed">
        Değerleme günü {dayLabel(data.logical_date, { today })} ·{" "}
        <Anchor component={Link} to={href(profile, "varliklar")}>
          Varlıklar
        </Anchor>
      </Text>
      <DataTable table={data.table} columns={columns} noun="lot" empty="Henüz lot yok." />
    </>
  );
}

export function LotsPage() {
  const profile = useProfile();
  const query = useQuery(lotsQuery(useApi(), profile, useTableQuery()));
  return (
    <Page title="Lotlar">
      <QueryView query={query}>{(data) => <Lots data={data} profile={profile} />}</QueryView>
    </Page>
  );
}
