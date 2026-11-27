import { Anchor, Button, Group, NativeSelect, Stack, Table, Text, TextInput } from "@mantine/core";
import type { FormEvent, ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import type { components } from "../api/schema";
import { useToday } from "../clock";
import { dayLabel } from "../format/display";
import { EmptyState } from "./Notice";
import {
  ariaSort,
  type Changes,
  DIRECTION,
  FROM,
  PAGE,
  SEARCH,
  SORT,
  type SortState,
  search,
  sortLink,
  TO,
} from "./tableLinks";

type Schemas = components["schemas"];

export interface TableState<R> extends SortState {
  rows: readonly R[];
  total: number;
  page: number;
  pages: number;
  active: readonly Schemas["TableChip"][];
  ignored: string;
  columns: readonly Schemas["TableColumn"][];
  choices: readonly Schemas["TableChoice"][];
  day_filter: boolean;
  search: boolean;
}

export interface DataColumn<R> {
  key: string;
  label: string;
  numeric?: boolean;
  // Başlıkta görünmez, ekran okuyucuya kalır (ör. satır bağlantıları).
  quietLabel?: boolean;
  cell: (row: R) => ReactNode;
}

// Sorgu anahtarı ve API isteği için adresin parametreleri, sırası korunarak.
export function useTableQuery(): string {
  return new URLSearchParams(useLocation().search).toString();
}

function directionValue(descending: boolean): string {
  return descending ? "azalan" : "artan";
}

function Tools<R>({
  table,
  searchHint,
  go,
}: {
  table: TableState<R>;
  searchHint: string;
  go: (changes: Changes) => void;
}) {
  const sortOptions = table.columns.flatMap((column) =>
    [false, true].map((descending) => ({
      value: `${column.key}.${directionValue(descending)}`,
      label: `${column.label}: ${column.directions[descending ? 1 : 0] ?? ""}`,
    })),
  );

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = String(new FormData(event.currentTarget).get(SEARCH) ?? "").trim();
    go({ [SEARCH]: value, [PAGE]: null });
  }

  function submitFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const changes: Record<string, string | null> = { [PAGE]: null };
    for (const choice of table.choices) {
      const value = String(form.get(choice.key) ?? "");
      changes[choice.key] = value === "" || value === choice.default ? null : value;
    }
    if (table.day_filter) {
      changes[FROM] = String(form.get(FROM) ?? "");
      changes[TO] = String(form.get(TO) ?? "");
    }
    go(changes);
  }

  const hasFilters = table.choices.length > 0 || table.day_filter;
  return (
    <Stack gap="xs">
      <Group align="flex-end" gap="sm" wrap="wrap">
        {table.search && (
          <search key={table.params[SEARCH] ?? ""}>
            <form onSubmit={submitSearch}>
              <Group align="flex-end" gap="xs" wrap="nowrap">
                <TextInput
                  label="Ara"
                  name={SEARCH}
                  type="search"
                  defaultValue={table.params[SEARCH] ?? ""}
                  placeholder={searchHint}
                  autoComplete="off"
                />
                <Button type="submit" variant="default">
                  Ara
                </Button>
              </Group>
            </form>
          </search>
        )}
        <NativeSelect
          label="Sırala"
          data={sortOptions}
          value={`${table.sort}.${directionValue(table.descending)}`}
          onChange={(event) => {
            const [key = table.sort, direction = "artan"] = event.currentTarget.value.split(".");
            go({ [SORT]: key, [DIRECTION]: direction, [PAGE]: null });
          }}
        />
      </Group>
      {hasFilters && (
        <details className="ft-details">
          <summary>
            Filtreler
            {table.active.length > 0 && ` · ${table.active.length} etkin`}
          </summary>
          <form onSubmit={submitFilters} key={search(table.params)}>
            <Stack gap="sm">
              <Group align="flex-end" gap="sm" wrap="wrap">
                {table.choices.map((choice) => (
                  <NativeSelect
                    key={choice.key}
                    label={choice.label}
                    name={choice.key}
                    defaultValue={table.params[choice.key] ?? choice.default ?? ""}
                    data={[
                      ...(choice.default === null ? [{ value: "", label: "Hepsi" }] : []),
                      ...choice.options,
                    ]}
                  />
                ))}
                {table.day_filter && (
                  <>
                    <TextInput
                      label="Başlangıç"
                      name={FROM}
                      type="date"
                      defaultValue={table.params[FROM] ?? ""}
                    />
                    <TextInput
                      label="Bitiş"
                      name={TO}
                      type="date"
                      defaultValue={table.params[TO] ?? ""}
                    />
                  </>
                )}
              </Group>
              <Group gap="sm">
                <Button type="submit">Uygula</Button>
                <Button component={Link} to={{ search: "" }} variant="default">
                  Temizle
                </Button>
              </Group>
            </Stack>
          </form>
        </details>
      )}
    </Stack>
  );
}

