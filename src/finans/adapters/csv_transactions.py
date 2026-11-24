import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from finans.domain.models import DomainError, Side, Transaction
from finans.ports.sources import ImportIssue, ImportRow, ParsedTransactions

_REQUIRED = ("date", "code", "side", "units", "price")
_OPTIONAL = ("fee", "ref", "note")


class _RowError(ValueError):
    pass


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
            except (_RowError, DomainError) as exc:
                issues.append(ImportIssue(reader.line_num, str(exc)))
        return ParsedTransactions(() if issues else tuple(rows), tuple(issues))


def _row(line: int, record: dict[str, str | None]) -> ImportRow:
    def field(name: str) -> str:
        return (record.get(name) or "").strip()

    for name in _REQUIRED:
        if not field(name):
            raise _RowError(f"{name}: boş olamaz.")
    side_text = field("side").upper()
    if side_text not in {s.value for s in Side}:
        raise _RowError(f"side: BUY ya da SELL olmalı, {field('side')!r} verildi.")
    return ImportRow(
        line=line,
        transaction=Transaction(
            instrument=field("code"),
            trade_date=_date(field("date")),
            side=Side(side_text),
            units=_decimal("units", field("units")),
            unit_price=_decimal("price", field("price")),
            fee=_decimal("fee", field("fee") or "0"),
        ),
        ref=field("ref") or None,
        note=field("note") or None,
    )


def _date(text: str) -> date:
    try:
        value = date.fromisoformat(text)
    except ValueError:
        value = None
    if value is None or value.isoformat() != text:
        raise _RowError(f"date: YYYY-AA-GG olmalı, {text!r} verildi.")
    return value


def _decimal(name: str, text: str) -> Decimal:
    if text.count(",") == 1 and "." not in text:
        raise _RowError(
            f"{name}: ondalık ayırıcı nokta olmalı; {text} yerine {text.replace(',', '.')} yaz."
        )
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise _RowError(f"{name}: sayı olmalı, {text!r} verildi.") from None
    if not value.is_finite():
        raise _RowError(f"{name}: sonlu bir sayı olmalı, {text!r} verildi.")
    return value
