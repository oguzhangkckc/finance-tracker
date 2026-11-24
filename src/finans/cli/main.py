from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from finans import bootstrap
from finans.application.cpi import CPI_HISTORY_START, CpiSyncReport, sync_cpi
from finans.application.data_check import DEFAULT_WINDOW, check_data, trade_price_issues
from finans.application.portfolio_config import ApplyReport, apply_portfolio
from finans.application.portfolio_view import portfolio_as_of
from finans.application.price_sync import PriceSyncReport, sync_prices
from finans.application.prices import set_manual_price
from finans.application.reconcile import reconcile_statement
from finans.application.report import ReportKind, build_report, payday_plan
from finans.application.transactions import (
    add_transaction,
    import_transactions,
    void_transaction,
)
from finans.cli._common import VersionOption
from finans.domain.models import DomainError, InstrumentKind, Side, Transaction, YearMonth
from finans.domain.numeric import canonical_text
from finans.domain.portfolio import ConfigError, QualityThresholds
from finans.domain.quality import DataIssue
from finans.domain.reconcile import PriceDateEvidence
from finans.domain.schedule import logical_date
from finans.ports.clock import BUSINESS_TZ
from finans.ports.repositories import StoredTransaction
from finans.settings import Settings, load_settings

app = typer.Typer(
    name="ft", no_args_is_help=True, add_completion=False, help="Finans takip: insan arayüzü."
)
db_app = typer.Typer(no_args_is_help=True, help="Veritabanı işlemleri.")
config_app = typer.Typer(no_args_is_help=True, help="Portföy tanımı (portfolio.toml).")
tx_app = typer.Typer(no_args_is_help=True, help="İşlemler.")
price_app = typer.Typer(
    no_args_is_help=True,
    help="Elle girilen fiyatlar; TEFAS fonlarında TEFAS fiyatı gelince yerini alır (K-63).",
)
app.add_typer(db_app, name="db")
app.add_typer(config_app, name="config")
app.add_typer(tx_app, name="tx")
sync_app = typer.Typer(no_args_is_help=True, help="Dış kaynaklardan veri çekme.")
data_app = typer.Typer(no_args_is_help=True, help="Veri kalitesi.")
app.add_typer(price_app, name="price")
app.add_typer(sync_app, name="sync")
app.add_typer(data_app, name="data")
report_app = typer.Typer(no_args_is_help=True, help="Raporlar (önizleme).")
app.add_typer(report_app, name="report")
notify_app = typer.Typer(no_args_is_help=True, help="Bildirim kanalı (Telegram).")
app.add_typer(notify_app, name="notify")
job_app = typer.Typer(
    no_args_is_help=True, help="Zamanlanmış işler; systemd yalnızca bunları çağırır."
)
app.add_typer(job_app, name="job")


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
        clock = bootstrap.system_clock()
        with bootstrap.open_unit_of_work(settings) as uow:
            txn_id = add_transaction(uow, transaction, ref=ref, note=note, now=clock.now())
            warnings = trade_price_issues(uow, [(f"#{txn_id}", transaction)], today=clock.today())
    typer.echo(f"İşlem eklendi: #{txn_id}")
    _print_warnings(warnings)


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
    clock = bootstrap.system_clock()
    with _user_errors(), bootstrap.open_unit_of_work(settings) as uow:
        report = import_transactions(uow, parsed, now=clock.now(), dry_run=dry_run)
        added = [(f"satır {row.line}", row.transaction) for row in report.added]
        warnings = [] if report.issues else trade_price_issues(uow, added, today=clock.today())
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
    _print_warnings(warnings)


