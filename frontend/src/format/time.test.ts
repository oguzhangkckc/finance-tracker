import { describe, expect, it } from "vitest";
import { istanbul, localDay, localTime } from "./time";

// Saatler İstanbul'a göre (K-99); referans değerler UTC+3.
describe("İstanbul saati", () => {
  it("anı İstanbul'un gününe ve saatine çevirir", () => {
    expect(istanbul(new Date("2026-11-25T21:30:00Z"))).toEqual({
      date: "2026-11-26",
      time: "00:30",
    });
  });

  it("saatli zamanı web'deki gibi yazar", () => {
    expect(localTime("2026-11-26T06:30:00Z", "2026-11-26")).toBe("26 Kasım 09:30");
    expect(localTime("2026-11-26T06:30:00+00:00", "2026-11-26")).toBe("26 Kasım 09:30");
  });

  it("yıl bugünkünden farklıysa yılı da yazar", () => {
    expect(localTime("2026-12-31T21:30:00Z", "2026-11-26")).toBe("1 Ocak 2027 00:30");
  });

  it("günü İstanbul'a göre verir", () => {
    expect(localDay("2026-11-25T22:15:00Z", "2026-11-26")).toBe("26 Kasım");
  });

  it("zaman olmayan metni reddeder", () => {
    expect(() => localTime("dün", "2026-11-26")).toThrow("Zaman bekleniyordu");
  });
});
