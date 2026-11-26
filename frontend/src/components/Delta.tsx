import { parseDecimal } from "../format/decimal";

// K-128: anlam yalnız renkle taşınmaz; ok ve ekran okuyucu metni de var.
export function Delta({ value, text }: { value: string; text: string }) {
  const { units } = parseDecimal(value);
  if (units > 0n) {
    return (
      <span className="ft-delta ft-gain">
        <span aria-hidden="true">▲</span>
        {text}
        <span className="ft-sr"> artış</span>
      </span>
    );
  }
  if (units < 0n) {
    return (
      <span className="ft-delta ft-loss">
        <span aria-hidden="true">▼</span>
        {text}
        <span className="ft-sr"> azalış</span>
      </span>
    );
  }
  return <span className="ft-delta">{text}</span>;
}
