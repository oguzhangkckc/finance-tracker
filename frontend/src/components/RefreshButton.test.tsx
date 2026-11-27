import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { json } from "../test/fetch";
import { overview } from "../test/pages";
import { pageRoutes, renderApp } from "../test/render";
import { REFRESH_ACCEPTED } from "./RefreshButton";

const REFRESH = "POST /api/gercek/fiyat-guncelle";

function open(response: () => Response) {
  const requests: Request[] = [];
  const view = renderApp("/gercek", {
    ...pageRoutes("/api/gercek/ozet", overview()),
    [REFRESH]: (request) => {
      requests.push(request);
      return response();
    },
  });
  return { ...view, requests };
}

const REFUSED_STATE = {
  allowed: false,
  reason: "bugün zaten güncellendi",
  earliest: null,
  last_sync: null,
};

describe("fiyatları güncelle", () => {
  it("isteği JSON türüyle ve gövdesiz gönderir; kabul edilirse bildirir", async () => {
    const { user, requests } = open(() => json({ accepted: true, refresh: REFUSED_STATE }));

    await user.click(await screen.findByRole("button", { name: "Fiyatları güncelle" }));

    expect(await screen.findByText(REFRESH_ACCEPTED)).toBeInTheDocument();
    expect(requests).toHaveLength(1);
    expect(requests[0]?.headers.get("content-type")).toBe("application/json");
    expect(await requests[0]?.text()).toBe("");
  });

  it("kabul edilmezse nedenini söyler", async () => {
    const { user } = open(() => json({ accepted: false, refresh: REFUSED_STATE }));

    await user.click(await screen.findByRole("button", { name: "Fiyatları güncelle" }));

    expect(
      await screen.findByText("Elle güncelleme şu an kapalı: bugün zaten güncellendi."),
    ).toBeInTheDocument();
  });

  it("istek yazılamazsa nedeni ve yeniden deneme çıkar", async () => {
    const failed = "Güncelleme isteği yazılamadı; Sistem sayfasına bakın.";
    const { user } = open(() => json({ error: failed }, 503));

    await user.click(await screen.findByRole("button", { name: "Fiyatları güncelle" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(failed);
    expect(within(alert).getByRole("button", { name: "Yeniden dene" })).toBeInTheDocument();
  });

  it("elle güncelleme kapalıyken düğme yoktur", async () => {
    renderApp(
      "/gercek",
      pageRoutes("/api/gercek/ozet", overview({ refresh: { ...REFUSED_STATE, last_sync: null } })),
    );

    expect(await screen.findByText(/Elle güncelleme şu an kapalı/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Fiyatları güncelle" })).not.toBeInTheDocument();
  });
});
