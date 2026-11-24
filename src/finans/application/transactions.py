import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from finans.application.codes import unknown_code_message
from finans.domain.models import DomainError, OversellError, Side, Transaction
from finans.domain.numeric import canonical_text
from finans.domain.positions import build_positions
from finans.ports.repositories import StoredTransaction
from finans.ports.sources import ImportIssue, ImportRow, ParsedTransactions
from finans.ports.unit_of_work import UnitOfWork

_Key = tuple[date, str, Side, str]


@dataclass(frozen=True, slots=True)
class ImportReport:
    added: tuple[ImportRow, ...]
    skipped: tuple[ImportRow, ...]
    issues: tuple[ImportIssue, ...]


def digest(tx: Transaction) -> str:
    parts = (
        tx.trade_date.isoformat(),
        tx.instrument,
        tx.side.value,
        canonical_text(tx.units),
        canonical_text(tx.unit_price),
        canonical_text(tx.fee),
    )
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _key(tx: Transaction) -> _Key:
    return (tx.trade_date, tx.instrument, tx.side, canonical_text(tx.units))


def _tradeable_issue(uow: UnitOfWork, tx: Transaction) -> str | None:
    stored = uow.instruments.get(tx.instrument)
    if stored is None:
        return unknown_code_message(uow, tx.instrument)
    if not stored.active and tx.side is Side.BUY:
        return f"{tx.instrument} pasif; alış girilemez, yalnızca satış girilebilir."
    return None


def _oversell_issue(transactions: Sequence[Transaction]) -> str | None:
    try:
        build_positions(transactions, as_of=date.max)
    except OversellError as exc:
        return str(exc)
    return None


def add_transaction(
    uow: UnitOfWork, tx: Transaction, *, ref: str | None, note: str | None, now: datetime
) -> int:
    issue = _tradeable_issue(uow, tx)
    if issue is not None:
        raise DomainError(issue)
    existing = uow.transactions.list()
    if ref is not None and any(s.external_ref == ref for s in existing):
        raise DomainError(f"{ref} ref'li etkin bir işlem zaten var.")
    issue = _oversell_issue([s.transaction for s in existing] + [tx])
    if issue is not None:
        raise DomainError(issue)
    return uow.transactions.add(tx, external_ref=ref, note=note, created_at=now)


def void_transaction(uow: UnitOfWork, txn_id: int, *, reason: str, now: datetime) -> None:
    if not reason.strip():
        raise DomainError("İptal gerekçesi boş olamaz.")
    stored = uow.transactions.get(txn_id)
    if stored is None:
        raise DomainError(f"{txn_id} numaralı işlem yok.")
    if stored.is_voided:
        raise DomainError(f"{txn_id} numaralı işlem zaten iptal edilmiş.")
    blocking = _sells_to_void_first([s for s in uow.transactions.list() if s.id != txn_id])
    if blocking:
        listed = ", ".join(
            f"#{s.id} ({s.transaction.trade_date} {s.transaction.instrument} "
            f"{canonical_text(s.transaction.units)} adet)"
            for s in blocking
        )
        raise DomainError(
            f"{txn_id} numaralı işlem iptal edilemez; sonraki satışlar elde olmayan payı satmış "
            f"olur. Önce şu satışları `ft tx void` ile iptal et: {listed}."
        )
    uow.transactions.void(txn_id, reason=reason.strip(), at=now)


def _sells_to_void_first(remaining: Sequence[StoredTransaction]) -> list[StoredTransaction]:
    """Eldeki payı aşan günlerin satışları; tarih sırasıyla, bulunanlar yok sayılarak (K-58)."""
    kept = list(remaining)
    blocking: list[StoredTransaction] = []
    while True:
        try:
            build_positions([s.transaction for s in kept], as_of=date.max)
        except OversellError as exc:
            day_sells = {
                s.id
                for s in kept
                if s.transaction.side is Side.SELL
                and s.transaction.instrument == exc.instrument
                and s.transaction.trade_date == exc.day
            }
            blocking.extend(s for s in kept if s.id in day_sells)
            kept = [s for s in kept if s.id not in day_sells]
        else:
            return sorted(blocking, key=lambda s: (s.transaction.trade_date, s.id))


