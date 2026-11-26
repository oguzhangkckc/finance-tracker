import {
  Alert,
  Button,
  Checkbox,
  Group,
  NativeSelect,
  Paper,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ChangeEvent, type ReactNode, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import type { ApiError } from "../api/client";
import { useApi } from "../api/context";
import { fundOptionsQuery } from "../api/queries";
import {
  changedPreview,
  type FundOption,
  priceDays,
  type Saved,
  settle,
  type TradePreview,
} from "../api/writes";
import { useToday } from "../clock";
import { Warning } from "../components/Notice";
import { Steps } from "../components/Steps";
import { TargetProfile } from "../components/TargetProfile";
import { WriteProblem } from "../components/WriteProblem";
import { dayLabel, exact, money } from "../format/display";
import { Icon } from "../layout/icons";
import { href } from "../layout/nav";
import { type ProfileSlug, useProfile } from "../profile";
import { NotFound } from "./NotFound";
import { Page } from "./Page";

type TradeKind = "alis" | "satis";

const HEADINGS: Record<ProfileSlug, Record<TradeKind, readonly [string, string]>> = {
  gercek: {
    alis: ["Alım ekle", "Dekonttaki adet ve fiyatla."],
    satis: ["Satış ekle", "Dekonttaki adet ve fiyatla."],
  },
  sanal: {
    alis: [
      "Sanal alım",
      "Tutarla; adet o günün kayıtlı fiyatından hesaplanır, artan tutar fona girmez.",
    ],
    satis: ["Sanal satış", "Adetle ya da eldeki payın tümü; fiyat o günün kayıtlı fiyatıdır."],
  },
};

const CONFIRM_LABELS: Record<ProfileSlug, Record<TradeKind, string>> = {
  gercek: { alis: "Gerçek alımı kaydet", satis: "Gerçek satışı kaydet" },
  sanal: { alis: "Sanal alımı kaydet", satis: "Sanal satışı kaydet" },
};

const SAVED_NAMES: Record<TradeKind, string> = { alis: "Alım", satis: "Satış" };
const DECIMAL_HINT = "Ondalık ayırıcı virgül; binlik ayırıcı yazma.";

export function tradeSavedMessage(kind: TradeKind, saved: Saved): string {
  return saved.duplicate
    ? `Bu onay zaten kullanıldı; işlem #${saved.number} olarak kaydedildi.`
    : `${SAVED_NAMES[kind]} #${saved.number} kaydedildi.`;
}

interface TradeValues {
  fund: string;
  day: string;
  units: string;
  price: string;
  fee: string;
  amount: string;
  ref: string;
  all: boolean;
}

type TextField = Exclude<keyof TradeValues, "all">;

type Stage =
  | { step: "form"; problem: ApiError | null; days: string[] }
  | { step: "preview"; preview: TradePreview; changed: boolean; problem: ApiError | null };

function fundLabel(option: FundOption): string {
  return option.name === option.code ? option.code : `${option.code} · ${option.name}`;
}

function optional(label: string): ReactNode {
  return (
    <>
      {label}{" "}
      <Text span c="dimmed" size="sm">
        (isteğe bağlı)
      </Text>
    </>
  );
}

function affix(unit: string): ReactNode {
  return (
    <Text size="sm" c="dimmed">
      {unit}
    </Text>
  );
}

export function SummaryRow({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div className="ft-summary-row">
      <dt>{term}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function Preview({
  preview,
  profile,
  today,
}: {
  preview: TradePreview;
  profile: ProfileSlug;
  today: string;
}) {
  const sanal = profile === "sanal";
  return (
    <Paper withBorder p="md" className="ft-surface">
      <dl className="ft-summary">
        <SummaryRow term="Fon">
          {preview.instrument}
          {preview.fund_name !== preview.instrument && ` · ${preview.fund_name}`}
        </SummaryRow>
        <SummaryRow term={sanal ? "Fiyat günü" : "İşlem günü"}>
          {dayLabel(preview.trade_date, { today })}
        </SummaryRow>
        <SummaryRow term="Adet">{exact(preview.units)} pay</SummaryRow>
        <SummaryRow term="Birim fiyat">{exact(preview.unit_price)} TL</SummaryRow>
        <SummaryRow term="Komisyon">{money(preview.fee)}</SummaryRow>
        {sanal && preview.leftover !== null && (
          <SummaryRow term="Artan tutar">
            {money(preview.leftover)}{" "}
            <Text span c="dimmed" size="sm">
              (fona girmez)
            </Text>
          </SummaryRow>
        )}
        {preview.ref !== null && <SummaryRow term="Dekont no">{preview.ref}</SummaryRow>}
        <SummaryRow term="Tutar">
          <strong>{money(preview.gross)}</strong>
        </SummaryRow>
        <SummaryRow term={`${preview.instrument} payın`}>
          {exact(preview.units_before)} → {exact(preview.units_after)}
        </SummaryRow>
      </dl>
    </Paper>
  );
}

export function TradePage() {
  const { tur } = useParams();
  if (tur !== "alis" && tur !== "satis") {
    return <NotFound />;
  }
  return <TradeFlow key={tur} kind={tur} />;
}

function TradeFlow({ kind }: { kind: TradeKind }) {
  const profile = useProfile();
  const api = useApi();
  const today = useToday();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const funds = useQuery(fundOptionsQuery(api, profile));
  const [values, setValues] = useState<TradeValues>({
    fund: "",
    day: today,
    units: "",
    price: "",
    fee: "",
    amount: "",
    ref: "",
    all: false,
  });
  const [stage, setStage] = useState<Stage>({ step: "form", problem: null, days: [] });
  const [busy, setBusy] = useState(false);
  const sanal = profile === "sanal";
  const [heading, lead] = HEADINGS[profile][kind];

  async function preview(input: TradeValues) {
    setBusy(true);
    const outcome = await settle(
      api.POST("/api/{profil}/islemler/{tur}/onizle", {
        params: { path: { profil: profile, tur: kind } },
        body: input,
      }),
    );
    setBusy(false);
    if (outcome.data !== undefined) {
      setStage({ step: "preview", preview: outcome.data, changed: false, problem: null });
    } else {
      setStage({ step: "form", problem: outcome.problem, days: priceDays(outcome.body) });
    }
  }

  async function save(current: TradePreview) {
    setBusy(true);
    const outcome = await settle(
      api.POST("/api/{profil}/islemler/kaydet", {
        params: { path: { profil: profile } },
        body: { confirmation: current.confirmation },
      }),
    );
    setBusy(false);
    if (outcome.data !== undefined) {
      void queryClient.invalidateQueries({ queryKey: ["sayfa", profile] });
      notifications.show({
        color: outcome.data.duplicate ? "kehribar" : "yaprak",
        message: tradeSavedMessage(kind, outcome.data),
      });
      navigate(href(profile, "islemler"));
      return;
    }
    const fresh = changedPreview<TradePreview>(outcome);
    setStage(
      fresh === null
        ? { step: "preview", preview: current, changed: false, problem: outcome.problem }
        : { step: "preview", preview: fresh, changed: true, problem: null },
    );
  }

  const set = (key: TextField) => (event: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const value = event.currentTarget.value;
    setValues((previous) => ({ ...previous, [key]: value }));
  };

  if (stage.step === "preview") {
    return (
      <Page title={kind === "alis" ? "Alımı kontrol et" : "Satışı kontrol et"}>
        <Text c="dimmed">Henüz bir şey kaydedilmedi.</Text>
        <Steps current={2} />
        {stage.changed && (
          <Warning>
            <strong>Önizlemeden sonra veriler değişti; kayıt yapılmadı.</strong> Yeni önizlemeyi
            kontrol et.
          </Warning>
        )}
        <TargetProfile profile={profile} />
        <Preview preview={stage.preview} profile={profile} today={today} />
        {stage.preview.warnings.map((warning) => (
          <Warning key={warning}>
            {warning}{" "}
            <span className="ft-muted">Bu bir uyarı; emin isen olduğu gibi kaydedebilirsin.</span>
          </Warning>
        ))}
        {stage.problem !== null && (
          <WriteProblem problem={stage.problem} onRetry={() => void save(stage.preview)} />
        )}
        <Group gap="sm">
          <Button onClick={() => void save(stage.preview)} loading={busy}>
            {CONFIRM_LABELS[profile][kind]}
          </Button>
          <Button
            variant="default"
            onClick={() => setStage({ step: "form", problem: null, days: [] })}
          >
            Düzenle
          </Button>
        </Group>
      </Page>
    );
  }

  const fields = stage.problem?.fields ?? {};
  const options = funds.data?.[kind === "alis" ? "buy" : "sell"] ?? [];
  return (
    <Page title={heading}>
      <Text c="dimmed">{lead}</Text>
      <Steps current={1} />
      {stage.problem !== null &&
        (stage.days.length > 0 ? (
          // K-109: gün hiçbir zaman kendiliğinden kaydırılmaz; en yakın fiyatlı günler yalnız seçenek.
          <Alert color="kiremit" variant="light" icon={<Icon name="hata" />} role="alert">
            <Stack gap="xs" align="flex-start">
              <Text size="sm">
                <strong>{stage.problem.message}</strong> Fiyat uydurulmaz, gün kendiliğinden
                kaydırılmaz.
              </Text>
              <Group gap="sm">
                {stage.days.map((day) => (
                  <Button
                    key={day}
                    variant="default"
                    onClick={() => {
                      const next = { ...values, day };
                      setValues(next);
                      void preview(next);
                    }}
                  >
                    {dayLabel(day, { today })} gününü kullan
                  </Button>
                ))}
              </Group>
            </Stack>
          </Alert>
        ) : (
          <WriteProblem problem={stage.problem} onRetry={() => void preview(values)} />
        ))}
      <form
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          void preview(values);
        }}
      >
        <Stack gap="md" maw={520}>
          <NativeSelect
            label="Fon"
            value={values.fund}
            onChange={set("fund")}
            error={fields.fund}
            data={[
              { value: "", label: "Seç" },
              ...options.map((option) => ({ value: option.code, label: fundLabel(option) })),
            ]}
          />
          <TextInput
            type="date"
            label={sanal ? "Fiyat günü" : "İşlem günü"}
            description={
              sanal
                ? "Fiyat yalnız bu günün kayıtlı fiyatından alınır; gün kaydırılmaz."
                : "Dekonttaki işlem günü; fiyatın açıklandığı gün."
            }
            value={values.day}
            onChange={set("day")}
            error={fields.day}
          />
          {!sanal && (
            <>
              <TextInput
                label="Adet"
                inputMode="decimal"
                rightSection={affix("pay")}
                value={values.units}
                onChange={set("units")}
                error={fields.units}
              />
              <TextInput
                label="Birim fiyat"
                inputMode="decimal"
                rightSection={affix("TL")}
                description={`Dekonttaki bütün basamaklarla (ör. 1,744322). ${DECIMAL_HINT}`}
                value={values.price}
                onChange={set("price")}
                error={fields.price}
              />
              <TextInput
                label={optional("Komisyon")}
                inputMode="decimal"
                rightSection={affix("TL")}
                value={values.fee}
                onChange={set("fee")}
                error={fields.fee}
              />
              <TextInput
                label={optional("Dekont no")}
                maxLength={64}
                description="Aynı dekontun iki kez girilmesini engeller, ekstre mutabakatını kolaylaştırır."
                value={values.ref}
                onChange={set("ref")}
                error={fields.ref}
              />
            </>
          )}
          {sanal && kind === "alis" && (
            <>
              <TextInput
                label="Tutar"
                inputMode="decimal"
                rightSection={affix("TL")}
                description={`Adet aşağı yuvarlanır; artan tutar fona girmez. ${DECIMAL_HINT}`}
                value={values.amount}
                onChange={set("amount")}
                error={fields.amount}
              />
              <TextInput
                label={optional("Komisyon")}
                inputMode="decimal"
                rightSection={affix("TL")}
                value={values.fee}
                onChange={set("fee")}
                error={fields.fee}
              />
            </>
          )}
          {sanal && kind === "satis" && (
            <>
              <TextInput
                label={optional("Adet")}
                inputMode="decimal"
                rightSection={affix("pay")}
                description="Eldeki payın tümü için boş bırakıp aşağıdaki kutuyu işaretle."
                value={values.units}
                onChange={set("units")}
                error={fields.units}
              />
              <Checkbox
                label="Eldeki payın tümünü sat"
                checked={values.all}
                onChange={(event) => {
                  const checked = event.currentTarget.checked;
                  setValues((previous) => ({ ...previous, all: checked }));
                }}
                error={fields.all}
              />
            </>
          )}
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
