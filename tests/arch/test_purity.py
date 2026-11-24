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
        "time.localtime",
        "time.gmtime",
        "time.ctime",
        "time.sleep",
    }
)
CURRENT_TIME_WHEN_SINGLE_ARGUMENT = "time.strftime"
DOMAIN_CONTEXT_DECORATOR = "in_domain_context"
DOMAIN_CONTEXT_DEFINITION = SRC / "domain" / "numeric.py"
# K-103: import-linter standart kütüphaneyi yalnız üst düzeyde tanır; urllib.parse serbest.
NETWORK_MODULES = (
    "urllib.request",
    "urllib.response",
    "http.client",
    "http.server",
    "socketserver",
    "ftplib",
    "smtplib",
    "poplib",
    "imaplib",
    "xmlrpc",
)
NETWORK_FREE = ("domain", "contracts", "ports", "application", "settings.py", "cli", "web")


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
        ) or (
            isinstance(node, ast.Call)
            and len(node.args) == 1
            and not node.keywords
            and _qualified_name(node.func, aliases) == CURRENT_TIME_WHEN_SINGLE_ARGUMENT
        ):
            yield node.lineno


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from datetime import datetime\nx = datetime.now()", [2]),
        ("import datetime\nx = datetime.date.today()", [2]),
        ("import datetime as dt\nx = dt.datetime.utcnow()", [2]),
        ("from time import time\nx = time()", [2]),
        ("import time\nx = time.localtime()", [2]),
        ("from time import gmtime\nx = gmtime(0)", [2]),
        ("import time\nx = time.ctime()", [2]),
        ("import time\nx = time.strftime('%Y')", [2]),
        ("import time\nx = time.strftime('%Y', t)", []),
        ("import time\ntime.sleep(1)", [2]),
        ("def f(clock):\n    return clock.now(), clock.today()", []),
        ("from datetime import UTC, datetime\nx = datetime(2026, 1, 1, tzinfo=UTC)", []),
    ],
)
def test_wall_clock_detector(source: str, expected: list[int]) -> None:
    assert list(wall_clock_usages(ast.parse(source))) == expected


def undecorated_public_functions(tree: ast.Module) -> Iterator[str]:
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
            continue
        decorators = {
            d.id if isinstance(d, ast.Name) else d.attr if isinstance(d, ast.Attribute) else ""
            for d in node.decorator_list
        }
        if DOMAIN_CONTEXT_DECORATOR not in decorators:
            yield node.name


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("def f(): ...", ["f"]),
        ("@in_domain_context\ndef f(): ...", []),
        ("@numeric.in_domain_context\ndef f(): ...", []),
        ("def _helper(): ...", []),
        ("@other\ndef g(): ...", ["g"]),
    ],
)
def test_undecorated_function_detector(source: str, expected: list[str]) -> None:
    assert list(undecorated_public_functions(ast.parse(source))) == expected


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


def test_domain_public_functions_run_in_domain_context() -> None:
    violations = [
        f"{_relative(path)}: {name}"
        for path in _python_files(SRC / "domain")
        if path != DOMAIN_CONTEXT_DEFINITION
        for name in undecorated_public_functions(_parse(path))
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


def network_imports(tree: ast.Module) -> Iterator[str]:
    """`from urllib import request` da yakalanır; ImportFrom'un adları da modül sayılır."""
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            names = [node.module, *(f"{node.module}.{alias.name}" for alias in node.names)]
        for name in names:
            if any(name == m or name.startswith(f"{m}.") for m in NETWORK_MODULES):
                yield name


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import urllib.request", ["urllib.request"]),
        ("from urllib import request", ["urllib.request"]),
        ("from urllib.request import urlopen", ["urllib.request", "urllib.request.urlopen"]),
        ("import http.client as hc", ["http.client"]),
        ("from http import server", ["http.server"]),
        ("from urllib.parse import parse_qsl", []),
        ("from http import HTTPStatus", []),
        ("import xmlrpc.client", ["xmlrpc.client"]),
    ],
)
def test_network_import_detector(source: str, expected: list[str]) -> None:
    assert list(network_imports(ast.parse(source))) == expected


def test_network_modules_only_in_adapters() -> None:
    files = [
        path
        for entry in NETWORK_FREE
        for path in ([SRC / entry] if entry.endswith(".py") else _python_files(SRC / entry))
    ]
    assert len(files) > 10
    violations = [
        f"{_relative(path)}: {module}" for path in files for module in network_imports(_parse(path))
    ]
    assert violations == []