@price_app.command("set")
def price_set(
    code: Annotated[str, typer.Argument(help="Varlık kodu")],
    on: Annotated[str, typer.Argument(help="Fiyat günü (YYYY-AA-GG)")],
    price: Annotated[str, typer.Argument(help="Birim fiyat (TL)")],
) -> None:
    """Bir varlığın o günkü birim fiyatını elle kaydeder; TEFAS fiyatı varsa reddeder."""
    settings = _load_settings_or_exit()
    day, amount = _parse_date(on), _parse_decimal("price", price)
    with _user_errors(), bootstrap.open_unit_of_work(settings) as uow:
        write = set_manual_price(uow, code, day, amount, now=bootstrap.system_clock().now())
        stored = uow.instruments.get(code)
    is_fund = stored is not None and stored.instrument.kind is not InstrumentKind.MANUAL
    if write.status == "inserted":
        typer.echo("Fiyat kaydedildi.")
    elif write.status == "unchanged":
        typer.echo("Fiyat aynı; değişiklik yok.")
    else:
        previous = "?" if write.previous is None else canonical_text(write.previous)
        typer.echo(f"Fiyat güncellendi; önceki değer {previous}.")
    if is_fund:
        typer.echo("Not: TEFAS fonu; o günün TEFAS fiyatı gelince yerini alır (K-63).")


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


@sync_app.command("prices")
def sync_prices_command(
    codes: Annotated[
        list[str] | None,
        typer.Option("--code", help="Yalnızca bu fon; birden çok kez verilebilir."),
    ] = None,
    start: Annotated[
        str | None,
        typer.Option("--from", help="YYYY-AA-GG; verilmezse fon başına otomatik seçilir."),
    ] = None,
    end: Annotated[str | None, typer.Option("--to", help="YYYY-AA-GG; verilmezse bugün.")] = None,
    backfill: Annotated[
        bool,
        typer.Option("--backfill", help="Kayıtlı fiyatları yok sayıp ilk işlemden başlar."),
    ] = False,
) -> None:
    """TEFAS fon fiyatlarını çeker (K-71); engel gelirse durur, aşmaya çalışmaz."""
    settings = _load_settings_or_exit()
    first = None if start is None else _parse_date(start)
    clock = bootstrap.system_clock()
    last = clock.today() if end is None else _parse_date(end)

    def announce(count: int) -> None:
        typer.echo(
            f"TEFAS fiyatları isteniyor ({count} fon); istekler arası en az "
            f"{settings.tefas_min_interval_s} sn."
        )

    with _user_errors(), bootstrap.price_source(settings, clock) as source:
        report = sync_prices(
            source,
            lambda: bootstrap.open_unit_of_work(settings),
            codes=codes,
            start=first,
            end=last,
            backfill=backfill,
            now=clock.now(),
            on_start=announce,
        )
    _print_price_sync(report)
    if report.funds:
        since = min(fund.start for fund in report.funds)
        with _user_errors(), bootstrap.open_unit_of_work(settings, readonly=True) as uow:
            issues = check_data(uow, quality=_quality(settings), today=last, since=since)
        typer.echo("Veri kalitesi:")
        _print_issues(issues)
    if not report.ok:
        raise typer.Exit(code=1)


def _print_price_sync(report: PriceSyncReport) -> None:
    if not report.funds:
        typer.echo(
            "Senkronize edilecek TEFAS fonu yok; portfolio.toml'a fon ekleyip "
            "`ft config apply` çalıştır."
        )
        return
    for fund in report.funds:
        if fund.error is not None:
            typer.echo(f"✗ {fund.code}: {fund.error}")
            continue
        typer.echo(
            f"✓ {fund.code} ({fund.start} ile {fund.end} arası): {fund.received} gün alındı; "
            f"eklenen {fund.inserted}, değişmeyen {fund.unchanged}, revize {len(fund.revised)}"
        )
        for revision in fund.revised:
            typer.echo(
                f"  revize {revision.day}: {canonical_text(revision.old)} → "
                f"{canonical_text(revision.new)}"
            )
        for item in fund.replaced:
            typer.echo(
                f"  elle fiyat yerine TEFAS {item.day}: {canonical_text(item.manual)} → "
                f"{canonical_text(item.tefas)}"
            )
            if not item.matches:
                typer.echo(
                    f"Uyarı: [elle ve TEFAS fiyatı] {fund.code} {item.day}: elle girilen "
                    f"{canonical_text(item.manual)} TEFAS fiyatıyla ({canonical_text(item.tefas)}) "
                    "uyuşmuyor"
                )
    if report.stopped is not None:
        typer.echo("Durduruldu: TEFAS isteği reddetti ya da sınırladı; engel aşılmaya çalışılmadı.")
        if report.skipped:
            typer.echo(f"Denenmeyen fonlar: {', '.join(report.skipped)}")
    typer.echo(f"Sonuç: {'tamam' if report.ok else 'kısmi'}")


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


