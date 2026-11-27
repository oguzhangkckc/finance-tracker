import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SANAL_NOTICE } from "./profile";
import { json, SESSION } from "./test/fetch";
import { renderApp } from "./test/render";

describe("yönlendirme", () => {
  it("kök adres oturumdaki açılış profiline gider", async () => {
    const session = () => json({ ...SESSION, default_profile: "sanal" });
    const { router } = renderApp("/", { "GET /api/oturum": session });

    expect(await screen.findByRole("heading", { level: 1, name: "Özet" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/sanal");
    expect(screen.getByText(SANAL_NOTICE)).toHaveAttribute("role", "status");
  });

  it("bilinmeyen profil için bulunamadı sayfası gösterir", async () => {
    renderApp("/baska/islemler");

    expect(await screen.findByRole("heading", { name: "Sayfa bulunamadı" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Özete dön" })).toHaveAttribute("href", "/");
    expect(screen.queryByRole("navigation", { name: "Sayfalar" })).not.toBeInTheDocument();
  });

  it("profil altında bilinmeyen sayfa kabuğun içinde bulunamadı der", async () => {
    renderApp("/sanal/yok");

    expect(await screen.findByRole("heading", { name: "Sayfa bulunamadı" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Özete dön" })).toHaveAttribute("href", "/sanal");
    expect(screen.getByText(SANAL_NOTICE)).toHaveAttribute("role", "status");
  });

  it("erişim reddedilirse iletiyi gösterir, yeniden deneme önermez", async () => {
    renderApp("/", { "GET /api/oturum": () => new Response("", { status: 403 }) });

    expect(await screen.findByRole("alert")).toHaveTextContent("Erişim reddedildi.");
    expect(screen.queryByRole("button", { name: "Yeniden dene" })).not.toBeInTheDocument();
  });

  it("sunucu meşgulse yeniden denemeyle açılır", async () => {
    let calls = 0;
    const flaky = () => {
      calls += 1;
      return calls === 1
        ? json({ error: "Veritabanı meşgul." }, 503, { "Retry-After": "5" })
        : json(SESSION);
    };
    const { user, router } = renderApp("/", { "GET /api/oturum": flaky });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Veritabanı meşgul.");
    expect(alert).toHaveTextContent("5 saniye sonra yeniden deneyebilirsin.");

    await user.click(screen.getByRole("button", { name: "Yeniden dene" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/gercek"));
    expect(calls).toBe(2);
  });
});
