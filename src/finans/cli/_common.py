from importlib.metadata import version
from typing import Annotated

import typer

DISTRIBUTION = "finans-takip"


def _print_version(value: bool) -> None:
    if value:
        typer.echo(version(DISTRIBUTION))
        raise typer.Exit


VersionOption = Annotated[
    bool,
    typer.Option("--version", callback=_print_version, is_eager=True, help="Sürümü yazdır ve çık."),
]