@app.command("reconcile")
def reconcile_command(
    path: Annotated[
        Path, typer.Argument(help="Ekstre CSV'si: date,code,units,price,value (price isteğe bağlı)")
    ],
) -> None:
    """Aracı kurum ekstresini kayıtlarla karşılaştırır; kalem başına ±0,01 TL (K-67, K-78)."""
    settings = _load_settings_or_exit()
    parsed = bootstrap.statement_file().read(path)
    if parsed.issues:
        typer.echo(f"Ekstre okunamadı; {len(parsed.issues)} sorun:", err=True)
        for issue in parsed.issues:
            typer.echo(f"  - {issue}", err=True)
        raise typer.Exit(code=1)
    if not parsed.lines:
        typer.echo("Ekstrede satır yok.", err=True)
        raise typer.Exit(code=1)
    with _user_errors(), bootstrap.open_unit_of_work(settings, readonly=True) as uow:
        report = reconcile_statement(uow, parsed.lines)
    for item in report.items:
        where = f"{item.day} {item.code}" + ("" if item.line is None else f" (satır {item.line})")
        typer.echo(f"{'✓' if item.ok else '✗'} {where}: {item.message}")
    _print_price_evidence(report.evidence)
    total = len(report.items)
    if report.passed:
        typer.echo(f"Mutabakat: geçti ({total} kalem, hepsi ±0,01 TL içinde).")
        return
    failed = sum(1 for item in report.items if not item.ok)
    typer.echo(f"Mutabakat: kaldı ({failed}/{total} kalem uyumsuz).")
    raise typer.Exit(code=1)


def _print_price_evidence(evidence: tuple[PriceDateEvidence, ...]) -> None:
    if not evidence:
        return
    typer.echo("Fiyat tarihi kanıtı (açık soru: D tarihli fiyat hangi emirlere uygulanıyor):")
    for offset in sorted({e.offset for e in evidence}):
        group = [e for e in evidence if e.offset == offset]
        typer.echo(f"  {_offset_label(offset)}: {len(group)} kalem")
        for e in group:
            typer.echo(
                f"    {e.code}: ekstre {e.statement_day}, TEFAS fiyatı {e.price_day} ({e.basis})"
            )


def _offset_label(offset: int) -> str:
    if offset == 0:
        return "ekstre gününün fiyatı"
    direction = "önceki" if offset < 0 else "sonraki"
    return f"{abs(offset)} işlem günü {direction} fiyat"


@data_app.command("check")
def data_check(
    since: Annotated[
        str | None,
        typer.Option("--since", help="YYYY-AA-GG; sıçrama ve boşluk penceresi, varsayılan 30 gün."),
    ] = None,
    strict: Annotated[
        bool, typer.Option("--strict", help="Uyarı varsa 1 ile çık (zamanlanmış işler için).")
    ] = False,
) -> None:
    """Fiyat verisini ve işlem fiyatlarını denetler; varsayılan olarak her durumda 0 ile çıkar."""
    settings = _load_settings_or_exit()
    first = None if since is None else _parse_date(since)
    today = bootstrap.system_clock().today()
    quality = _quality(settings)
    with _user_errors(), bootstrap.open_unit_of_work(settings, readonly=True) as uow:
        issues = check_data(
            uow, quality=quality, today=today, since=first or today - DEFAULT_WINDOW
        )
    _print_issues(issues)
    if strict and any(issue.level == "warn" for issue in issues):
        raise typer.Exit(code=1)


def _quality(settings: Settings) -> QualityThresholds:
    if settings.portfolio_path is None:
        return QualityThresholds()
    try:
        return bootstrap.portfolio_source().load(settings.portfolio_path).quality
    except ConfigError:
        typer.echo(
            "Not: portfolio.toml okunamadı; varsayılan eşikler kullanıldı (`ft config check`).",
            err=True,
        )
        return QualityThresholds()


