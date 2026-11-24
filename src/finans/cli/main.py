from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from finans import bootstrap
from finans.application.cpi import CPI_HISTORY_START, CpiSyncReport, sync_cpi
from finans.application.portfolio_config import ApplyReport, apply_portfolio
from finans.application.portfolio_view import portfolio_as_of
from finans.application.prices import set_manual_price
from finans.application.transactions import (
    add_transaction,
    import_transactions,
    void_transaction,
)
from finans.cli._common import VersionOption
from finans.domain.models import DomainError, Side, Transaction, YearMonth
from finans.domain.numeric import canonical_text
from finans.domain.portfolio import ConfigError
from finans.ports.repositories import StoredTransaction
from finans.settings import Settings, load_settings

app = typer.Typer(
    name="ft", no_args_is_help=True, add_completion=False, help="Finans takip: insan arayüzü."
)
db_app = typer.Typer(no_args_is_help=True, help="Veritabanı işlemleri.")
config_app = typer.Typer(no_args_is_help=True, help="Portföy tanımı (portfolio.toml).")
tx_app = typer.Typer(no_args_is_help=True, help="İşlemler.")
price_app = typer.Typer(
    no_args_is_help=True, help="Elle girilen fiyatlar (yalnızca MANUAL varlıklar)."
)
app.add_typer(db_app, name="db")
app.add_typer(config_app, name="config")
app.add_typer(tx_app, name="tx")
sync_app = typer.Typer(no_args_is_help=True, help="Dış kaynaklardan veri çekme.")
app.add_typer(price_app, name="price")
app.add_typer(sync_app, name="sync")


class SideChoice(StrEnum):
    buy = "buy"
    sell = "sell"


FileOption = Annotated[
    Path | None,
    typer.Option("--file", help="portfolio.toml yolu; verilmezse FT_PORTFOLIO_PATH kullanılır."),
]


@app.callback()
def main(_version: VersionOption = False) -> None:
    """Finans takip: insan arayüzü."""


