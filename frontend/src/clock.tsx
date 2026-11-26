import { createContext, type ReactNode, use } from "react";
import { istanbul } from "./format/time";

const ClockContext = createContext<() => Date>(() => new Date());

export function ClockProvider({ now, children }: { now: () => Date; children: ReactNode }) {
  return <ClockContext value={now}>{children}</ClockContext>;
}

// Gün etiketinde yıl, bugünün yılından farklıysa yazılır (K-128); bugün İstanbul'un günüdür.
export function useToday(): string {
  return istanbul(use(ClockContext)()).date;
}
