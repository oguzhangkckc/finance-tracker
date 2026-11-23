from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from finans import bootstrap
from finans.application.portfolio_config import ApplyReport, apply_portfolio
from finans.cli._common import VersionOption
from finans.domain.models import DomainError
from finans.domain.portfolio import ConfigError
from finans.settings import Settings, load_settings

app = typer.Typer(
    name="ft", no_args_is_help=True, add_completion=False, help="Finans takip: insan arayüzü."
)
db_app = typer.Typer(no_args_is_help=True, help="Veritabanı işlemleri.")
config_app = typer.Typer(no_args_is_help=True, help="Portföy tanımı (portfolio.toml).")
app.add_typer(db_app, name="db")
app.add_typer(config_app, name="config")

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
        applied = bootstrap.migrate_database(settings)
    except bootstrap.MigrationError as exc:
        typer.echo(f"Migration hatası: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if applied:
        typer.echo(f"Uygulanan migration'lar: {', '.join(map(str, applied))}")
    else:
        typer.echo("Veritabanı güncel.")


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
    except (DomainError, bootstrap.MigrationError, bootstrap.SetupError) as exc:
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
