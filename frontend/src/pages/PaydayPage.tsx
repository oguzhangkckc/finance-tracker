import {
  Alert,
  Button,
  Checkbox,
  Group,
  Paper,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router";
import type { ApiError } from "../api/client";
import { useApi } from "../api/context";
import { paydayQuery } from "../api/queries";
import {
  changedPreview,
  type PaydayLine,
  type PaydayPlan,
  type Saved,
  settle,
} from "../api/writes";
import { useToday } from "../clock";
import { Warning } from "../components/Notice";
import { QueryView } from "../components/QueryView";
import { TargetProfile } from "../components/TargetProfile";
import { WriteProblem } from "../components/WriteProblem";
import { dayLabel, exact, money } from "../format/display";
import { Icon } from "../layout/icons";
import { href } from "../layout/nav";
import { useProfile } from "../profile";
import { NotFound } from "./NotFound";
import { Page } from "./Page";

export function paydaySavedMessage(saved: Saved): string {
  return saved.duplicate
    ? `Bu onay zaten kullanıldı; maaş günü planı uygulandı (${saved.number} alım).`
    : `Maaş günü planı uygulandı: ${saved.number} sanal alım.`;
}

function lineText(line: PaydayLine, plan: PaydayPlan, today: string): string {
  switch (line.status) {
    case "ready":
      return `${line.price_day === null ? "" : dayLabel(line.price_day, { today })} fiyatıyla ${exact(line.units ?? "0")} pay × ${exact(line.price ?? "0")} TL = ${money(line.spent ?? "0")}; artan ${money(line.leftover ?? "0")}.`;
    case "nothing":
      return "Bu ay alım yok; katkı hedefin altında kalan sınıflara gitti.";
    case "pending":
      return `Fiyat henüz açıklanmadı; ${dayLabel(plan.retry_after, { today })} tarihinden sonra tekrar bak.`;
    case "expired":
      return "Pencerede fiyat yok; işlem yapılmadı, tutar başka fona aktarılmaz.";
    case "applied":
      return "Zaten uygulandı.";
    case "voided":
      return "İptal edilmiş bir alımı var, uygulanmış sayılır; yeniden önermek için yukarıdaki kutuyu işaretle.";
    default:
      return `İşlem yapılmadı: ${line.reason ?? ""}`;
  }
}

function Plan({ initial }: { initial: PaydayPlan }) {
  const profile = useProfile();
  const api = useApi();
  const today = useToday();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [plan, setPlan] = useState(initial);
  const [changed, setChanged] = useState(false);
  const [payday, setPayday] = useState(initial.payday);
  const [reapply, setReapply] = useState(initial.reapply_voided);
  const [problem, setProblem] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const path = { params: { path: { profil: profile } } };

  async function show() {
    setBusy(true);
    setProblem(null);
    const outcome = await settle(
      api.POST("/api/{profil}/maas-gunu/onizle", {
        ...path,
        body: { payday, reapply_voided: reapply },
      }),
    );
    setBusy(false);
    if (outcome.data !== undefined) {
      setPlan(outcome.data);
      setChanged(false);
    } else {
      setProblem(outcome.problem);
    }
  }

  async function apply(confirmation: Record<string, string>) {
    setBusy(true);
    setProblem(null);
    const outcome = await settle(
      api.POST("/api/{profil}/maas-gunu/kaydet", { ...path, body: { confirmation } }),
    );
    setBusy(false);
    if (outcome.data !== undefined) {
      void queryClient.invalidateQueries({ queryKey: ["sayfa", profile] });
      notifications.show({
        color: outcome.data.duplicate ? "kehribar" : "yaprak",
        message: paydaySavedMessage(outcome.data),
      });
      navigate(href(profile, "islemler"));
      return;
    }
    const fresh = changedPreview<PaydayPlan>(outcome);
    if (fresh !== null) {
      setPlan(fresh);
      setChanged(true);
    } else {
      setProblem(outcome.problem);
    }
  }

  const confirmation = plan.confirmation;
  return (
    <Stack gap="md">
      <Text c="dimmed">
        Katkı, maaş günündeki değerlemeyle sınıflara ve fonlara dağıtılır. Fiyat günü maaş gününden
        sonraki ilk fiyatlı gündür; adet aşağı yuvarlanır, artan tutar fona girmez.
      </Text>
      <form
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          void show();
        }}
      >
        <Stack gap="md" maw={520}>
          <TextInput
            type="date"
            label="Maaş günü"
            description="Varsayılan son maaş günü."
            value={payday}
            onChange={(event) => setPayday(event.currentTarget.value)}
            error={problem?.fields.payday}
          />
          <Checkbox
            label="İptal ettiğim maaş günü alımlarını da yeniden öner"
            checked={reapply}
            onChange={(event) => setReapply(event.currentTarget.checked)}
          />
          <Group>
            <Button type="submit" variant="default" loading={busy}>
              Planı göster
            </Button>
          </Group>
        </Stack>
      </form>
      {problem !== null && (
        <WriteProblem
          problem={problem}
          onRetry={() => void (confirmation === null ? show() : apply(confirmation))}
        />
      )}
      {changed && (
        <Warning>
          <strong>Önizlemeden sonra veriler değişti; kayıt yapılmadı.</strong> Yeni planı kontrol
          et.
        </Warning>
      )}
      <Title order={2}>{dayLabel(plan.payday, { today })} planı</Title>
      {plan.missing_prices.length > 0 ? (
        <Alert color="kiremit" variant="light" icon={<Icon name="hata" />} role="alert">
          Plan hesaplanmadı: {plan.missing_prices.join(", ")} için maaş gününde fiyat yok. Hiçbir
          işlem yapılmadı.
        </Alert>
      ) : (
        <>
          <Text size="sm" c="dimmed">
            Fiyat penceresi {dayLabel(plan.window_end, { today, case: "de" })} biter.
          </Text>
          <ul className="ft-cards" aria-label="Plan">
            {plan.lines.map((line) => (
              <li key={`${line.asset_class}-${line.instrument}`}>
                <Paper withBorder p="sm" className="ft-surface">
                  <Group justify="space-between" wrap="nowrap">
                    <Text>
                      <strong>{line.instrument}</strong>{" "}
                      <Text span c="dimmed" size="sm">
                        {line.class_name}
                      </Text>
                    </Text>
                    <Text className="ft-num">{money(line.amount)}</Text>
                  </Group>
                  <Text size="sm">{lineText(line, plan, today)}</Text>
                </Paper>
              </li>
            ))}
          </ul>
          {confirmation === null ? (
            <Text size="sm" c="dimmed">
              Uygulanacak alım yok.
            </Text>
          ) : (
            <>
              <TargetProfile profile={profile} />
              <Group>
                <Button onClick={() => void apply(confirmation)} loading={busy}>
                  Planı uygula ({plan.ready} alım)
                </Button>
              </Group>
            </>
          )}
        </>
      )}
    </Stack>
  );
}

function PaydayLoader() {
  const query = useQuery(paydayQuery(useApi(), "sanal"));
  return <QueryView query={query}>{(initial) => <Plan initial={initial} />}</QueryView>;
}

// Maaş günü planı yalnız sanal profilde vardır; gerçek profilde adres yoktur (K-138).
export function PaydayPage() {
  const profile = useProfile();
  if (profile !== "sanal") {
    return <NotFound />;
  }
  return (
    <Page title="Maaş günü planı">
      <PaydayLoader />
    </Page>
  );
}
