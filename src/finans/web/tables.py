"""Web tablolarının tanımları (K-129): her tablonun sıralama sütunları ve filtreleri tek yerde."""

from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Final

from finans.domain.models import Side
from finans.ports.repositories import StoredRun
from finans.web.table import Choice, Column, TableSpec
from finans.web.views import AlertEventRow, HoldingRow, LotRow, TransactionRow

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


# Fiyatı olmayan satır sıralamada en küçük değer sayılır; Decimal sonsuzluk, float değil.
_MISSING: Final = Decimal("-Infinity")


def _or_missing(value: Decimal | None) -> Decimal:
    return _MISSING if value is None else value


def _named[R](
    name: Callable[[R], tuple[str, str]],
) -> Callable[[Sequence[R]], list[tuple[str, str]]]:
    """Satırlardaki (kod, ad) çiftleri, ada göre sıralı; filtre seçenekleri buradan."""

    def options(rows: Sequence[R]) -> list[tuple[str, str]]:
        pairs = dict(name(row) for row in rows)
        return sorted(pairs.items(), key=lambda item: item[1].casefold())

    return options


HOLDINGS: Final = TableSpec[HoldingRow](
    columns=(
        Column("deger", "Değer", lambda r: _or_missing(r.line.value), _SIZE),
        Column("fon", "Fon", lambda r: r.line.instrument, _LETTERS),
        Column("sinif", "Sınıf", lambda r: r.class_name.casefold(), _LETTERS),
        Column("adet", "Adet", lambda r: r.line.units, _SIZE),
        Column("maliyet", "Maliyet", lambda r: r.line.cost, _SIZE),
        Column("getiri", "Getiri", lambda r: _or_missing(r.line.simple_return), _SIZE),
    ),
    default_sort="deger",
    default_descending=True,
    tiebreak=lambda r: r.index,
    choices=(
        Choice(
            "sinif",
            "Sınıf",
            _named(lambda r: (r.line.asset_class, r.class_name)),
            lambda r, v: r.line.asset_class == v,
        ),
        Choice(
            "dagilim",
            "Dağılım",
            lambda _: [("ici", "Dağılım içi"), ("disi", "Dağılım dışı")],
            lambda r, v: r.line.allocation is (v == "ici"),
        ),
    ),
    search=lambda r: r.line.instrument,
)

LOTS: Final = TableSpec[LotRow](
    columns=(
        Column("alis", "Alış günü", lambda r: r.line.acquired, _NEWEST),
        Column("fon", "Fon", lambda r: r.line.instrument, _LETTERS),
        Column("adet", "Adet", lambda r: r.line.units, _SIZE),
        Column("maliyet", "Maliyet", lambda r: r.line.cost, _SIZE),
        Column("kar", "Kâr/zarar", lambda r: _or_missing(r.gain), _SIZE),
    ),
    default_sort="alis",
    default_descending=False,
    tiebreak=lambda r: r.index,
    choices=(
        Choice(
            "fon",
            "Fon",
            _named(lambda r: (r.line.instrument, r.line.instrument)),
            lambda r, v: r.line.instrument == v,
        ),
    ),
    day=lambda r: r.line.acquired,
)

ALERT_EVENTS: Final = TableSpec[AlertEventRow](
    columns=(
        Column("tarih", "Tarih", lambda r: r.stored.event.occurred_at, _NEWEST),
        Column("sinif", "Sınıf", lambda r: r.class_name.casefold(), _LETTERS),
        Column("sapma", "Sapma", lambda r: abs(r.stored.deviation), _SIZE),
    ),
    default_sort="tarih",
    default_descending=True,
    tiebreak=lambda r: r.stored.id,
    choices=(
        Choice(
            "olay",
            "Olay",
            lambda _: [("acildi", "Açıldı"), ("kapandi", "Kapandı")],
            lambda r, v: r.stored.event.kind == ("opened" if v == "acildi" else "resolved"),
        ),
        Choice(
            "sinif",
            "Sınıf",
            _named(lambda r: (r.asset_class, r.class_name)),
            lambda r, v: r.asset_class == v,
        ),
    ),
    day=lambda r: r.day,
)

RUN_STATUS: Final = {
    "ok": "Tamam",
    "partial": "Kısmi",
    "failed": "Başarısız",
    "running": "Çalışıyor",
}

RUNS: Final = TableSpec[StoredRun](
    columns=(
        Column("baslangic", "Başladı", lambda r: r.started_at, _NEWEST),
        Column("is", "İş", lambda r: r.job, _LETTERS),
        Column("durum", "Durum", lambda r: r.status, _LETTERS),
    ),
    default_sort="baslangic",
    default_descending=True,
    tiebreak=lambda r: r.id,
    choices=(
        Choice("is", "İş", _named(lambda r: (r.job, r.job)), lambda r, v: r.job == v),
        Choice(
            "durum",
            "Durum",
            lambda _: list(RUN_STATUS.items()),
            lambda r, v: r.status == v,
        ),
    ),
    day=lambda r: r.logical_date,
)
