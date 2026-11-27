import { describe, expect, it, vi } from "vitest";
import { fakeFetch, json, SESSION } from "../test/fetch";
import {
  ApiError,
  createApi,
  NETWORK_STATUS,
  reloadOnce,
  SESSION_EXPIRED,
  SESSION_STATUS,
  SESSION_STUCK,
  unwrap,
} from "./client";

function failure(pending: Promise<unknown>): Promise<ApiError> {
  return pending.then(
    () => {
      throw new Error("İstek başarılı oldu, hata bekleniyordu.");
    },
    (error: unknown) => {
      expect(error).toBeInstanceOf(ApiError);
      return error as ApiError;
    },
  );
}

function redirected(): Response {
  const response = new Response(null, { status: 200 });
  Object.defineProperty(response, "type", { value: "opaqueredirect" });
  Object.defineProperty(response, "status", { value: 0 });
  return response;
}

describe("API istemcisi", () => {
  it("başarılı yanıtın verisini döndürür ve isteği yönlendirme izlemeden gönderir", async () => {
    const fetch = fakeFetch({ "GET /api/oturum": () => json(SESSION) });
    const api = createApi({ fetch });

    await expect(unwrap(api.GET("/api/oturum"))).resolves.toEqual(SESSION);

    const request = fetch.mock.calls[0]?.[0];
    expect(request?.redirect).toBe("manual");
    expect(request?.credentials).toBe("same-origin");
  });

  it("hata gövdesindeki iletiyi ve alan hatalarını taşır", async () => {
    const body = { error: "Girdi geçersiz.", fields: { amount: "Tutar sayı olmalı." } };
    const api = createApi({ fetch: fakeFetch({ "GET /api/oturum": () => json(body, 422) }) });

    const error = await failure(unwrap(api.GET("/api/oturum")));

    expect(error.status).toBe(422);
    expect(error.message).toBe("Girdi geçersiz.");
    expect(error.fields).toEqual({ amount: "Tutar sayı olmalı." });
    expect(error.retryAfter).toBeNull();
  });

  it("503'te sunucunun iletisini ve Retry-After süresini verir", async () => {
    const busy = () => json({ error: "Veritabanı meşgul." }, 503, { "Retry-After": "5" });
    const api = createApi({ fetch: fakeFetch({ "GET /api/oturum": busy }) });

    const error = await failure(unwrap(api.GET("/api/oturum")));

    expect(error.message).toBe("Veritabanı meşgul.");
    expect(error.retryAfter).toBe(5);
  });

  it("gövdesiz yanıtta duruma göre Türkçe ileti verir", async () => {
    const empty = () => new Response("", { status: 403 });
    const api = createApi({ fetch: fakeFetch({ "GET /api/oturum": empty }) });

    const error = await failure(unwrap(api.GET("/api/oturum")));

    expect(error.status).toBe(403);
    expect(error.message).toBe("Erişim reddedildi.");
  });

  it("ağ hatasını yeniden denenebilir bir hataya çevirir", async () => {
    const api = createApi({ fetch: () => Promise.reject(new TypeError("Failed to fetch")) });

    const error = await failure(unwrap(api.GET("/api/oturum")));

    expect(error.status).toBe(NETWORK_STATUS);
    expect(error.message).toContain("Sunucuya ulaşılamadı");
  });

  it.each([
    ["opak yönlendirme", redirected],
    ["3xx", () => new Response(null, { status: 302, headers: { Location: "/giris" } })],
  ])("Access %s döndürürse sayfayı bir kez yeniler", async (_, response) => {
    const onSessionExpired = vi.fn(() => true);
    const api = createApi({ fetch: async () => response(), onSessionExpired });

    const error = await failure(api.GET("/api/oturum"));

    expect(onSessionExpired).toHaveBeenCalledOnce();
    expect(error.status).toBe(SESSION_STATUS);
    expect(error.message).toBe(SESSION_EXPIRED);
  });

  it("yenileme yapılamazsa kullanıcıdan elle yenilemesini ister", async () => {
    const api = createApi({ fetch: async () => redirected(), onSessionExpired: () => false });

    const error = await failure(api.GET("/api/oturum"));

    expect(error.message).toBe(SESSION_STUCK);
  });
});

describe("oturum yenileme", () => {
  it("30 saniyede en çok bir kez yeniler", () => {
    const reload = vi.fn();
    const storage = window.sessionStorage;

    expect(reloadOnce(storage, 1_000_000, reload)).toBe(true);
    expect(reloadOnce(storage, 1_029_999, reload)).toBe(false);
    expect(reloadOnce(storage, 1_030_000, reload)).toBe(true);
    expect(reload).toHaveBeenCalledTimes(2);
  });

  it("depo yoksa ya da yazılamıyorsa yenilemez", () => {
    const reload = vi.fn();
    const broken = {
      getItem: () => null,
      setItem: () => {
        throw new DOMException("Depo dolu", "QuotaExceededError");
      },
    } as unknown as Storage;

    expect(reloadOnce(null, 0, reload)).toBe(false);
    expect(reloadOnce(broken, 0, reload)).toBe(false);
    expect(reload).not.toHaveBeenCalled();
  });
});
