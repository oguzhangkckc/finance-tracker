import tomllib
from decimal import Decimal
from pathlib import Path

from finans.domain.models import Instrument, InstrumentKind
from finans.domain.portfolio import (
    AlertThresholds,
    ConfigError,
    ConfigIssue,
    InstrumentEntry,
    PortfolioConfig,
    QualityThresholds,
    validate_portfolio,
    validate_quality,
)

_SECTIONS = ("alerts", "contribution", "instruments", "quality", "targets")
_INSTRUMENT_FIELDS = ("code", "kind", "asset_class", "category", "name", "allocation")
_ALERT_FIELDS = ("open_above", "close_below", "reminder_days")
_KIND_HINT = "TEFAS_YAT, TEFAS_EMK, TEFAS_BYF ya da MANUAL olmalı."


class TomlPortfolioSource:
    def load(self, path: Path) -> PortfolioConfig:
        data = _read(path)
        issues = [
            ConfigIssue(key, f"tanınmayan bölüm; geçerli bölümler: {', '.join(_SECTIONS)}.")
            for key in data
            if key not in _SECTIONS
        ]
        entries, instruments = _instruments(data.get("instruments", []), issues)
        targets = _targets(data.get("targets", {}), issues)
        contribution, payday = _contribution(data.get("contribution", {}), issues)
        alerts = _alerts(data.get("alerts", {}), issues)
        jump = _jump(data.get("quality", {}), issues)
        issues.extend(validate_portfolio(entries, targets, alerts, contribution, payday=payday))
        issues.extend(validate_quality(jump))
        if issues or alerts is None:
            raise ConfigError(issues)
        return PortfolioConfig(
            instruments=tuple(instruments),
            targets={name: value for name, value in targets.items() if value is not None},
            monthly_contribution=contribution,
            payday=payday,
            alerts=alerts,
            quality=QualityThresholds.with_overrides(
                {name: value for name, value in jump.items() if value is not None}
            ),
        )


def _read(path: Path) -> dict[str, object]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError([ConfigIssue(str(path), "dosya bulunamadı.")]) from None
    try:
        return tomllib.loads(text, parse_float=Decimal)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError([ConfigIssue(str(path), f"TOML okunamadı: {exc}")]) from None


def _number(value: object, path: str, issues: list[ConfigIssue]) -> Decimal | None:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return Decimal(value)
    if isinstance(value, str):
        issues.append(ConfigIssue(path, f'sayı olmalı (tırnaksız), "{value}" verildi.'))
    else:
        issues.append(ConfigIssue(path, f"sayı olmalı, {value!r} verildi."))
    return None


def _text(
    item: dict[str, object], path: str, key: str, issues: list[ConfigIssue], *, required: bool
) -> str | None:
    value = item.get(key)
    if value is None:
        if required:
            issues.append(ConfigIssue(f"{path}.{key}", "zorunlu alan eksik."))
        return None
    if not isinstance(value, str) or not value.strip():
        issues.append(ConfigIssue(f"{path}.{key}", f"boş olmayan metin olmalı, {value!r} verildi."))
        return None
    return value


def _unknown_keys(
    item: dict[str, object], path: str, allowed: tuple[str, ...], issues: list[ConfigIssue]
) -> None:
    issues.extend(
        ConfigIssue(f"{path}.{key}", "tanınmayan alan.") for key in item if key not in allowed
    )


def _table(value: object, path: str, issues: list[ConfigIssue]) -> dict[str, object] | None:
    if isinstance(value, dict):
        return value
    issues.append(ConfigIssue(path, f"[{path}] tablosu olmalı."))
    return None


def _instruments(
    raw: object, issues: list[ConfigIssue]
) -> tuple[list[InstrumentEntry], list[Instrument]]:
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        issues.append(ConfigIssue("instruments", "[[instruments]] tabloları olarak yazılmalı."))
        return [], []
    entries: list[InstrumentEntry] = []
    instruments: list[Instrument] = []
    for index, item in enumerate(raw):
        path = f"instruments[{index}]"
        code = _text(item, path, "code", issues, required=True)
        kind_text = _text(item, path, "kind", issues, required=True)
        kind: InstrumentKind | None = None
        if kind_text is not None:
            try:
                kind = InstrumentKind(kind_text)
            except ValueError:
                issues.append(ConfigIssue(f"{path}.kind", f'"{kind_text}" geçersiz; {_KIND_HINT}'))
        asset_class = _text(item, path, "asset_class", issues, required=True)
        category = _text(item, path, "category", issues, required=False)
        name = _text(item, path, "name", issues, required=False)
        allocation = item.get("allocation", True)
        if not isinstance(allocation, bool):
            message = f"true ya da false olmalı, {allocation!r} verildi."
            issues.append(ConfigIssue(f"{path}.allocation", message))
            allocation = True
        _unknown_keys(item, path, _INSTRUMENT_FIELDS, issues)
        entries.append(InstrumentEntry(path, code, asset_class, allocation))
        if code is not None and kind is not None and asset_class is not None:
            instruments.append(
                Instrument(
                    code, kind, asset_class, category=category, name=name, allocation=allocation
                )
            )
    return entries, instruments


def _targets(raw: object, issues: list[ConfigIssue]) -> dict[str, Decimal | None]:
    table = _table(raw, "targets", issues)
    if table is None:
        return {}
    return {name: _number(value, f"targets.{name}", issues) for name, value in table.items()}


def _contribution(raw: object, issues: list[ConfigIssue]) -> tuple[Decimal | None, int | None]:
    """Eksik `monthly` "tanımlı değil"dir (K-56); açıkça yazılmış 0'dan ayrılır."""
    table = _table(raw, "contribution", issues)
    if table is None:
        return None, None
    _unknown_keys(table, "contribution", ("monthly", "payday"), issues)
    monthly = (
        _number(table["monthly"], "contribution.monthly", issues) if "monthly" in table else None
    )
    payday = table.get("payday")
    if payday is None:
        return monthly, None
    if not isinstance(payday, int) or isinstance(payday, bool):
        issues.append(ConfigIssue("contribution.payday", f"tam sayı olmalı, {payday!r} verildi."))
        return monthly, None
    if "monthly" not in table:
        message = "maaş günü için contribution.monthly da tanımlı olmalı."
        issues.append(ConfigIssue("contribution.payday", message))
    return monthly, payday


def _alerts(raw: object, issues: list[ConfigIssue]) -> AlertThresholds | None:
    table = _table(raw, "alerts", issues)
    if table is None:
        return None
    _unknown_keys(table, "alerts", _ALERT_FIELDS, issues)
    defaults = AlertThresholds()
    open_above = _number(table.get("open_above", defaults.open_above), "alerts.open_above", issues)
    close_below = _number(
        table.get("close_below", defaults.close_below), "alerts.close_below", issues
    )
    reminder_days = table.get("reminder_days", defaults.reminder_days)
    if not isinstance(reminder_days, int) or isinstance(reminder_days, bool):
        issues.append(
            ConfigIssue("alerts.reminder_days", f"tam sayı olmalı, {reminder_days!r} verildi.")
        )
        return None
    if open_above is None or close_below is None:
        return None
    return AlertThresholds(open_above, close_below, reminder_days)


def _jump(raw: object, issues: list[ConfigIssue]) -> dict[str, Decimal | None]:
    quality = _table(raw, "quality", issues)
    if quality is None:
        return {}
    _unknown_keys(quality, "quality", ("jump",), issues)
    table = _table(quality.get("jump", {}), "quality.jump", issues)
    if table is None:
        return {}
    return {name: _number(value, f"quality.jump.{name}", issues) for name, value in table.items()}
