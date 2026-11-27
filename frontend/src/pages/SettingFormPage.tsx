import {
  Button,
  Checkbox,
  Fieldset,
  Group,
  Paper,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { Link } from "react-router";
import type { ApiError } from "../api/client";
import { useApi } from "../api/context";
import { settingsQuery } from "../api/queries";
import type { SettingsData } from "../api/types";
import {
  changedPreview,
  type ProfileProposal,
  type ProfileResult,
  type SettingPreview,
  type SettingSaved,
  settle,
} from "../api/writes";
import { useToday } from "../clock";
import { Failure, Info, Success, Warning } from "../components/Notice";
import { QueryView } from "../components/QueryView";
import { Steps } from "../components/Steps";
import { TargetProfile } from "../components/TargetProfile";
import { WriteProblem } from "../components/WriteProblem";
import { dayLabel, exact, ratioPercent } from "../format/display";
import { targetTotal } from "../format/targets";
import { href } from "../layout/nav";
import { PROFILE_LABELS, type ProfileSlug, useProfile } from "../profile";
import { classLabels, Page } from "./Page";
import { SummaryRow } from "./TradePage";

interface SettingValues {
  day: string;
  payday: string;
  contribution: string;
  targets: Record<string, string>;
  also_sanal: boolean;
}

type Stage =
  | { step: "form"; problem: ApiError | null }
  | { step: "preview"; preview: SettingPreview; changed: boolean; problem: ApiError | null }
  | {
      step: "result";
      saved: SettingSaved;
      confirmation: Record<string, string>;
      problem: ApiError | null;
    };

function optional(label: string, isOptional: boolean): ReactNode {
  if (!isOptional) {
    return label;
  }
  return (
    <>
      {label}{" "}
      <Text span c="dimmed" size="sm">
        (isteğe bağlı)
      </Text>
    </>
  );
}

function capitalized(text: string): string {
  return text.charAt(0).toLocaleUpperCase("tr") + text.slice(1);
}

function saveLabel(preview: SettingPreview, profile: ProfileSlug): string {
  if (preview.plans.length > 1) {
    return "İki portföye de kaydet";
  }
  return profile === "sanal" ? "Sanal ayarı kaydet" : "Gerçek ayarı kaydet";
}

function Plan({ plan, carry, today }: { plan: ProfileProposal; carry: boolean; today: string }) {
  return (
    <section aria-label={`${PROFILE_LABELS[plan.profile]} portföy`}>
      <Stack gap="sm">
        <Title order={2}>{PROFILE_LABELS[plan.profile]} portföy</Title>
        <TargetProfile profile={plan.profile} />
        {plan.problem !== null ? (
          <Failure>
            <strong>Bu portföye yazılamaz.</strong> {plan.problem}
          </Failure>
        ) : (
          <>
            <Paper withBorder p="md" className="ft-surface">
              <dl className="ft-summary">
                {plan.changes.length > 0 ? (
                  plan.changes.map((change) => (
                    <SummaryRow key={change.setting} term={change.setting}>
                      {change.change}
                    </SummaryRow>
                  ))
                ) : (
                  <SummaryRow term="Değişiklik">yok</SummaryRow>
                )}
              </dl>
            </Paper>
            {plan.issues.map((issue) => (
              <Failure key={issue}>{capitalized(issue)}</Failure>
            ))}
            {plan.later.map((later) =>
              carry ? (
                <Info key={later.id}>
                  Yürürlüğü {dayLabel(later.effective_from, { today })} olan planlanan sürüm (#
                  {later.id}) bu değişikliği taşımıyordu; kaydedilince ona da taşınacak.
                </Info>
              ) : (
                <Warning key={later.id}>
                  Yürürlüğü {dayLabel(later.effective_from, { today })} olan planlanan sürüm (#
                  {later.id}) bu değişikliği taşımıyor; o günden itibaren {later.kept} olur.
                </Warning>
              ),
            )}
          </>
        )}
      </Stack>
    </section>
  );
}

function Carry({
  preview,
  today,
  onToggle,
}: {
  preview: SettingPreview;
  today: string;
  onToggle: (carry: boolean) => void;
}) {
  return (
    <Stack gap="xs">
      <Checkbox
        label="Sonraki planlanan sürümlere de uygula"
        checked={preview.carry}
        onChange={(event) => onToggle(event.currentTarget.checked)}
      />
      <Text size="sm" c="dimmed">
        {preview.carry
          ? 'Kaydedilince şu sürümlerden "yeni değişiklik taşındı" gerekçesiyle vazgeçilecek ve aynı yürürlük günüyle, yalnız değişen ayar güncellenmiş olarak yeniden yazılacak. Kutuyu kaldırırsan yeni önizleme gösterilir.'
          : 'Seçilirse şu sürümlerden "yeni değişiklik taşındı" gerekçesiyle vazgeçilir ve aynı yürürlük günüyle, yalnız değişen ayar güncellenmiş olarak yeniden yazılır. Kutuyu işaretlersen yeni önizleme gösterilir:'}
      </Text>
      <ul className="ft-plain" aria-label="Sonraki planlanan sürümler">
        {preview.plans.flatMap((plan) =>
          plan.later.map((later) => (
            <li key={`${plan.profile}-${later.id}`}>
              {PROFILE_LABELS[plan.profile]} #{later.id} ·{" "}
              {dayLabel(later.effective_from, { today, case: "den" })} itibaren:{" "}
              {later.carried.map((change) => `${change.setting} ${change.change}`).join("; ")}
            </li>
          )),
        )}
      </ul>
    </Stack>
  );
}

function Outcome({ outcome }: { outcome: ProfileResult }) {
  const name = PROFILE_LABELS[outcome.profile];
  switch (outcome.status) {
    case "saved":
      return (
        <Success>
          <strong>{name}:</strong> ayar sürümü #{outcome.setting_id} kaydedildi.
          {outcome.rewritten.map((pair) => (
            <span key={pair.cancelled} className="ft-block">
              Sonraki sürüme taşındı: #{pair.cancelled} yerine #{pair.written}.
            </span>
          ))}
        </Success>
      );
    case "duplicate":
      return (
        <Success>
          <strong>{name}:</strong> bu onay zaten kullanılmıştı; ayar sürümü #{outcome.setting_id}{" "}
          olarak kayıtlı.
        </Success>
      );
    case "changed":
      return (
        <Failure>
          <strong>{name}: yazılmadı.</strong> Önizlemeden sonra bu portföyün ayarları değişti. Diğer
          portföyün sonucu yukarıda; bu portföy için değişikliği kendi ayarlar sayfasından yeniden
          yap.
        </Failure>
      );
    case "busy":
      return (
        <Warning>
          <strong>{name}: yazılmadı.</strong> Şu an zamanlanmış bir iş çalışıyor. Birkaç saniye
          sonra yeniden dene; yazılmış olan portföy tekrar yazılmaz.
        </Warning>
      );
    default:
      return (
        <Failure>
          <strong>{name}: yazılmadı.</strong> {outcome.message}
        </Failure>
      );
  }
}

function SettingFlow({ data }: { data: SettingsData }) {
  const profile = useProfile();
  const api = useApi();
  const today = useToday();
  const queryClient = useQueryClient();
  const label = classLabels(data.class_names);
  const { current } = data;
  const [values, setValues] = useState<SettingValues>({
    day: today,
    payday: current.payday === null ? "" : String(current.payday),
    contribution: current.monthly_contribution === null ? "" : exact(current.monthly_contribution),
    targets: Object.fromEntries(
      data.classes.map((code) => [code, ratioPercent(current.targets[code] ?? "0")]),
    ),
    also_sanal: false,
  });
  const [stage, setStage] = useState<Stage>({ step: "form", problem: null });
  const [busy, setBusy] = useState(false);
  const total = targetTotal(data.classes.map((code) => values.targets[code] ?? ""));
  const path = { params: { path: { profil: profile } } };

  // Girdi web formundaki gibi gider: bugünkü değerle aynı alan değişmiş sayılmaz (K-138).
  async function preview(carry: boolean) {
    setBusy(true);
    const outcome = await settle(
      api.POST("/api/{profil}/ayarlar/onizle", { ...path, body: { ...values, carry } }),
    );
    setBusy(false);
    if (outcome.data !== undefined) {
      setStage({ step: "preview", preview: outcome.data, changed: false, problem: null });
    } else {
      setStage({ step: "form", problem: outcome.problem });
    }
  }

  async function save(current: SettingPreview, confirmation: Record<string, string>) {
    setBusy(true);
    const outcome = await settle(
      api.POST("/api/{profil}/ayarlar/kaydet", { ...path, body: { confirmation } }),
    );
    setBusy(false);
    if (outcome.data !== undefined) {
      void queryClient.invalidateQueries({ queryKey: ["sayfa"] });
      setStage({ step: "result", saved: outcome.data, confirmation, problem: null });
      return;
    }
    const fresh = changedPreview<SettingPreview>(outcome);
    setStage(
      fresh === null
        ? { step: "preview", preview: current, changed: false, problem: outcome.problem }
        : { step: "preview", preview: fresh, changed: true, problem: null },
    );
  }

  async function retry(confirmation: Record<string, string>) {
    setBusy(true);
    const outcome = await settle(
      api.POST("/api/{profil}/ayarlar/kaydet", { ...path, body: { confirmation } }),
    );
    setBusy(false);
    if (outcome.data !== undefined) {
      void queryClient.invalidateQueries({ queryKey: ["sayfa"] });
      setStage({ step: "result", saved: outcome.data, confirmation, problem: null });
    } else if (stage.step === "result") {
      setStage({ ...stage, problem: outcome.problem });
    }
  }

  if (stage.step === "result") {
    const anyBusy = stage.saved.outcomes.some((outcome) => outcome.status === "busy");
    return (
      <Page title="Ayar sürümü sonucu">
        <Steps current={3} />
        <Text c="dimmed">İki portföy ayrı veritabanındadır; her birinin sonucu ayrı.</Text>
        {stage.saved.outcomes.map((outcome) => (
          <Outcome key={outcome.profile} outcome={outcome} />
        ))}
        {stage.problem !== null && <WriteProblem problem={stage.problem} />}
        <Group gap="sm">
          {anyBusy && (
            <Button onClick={() => void retry(stage.confirmation)} loading={busy}>
              Yeniden dene
            </Button>
          )}
          <Button component={Link} to={href(profile, "ayarlar")} variant="default">
            Ayarlara dön
          </Button>
        </Group>
      </Page>
    );
  }

  if (stage.step === "preview") {
    const { preview: shown } = stage;
    const confirmation = shown.confirmation;
    return (
      <Page title="Ayar sürümünü kontrol et">
        <Text c="dimmed">
          Henüz bir şey kaydedilmedi. Yürürlük: {dayLabel(shown.day, { today, case: "den" })}{" "}
          itibaren.
        </Text>
        <Steps current={2} />
        {stage.changed && (
          <Warning>
            <strong>Önizlemeden sonra veriler değişti; kayıt yapılmadı.</strong> Yeni önizlemeyi
            kontrol et.
          </Warning>
        )}
        {shown.plans.map((plan) => (
          <Plan key={plan.profile} plan={plan} carry={shown.carry} today={today} />
        ))}
        {stage.problem !== null && (
          <WriteProblem
            problem={stage.problem}
            onRetry={confirmation === null ? undefined : () => void save(shown, confirmation)}
          />
        )}
        {confirmation !== null && shown.carry_option && (
          <Carry preview={shown} today={today} onToggle={(carry) => void preview(carry)} />
        )}
        <Group gap="sm">
          {confirmation !== null && (
            <Button onClick={() => void save(shown, confirmation)} loading={busy}>
              {saveLabel(shown, profile)}
            </Button>
          )}
          <Button variant="default" onClick={() => setStage({ step: "form", problem: null })}>
            Düzenle
          </Button>
        </Group>
      </Page>
    );
  }

  const fields = stage.problem?.fields ?? {};
  return (
    <Page title="Yeni ayar sürümü">
      <Text c="dimmed">Değiştirmediğin ayar, yürürlük gününde geçerli olan değeriyle kalır.</Text>
      <Steps current={1} />
      {stage.problem !== null && (
        <WriteProblem problem={stage.problem} onRetry={() => void preview(false)} />
      )}
      <form
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          void preview(false);
        }}
      >
        <Stack gap="md" maw={520}>
          <TextInput
            type="date"
            label="Yürürlük günü"
            description="En erken bugün. Maaş günü değişikliği yalnız bir ayın 1'inden geçerli olabilir."
            value={values.day}
            onChange={(event) => {
              const day = event.currentTarget.value;
              setValues((previous) => ({ ...previous, day }));
            }}
            error={fields.day}
          />
          <TextInput
            label={optional("Maaş günü", current.payday === null)}
            inputMode="numeric"
            maxLength={2}
            description="Ayın kaçı (1 ile 31 arası); ay daha kısaysa ayın son günü."
            value={values.payday}
            onChange={(event) => {
              const payday = event.currentTarget.value;
              setValues((previous) => ({ ...previous, payday }));
            }}
            error={fields.payday}
          />
          <TextInput
            label={optional("Aylık katkı", current.monthly_contribution === null)}
            inputMode="decimal"
            rightSection={
              <Text size="sm" c="dimmed">
                TL
              </Text>
            }
            description="Ondalık ayırıcı virgül; binlik ayırıcı yazma."
            value={values.contribution}
            onChange={(event) => {
              const contribution = event.currentTarget.value;
              setValues((previous) => ({ ...previous, contribution }));
            }}
            error={fields.contribution}
          />
          <Fieldset legend="Hedef dağılım">
            <Stack gap="sm">
              {data.classes.map((code) => (
                <TextInput
                  key={code}
                  label={label(code)}
                  inputMode="decimal"
                  rightSection={
                    <Text size="sm" c="dimmed">
                      %
                    </Text>
                  }
                  value={values.targets[code] ?? ""}
                  onChange={(event) => {
                    const value = event.currentTarget.value;
                    setValues((previous) => ({
                      ...previous,
                      targets: { ...previous.targets, [code]: value },
                    }));
                  }}
                  error={fields[`targets.${code}`]}
                />
              ))}
              <Text
                fw={600}
                className={total.exact ? "ft-num" : "ft-num ft-warn"}
                aria-live="polite"
              >
                {total.text}
              </Text>
              {fields.targets !== undefined && (
                <Text size="sm" className="ft-loss">
                  {fields.targets}
                </Text>
              )}
              <Text size="sm" c="dimmed">
                Yüzde olarak, virgüllü ondalıkla (ör. 17,5); toplam tam %100 olmalı.
              </Text>
            </Stack>
          </Fieldset>
          {profile === "gercek" && (
            <Checkbox
              label="Sanal portföye de uygula"
              description="Aynı değişiklik sanal portföyün ayarına ayrı bir kayıtla yazılır; önizlemede iki portföy ayrı gösterilir."
              checked={values.also_sanal}
              onChange={(event) => {
                const also = event.currentTarget.checked;
                setValues((previous) => ({ ...previous, also_sanal: also }));
              }}
            />
          )}
          <Group gap="sm">
            <Button type="submit" loading={busy} disabled={!total.exact}>
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

export function SettingFormPage() {
  const query = useQuery(settingsQuery(useApi(), useProfile(), ""));
  return <QueryView query={query}>{(data) => <SettingFlow data={data} />}</QueryView>;
}
