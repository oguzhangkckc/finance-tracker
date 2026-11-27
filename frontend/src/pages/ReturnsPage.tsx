import { Stack, Table, Text, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useApi } from "../api/context";
import { returnsQuery } from "../api/queries";
import type { ReturnFigure, ReturnsData } from "../api/types";
import { useToday } from "../clock";
import { ContributionChart } from "../components/ContributionChart";
import { QueryView } from "../components/QueryView";
import { ValueChart } from "../components/ValueChart";
import { dayLabel, monthLabel, percent } from "../format/display";
import { useProfile } from "../profile";
import { Page } from "./Page";

export function figureText(figure: ReturnFigure | null | undefined): string {
  if (figure === null || figure === undefined) {
    return "—";
  }
  if (figure.status === "ok" && figure.rate !== null && figure.rate !== undefined) {
    return `${percent(figure.rate)} ${figure.annualized ? "(yıllık)" : "(dönemlik)"}`;
  }
  if (figure.status === "out_of_range") {
    return "anlamlı değil";
  }
  if (figure.status === "missing_price") {
    return "fiyat eksik";
  }
  return "hesaplanamadı";
}

function Returns({ data }: { data: ReturnsData }) {
  const today = useToday();
  const { report } = data;
  const { summary } = report;
  const inflation = report.inflation;
  return (
    <Stack gap="md">
      <Text c="dimmed">Değerleme günü {dayLabel(report.logical_date, { today })}</Text>
      <dl className="ft-stats">
        <div>
          <dt>Basit getiri</dt>
          <dd className="ft-num">
            {summary.simple_return === null ? "—" : percent(summary.simple_return)}
          </dd>
        </div>
        <div>
          <dt>Para ağırlıklı getiri</dt>
          <dd className="ft-num">{figureText(summary.money_weighted)}</dd>
        </div>
        <div>
          <dt>Reel para ağırlıklı getiri</dt>
          <dd className="ft-num">{figureText(summary.real_money_weighted)}</dd>
        </div>
        {inflation !== null && inflation !== undefined && inflation.annual_inflation !== null && (
          <div>
            <dt>Yıllık enflasyon ({monthLabel(inflation.valuation_period)})</dt>
            <dd className="ft-num">{percent(inflation.annual_inflation)}</dd>
          </div>
        )}
      </dl>
      {summary.real_same_as_nominal === true && (
        <Text size="sm" c="dimmed">
          Alımlar ve değerleme aynı TÜFE dönemine düştüğü için reel getiri henüz nominalle aynı.
        </Text>
      )}
      <Text size="sm" c="dimmed">
        Para ağırlıklı getiri alım ve satışların tarihini ve tutarını hesaba katar; bir yıldan kısa
        dönemde yıllığa çevrilmez.
      </Text>

      <ValueChart chart={data.chart} />
      <ContributionChart months={data.contributions} />

      <Title order={2} mt="md">
        Fon bazında
      </Title>
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Fon</Table.Th>
            <Table.Th ta="right">Basit getiri</Table.Th>
            <Table.Th ta="right">Reel getiri</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {report.holdings.length > 0 ? (
            report.holdings.map((holding) => (
              <Table.Tr key={holding.instrument}>
                <Table.Td fw={700}>{holding.instrument}</Table.Td>
                <Table.Td ta="right" className="ft-num">
                  {holding.simple_return === null ? "—" : percent(holding.simple_return)}
                </Table.Td>
                <Table.Td ta="right" className="ft-num">
                  {holding.real_return === null || holding.real_return === undefined
                    ? "—"
                    : percent(holding.real_return)}
                </Table.Td>
              </Table.Tr>
            ))
          ) : (
            <Table.Tr>
              <Table.Td colSpan={3}>Henüz pozisyon yok.</Table.Td>
            </Table.Tr>
          )}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}

export function ReturnsPage() {
  const query = useQuery(returnsQuery(useApi(), useProfile()));
  return (
    <Page title="Getiri">
      <QueryView query={query}>{(data) => <Returns data={data} />}</QueryView>
    </Page>
  );
}