def import_transactions(
    uow: UnitOfWork, parsed: ParsedTransactions, *, now: datetime, dry_run: bool
) -> ImportReport:
    existing = uow.transactions.list()
    by_ref = {s.external_ref: s for s in existing if s.external_ref is not None}
    by_key: dict[_Key, list[StoredTransaction]] = {}
    for stored in existing:
        by_key.setdefault(_key(stored.transaction), []).append(stored)

    issues = list(parsed.issues)
    to_add: list[tuple[ImportRow, str]] = []
    skipped: list[ImportRow] = []
    refs_in_file: dict[str, int] = {}
    keys_in_file: dict[_Key, tuple[str, int]] = {}
    for row in parsed.rows:
        message = _row_issue(uow, row, by_ref, by_key, refs_in_file, keys_in_file)
        if message is None:
            to_add.append((row, row.ref or f"sha256:{digest(row.transaction)}"))
        elif message == "":
            skipped.append(row)
        else:
            issues.append(ImportIssue(row.line, message))

    oversell = _oversell_issue(
        [s.transaction for s in existing] + [r.transaction for r, _ in to_add]
    )
    if oversell is not None:
        issues.append(ImportIssue(None, oversell))
    report = ImportReport(tuple(r for r, _ in to_add), tuple(skipped), tuple(issues))
    if issues or dry_run:
        return report
    for row, ref in to_add:
        uow.transactions.add(row.transaction, external_ref=ref, note=row.note, created_at=now)
    return report


def _row_issue(
    uow: UnitOfWork,
    row: ImportRow,
    by_ref: dict[str, StoredTransaction],
    by_key: dict[_Key, list[StoredTransaction]],
    refs_in_file: dict[str, int],
    keys_in_file: dict[_Key, tuple[str, int]],
) -> str | None:
    """None: eklenecek; boş metin: zaten var, atlanacak; diğer: içe aktarmayı durduran sorun."""
    tx = row.transaction
    issue = _tradeable_issue(uow, tx)
    if issue is not None:
        return issue
    row_digest = digest(tx)
    ref = row.ref or f"sha256:{row_digest}"
    if ref in refs_in_file:
        if row.ref is None:
            return (
                f"satır {refs_in_file[ref]} ile birebir aynı ve ref'siz; aynı gün aynı işlem "
                "gerçekten iki kez yapıldıysa ref sütununu doldur."
            )
        return f"{ref} ref'i dosyada iki kez var (ilki satır {refs_in_file[ref]})."
    refs_in_file[ref] = row.line
    key = _key(tx)
    seen = keys_in_file.get(key)
    if seen is not None and seen[0] != row_digest:
        return (
            f"olası düzeltme ya da çift kayıt: satır {seen[1]} ile tarih, kod, yön ve adet aynı "
            "ama içerik farklı."
        )
    keys_in_file.setdefault(key, (row_digest, row.line))

    stored = by_ref.get(ref)
    if stored is not None:
        if digest(stored.transaction) == row_digest:
            return ""
        return (
            f"{ref} ref'i mevcut #{stored.id} kaydında farklı içerikle var; düzeltmek için önce "
            f"`ft tx void {stored.id}` ile iptal et."
        )
    same_key = by_key.get(key, [])
    differing = [s for s in same_key if digest(s.transaction) != row_digest]
    if differing and len(differing) == len(same_key):
        return (
            f"olası düzeltme ya da çift kayıt: mevcut #{differing[0].id} kaydıyla tarih, kod, yön "
            "ve adet aynı ama içerik farklı."
        )
    if same_key and row.ref is None:
        return ""
    return None