def _print_issues(issues: list[DataIssue]) -> None:
    if not issues:
        typer.echo("Veri sorunu yok.")
        return
    for issue in issues:
        typer.echo(f"{'!' if issue.level == 'warn' else '·'} {issue}")
    warnings = sum(1 for issue in issues if issue.level == "warn")
    typer.echo(f"{warnings} uyarı, {len(issues) - warnings} bilgi")


def _print_warnings(issues: list[DataIssue]) -> None:
    for issue in issues:
        typer.echo(f"{'Uyarı' if issue.level == 'warn' else 'Bilgi'}: {issue}")


_SYMBOLS = {"ok": "✓", "warn": "!", "fail": "✗"}


class JobChoice(StrEnum):
    SYNC_PRICES = "sync-prices"
    SYNC_CPI = "sync-cpi"
    WEEKLY_REPORT = "weekly-report"
    MONTHLY_REPORT = "monthly-report"
    PAYDAY = "payday"
    BACKUP = "backup"


_OUTCOME_LABELS = {
    "ok": "tamam",
    "partial": "kısmi",
    "failed": "başarısız",
    "skipped": "bu gün için zaten tamamlanmış; atlandı",
    "busy": "başka bir örnek çalışıyor; beklemeden çıkıldı",
}


@job_app.command("run")
def job_run(
    name: Annotated[JobChoice, typer.Argument(help="İş adı")],
    logical: Annotated[
        str | None,
        typer.Option("--logical-date", help="YYYY-AA-GG; verilmezse son planlı çalışmanın günü."),
    ] = None,
) -> None:
    """Bir zamanlanmış işi çalıştırır (K-80); aynı gün için "ok" varsa atlar (K-12)."""
    settings = _load_settings_or_exit()
    bootstrap.configure_logging(settings)
    clock = bootstrap.system_clock()
    with _user_errors():
        payday = bootstrap.portfolio_source().load(_portfolio_path(settings, None)).payday
        day = (
            _parse_date(logical)
            if logical is not None
            else logical_date(name.value, clock.now().astimezone(BUSINESS_TZ), payday=payday)
        )
        outcome = bootstrap.run_scheduled_job(settings, clock, name.value, day)
    typer.echo(f"{name.value} {day}: {_OUTCOME_LABELS[outcome.status]}")
    for key, value in outcome.detail.items():
        typer.echo(f"  {key}: {value}")
    if outcome.status == "failed":
        raise typer.Exit(code=1)


@job_app.command("list")
def job_list(
    days: Annotated[int, typer.Option("--days", help="Kaç günlük kayıt.")] = 7,
) -> None:
    """Son iş denemelerini gösterir."""
    settings = _load_settings_or_exit()
    clock = bootstrap.system_clock()
    with _user_errors(), bootstrap.open_unit_of_work(settings, readonly=True) as uow:
        runs = uow.runs.recent(since=clock.now() - timedelta(days=days))
    if not runs:
        typer.echo(f"Son {days} günde iş kaydı yok.")
    for run in runs:
        started = run.started_at.astimezone(BUSINESS_TZ)
        typer.echo(
            f"#{run.id} {run.job} {run.logical_date} {run.status} ({started:%Y-%m-%d %H:%M})"
        )


@notify_app.command("test")
def notify_test() -> None:
    """Telegram kurulumunu doğrulamak için kısa bir mesaj gönderir (K-89)."""
    settings = _load_settings_or_exit()
    with _user_errors(), bootstrap.notifier(settings, bootstrap.system_clock()) as channel:
        channel.send("finans-takip: Telegram bağlantısı çalışıyor.", silent=False)
    typer.echo("Test mesajı gönderildi.")


