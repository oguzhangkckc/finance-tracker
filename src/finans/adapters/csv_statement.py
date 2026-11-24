import csv
import io
from datetime import date
from decimal import Decimal
from pathlib import Path

from finans.adapters._csv import RowError, parse_date, parse_decimal
from finans.domain.reconcile import StatementLine
from finans.ports.sources import ImportIssue, ParsedStatement

# Ekstreden elle doldurulan genel biçim (K-78); aracı kuruma özel ayrıştırıcı değildir.
_REQUIRED = ("date", "code", "units", "value")
_OPTIONAL = ("price",)


class CsvStatementFile:
    def read(self, path: Path) -> ParsedStatement:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            return ParsedStatement((), (ImportIssue(None, f"{path}: dosya bulunamadı."),))
        reader = csv.DictReader(io.StringIO(text))
        header = list(reader.fieldnames or [])
        issues = [ImportIssue(1, f"eksik sütun: {c}") for c in _REQUIRED if c not in header]
        issues += [
            ImportIssue(1, f"tanınmayan sütun: {c}")
            for c in header
            if c not in _REQUIRED + _OPTIONAL
        ]
        if issues:
            return ParsedStatement((), tuple(issues))
        lines: list[StatementLine] = []
        seen: dict[tuple[date, str], int] = {}
        for record in reader:
            try:
                line = _line(reader.line_num, record)
            except RowError as exc:
                issues.append(ImportIssue(reader.line_num, str(exc)))
                continue
            key = (line.day, line.code)
            if key in seen:
                message = f"{line.day} {line.code} iki kez var (ilki satır {seen[key]})."
                issues.append(ImportIssue(line.line, message))
                continue
            seen[key] = line.line
            lines.append(line)
        return ParsedStatement(() if issues else tuple(lines), tuple(issues))


def _line(number: int, record: dict[str, str | None]) -> StatementLine:
    def field(name: str) -> str:
        return (record.get(name) or "").strip()

    for name in _REQUIRED:
        if not field(name):
            raise RowError(f"{name}: boş olamaz.")
    units = _positive("units", field("units"))
    price = _positive("price", field("price")) if field("price") else None
    value = parse_decimal("value", field("value"))
    if value < 0:
        raise RowError(f"value: negatif olamaz, {field('value')!r} verildi.")
    return StatementLine(number, parse_date(field("date")), field("code"), units, price, value)


def _positive(name: str, text: str) -> Decimal:
    value = parse_decimal(name, text)
    if value <= 0:
        raise RowError(f"{name}: sıfırdan büyük olmalı, {text!r} verildi.")
    return value
