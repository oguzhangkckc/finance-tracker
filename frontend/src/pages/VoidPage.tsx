import { Alert, Anchor, Button, Group, Paper, Stack, Text, Textarea } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import type { ApiError } from "../api/client";
import { useApi } from "../api/context";
import {
  type BlockingSale,
  blockingSales,
  changedPreview,
  type Saved,
  settle,
  type VoidPreview,
  type VoidTarget,
} from "../api/writes";
import { useToday } from "../clock";
import { Warning } from "../components/Notice";
import { QueryView } from "../components/QueryView";
import { Steps } from "../components/Steps";
import { TargetProfile } from "../components/TargetProfile";
import { WriteProblem } from "../components/WriteProblem";
import { dayLabel, exact } from "../format/display";
import { Icon } from "../layout/icons";
import { href } from "../layout/nav";
import { type ProfileSlug, useProfile } from "../profile";
import { NotFound } from "./NotFound";
import { Page } from "./Page";
import { SummaryRow } from "./TradePage";

export function voidSavedMessage(saved: Saved): string {
  return saved.duplicate
    ? `Bu onay zaten kullanıldı; #${saved.number} numaralı işlem iptal edildi.`
    : `#${saved.number} numaralı işlem iptal edildi.`;
}

type Loaded = { target: VoidTarget } | { blocking: BlockingSale[] };

type Stage =
  | { step: "form"; problem: ApiError | null }
  | { step: "preview"; preview: VoidPreview; changed: boolean; problem: ApiError | null }
  | { step: "blocked"; blocking: BlockingSale[] };

function Blocked({ blocking, profile }: { blocking: BlockingSale[]; profile: ProfileSlug }) {
  const today = useToday();
  return (
    <>
      <Alert color="kiremit" variant="light" icon={<Icon name="hata" />} role="alert">
        <Text size="sm">
          <strong>Bu işlem şimdi iptal edilemez.</strong> İptal edilirse sonraki satışlar elde
          olmayan payı satmış olur. Önce şu satışları iptal et:
        </Text>
        <ul className="ft-plain" aria-label="Önce iptal edilecek satışlar">
          {blocking.map((sale) => (
            <li key={sale.id}>
              <Anchor component={Link} to={href(profile, `islemler/${sale.id}/iptal`)}>
                #{sale.id}
              </Anchor>{" "}
              · {dayLabel(sale.trade_date, { today })} · {sale.instrument} · {exact(sale.units)} pay
            </li>
          ))}
        </ul>
      </Alert>
      <Group>
        <Button component={Link} to={href(profile, "islemler")} variant="default">
          İşlemlere dön
        </Button>
      </Group>
    </>
  );
}

function Summary({ target, reason }: { target: VoidTarget; reason?: string }) {
  const today = useToday();
  return (
    <Paper withBorder p="md" className="ft-surface">
      <dl className="ft-summary">
        <SummaryRow term="Fon">{target.instrument}</SummaryRow>
        <SummaryRow term="Gün">{dayLabel(target.trade_date, { today })}</SummaryRow>
        <SummaryRow term="Yön">{target.side === "BUY" ? "alış" : "satış"}</SummaryRow>
        <SummaryRow term="Adet">{exact(target.units)} pay</SummaryRow>
        <SummaryRow term="Birim fiyat">{exact(target.unit_price)} TL</SummaryRow>
        {target.external_ref !== null && (
          <SummaryRow term="Dekont no">{target.external_ref}</SummaryRow>
        )}
        {reason !== undefined && (
          <SummaryRow term="Gerekçe">
            <strong>{reason}</strong>
          </SummaryRow>
        )}
      </dl>
    </Paper>
  );
}