@app.command("alerts")
def alerts_command() -> None:
    """Açık sapma alarmlarını ve sessiz dönemin durumunu gösterir (K-46, K-75)."""
    settings = _load_settings_or_exit()
    with _user_errors(), bootstrap.open_unit_of_work(settings, readonly=True) as uow:
        states = uow.alerts.list_open()
        ended = uow.allocation_state.quiet_ended_on()
    typer.echo(
        f"Sessiz dönem: {ended} tarihinde bitti" if ended else "Sessiz dönem: sürüyor (K-75)"
    )
    if not states:
        typer.echo("Açık alarm yok.")
    for state in states:
        side = "üstünde" if state.direction == "above" else "altında"
        last = (
            "yok" if state.last_notified_at is None else f"{state.last_notified_at:%Y-%m-%d %H:%M}"
        )
        typer.echo(
            f"{state.fingerprint.removeprefix('drift:')}: hedefin {side}, açılış "
            f"{state.opened_at:%Y-%m-%d %H:%M} UTC, son bildirim {last}"
        )


class ReportFormat(StrEnum):
    TEXT = "text"
    JSON = "json"


ReportOnOption = Annotated[
    str | None, typer.Option("--on", help="YYYY-AA-GG; verilmezse son planlı rapor günü (K-86).")
]
ReportFormatOption = Annotated[ReportFormat, typer.Option("--format", help="text ya da json")]
HideAmountsOption = Annotated[
    bool, typer.Option("--hide-amounts", help="Telegram görünümü: TL tutarlarını gizle (K-90).")
]
ContributionOption = Annotated[
    str | None, typer.Option("--contribution", help="Bu ayki katkı; config'teki değerin yerine.")
]


@report_app.command("weekly")
def report_weekly(
    on: ReportOnOption = None,
    fmt: ReportFormatOption = ReportFormat.TEXT,
    hide_amounts: HideAmountsOption = False,
) -> None:
    """Haftalık raporu gösterir; gönderim zamanlanmış işin (weekly-report) işidir."""
    _show_report("weekly", on, None, fmt, hide_amounts)


@report_app.command("monthly")
def report_monthly(
    on: ReportOnOption = None,
    contribution: ContributionOption = None,
    fmt: ReportFormatOption = ReportFormat.TEXT,
    hide_amounts: HideAmountsOption = False,
) -> None:
    """Aylık raporu gösterir: XIRR, lotlar, enflasyon ve katkıyla dengeleme."""
    _show_report("monthly", on, contribution, fmt, hide_amounts)


@report_app.command("payday")
def report_payday(
    on: Annotated[str | None, typer.Option("--on", help="YYYY-AA-GG; verilmezse bugün.")] = None,
    contribution: ContributionOption = None,
    fmt: ReportFormatOption = ReportFormat.TEXT,
    hide_amounts: HideAmountsOption = False,
) -> None:
    """Bu ayki katkının sınıf ve fon bazında dağılım önerisi (K-83)."""
    settings = _load_settings_or_exit()
    clock = bootstrap.system_clock()
    day = clock.today() if on is None else _parse_date(on)
    with _user_errors():
        config = bootstrap.portfolio_source().load(_portfolio_path(settings, None))
        amount = (
            config.monthly_contribution
            if contribution is None
            else _parse_decimal("--contribution", contribution)
        )
        with bootstrap.open_unit_of_work(settings, readonly=True) as uow:
            plan = payday_plan(uow, config, on=day, contribution=amount)
    renderer = bootstrap.report_renderer(fmt.value, payday_amounts=not hide_amounts)
    typer.echo(renderer.payday(plan))


def _show_report(
    kind: ReportKind, on: str | None, contribution: str | None, fmt: ReportFormat, hide: bool
) -> None:
    settings = _load_settings_or_exit()
    clock = bootstrap.system_clock()
    with _user_errors():
        config = bootstrap.portfolio_source().load(_portfolio_path(settings, None))
        day = (
            logical_date(f"{kind}-report", clock.now().astimezone(BUSINESS_TZ))
            if on is None
            else _parse_date(on)
        )
        amount = (
            config.monthly_contribution
            if contribution is None
            else _parse_decimal("--contribution", contribution)
        )
        with bootstrap.open_unit_of_work(settings, readonly=True) as uow:
            report = build_report(
                uow,
                config,
                kind=kind,
                logical_date=day,
                contribution=amount,
                now=clock.now(),
                cpi_series=settings.cpi_series,
            )
    typer.echo(bootstrap.report_renderer(fmt.value, hide_amounts=hide).report(report))


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
        bootstrap.NotifyError,
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