function Chips<R>({ table }: { table: TableState<R> }) {
  const today = useToday();
  if (table.active.length === 0) {
    return null;
  }
  return (
    <ul className="ft-chips" aria-label="Etkin filtreler">
      {table.active.map((chip) => (
        <li key={chip.key}>
          <Anchor
            component={Link}
            to={{ search: search(table.params, { [chip.key]: null, [PAGE]: null }) }}
          >
            {chip.name}: {chip.day ? dayLabel(chip.value, { today }) : chip.value}{" "}
            <span aria-hidden="true">×</span>
            <span className="ft-sr">filtresini kaldır</span>
          </Anchor>
        </li>
      ))}
      <li>
        <Anchor component={Link} to={{ search: "" }}>
          Hepsini temizle
        </Anchor>
      </li>
    </ul>
  );
}

function Pager<R>({ table }: { table: TableState<R> }) {
  if (table.pages <= 1) {
    return null;
  }
  const to = (page: number) => ({ search: search(table.params, { [PAGE]: String(page) }) });
  return (
    <nav aria-label="Tablo sayfaları">
      <Group gap="sm" justify="center">
        {table.page > 1 && (
          <Button component={Link} to={to(table.page - 1)} rel="prev" variant="default">
            Önceki
          </Button>
        )}
        <Text size="sm">
          Sayfa {table.page} / {table.pages} · {table.total} satır
        </Text>
        {table.page < table.pages && (
          <Button component={Link} to={to(table.page + 1)} rel="next" variant="default">
            Sonraki
          </Button>
        )}
      </Group>
    </nav>
  );
}

// K-129: sıralama, filtre ve sayfa sunucudadır; tablo yalnız adresi değiştirir.
export function DataTable<R>({
  table,
  columns,
  rowKey,
  rowVoided,
  searchHint = "",
  noun,
  empty,
}: {
  table: TableState<R>;
  columns: readonly DataColumn<R>[];
  rowKey?: (row: R) => string | number;
  rowVoided?: (row: R) => boolean;
  searchHint?: string;
  noun: string;
  empty: string;
}) {
  const navigate = useNavigate();
  const sortable = new Set(table.columns.map((column) => column.key));
  const go = (changes: Changes) => navigate({ search: search(table.params, changes) });

  return (
    <Stack gap="sm">
      <Tools table={table} searchHint={searchHint} go={go} />
      <Chips table={table} />
      {table.ignored !== "" && (
        <Text size="sm" c="dimmed">
          Filtre anlaşılmadı: {table.ignored}. Yok sayıldı.
        </Text>
      )}
      {table.rows.length > 0 ? (
        <>
          <Table.ScrollContainer minWidth={640}>
            <Table>
              <Table.Thead>
                <Table.Tr>
                  {columns.map((column) => (
                    <Table.Th
                      key={column.key}
                      ta={column.numeric ? "right" : undefined}
                      aria-sort={sortable.has(column.key) ? ariaSort(table, column.key) : undefined}
                    >
                      {sortable.has(column.key) ? (
                        <Anchor
                          component={Link}
                          to={{ search: sortLink(table, column.key) }}
                          inherit
                        >
                          {column.label}
                          {table.sort === column.key && (
                            <span aria-hidden="true"> {table.descending ? "↓" : "↑"}</span>
                          )}
                        </Anchor>
                      ) : column.quietLabel ? (
                        <span className="ft-sr">{column.label}</span>
                      ) : (
                        column.label
                      )}
                    </Table.Th>
                  ))}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {table.rows.map((row, index) => (
                  <Table.Tr
                    key={rowKey?.(row) ?? index}
                    className={rowVoided?.(row) ? "ft-voided" : undefined}
                  >
                    {columns.map((column) => (
                      <Table.Td
                        key={column.key}
                        ta={column.numeric ? "right" : undefined}
                        className={column.numeric ? "ft-num" : undefined}
                      >
                        {column.cell(row)}
                      </Table.Td>
                    ))}
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          <Pager table={table} />
        </>
      ) : table.active.length > 0 ? (
        <EmptyState>
          Bu filtrelerle {noun} yok.{" "}
          <Anchor component={Link} to={{ search: "" }}>
            Filtreleri temizle
          </Anchor>
        </EmptyState>
      ) : (
        <EmptyState>{empty}</EmptyState>
      )}
    </Stack>
  );
}
