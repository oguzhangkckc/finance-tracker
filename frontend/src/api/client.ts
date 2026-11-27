import createClient, { type Client, type Middleware } from "openapi-fetch";
import type { components, paths } from "./schema";

export type Api = Client<paths>;
export type ErrorBody = components["schemas"]["ErrorBody"];

// API 401 döndürmez; bu kod yalnız Access oturumunun bittiğini gösterir.
export const SESSION_STATUS = 401;
export const NETWORK_STATUS = 0;

const MESSAGES: Readonly<Record<number, string>> = {
  [NETWORK_STATUS]: "Sunucuya ulaşılamadı; bağlantını denetleyip yeniden dene.",
  403: "Erişim reddedildi.",
  404: "Aradığın sayfa ya da kayıt bulunamadı.",
  503: "Sunucu şu an yanıt veremiyor; biraz sonra yeniden dene.",
};
const UNEXPECTED = "Beklenmeyen bir hata oluştu.";
export const SESSION_EXPIRED = "Oturumun süresi doldu; sayfa yenileniyor.";
export const SESSION_STUCK = "Oturum yenilenemedi; sayfayı elle yenile.";

export class ApiError extends Error {
  readonly status: number;
  readonly fields: Readonly<Record<string, string>>;
  readonly retryAfter: number | null;

  constructor(
    status: number,
    message: string,
    fields: Readonly<Record<string, string>> = {},
    retryAfter: number | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.fields = fields;
    this.retryAfter = retryAfter;
  }
}

function isErrorBody(body: unknown): body is ErrorBody {
  return (
    typeof body === "object" && body !== null && "error" in body && typeof body.error === "string"
  );
}

function retryAfter(response: Response): number | null {
  const value = response.headers.get("Retry-After");
  return value !== null && /^\d+$/.test(value) ? Number.parseInt(value, 10) : null;
}

export function apiError(response: Response, body: unknown): ApiError {
  const parsed = isErrorBody(body) ? body : undefined;
  return new ApiError(
    response.status,
    parsed?.error ?? MESSAGES[response.status] ?? UNEXPECTED,
    parsed?.fields ?? {},
    retryAfter(response),
  );
}

interface Outcome<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

export async function unwrap<T>(pending: Promise<Outcome<T>>): Promise<T> {
  const { data, error, response } = await pending;
  if (response.ok && data !== undefined) {
    return data;
  }
  throw apiError(response, error);
}

// Access oturumu bitince giriş sayfasına yönlendirir. Tarayıcı `redirect: "manual"` ile
// bunu opak bir yanıt olarak verir; testlerdeki Node fetch'i 3xx'i olduğu gibi döndürür.
function isAccessRedirect(response: Response): boolean {
  return response.type === "opaqueredirect" || (response.status >= 300 && response.status < 400);
}

const RELOAD_KEY = "ft-oturum-yenileme";
const RELOAD_GAP_MS = 30_000;

function sessionStore(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

// Yönlendirme yenilemeden sonra da sürerse sayfa döngüye girmesin: 30 saniyede en çok bir kez.
export function reloadOnce(
  storage: Storage | null = sessionStore(),
  now: number = Date.now(),
  reload: () => void = () => window.location.reload(),
): boolean {
  if (storage === null) {
    return false;
  }
  try {
    const last = Number.parseInt(storage.getItem(RELOAD_KEY) ?? "", 10);
    if (Number.isFinite(last) && now - last < RELOAD_GAP_MS) {
      return false;
    }
    storage.setItem(RELOAD_KEY, String(now));
  } catch {
    return false;
  }
  reload();
  return true;
}

function guard(onSessionExpired: () => boolean): Middleware {
  return {
    onResponse({ response }) {
      if (isAccessRedirect(response)) {
        const reloading = onSessionExpired();
        throw new ApiError(SESSION_STATUS, reloading ? SESSION_EXPIRED : SESSION_STUCK);
      }
      return undefined;
    },
    onError({ error }) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return error;
      }
      return new ApiError(NETWORK_STATUS, MESSAGES[NETWORK_STATUS] ?? UNEXPECTED);
    },
  };
}

export interface ApiOptions {
  fetch?: (request: Request) => Promise<Response>;
  baseUrl?: string;
  onSessionExpired?: () => boolean;
}

export function createApi(options: ApiOptions = {}): Api {
  const client = createClient<paths>({
    baseUrl: options.baseUrl ?? window.location.origin,
    fetch: options.fetch ?? ((request) => globalThis.fetch(request)),
    redirect: "manual",
    credentials: "same-origin",
  });
  client.use(guard(options.onSessionExpired ?? (() => reloadOnce())));
  return client;
}
