import { Anchor, Button, Code, Stack, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { useApi } from "../api/context";
import { type ReportSlug, reportTextQuery } from "../api/queries";
import { QueryView } from "../components/QueryView";
import { href } from "../layout/nav";
import { useProfile } from "../profile";
import { NotFound } from "./NotFound";
import { Page } from "./Page";

// Sunucudaki başlıklarla aynı (api/routes/okuma.py TITLES); sayfa başlığı veri gelmeden de yazılır.
const TITLES: Readonly<Record<ReportSlug, string>> = {
  haftalik: "Haftalık rapor",
  aylik: "Aylık rapor",
  "maas-gunu": "Maaş günü",
};

function isReportSlug(value: string | undefined): value is ReportSlug {
  return value !== undefined && Object.hasOwn(TITLES, value);
}

export function ReportsPage() {
  const profile = useProfile();
  return (
    <Page title="Raporlar">
      <Text size="sm" c="dimmed">
        Telegram'a giden metnin aynısı; burada TL tutarları gizlenmez.
      </Text>
      <nav aria-label="Rapor türleri">
        <Stack gap="sm" align="flex-start">
          {Object.entries(TITLES).map(([slug, title]) => (
            <Button
              key={slug}
              component={Link}
              to={href(profile, `raporlar/${slug}`)}
              variant="light"
            >
              {title}
            </Button>
          ))}
        </Stack>
      </nav>
    </Page>
  );
}

function ReportText({ slug }: { slug: ReportSlug }) {
  const profile = useProfile();
  const query = useQuery(reportTextQuery(useApi(), profile, slug));
  return (
    <Page title={query.data?.title ?? TITLES[slug]}>
      <QueryView query={query}>
        {(data) => (
          <Code block className="ft-report">
            {data.text}
          </Code>
        )}
      </QueryView>
      <Anchor component={Link} to={href(profile, "raporlar")}>
        Raporlar
      </Anchor>
    </Page>
  );
}

export function ReportPage() {
  const { tur } = useParams();
  return isReportSlug(tur) ? <ReportText slug={tur} /> : <NotFound />;
}
