import type { TradePreview } from "../api/writes";
import { type Handler, json, SESSION } from "./fetch";
import { tableState } from "./tables";

export const CONFIRMATION = { nonce: "n-1", imza: "s-1" };

export function tradePreview(overrides: Partial<TradePreview> = {}): TradePreview {
  return {
    profile: "gercek",
    kind: "alis",
    instrument: "XHT",
    fund_name: "Hisse Fonu",
    trade_date: "2026-11-20",
    side: "BUY",
    units: "100",
    unit_price: "12.5",
    fee: "0",
    gross: "1250",
    ref: "D-1",
    units_before: "0",
    units_after: "100",
    leftover: null,
    warnings: [],
    confirmation: CONFIRMATION,
    changed: false,
    ...overrides,
  };
}

// Sırayla yanıt verir, son yanıtı tekrarlar; gelen JSON gövdelerini saklar.
export function recorded(...responses: (() => Response)[]): Handler & { bodies: unknown[] } {
  const bodies: unknown[] = [];
  let index = 0;
  const handler = async (request: Request) => {
    bodies.push(await request.json().catch(() => null));
    const respond = responses[Math.min(index, responses.length - 1)] as () => Response;
    index += 1;
    return respond();
  };
  return Object.assign(handler, { bodies });
}

export function baseRoutes(profile: "gercek" | "sanal"): Record<string, Handler> {
  return {
    "GET /api/oturum": () => json(SESSION),
    [`GET /api/${profile}/secenekler`]: () =>
      json({
        buy: [
          { code: "XHT", name: "Hisse Fonu" },
          { code: "XAC", name: "XAC" },
        ],
        sell: [{ code: "XHT", name: "Hisse Fonu" }],
      }),
    [`GET /api/${profile}/islemler`]: () => json({ table: tableState([]) }),
  };
}
