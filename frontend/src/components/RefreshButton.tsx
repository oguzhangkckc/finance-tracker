import { Button, Stack } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { ApiError } from "../api/client";
import { useApi } from "../api/context";
import { settle } from "../api/writes";
import type { ProfileSlug } from "../profile";
import { WriteProblem } from "./WriteProblem";

export const REFRESH_ACCEPTED =
  "Güncelleme isteği alındı; fiyat işi birkaç dakika içinde çalışır. Bugünün fiyatları zaten tamamsa TEFAS'a istek atılmaz.";

// Web süreci fiyat çekmez; istek bırakılır, işi .path birimi başlatır (K-122).
export function RefreshButton({ profile }: { profile: ProfileSlug }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<ApiError | null>(null);

  async function ask() {
    setBusy(true);
    setProblem(null);
    // Gövde yok; CSRF denetimi JSON türünü ister (K-137), uzunluğu tarayıcı 0 yazar.
    const outcome = await settle(
      api.POST("/api/{profil}/fiyat-guncelle", {
        params: { path: { profil: profile } },
        headers: { "Content-Type": "application/json" },
      }),
    );
    setBusy(false);
    if (outcome.data === undefined) {
      setProblem(outcome.problem);
      return;
    }
    const { accepted, refresh } = outcome.data;
    notifications.show({
      color: accepted ? "yaprak" : "kehribar",
      message: accepted
        ? REFRESH_ACCEPTED
        : `Elle güncelleme şu an kapalı: ${refresh.reason ?? "neden bildirilmedi"}.`,
    });
    await queryClient.invalidateQueries({ queryKey: ["sayfa", profile, "ozet"] });
  }

  return (
    <Stack gap="xs" align="flex-start">
      <Button onClick={() => void ask()} loading={busy}>
        Fiyatları güncelle
      </Button>
      {problem !== null && <WriteProblem problem={problem} onRetry={() => void ask()} />}
    </Stack>
  );
}
