import { Button, Group, Paper, Stack, Text, Textarea } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { type ApiError, unwrap } from "../api/client";
import { useApi } from "../api/context";
import type { SettingItem } from "../api/types";
import { type CancelPreview, changedPreview, type Saved, settle } from "../api/writes";
import { useToday } from "../clock";
import { Warning } from "../components/Notice";
import { QueryView } from "../components/QueryView";
import { Steps } from "../components/Steps";
import { TargetProfile } from "../components/TargetProfile";
import { WriteProblem } from "../components/WriteProblem";
import { dayLabel } from "../format/display";
import { href } from "../layout/nav";
import { useProfile } from "../profile";
import { NotFound } from "./NotFound";
import { Page } from "./Page";
import { SummaryRow } from "./TradePage";

export function cancelSavedMessage(saved: Saved): string {
  return saved.duplicate
    ? `Bu onay zaten kullanıldı; ayar sürümü #${saved.number} için vazgeçildi.`
    : `Ayar sürümü #${saved.number} için vazgeçildi.`;
}

type Stage =
  | { step: "form"; problem: ApiError | null }
  | { step: "preview"; preview: CancelPreview; changed: boolean; problem: ApiError | null };

function Summary({ item, reason }: { item: SettingItem; reason?: string }) {
  const today = useToday();
  return (
    <Paper withBorder p="md" className="ft-surface">
      <dl className="ft-summary">
        <SummaryRow term="Yürürlük">
          {dayLabel(item.effective_from, { today, case: "den" })} itibaren
        </SummaryRow>
        {item.changes.map((change) => (
          <SummaryRow key={change.setting} term={change.setting}>
            {change.change}
          </SummaryRow>
        ))}
        {reason !== undefined && (
          <SummaryRow term="Gerekçe">
            <strong>{reason}</strong>
          </SummaryRow>
        )}
      </dl>
    </Paper>
  );
}

function CancelFlow({ item }: { item: SettingItem }) {
  const profile = useProfile();
  const api = useApi();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [stage, setStage] = useState<Stage>({ step: "form", problem: null });
  const [busy, setBusy] = useState(false);
  const title = `Ayar sürümü #${item.id}: vazgeç`;
  const path = { params: { path: { profil: profile, no: item.id } } };
  const note = "Kayıt silinmez; vazgeçildiği ve gerekçesi geçmişte kalır.";

  async function preview() {
    setBusy(true);
    const outcome = await settle(
      api.POST("/api/{profil}/ayarlar/{no}/vazgec/onizle", { ...path, body: { reason } }),
    );
    setBusy(false);
    setStage(
      outcome.data === undefined
        ? { step: "form", problem: outcome.problem }
        : { step: "preview", preview: outcome.data, changed: false, problem: null },
    );
  }

  async function save(current: CancelPreview) {
    setBusy(true);
    const outcome = await settle(
      api.POST("/api/{profil}/ayarlar/{no}/vazgec/kaydet", {
        ...path,
        body: { confirmation: current.confirmation },
      }),
    );
    setBusy(false);
    if (outcome.data !== undefined) {
      void queryClient.invalidateQueries({ queryKey: ["sayfa", profile] });
      notifications.show({
        color: outcome.data.duplicate ? "kehribar" : "yaprak",
        message: cancelSavedMessage(outcome.data),
      });
      navigate(href(profile, "ayarlar"));
      return;
    }
    const fresh = changedPreview<CancelPreview>(outcome);
    setStage(
      fresh === null
        ? { step: "preview", preview: current, changed: false, problem: outcome.problem }
        : { step: "preview", preview: fresh, changed: true, problem: null },
    );
  }

  if (stage.step === "preview") {
    return (
      <Page title={title}>
        <Text c="dimmed">{note} Henüz bir şey kaydedilmedi.</Text>
        <Steps current={2} />
        {stage.changed && (
          <Warning>
            <strong>Önizlemeden sonra veriler değişti; kayıt yapılmadı.</strong> Yeni önizlemeyi
            kontrol et.
          </Warning>
        )}
        <TargetProfile profile={profile} />
        <Summary item={stage.preview.target} reason={stage.preview.reason} />
        {stage.problem !== null && (
          <WriteProblem problem={stage.problem} onRetry={() => void save(stage.preview)} />
        )}
        <Group gap="sm">
          <Button color="kiremit" onClick={() => void save(stage.preview)} loading={busy}>
            Vazgeçmeyi kaydet
          </Button>
          <Button variant="default" onClick={() => setStage({ step: "form", problem: null })}>
            Düzenle
          </Button>
        </Group>
      </Page>
    );
  }

  return (
    <Page title={title}>
      <Text c="dimmed">{note}</Text>
      <Steps current={1} />
      {stage.problem !== null && (
        <WriteProblem problem={stage.problem} onRetry={() => void preview()} />
      )}
      <Summary item={item} />
      <form
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          void preview();
        }}
      >
        <Stack gap="md" maw={520}>
          <Textarea
            label="Gerekçe"
            maxLength={200}
            rows={3}
            description='Ör. "yanlış tutar", "plan değişti". Kayıtta kalır.'
            value={reason}
            onChange={(event) => setReason(event.currentTarget.value)}
            error={stage.problem?.fields.reason}
          />
          <Group gap="sm">
            <Button type="submit" loading={busy}>
              Önizle
            </Button>
            <Button component={Link} to={href(profile, "ayarlar")} variant="default">
              Vazgeç
            </Button>
          </Group>
        </Stack>
      </form>
    </Page>
  );
}

function CancelLoader({ number }: { number: number }) {
  const profile = useProfile();
  const api = useApi();
  const query = useQuery({
    queryKey: ["sayfa", profile, "vazgec", number],
    queryFn: () =>
      unwrap(
        api.GET("/api/{profil}/ayarlar/{no}/vazgec", {
          params: { path: { profil: profile, no: number } },
        }),
      ),
    staleTime: 0,
    gcTime: 0,
  });
  return <QueryView query={query}>{(item) => <CancelFlow item={item} />}</QueryView>;
}

export function SettingCancelPage() {
  const { no } = useParams();
  if (no === undefined || !/^[1-9][0-9]*$/.test(no)) {
    return <NotFound />;
  }
  return <CancelLoader key={no} number={Number.parseInt(no, 10)} />;
}
