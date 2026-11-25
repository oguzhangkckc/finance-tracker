"""Web tablolarının tanımları (K-129): her tablonun sıralama sütunları ve filtreleri tek yerde."""

from collections.abc import Sequence
from typing import Final

from finans.domain.models import Side
from finans.web.table import Choice, Column, TableSpec
from finans.web.views import TransactionRow

# Başka özelliklerin sayfaya taşıdığı parametreler (ör. kayıt bildirimi); tablo filtresi değildir.
PAGE_PARAMS: Final = ("islem", "no", "istek")
_NEWEST: Final = ("eskiden yeniye", "yeniden eskiye")
_SIZE: Final = ("küçükten büyüğe", "büyükten küçüğe")
_LETTERS: Final = ("A'dan Z'ye", "Z'den A'ya")
_SIDES: Final = {"alis": Side.BUY, "satis": Side.SELL}


def _funds(rows: Sequence[TransactionRow]) -> list[tuple[str, str]]:
    codes = sorted({row.stored.transaction.instrument for row in rows})
    return [(code, code) for code in codes]


def _classes(rows: Sequence[TransactionRow]) -> list[tuple[str, str]]:
    named = {row.asset_class: row.class_name for row in rows if row.asset_class}
    return sorted(named.items(), key=lambda item: item[1].casefold())


def _voided(row: TransactionRow, value: str) -> bool:
    if value == "gizle":
        return not row.stored.is_voided
    if value == "yalniz":
        return row.stored.is_voided
    return True


def _searchable(row: TransactionRow) -> str:
    stored = row.stored
    parts = (stored.transaction.instrument, stored.external_ref, stored.note, stored.void_reason)
    return " ".join(part for part in parts if part)


TRANSACTIONS: Final = TableSpec[TransactionRow](
    columns=(
        Column("tarih", "Tarih", lambda r: r.stored.transaction.trade_date, _NEWEST),
        Column("fon", "Fon", lambda r: r.stored.transaction.instrument, _LETTERS),
        Column(
            "tur", "Tür", lambda r: r.stored.transaction.side.value, ("önce alış", "önce satış")
        ),
        Column("adet", "Adet", lambda r: r.stored.transaction.units, _SIZE),
        Column("tutar", "Tutar", lambda r: r.amount, _SIZE),
        Column("no", "No", lambda r: r.stored.id, _SIZE),
    ),
    default_sort="tarih",
    default_descending=True,
    tiebreak=lambda r: r.stored.id,
    choices=(
        Choice("fon", "Fon", _funds, lambda r, v: r.stored.transaction.instrument == v),
        Choice("sinif", "Sınıf", _classes, lambda r, v: r.asset_class == v),
        Choice(
            "tur",
            "Tür",
            lambda _: [("alis", "Alış"), ("satis", "Satış")],
            lambda r, v: r.stored.transaction.side is _SIDES[v],
        ),
        Choice(
            "iptal",
            "İptal edilenler",
            lambda _: [("goster", "Göster"), ("gizle", "Gizle"), ("yalniz", "Yalnız iptaller")],
            _voided,
            default="goster",
        ),
    ),
    day=lambda r: r.stored.transaction.trade_date,
    search=_searchable,
)
