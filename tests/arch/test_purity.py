import ast
import sys
import tomllib
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "finans"
WALL_CLOCK_ALLOWED = SRC / "adapters" / "clock.py"
WALL_CLOCK_CALLS = frozenset(
    {
        "datetime.datetime.now",
        "datetime.datetime.utcnow",
        "datetime.datetime.today",
        "datetime.date.today",
        "time.time",
        "time.time_ns",
    }
)


def _python_files(base: Path) -> list[Path]:
    return sorted(base.rglob("*.py"))


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def imported_modules(tree: ast.Module) -> Iterator[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            yield node.module


def float_usages(tree: ast.Module) -> Iterator[int]:
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and type(node.value) is float) or (
            isinstance(node, ast.Name) and node.id == "float"
        ):
            yield node.lineno


def _import_aliases(tree: ast.Module) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname is not None:
                    aliases[alias.asname] = alias.name
                else:
                    top = alias.name.split(".")[0]
                    aliases[top] = top
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def _qualified_name(node: ast.expr, aliases: dict[str, str]) -> str | None:
    attributes: list[str] = []
    while isinstance(node, ast.Attribute):
        attributes.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name) or node.id not in aliases:
        return None
    return ".".join([aliases[node.id], *reversed(attributes)])


def wall_clock_usages(tree: ast.Module) -> Iterator[int]:
    aliases = _import_aliases(tree)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute | ast.Name)
            and _qualified_name(node, aliases) in WALL_CLOCK_CALLS
        ):
            yield node.lineno


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from datetime import datetime\nx = datetime.now()", [2]),
        ("import datetime\nx = datetime.date.today()", [2]),
        ("import datetime as dt\nx = dt.datetime.utcnow()", [2]),
        ("from time import time\nx = time()", [2]),
        ("def f(clock):\n    return clock.now(), clock.today()", []),
        ("from datetime import UTC, datetime\nx = datetime(2026, 1, 1, tzinfo=UTC)", []),
    ],
)
def test_wall_clock_detector(source: str, expected: list[int]) -> None:
    assert list(wall_clock_usages(ast.parse(source))) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("x = 1.5", [1]),
        ("x = float('1')", [1]),
        ("def f(x: float) -> None: ...", [1]),
        ("from decimal import Decimal\nx = Decimal('1.5')\ny = 2", []),
    ],
)
def test_float_detector(source: str, expected: list[int]) -> None:
    assert list(float_usages(ast.parse(source))) == expected


def test_source_tree_is_scanned() -> None:
    assert len(_python_files(SRC)) > 10


def test_domain_imports_only_stdlib_and_itself() -> None:
    violations = [
        f"{_relative(path)}: {module}"
        for path in _python_files(SRC / "domain")
        for module in imported_modules(_parse(path))
        if module.split(".")[0] not in sys.stdlib_module_names
        and module != "finans.domain"
        and not module.startswith("finans.domain.")
    ]
    assert violations == []


def test_no_float_in_source() -> None:
    violations = [
        f"{_relative(path)}:{line}"
        for path in _python_files(SRC)
        for line in float_usages(_parse(path))
    ]
    assert violations == []


def test_wall_clock_only_in_system_clock_adapter() -> None:
    violations = [
        f"{_relative(path)}:{line}"
        for path in _python_files(SRC)
        if path != WALL_CLOCK_ALLOWED
        for line in wall_clock_usages(_parse(path))
    ]
    assert violations == []


def test_every_adapter_is_listed_in_the_independence_contract() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    contracts = config["tool"]["importlinter"]["contracts"]
    listed = next(c for c in contracts if c["type"] == "independence")["modules"]
    adapters = SRC / "adapters"
    present = {
        f"finans.adapters.{entry.stem}"
        for entry in adapters.iterdir()
        if not entry.name.startswith("_")
        and (entry.suffix == ".py" or (entry / "__init__.py").is_file())
    }
    assert present == set(listed)
