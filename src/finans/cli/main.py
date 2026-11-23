import typer
from pydantic import ValidationError

from finans import bootstrap
from finans.cli._common import VersionOption
from finans.settings import Settings, load_settings

app = typer.Typer(
    name="ft", no_args_is_help=True, add_completion=False, help="Finans takip: insan arayüzü."
)
db_app = typer.Typer(no_args_is_help=True, help="Veritabanı işlemleri.")
app.add_typer(db_app, name="db")


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
