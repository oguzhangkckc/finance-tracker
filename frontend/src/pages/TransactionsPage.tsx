import { Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useApi } from "../api/context";
import { transactionsQuery } from "../api/queries";
import type { TransactionItem, TransactionsData } from "../api/types";
import { useToday } from "../clock";
import { type DataColumn, DataTable, useTableQuery } from "../components/DataTable";
import { QueryView } from "../components/QueryView";
import { dayLabel, exact, money } from "../format/display";
import { useProfile } from "../profile";
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

function Transactions({ data }: { data: TransactionsData }) {
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
  const query = useQuery(transactionsQuery(useApi(), useProfile(), useTableQuery()));
  return (
    <Page title="İşlemler">
      <QueryView query={query}>{(data) => <Transactions data={data} />}</QueryView>
    </Page>
  );
}
