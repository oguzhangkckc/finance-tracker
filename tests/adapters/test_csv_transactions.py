from datetime import date
from decimal import Decimal
from pathlib import Path

from finans.adapters.csv_transactions import CsvTransactionFile
from finans.domain.models import Side, Transaction
from finans.ports.sources import ParsedTransactions

D = Decimal
HEADER = "date,code,side,units,price,fee,ref,note\n"


def _read(tmp_path: Path, text: str) -> ParsedTransactions:
    path = tmp_path / "islemler.csv"
    path.write_text(text, encoding="utf-8")
    return CsvTransactionFile().read(path)


def test_rows_are_parsed_with_line_numbers(tmp_path: Path) -> None:
    parsed = _read(
        tmp_path,
        HEADER + "2026-01-05,TTE,BUY,10,12.345678,0,R1,ilk\n2026-02-01,TTE,sell,4,13,0.5,,\n",
    )
    assert parsed.issues == ()
    first, second = parsed.rows
    assert (first.line, first.ref, first.note) == (2, "R1", "ilk")
    assert first.transaction == Transaction(
        "TTE", date(2026, 1, 5), Side.BUY, D(10), D("12.345678")
    )
    assert (second.line, second.ref, second.note, second.transaction.side) == (
        3,
        None,
        None,
        Side.SELL,
    )
    assert second.transaction.fee == D("0.5")


def test_optional_columns_may_be_absent(tmp_path: Path) -> None:
    parsed = _read(tmp_path, "date,code,side,units,price\n2026-01-05,TTE,BUY,1,2\n")
    assert parsed.issues == ()
    assert parsed.rows[0].transaction.fee == D(0)


def test_header_problems_are_reported(tmp_path: Path) -> None:
    parsed = _read(tmp_path, "date,code,side,units,renk\n2026-01-05,TTE,BUY,1,mavi\n")
    assert [str(issue) for issue in parsed.issues] == [
        "satır 1: eksik sütun: price",
        "satır 1: tanınmayan sütun: renk",
    ]
    assert parsed.rows == ()


def test_row_errors_are_collected_with_line_numbers(tmp_path: Path) -> None:
    parsed = _read(
        tmp_path,
        HEADER
        + "05.01.2026,TTE,BUY,1,1,0,,\n"
        + "2026-01-05,TTE,AL,1,1,0,,\n"
        + "2026-01-05,TTE,BUY,12,5,1,0,,\n".replace("12,5", '"12,5"')
        + "2026-01-05,TTE,BUY,1,-1,0,,\n"
        + "2026-01-05,,BUY,1,1,0,,\n",
    )
    assert parsed.rows == ()
    assert [str(issue) for issue in parsed.issues] == [
        "satır 2: date: YYYY-AA-GG olmalı, '05.01.2026' verildi.",
        "satır 3: side: BUY ya da SELL olmalı, 'AL' verildi.",
        "satır 4: units: ondalık ayırıcı nokta olmalı; 12,5 yerine 12.5 yaz.",
        "satır 5: unit_price sıfırdan büyük olmalı: -1",
        "satır 6: code: boş olamaz.",
    ]


def test_exponent_notation_points_to_the_excel_column_format(tmp_path: Path) -> None:
    parsed = _read(
        tmp_path,
        HEADER
        + "2026-01-05,XHT,BUY,1.23457E+11,1,0,,\n"
        + '2026-01-05,XHT,BUY,"1,23457E+11",1,0,,\n'
        + "2026-01-05,XHT,BUY,10,1e-2,0,,\n",
    )
    excel = "Excel'de sütun biçimini Sayı yap ve dosyayı yeniden kaydet."
    assert parsed.rows == ()
    assert [str(issue) for issue in parsed.issues] == [
        f"satır 2: units: üstel gösterim kullanılamaz (1.23457E+11); {excel}",
        f"satır 3: units: üstel gösterim kullanılamaz (1,23457E+11); {excel}",
        f"satır 4: price: üstel gösterim kullanılamaz (1e-2); {excel}",
    ]


def test_missing_file(tmp_path: Path) -> None:
    parsed = CsvTransactionFile().read(tmp_path / "yok.csv")
    assert [str(issue) for issue in parsed.issues] == [f"{tmp_path / 'yok.csv'}: dosya bulunamadı."]
