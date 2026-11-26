import { ApiError, apiError, NETWORK_STATUS } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];
export type TradePreview = Schemas["TradePreviewBody"];
export type VoidPreview = Schemas["VoidPreviewBody"];
export type VoidTarget = Schemas["VoidTarget"];
export type BlockingSale = Schemas["BlockingSale"];
export type PaydayPlan = Schemas["PaydayPreviewBody"];
export type PaydayLine = Schemas["PaydayLine"];
export type Saved = Schemas["Saved"];
export type FundOption = Schemas["FundOption"];

export interface Outcome<T> {
  status: number;
  data?: T;
  // Başarısız yanıtın gövdesi: 409'da yeni önizleme, 422'de öneri (price_days, blocking).
  body?: unknown;
  problem: ApiError | null;
}

// Yazma yanıtı duruma göre okunur; ağ hatası ve oturum sonu da sorun olarak döner.
export async function settle<T>(
  pending: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<Outcome<T>> {
  try {
    const { data, error, response } = await pending;
    if (response.ok) {
      return { status: response.status, data, problem: null };
    }
    return { status: response.status, body: error, problem: apiError(response, error) };
  } catch (thrown) {
    if (thrown instanceof ApiError) {
      return { status: thrown.status, problem: thrown };
    }
    throw thrown;
  }
}

export function retriable(problem: ApiError): boolean {
  return problem.status === NETWORK_STATUS || problem.status >= 500;
}

function isObject(body: unknown): body is Record<string, unknown> {
  return typeof body === "object" && body !== null;
}

// 409: sonuç önizlemeden farklı; gövde yeni önizlemedir (K-138).
export function changedPreview<T>(outcome: Outcome<unknown>): T | null {
  return outcome.status === 409 && isObject(outcome.body) && "confirmation" in outcome.body
    ? (outcome.body as T)
    : null;
}

export function priceDays(body: unknown): string[] {
  return isObject(body) && Array.isArray(body.price_days) ? body.price_days.map(String) : [];
}

export function blockingSales(body: unknown): BlockingSale[] | null {
  return isObject(body) && Array.isArray(body.blocking) ? (body.blocking as BlockingSale[]) : null;
}
