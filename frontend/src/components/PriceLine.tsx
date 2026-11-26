import { Badge } from "@mantine/core";
import type { HoldingLine } from "../api/types";
import { useToday } from "../clock";
import { dayLabel, exact } from "../format/display";

// Fiyat her zaman günüyle; elle girilen fiyat etiketli, bayat fiyat uyarılı (K-117, K-120).
export function PriceLine({
  holding,
  stale,
}: {
  holding: HoldingLine;
  stale: Readonly<Record<string, string>>;
}) {
  const today = useToday();
  if (holding.price === null) {
    return <span className="ft-warn">fiyat yok</span>;
  }
  const warning = stale[holding.instrument];
  return (
    <>
      son fiyat: <span className="ft-num">{exact(holding.price)}</span> TL
      {holding.price_date !== null && ` (${dayLabel(holding.price_date, { today })})`}
      {holding.source === "manual" && (
        <>
          {" "}
          <Badge size="xs" variant="outline" color="gray">
            elle
          </Badge>
        </>
      )}
      {warning !== undefined && <span className="ft-warn"> bayat: {warning}</span>}
    </>
  );
}