@db_app.command("migrate")
def migrate() -> None:
    """Bekleyen migration'ları uygular."""
    settings = _load_settings_or_exit()
    try:
        run = bootstrap.migrate_database(settings)
    except bootstrap.MigrationError as exc:
        typer.echo(f"Migration hatası: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if run.applied:
        typer.echo(f"Uygulanan migration'lar: {', '.join(map(str, run.applied))}")
    else:
        typer.echo("Veritabanı güncel.")
    if run.backup is not None:
        typer.echo(f"Migration öncesi yedek: {run.backup}")


@config_app.command("check")
def config_check(file: FileOption = None) -> None:
    """portfolio.toml'u doğrular; bütün hataları birlikte gösterir."""
    settings = _load_settings_or_exit()
    with _user_errors():
        config = bootstrap.portfolio_source().load(_portfolio_path(settings, file))
    typer.echo(
        f"Config geçerli: {len(config.instruments)} varlık, {len(config.targets)} hedef sınıf."
    )


@config_app.command("apply")
def config_apply(file: FileOption = None) -> None:
    """portfolio.toml'u doğrular ve varlık tanımlarını veritabanına yazar."""
    settings = _load_settings_or_exit()
    with _user_errors():
        config = bootstrap.portfolio_source().load(_portfolio_path(settings, file))
        with bootstrap.open_unit_of_work(settings) as uow:
            report = apply_portfolio(uow, config)
    _print_apply(report)


@tx_app.command("add")
def tx_add(
    side: Annotated[SideChoice, typer.Argument(help="buy ya da sell")],
    code: Annotated[str, typer.Argument(help="Varlık kodu")],
    units: Annotated[str, typer.Argument(help="Adet")],
    price: Annotated[str, typer.Argument(help="Birim fiyat")],
    trade_date: Annotated[str, typer.Option("--date", help="Fiyatın uygulandığı gün (YYYY-AA-GG)")],
    fee: Annotated[str, typer.Option("--fee", help="Komisyon")] = "0",
    ref: Annotated[str | None, typer.Option("--ref", help="Dış referans")] = None,
    note: Annotated[str | None, typer.Option("--note", help="Not")] = None,
) -> None:
    """İşlem ekler."""
    settings = _load_settings_or_exit()
    parsed_date = _parse_date(trade_date)
    amounts = _parse_decimal("units", units), _parse_decimal("price", price)
    parsed_fee = _parse_decimal("fee", fee)
    with _user_errors():
        transaction = Transaction(
            code, parsed_date, Side(side.value.upper()), amounts[0], amounts[1], parsed_fee
        )
        with bootstrap.open_unit_of_work(settings) as uow:
            txn_id = add_transaction(
                uow, transaction, ref=ref, note=note, now=bootstrap.system_clock().now()
            )
    typer.echo(f"İşlem eklendi: #{txn_id}")


@tx_app.command("list")
def tx_list(
    until: Annotated[str | None, typer.Option("--until", help="Bu güne kadar")] = None,
    instrument: Annotated[str | None, typer.Option("--instrument", help="Varlık kodu")] = None,
    show_all: Annotated[bool, typer.Option("--all", help="İptal edilenleri de göster.")] = False,
) -> None:
    """İşlemleri listeler; iptal edilenler yalnızca --all ile görünür."""
    settings = _load_settings_or_exit()
    until_date = None if until is None else _parse_date(until)
    with _user_errors(), bootstrap.open_unit_of_work(settings, readonly=True) as uow:
        rows = uow.transactions.list(
            include_voided=show_all, until=until_date, instrument=instrument
        )
    if not rows:
        typer.echo("Kayıtlı işlem yok.")
    for stored in rows:
        typer.echo(_format_transaction(stored))


@tx_app.command("void")
def tx_void(
    txn_id: Annotated[int, typer.Argument(help="İşlem numarası")],
    reason: Annotated[str, typer.Option("--reason", help="İptal gerekçesi")],
) -> None:
    """İşlemi iptal eder; kayıt ve gerekçe kalır, pozisyonda yok sayılır."""
    settings = _load_settings_or_exit()
    with _user_errors(), bootstrap.open_unit_of_work(settings) as uow:
        void_transaction(uow, txn_id, reason=reason, now=bootstrap.system_clock().now())
    typer.echo(f"İşlem #{txn_id} iptal edildi.")


@tx_app.command("import")
def tx_import(
    path: Annotated[Path, typer.Argument(help="CSV dosyası")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Yazmadan ne olacağını göster.")
    ] = False,
) -> None:
    """CSV'den işlem içe aktarır; ya bütün satırlar yazılır ya hiçbiri."""
    settings = _load_settings_or_exit()
    parsed = bootstrap.transaction_file().read(path)
    with _user_errors(), bootstrap.open_unit_of_work(settings) as uow:
        report = import_transactions(
            uow, parsed, now=bootstrap.system_clock().now(), dry_run=dry_run
        )
    if report.issues:
        typer.echo(
            f"İçe aktarma durduruldu; hiçbir işlem yazılmadı. {len(report.issues)} sorun:",
            err=True,
        )
        for issue in report.issues:
            typer.echo(f"  - {issue}", err=True)
        raise typer.Exit(code=1)
    verb, skip = ("Eklenecek", "atlanacak") if dry_run else ("Eklendi", "atlandı")
    typer.echo(f"{verb}: {len(report.added)}, {skip} (zaten var): {len(report.skipped)}")


@price_app.command("set")
def price_set(
    code: Annotated[str, typer.Argument(help="Varlık kodu")],
    on: Annotated[str, typer.Argument(help="Fiyat günü (YYYY-AA-GG)")],
    price: Annotated[str, typer.Argument(help="Birim fiyat (TL)")],
) -> None:
    """MANUAL bir varlığın o günkü birim fiyatını kaydeder."""
    settings = _load_settings_or_exit()
    day, amount = _parse_date(on), _parse_decimal("price", price)
    with _user_errors(), bootstrap.open_unit_of_work(settings) as uow:
        write = set_manual_price(uow, code, day, amount, now=bootstrap.system_clock().now())
    if write.status == "inserted":
        typer.echo("Fiyat kaydedildi.")
    elif write.status == "unchanged":
        typer.echo("Fiyat aynı; değişiklik yok.")
    else:
        previous = "?" if write.previous is None else canonical_text(write.previous)
        typer.echo(f"Fiyat güncellendi; önceki değer {previous}.")


@app.command("value")
def value(
    on: Annotated[str | None, typer.Option("--on", help="Değerleme günü; verilmezse bugün")] = None,
) -> None:
    """Portföyün verilen gündeki değerini gösterir."""
    settings = _load_settings_or_exit()
    day = bootstrap.system_clock().today() if on is None else _parse_date(on)
    with _user_errors(), bootstrap.open_unit_of_work(settings, readonly=True) as uow:
        view = portfolio_as_of(uow, day)
    typer.echo(f"Değerleme: {day.isoformat()}")
    valuation = view.valuation
    if not valuation.holdings:
        typer.echo("Pozisyon yok.")
        return
    for holding in valuation.holdings:
        units, cost = canonical_text(holding.units), canonical_text(holding.cost)
        if holding.price is None or holding.value is None:
            typer.echo(f"{holding.instrument}  {units} adet  fiyat yok  maliyet {cost}")
            continue
        typer.echo(
            f"{holding.instrument}  {units} adet × {canonical_text(holding.price.price)} "
            f"({holding.price.price_date.isoformat()}) = {canonical_text(holding.value)}"
            f"  maliyet {cost}"
        )
    typer.echo(
        f"Toplam değer: {canonical_text(valuation.total_value)} "
        f"(fiyatı olan varlıkların maliyeti {canonical_text(valuation.priced_cost)})"
    )
    if view.simple_return is None:
        typer.echo("Basit getiri: hesaplanamadı")
    else:
        typer.echo(f"Basit getiri: %{(view.simple_return * 100).quantize(Decimal('0.01'))}")
    typer.echo(f"Gerçekleşmiş K/Z: {canonical_text(view.realized_pnl)}")
    if valuation.missing_prices:
        typer.echo(f"Fiyatı eksik: {', '.join(valuation.missing_prices)}")


@sync_app.command("cpi")
def sync_cpi_command(
    start: Annotated[
        str | None,
        typer.Option("--from", help="İlk dönem, YYYY-AA; verilmezse bütün geçmiş (2005-01)."),
    ] = None,
) -> None:
    """TÜFE'yi EVDS3'ten çeker; değişen dönemler revizyon olarak yazılır."""
    settings = _load_settings_or_exit()
    first = CPI_HISTORY_START if start is None else _parse_period(start)
    clock = bootstrap.system_clock()
    with _user_errors(), bootstrap.cpi_source(settings, clock) as source:
        report = sync_cpi(
            source,
            lambda: bootstrap.open_unit_of_work(settings),
            series=settings.cpi_series,
            base=settings.cpi_base,
            start=first,
            end=YearMonth.of(clock.today()),
            now=clock.now(),
        )
    _print_cpi_sync(report)


def _print_cpi_sync(report: CpiSyncReport) -> None:
    typer.echo(
        f"TÜFE {report.series}: {report.received} dönem alındı; eklenen {report.inserted}, "
        f"değişmeyen {report.unchanged}, revize {len(report.revised)}"
    )
    for revision in report.revised:
        typer.echo(
            f"Revize {revision.period}: {canonical_text(revision.old)} → "
            f"{canonical_text(revision.new)}"
        )
    typer.echo(f"Son dönem: {report.latest or 'yok'}")


_SYMBOLS = {"ok": "✓", "warn": "!", "fail": "✗"}


@app.command("doctor")
def doctor() -> None:
    """Kurulumu ve verinin tutarlılığını kontrol eder; yalnızca hatalar 1 ile çıkar."""
    settings = _load_settings_or_exit()
    checks = bootstrap.run_doctor(settings)
    for check in checks:
        typer.echo(f"{_SYMBOLS[check.status]} {check.name}: {check.detail}")
    if any(check.status == "fail" for check in checks):
        raise typer.Exit(code=1)


def _format_transaction(stored: StoredTransaction) -> str:
    tx = stored.transaction
    parts = [
        f"#{stored.id}",
        tx.trade_date.isoformat(),
        tx.instrument,
        tx.side.value,
        f"{canonical_text(tx.units)} × {canonical_text(tx.unit_price)}",
        f"komisyon {canonical_text(tx.fee)}",
    ]
    if stored.external_ref:
        parts.append(f"ref {stored.external_ref}")
    if stored.note:
        parts.append(f"not: {stored.note}")
    if stored.is_voided:
        parts.append(f"[İPTAL: {stored.void_reason}]")
    return "  ".join(parts)


def _parse_date(text: str) -> date:
    try:
        value = date.fromisoformat(text)
    except ValueError:
        value = None
    if value is None or value.isoformat() != text:
        typer.echo(f"Tarih YYYY-AA-GG biçiminde olmalı, {text!r} verildi.", err=True)
        raise typer.Exit(code=2)
    return value


def _parse_period(text: str) -> YearMonth:
    try:
        return YearMonth.parse(text)
    except DomainError:
        typer.echo(f"Dönem YYYY-AA biçiminde geçerli bir ay olmalı, {text!r} verildi.", err=True)
        raise typer.Exit(code=2) from None


def _parse_decimal(name: str, text: str) -> Decimal:
    if text.count(",") == 1 and "." not in text:
        typer.echo(
            f"{name}: ondalık ayırıcı nokta olmalı; {text} yerine {text.replace(',', '.')} yaz.",
            err=True,
        )
        raise typer.Exit(code=2)
    try:
        return Decimal(text)
    except InvalidOperation:
        typer.echo(f"{name}: sayı olmalı, {text!r} verildi.", err=True)
        raise typer.Exit(code=2) from None


def _print_apply(report: ApplyReport) -> None:
    sync = report.sync
    changes = [
        (label, codes)
        for label, codes in (
            ("Eklenen", sync.added),
            ("Güncellenen", sync.updated),
            ("Pasif yapılan", sync.deactivated),
            ("Yeniden etkinleşen", sync.reactivated),
        )
        if codes
    ]
    if not changes:
        typer.echo("Değişiklik yok.")
    for label, codes in changes:
        typer.echo(f"{label}: {', '.join(codes)}")
    for warning in report.warnings:
        typer.echo(f"Uyarı: {warning}")


@contextmanager
def _user_errors() -> Iterator[None]:
    try:
        yield
    except ConfigError as exc:
        typer.echo(f"Config'te {len(exc.issues)} hata var:", err=True)
        for issue in exc.issues:
            typer.echo(f"  - {issue}", err=True)
        raise typer.Exit(code=1) from exc
    except (
        DomainError,
        bootstrap.MigrationError,
        bootstrap.SetupError,
        bootstrap.SourceError,
    ) as exc:
        typer.echo(f"Hata: {exc}", err=True)
        raise typer.Exit(code=1) from exc


def _portfolio_path(settings: Settings, file: Path | None) -> Path:
    path = file or settings.portfolio_path
    if path is None:
        typer.echo(
            "Portföy dosyası belirtilmedi: FT_PORTFOLIO_PATH ayarla ya da --file kullan.", err=True
        )
        raise typer.Exit(code=2)
    return path


def _load_settings_or_exit() -> Settings:
    try:
        return load_settings()
    except ValidationError as exc:
        # Yalnızca alan adları yazdırılır; değerler sır içerebilir.
        fields = ", ".join(".".join(map(str, error["loc"])) for error in exc.errors())
        typer.echo(
            f"Ayarlar eksik ya da geçersiz: {fields}. "
            "FT_ önekli ortam değişkenlerini ya da .env dosyasını kontrol et.",
            err=True,
        )
        raise typer.Exit(code=2) from exc
