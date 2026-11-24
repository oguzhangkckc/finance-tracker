import csv
import io
from pathlib import Path

from finans.adapters._csv import RowError, parse_date, parse_decimal
from finans.domain.models import DomainError, Side, Transaction
from finans.ports.sources import ImportIssue, ImportRow, ParsedTransactions

_REQUIRED = ("date", "code", "side", "units", "price")
_OPTIONAL = ("fee", "ref", "note")


class CsvTransactionFile:
    def read(self, path: Path) -> ParsedTransactions:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            return ParsedTransactions((), (ImportIssue(None, f"{path}: dosya bulunamadı."),))
        reader = csv.DictReader(io.StringIO(text))
        header = list(reader.fieldnames or [])
        issues = [ImportIssue(1, f"eksik sütun: {c}") for c in _REQUIRED if c not in header]
        issues += [
            ImportIssue(1, f"tanınmayan sütun: {c}")
            for c in header
            if c not in _REQUIRED + _OPTIONAL
        ]
        if issues:
            return ParsedTransactions((), tuple(issues))
        rows: list[ImportRow] = []
        for record in reader:
            try:
                rows.append(_row(reader.line_num, record))
            except (RowError, DomainError) as exc:
                issues.append(ImportIssue(reader.line_num, str(exc)))
        return ParsedTransactions(() if issues else tuple(rows), tuple(issues))


def _row(line: int, record: dict[str, str | None]) -> ImportRow:
    def field(name: str) -> str:
        return (record.get(name) or "").strip()

    for name in _REQUIRED:
        if not field(name):
            raise RowError(f"{name}: boş olamaz.")
    side_text = field("side").upper()
    if side_text not in {s.value for s in Side}:
        raise RowError(f"side: BUY ya da SELL olmalı, {field('side')!r} verildi.")
    return ImportRow(
        line=line,
        transaction=Transaction(
            instrument=field("code"),
            trade_date=parse_date(field("date")),
            side=Side(side_text),
            units=parse_decimal("units", field("units")),
            unit_price=parse_decimal("price", field("price")),
            fee=parse_decimal("fee", field("fee") or "0"),
        ),
        ref=field("ref") or None,
        note=field("note") or None,
    )
