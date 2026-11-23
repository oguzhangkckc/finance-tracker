import typer

from finans.cli._common import VersionOption

app = typer.Typer(
    name="ft-agent",
    no_args_is_help=True,
    add_completion=False,
    help="OpenClaw için salt okunur arayüz. Yazma komutu içermez.",
)


@app.callback()
def main(_version: VersionOption = False) -> None:
    """OpenClaw için salt okunur arayüz. Yazma komutu içermez."""