function VoidFlow({ number, loaded }: { number: number; loaded: Loaded }) {
  const profile = useProfile();
  const api = useApi();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [stage, setStage] = useState<Stage>(
    "blocking" in loaded
      ? { step: "blocked", blocking: loaded.blocking }
      : { step: "form", problem: null },
  );
  const [busy, setBusy] = useState(false);
  const title = `İşlem #${number} iptali`;
  const path = { params: { path: { profil: profile, no: number } } };

  function blockedOr(body: unknown): BlockingSale[] | null {
    const blocking = blockingSales(body);
    return blocking !== null && blocking.length > 0 ? blocking : null;
  }

  async function preview() {
    setBusy(true);
    const outcome = await settle(
      api.POST("/api/{profil}/islemler/{no}/iptal/onizle", { ...path, body: { reason } }),
    );
    setBusy(false);
    const blocking = blockedOr(outcome.body);
    if (outcome.data !== undefined) {
      setStage({ step: "preview", preview: outcome.data, changed: false, problem: null });
    } else if (blocking !== null) {
      setStage({ step: "blocked", blocking });
    } else {
      setStage({ step: "form", problem: outcome.problem });
    }
  }

  async function save(current: VoidPreview) {
    setBusy(true);
    const outcome = await settle(
      api.POST("/api/{profil}/islemler/{no}/iptal/kaydet", {
        ...path,
        body: { confirmation: current.confirmation },
      }),
    );
    setBusy(false);
    if (outcome.data !== undefined) {
      void queryClient.invalidateQueries({ queryKey: ["sayfa", profile] });
      notifications.show({
        color: outcome.data.duplicate ? "kehribar" : "yaprak",
        message: voidSavedMessage(outcome.data),
      });
      navigate(href(profile, "islemler"));
      return;
    }
    const fresh = changedPreview<VoidPreview>(outcome);
    const blocking = blockedOr(outcome.body);
    if (fresh !== null) {
      setStage({ step: "preview", preview: fresh, changed: true, problem: null });
    } else if (blocking !== null) {
      setStage({ step: "blocked", blocking });
    } else {
      setStage({ step: "preview", preview: current, changed: false, problem: outcome.problem });
    }
  }

  if (stage.step === "blocked") {
    return (
      <Page title={title}>
        <Blocked blocking={stage.blocking} profile={profile} />
      </Page>
    );
  }
  const note = "Kayıt silinmez; iptal edildiği ve gerekçesi işlem listesinde kalır.";
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
        <Summary target={stage.preview.target} reason={stage.preview.reason} />
        {stage.problem !== null && (
          <WriteProblem problem={stage.problem} onRetry={() => void save(stage.preview)} />
        )}
        <Group gap="sm">
          <Button color="kiremit" onClick={() => void save(stage.preview)} loading={busy}>
            İptali kaydet
          </Button>
          <Button variant="default" onClick={() => setStage({ step: "form", problem: null })}>
            Düzenle
          </Button>
        </Group>
      </Page>
    );
  }
  if (!("target" in loaded)) {
    return null;
  }
  return (
    <Page title={title}>
      <Text c="dimmed">{note}</Text>
      <Steps current={1} />
      {stage.problem !== null && (
        <WriteProblem problem={stage.problem} onRetry={() => void preview()} />
      )}
      <Summary target={loaded.target} />
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
            description='Ör. "yanlış adet", "dekont iptal edildi". Kayıtta kalır.'
            value={reason}
            onChange={(event) => setReason(event.currentTarget.value)}
            error={stage.problem?.fields.reason}
          />
          <Group gap="sm">
            <Button type="submit" loading={busy}>
              Önizle
            </Button>
            <Button component={Link} to={href(profile, "islemler")} variant="default">
              Vazgeç
            </Button>
          </Group>
        </Stack>
      </form>
    </Page>
  );
}

function VoidLoader({ number }: { number: number }) {
  const profile = useProfile();
  const api = useApi();
  // İptali engelleyen satışlar 422 ile gelir (K-58); bu durum hata değil, ayrı bir ekrandır.
  const query = useQuery({
    queryKey: ["sayfa", profile, "iptal", number],
    queryFn: async (): Promise<Loaded> => {
      const outcome = await settle(
        api.GET("/api/{profil}/islemler/{no}/iptal", {
          params: { path: { profil: profile, no: number } },
        }),
      );
      if (outcome.data !== undefined) {
        return { target: outcome.data };
      }
      const blocking = blockingSales(outcome.body);
      if (outcome.status === 422 && blocking !== null && blocking.length > 0) {
        return { blocking };
      }
      throw outcome.problem;
    },
    staleTime: 0,
    gcTime: 0,
  });
  return (
    <QueryView query={query}>
      {(loaded) => <VoidFlow key={number} number={number} loaded={loaded} />}
    </QueryView>
  );
}

export function VoidPage() {
  const { no } = useParams();
  if (no === undefined || !/^[1-9][0-9]*$/.test(no)) {
    return <NotFound />;
  }
  return <VoidLoader key={no} number={Number.parseInt(no, 10)} />;
}
