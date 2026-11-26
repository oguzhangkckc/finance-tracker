import { Anchor, Button, Group, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { useApi } from "../api/context";
import { transactionsQuery } from "../api/queries";
import type { TransactionItem, TransactionsData } from "../api/types";
import { useToday } from "../clock";
import { type DataColumn, DataTable, useTableQuery } from "../components/DataTable";
import { QueryView } from "../components/QueryView";
import { dayLabel, exact, money } from "../format/display";
import { href } from "../layout/nav";
import { type ProfileSlug, useProfile } from "../profile";
import { Page } from "./Page";

function Note({ row }: { row: TransactionItem }) {
  return (
    <>
      {row.voided_at !== null && <span className="ft-warn">İptal: {row.void_reason} </span>}
      {row.note ?? ""}
      {row.external_ref !== null && (
        <Text span c="dimmed" size="sm">
          {" "}
          {row.external_ref}
        </Text>
      )}
    </>
  );
}

function Actions({ profile }: { profile: ProfileSlug }) {
  const sanal = profile === "sanal";
  return (
    <Group gap="sm">
      <Button component={Link} to={href(profile, "islemler/yeni/alis")}>
        {sanal ? "Sanal alım" : "Alım ekle"}
      </Button>
      <Button component={Link} to={href(profile, "islemler/yeni/satis")} variant="default">
        {sanal ? "Sanal satış" : "Satış ekle"}
      </Button>
      {sanal && (
        <Button component={Link} to={href(profile, "maas-gunu")} variant="default">
          Maaş günü planı
        </Button>
      )}
    </Group>
  );
}

function Transactions({ data, profile }: { data: TransactionsData; profile: ProfileSlug }) {
  const today = useToday();
  const columns: DataColumn<TransactionItem>[] = [
    { key: "no", label: "#", cell: (row) => row.id },
    { key: "tarih", label: "Tarih", cell: (row) => dayLabel(row.trade_date, { today }) },
    {
      key: "fon",
      label: "Fon",
      cell: (row) => (
        <>
          <strong>{row.instrument}</strong>{" "}
          <Text span c="dimmed" size="sm">
            {row.class_name}
          </Text>
        </>
      ),
    },
    { key: "tur", label: "Tür", cell: (row) => (row.side === "BUY" ? "alış" : "satış") },
    { key: "adet", label: "Adet", numeric: true, cell: (row) => exact(row.units) },
    { key: "fiyat", label: "Fiyat", numeric: true, cell: (row) => exact(row.unit_price) },
    { key: "tutar", label: "Tutar", numeric: true, cell: (row) => money(row.amount) },
    { key: "komisyon", label: "Komisyon", numeric: true, cell: (row) => exact(row.fee) },
    { key: "not", label: "Not", cell: (row) => <Note row={row} /> },
    {
      key: "islem",
      label: "İşlem",
      quietLabel: true,
      cell: (row) =>
        row.voided_at === null && (
          <Anchor component={Link} to={href(profile, `islemler/${row.id}/iptal`)}>
            İptal et <span className="ft-sr">(#{row.id})</span>
          </Anchor>
        ),
    },
  ];
  return (
    <DataTable
      table={data.table}
      columns={columns}
      rowKey={(row) => row.id}
      rowVoided={(row) => row.voided_at !== null}
      searchHint="Fon kodu, dekont no ya da not"
      noun="işlem"
      empty="Kayıtlı işlem yok."
    />
  );
}

export function TransactionsPage() {
  const profile = useProfile();
  const query = useQuery(transactionsQuery(useApi(), profile, useTableQuery()));
  return (
    <Page title="İşlemler">
      <Actions profile={profile} />
      <QueryView query={query}>
        {(data) => <Transactions data={data} profile={profile} />}
      </QueryView>
    </Page>
  );
}
