import { Anchor, Group, Paper, Stack, Text, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { useApi } from "../api/context";
import { overviewQuery } from "../api/queries";
import type { OverviewData } from "../api/types";
import { useToday } from "../clock";
import { AllocationBars } from "../components/AllocationBars";
import { Delta } from "../components/Delta";
import { EmptyState, Warning } from "../components/Notice";
import { PriceLine } from "../components/PriceLine";
import { QueryView } from "../components/QueryView";
import { RefreshButton } from "../components/RefreshButton";
import { ValueChart } from "../components/ValueChart";
import { parseDecimal } from "../format/decimal";
import { dayLabel, money, percent } from "../format/display";
import { localTime } from "../format/time";
import { href } from "../layout/nav";
import { type ProfileSlug, useProfile } from "../profile";
import { classLabels, Page } from "./Page";

export const QUIET_PERIOD = "Portföy henüz küçük; sapma alarmları 3 aylık katkıya ulaşınca başlar.";

function Section({ title, more, to }: { title: string; more: string; to: string }) {
  return (
    <Group justify="space-between" align="baseline" mt="md">
      <Title order={2}>{title}</Title>
      <Anchor component={Link} to={to} size="sm">
        {more} ›
      </Anchor>
    </Group>
  );
}

function Overview({ data, profile }: { data: OverviewData; profile: ProfileSlug }) {
  const today = useToday();
  const { report, refresh } = data;
  const { summary } = report;
  const label = classLabels(data.class_names);
  return (
    <Stack gap="md">
      <section aria-labelledby="toplam">
        <Text size="sm" c="dimmed" id="toplam">
          Toplam değer · Değerleme günü {dayLabel(report.logical_date, { today })}
        </Text>
        <Text className="ft-hero ft-num">{money(summary.values.total)}</Text>
        {summary.change !== null && (
          <Text>
            <Delta value={summary.change} text={percent(summary.change, { signed: true })} />{" "}
            <Text span c="dimmed">
              {dayLabel(summary.change_since, { today })} sonrasında
            </Text>
          </Text>
        )}
        <dl className="ft-stats">
          <div>
            <dt>Dağılım içi</dt>
            <dd className="ft-num">{money(summary.values.in_allocation)}</dd>
          </div>
          {parseDecimal(summary.values.out_of_allocation).units !== 0n && (
            <div>
              <dt>Dağılım dışı</dt>
              <dd className="ft-num">{money(summary.values.out_of_allocation)}</dd>
            </div>
          )}
          {summary.simple_return !== null && (
            <div>
              <dt>Basit getiri</dt>
              <dd>
                <Delta
                  value={summary.simple_return}
                  text={percent(summary.simple_return, { signed: true })}
                />
              </dd>
            </div>
          )}
          <div>
            <dt>Gerçekleşmiş K/Z</dt>
            <dd className="ft-num">{money(summary.realized_pnl)}</dd>
          </div>
        </dl>
      </section>

      <ValueChart chart={data.chart} />

      {data.stale_all.map((message) => (
        <Warning key={message}>
          <strong>Fiyatlar bayat: {message}.</strong>
        </Warning>
      ))}
      {report.missing_prices !== undefined && report.missing_prices.length > 0 && (
        <Warning>
          <strong>Fiyatı eksik: {report.missing_prices.join(", ")}.</strong> Dağılım ve alarmlar bu
          yüzden hesaplanmadı; fiyat gelince kendiliğinden hesaplanır.
        </Warning>
      )}
      {report.alerts.length > 0 && (
        <Warning>
          <strong>Açık sapma alarmı: {report.alerts.length}.</strong>{" "}
          <Anchor component={Link} to={href(profile, "dagilim")}>
            Dağılımı gör
          </Anchor>
        </Warning>
      )}

      {report.allocation.length > 0 && (
        <>
          <Section title="Dağılım" more="Ayrıntı" to={href(profile, "dagilim")} />
          <AllocationBars lines={report.allocation} alerts={report.alerts} label={label} />
        </>
      )}
      {report.quiet_period && (
        <Text size="sm" c="dimmed">
          {QUIET_PERIOD}
        </Text>
      )}

      <Section title="Varlıklar" more="Tümü" to={href(profile, "varliklar")} />
      {report.holdings.length > 0 ? (
        <ul className="ft-cards" aria-label="Varlıklar">
          {report.holdings.map((holding) => (
            <li key={holding.instrument}>
              <Paper withBorder p="sm" className="ft-surface">
                <Group justify="space-between" wrap="nowrap">
                  <Text fw={700}>{holding.instrument}</Text>
                  <Text className="ft-num">
                    {holding.value === null ? "" : money(holding.value)}
                  </Text>
                </Group>
                <Text size="sm" c="dimmed">
                  {label(holding.asset_class)}
                  {!holding.allocation && " · dağılım dışı"}
                </Text>
                <Text size="sm">
                  <PriceLine holding={holding} stale={data.stale} />
                </Text>
              </Paper>
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState>Henüz pozisyon yok. İşlemler girildiğinde fonlar burada görünür.</EmptyState>
      )}

      <Title order={2} mt="md">
        Fiyatlar
      </Title>
      <Paper withBorder p="md" className="ft-surface">
        <Stack gap="xs">
          <Text size="sm" c="dimmed">
            Fonların günde bir fiyatı vardır; gösterilen, açıklanmış son fiyattır ve günüyle
            yazılır.
          </Text>
          <Text size="sm">
            Son fiyat güncellemesi:{" "}
            {refresh.last_sync === null ? "son iki günde yok" : localTime(refresh.last_sync, today)}
          </Text>
          {refresh.allowed && <RefreshButton profile={profile} />}
          {!refresh.allowed && (
            <Text size="sm" c="dimmed">
              Elle güncelleme şu an kapalı: {refresh.reason}.
              {refresh.earliest !== null && ` En erken ${localTime(refresh.earliest, today)}.`}
            </Text>
          )}
        </Stack>
      </Paper>
    </Stack>
  );
}

export function OverviewPage() {
  const profile = useProfile();
  const query = useQuery(overviewQuery(useApi(), profile));
  return (
    <Page title="Özet" hideTitle>
      <QueryView query={query}>{(data) => <Overview data={data} profile={profile} />}</QueryView>
    </Page>
  );
}
