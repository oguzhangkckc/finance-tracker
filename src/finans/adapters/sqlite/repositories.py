import sqlite3
from collections.abc import Sequence
from datetime import date, datetime

from finans.adapters.sqlite.codec import (
    decode_date,
    decode_decimal,
    decode_timestamp,
    encode_date,
    encode_decimal,
    encode_timestamp,
)
from finans.domain.models import Instrument, InstrumentKind, PricePoint, Side, Transaction
from finans.ports.repositories import (
    InstrumentSync,
    PriceWrite,
    StoredInstrument,
    StoredTransaction,
)

_INSTRUMENT_COLUMNS = "code, kind, asset_class, category, name, active"


def _instrument_id(conn: sqlite3.Connection, code: str) -> int:
    row = conn.execute("SELECT id FROM instrument WHERE code = ?", (code,)).fetchone()
    if row is None:
        raise LookupError(f"{code} tanımlı bir enstrüman değil")
    return int(row[0])


def _stored_instrument(row: tuple[str, str, str, str | None, str | None, int]) -> StoredInstrument:
    code, kind, asset_class, category, name, active = row
    return StoredInstrument(
        Instrument(code, InstrumentKind(kind), asset_class, category=category, name=name),
        active=bool(active),
    )


class SqliteInstrumentRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def sync(self, instruments: Sequence[Instrument]) -> InstrumentSync:
        existing = {s.instrument.code: s for s in self.list(include_inactive=True)}
        added: list[str] = []
        updated: list[str] = []
        reactivated: list[str] = []
        for instrument in instruments:
            values = (
                instrument.kind.value,
                instrument.asset_class,
                instrument.category,
                instrument.name,
            )
            stored = existing.get(instrument.code)
            if stored is None:
                self._conn.execute(
                    "INSERT INTO instrument (kind, asset_class, category, name, code)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (*values, instrument.code),
                )
                added.append(instrument.code)
                continue
            if stored.instrument != instrument:
                self._conn.execute(
                    "UPDATE instrument SET kind = ?, asset_class = ?, category = ?, name = ?"
                    " WHERE code = ?",
                    (*values, instrument.code),
                )
                updated.append(instrument.code)
            if not stored.active:
                self._conn.execute(
                    "UPDATE instrument SET active = 1 WHERE code = ?", (instrument.code,)
                )
                reactivated.append(instrument.code)
        wanted = {i.code for i in instruments}
        deactivated = [code for code, s in existing.items() if s.active and code not in wanted]
        for code in deactivated:
            self._conn.execute("UPDATE instrument SET active = 0 WHERE code = ?", (code,))
        return InstrumentSync(
            added=tuple(sorted(added)),
            updated=tuple(sorted(updated)),
            deactivated=tuple(sorted(deactivated)),
            reactivated=tuple(sorted(reactivated)),
        )

    def get(self, code: str) -> StoredInstrument | None:
        row = self._conn.execute(
            f"SELECT {_INSTRUMENT_COLUMNS} FROM instrument WHERE code = ?",  # noqa: S608
            (code,),
        ).fetchone()
        return None if row is None else _stored_instrument(row)

    def list(self, *, include_inactive: bool = False) -> list[StoredInstrument]:
        rows = self._conn.execute(
            f"SELECT {_INSTRUMENT_COLUMNS} FROM instrument"  # noqa: S608
            " WHERE active = 1 OR ? ORDER BY code",
            (include_inactive,),
        ).fetchall()
        return [_stored_instrument(row) for row in rows]


_TXN_SELECT = """
SELECT t.id, i.code, t.trade_date, t.side, t.units, t.unit_price, t.fee,
       t.external_ref, t.note, t.created_at, t.voided_at, t.void_reason
FROM txn t JOIN instrument i ON i.id = t.instrument_id
"""


_TxnRow = tuple[
    int, str, str, str, str, str, str, str | None, str | None, str, str | None, str | None
]


def _stored_transaction(row: _TxnRow) -> StoredTransaction:
    (txn_id, code, trade_date, side, units, unit_price, fee, ref, note, created, voided, reason) = (
        row
    )
    return StoredTransaction(
        id=txn_id,
        transaction=Transaction(
            instrument=code,
            trade_date=decode_date(trade_date),
            side=Side(side),
            units=decode_decimal(units),
            unit_price=decode_decimal(unit_price),
            fee=decode_decimal(fee),
        ),
        external_ref=ref,
        note=note,
        created_at=decode_timestamp(created),
        voided_at=None if voided is None else decode_timestamp(voided),
        void_reason=reason,
    )


class SqliteTransactionRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(
        self, tx: Transaction, *, external_ref: str | None, note: str | None, created_at: datetime
    ) -> int:
        cursor = self._conn.execute(
            "INSERT INTO txn (instrument_id, trade_date, side, units, unit_price, fee,"
            " external_ref, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                _instrument_id(self._conn, tx.instrument),
                encode_date(tx.trade_date),
                tx.side.value,
                encode_decimal(tx.units),
                encode_decimal(tx.unit_price),
                encode_decimal(tx.fee),
                external_ref,
                note,
                encode_timestamp(created_at),
            ),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("İşlem eklendi ama satır kimliği alınamadı")
        return cursor.lastrowid

    def get(self, txn_id: int) -> StoredTransaction | None:
        row = self._conn.execute(_TXN_SELECT + " WHERE t.id = ?", (txn_id,)).fetchone()
        return None if row is None else _stored_transaction(row)

    def list(
        self,
        *,
        include_voided: bool = False,
        until: date | None = None,
        instrument: str | None = None,
    ) -> list[StoredTransaction]:
        rows = self._conn.execute(
            _TXN_SELECT + " WHERE (t.voided_at IS NULL OR ?)"
            " AND (? IS NULL OR t.trade_date <= ?)"
            " AND (? IS NULL OR i.code = ?)"
            " ORDER BY t.trade_date, t.id",
            (
                include_voided,
                None if until is None else encode_date(until),
                None if until is None else encode_date(until),
                instrument,
                instrument,
            ),
        ).fetchall()
        return [_stored_transaction(row) for row in rows]

    def void(self, txn_id: int, *, reason: str, at: datetime) -> None:
        cursor = self._conn.execute(
            "UPDATE txn SET voided_at = ?, void_reason = ? WHERE id = ? AND voided_at IS NULL",
            (encode_timestamp(at), reason, txn_id),
        )
        if cursor.rowcount != 1:
            raise LookupError(f"İptal edilebilecek {txn_id} numaralı işlem yok")


class SqlitePriceRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, point: PricePoint, *, fetched_at: datetime) -> PriceWrite:
        instrument_id = _instrument_id(self._conn, point.instrument)
        day = encode_date(point.price_date)
        row = self._conn.execute(
            "SELECT price FROM price WHERE instrument_id = ? AND price_date = ?",
            (instrument_id, day),
        ).fetchone()
        new_price = encode_decimal(point.price)
        if row is None:
            self._conn.execute(
                "INSERT INTO price (instrument_id, price_date, price, source, fetched_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (instrument_id, day, new_price, point.source, encode_timestamp(fetched_at)),
            )
            return PriceWrite("inserted")
        previous = decode_decimal(row[0])
        if previous == point.price:
            return PriceWrite("unchanged")
        self._conn.execute(
            "UPDATE price SET price = ?, source = ?, fetched_at = ?"
            " WHERE instrument_id = ? AND price_date = ?",
            (new_price, point.source, encode_timestamp(fetched_at), instrument_id, day),
        )
        self._conn.execute(
            "INSERT INTO price_revision"
            " (instrument_id, price_date, old_price, new_price, revised_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (instrument_id, day, row[0], new_price, encode_timestamp(fetched_at)),
        )
        return PriceWrite("revised", previous=previous)

    def history(self, *, until: date) -> list[PricePoint]:
        rows = self._conn.execute(
            "SELECT i.code, p.price_date, p.price, p.source FROM price p"
            " JOIN instrument i ON i.id = p.instrument_id"
            " WHERE p.price_date <= ? ORDER BY i.code, p.price_date",
            (encode_date(until),),
        ).fetchall()
        return [
            PricePoint(code, decode_date(day), decode_decimal(price), source)
            for code, day, price, source in rows
        ]

    def latest(self, instrument: str) -> PricePoint | None:
        row = self._conn.execute(
            "SELECT i.code, p.price_date, p.price, p.source FROM price p"
            " JOIN instrument i ON i.id = p.instrument_id"
            " WHERE i.code = ? ORDER BY p.price_date DESC LIMIT 1",
            (instrument,),
        ).fetchone()
        if row is None:
            return None
        code, day, price, source = row
        return PricePoint(code, decode_date(day), decode_decimal(price), source)
