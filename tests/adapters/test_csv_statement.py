from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from finans.adapters.csv_statement import CsvStatementFile
from finans.domain.reconcile import StatementLine

D = Decimal


def _read(tmp_path: Path, text: str) -> tuple[list[StatementLine], list[str]]:
    path = tmp_path / "ekstre.csv"
    path.write_text(text, encoding="utf-8-sig")
    parsed = CsvStatementFile().read(path)
    return list(parsed.lines), [str(issue) for issue in parsed.issues]


def test_lines_are_read_with_exact_decimals_and_an_optional_price(tmp_path: Path) -> None:
    lines, issues = _read(
        tmp_path,
        "date,code,units,price,value\n2026-11-23,XHT,15,1.730000,25.95\n2026-11-23,XPP,100,,700\n",
    )
    assert issues == []
    assert lines == [
        StatementLine(2, date(2026, 11, 23), "XHT", D(15), D("1.730000"), D("25.95")),
        StatementLine(3, date(2026, 11, 23), "XPP", D(100), None, D(700)),
    ]
    assert lines[0].price is not None
    assert lines[0].price.as_tuple().exponent == -6


def test_price_column_may_be_left_out(tmp_path: Path) -> None:
    lines, issues = _read(tmp_path, "date,code,units,value\n2026-11-23,XHT,15,25.95\n")
    assert issues == []
    assert lines[0].price is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("date,code,units\n", "satır 1: eksik sütun: value"),
        ("date,code,units,value,broker\n", "satır 1: tanınmayan sütun: broker"),
        ("date,code,units,value\n23.11.2026,XHT,1,1\n", "satır 2: date: YYYY-AA-GG olmalı"),
        ("date,code,units,value\n2026-11-23,,1,1\n", "satır 2: code: boş olamaz."),
        (
            'date,code,units,value\n2026-11-23,XHT,1,"25,95"\n',
            "satır 2: value: ondalık ayırıcı nokta olmalı; 25,95 yerine 25.95 yaz.",
        ),
        ("date,code,units,value\n2026-11-23,XHT,0,1\n", "satır 2: units: sıfırdan büyük olmalı"),
        ("date,code,units,value\n2026-11-23,XHT,1,-1\n", "satır 2: value: negatif olamaz"),
        (
            "date,code,units,price,value\n2026-11-23,XHT,1,0,1\n",
            "satır 2: price: sıfırdan büyük olmalı",
        ),
        (
            "date,code,units,value\n2026-11-23,XHT,1,1\n2026-11-23,XHT,2,2\n",
            "satır 3: 2026-11-23 XHT iki kez var (ilki satır 2)",
        ),
    ],
)
def test_problems_are_reported_with_line_numbers(tmp_path: Path, text: str, expected: str) -> None:
    lines, issues = _read(tmp_path, text)
    assert lines == []
    assert any(issue.startswith(expected) for issue in issues), issues


def test_missing_file_is_reported(tmp_path: Path) -> None:
    parsed = CsvStatementFile().read(tmp_path / "yok.csv")
    assert [str(issue) for issue in parsed.issues] == [f"{tmp_path / 'yok.csv'}: dosya bulunamadı."]
