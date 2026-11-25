"""K-128: tasarım sisteminin denetlenebilir kuralları."""

import re
from decimal import Decimal
from pathlib import Path

import pytest

from finans.settings import Settings
from finans.web.app import MORE, STATIC, TABS
from tests.support.web_profiles import ME, PAGES, two_profiles, web

CSS = (STATIC / "site.css").read_text(encoding="utf-8")
AA = Decimal("4.5")
NON_TEXT = Decimal(3)


@pytest.fixture
def base(tmp_path: Path, migrated_db: Path) -> Settings:
    return two_profiles(tmp_path, migrated_db)


def _tokens() -> dict[tuple[str, str], dict[str, str]]:
    light, marker, dark = CSS.partition("@media (prefers-color-scheme: dark)")
    assert marker, "koyu tema bloğu yok"
    themes: dict[tuple[str, str], dict[str, str]] = {}
    for theme, part in (("açık", light), ("koyu", dark)):
        for profile, selector in (
            ("gercek", r":root\s*\{"),
            ("sanal", r':root\[data-profile="sanal"\]\s*\{'),
        ):
            block = re.search(selector + r"([^}]*)\}", part)
            assert block is not None, (theme, profile)
            themes[(theme, profile)] = dict(re.findall(r"--([a-z0-9-]+):\s*([^;]+);", block[1]))
        # Sanal yalnız vurgu renklerini değiştirir; gerisi temanınkiyle aynı.
        themes[(theme, "sanal")] = {**themes[(theme, "gercek")], **themes[(theme, "sanal")]}
    return themes


def _luminance(color: str) -> Decimal:
    channels = [Decimal(int(color.strip().lstrip("#")[i : i + 2], 16)) / 255 for i in (0, 2, 4)]
    linear = [
        c / Decimal("12.92")
        if c <= Decimal("0.04045")
        else ((c + Decimal("0.055")) / Decimal("1.055")) ** Decimal("2.4")
        for c in channels
    ]
    return (
        Decimal("0.2126") * linear[0]
        + Decimal("0.7152") * linear[1]
        + Decimal("0.0722") * linear[2]
    )


def _ratio(first: str, second: str) -> Decimal:
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + Decimal("0.05")) / (low + Decimal("0.05"))


THEMES = _tokens()


@pytest.mark.parametrize("key", sorted(THEMES), ids=lambda key: "-".join(key))
def test_colours_meet_wcag_aa_in_every_theme_and_profile(key: tuple[str, str]) -> None:
    t = THEMES[key]
    pairs = [
        (text, back, AA)
        for text in ("ink", "ink-2", "accent", "gain", "loss", "warn")
        for back in ("paper", "surface")
    ]
    pairs += [("on-accent", "accent", AA)]
    pairs += [
        (text, f"{tone}-soft", AA)
        for tone in ("accent", "gain", "loss", "warn")
        for text in ("ink", tone)
    ]
    # Form çerçevesi ve odak halkası metin değil, ama 3:1 gerekir (WCAG 1.4.11).
    pairs += [
        ("field", "surface", NON_TEXT),
        ("field", "paper", NON_TEXT),
        ("accent", "paper", NON_TEXT),
    ]

    weak = [
        (a, b, f"{_ratio(t[a], t[b]):.2f}") for a, b, floor in pairs if _ratio(t[a], t[b]) < floor
    ]

    assert weak == []


def test_the_sanal_accent_differs_from_the_real_one_in_both_themes() -> None:
    for theme in ("açık", "koyu"):
        assert THEMES[(theme, "sanal")]["accent"] != THEMES[(theme, "gercek")]["accent"]
        assert THEMES[(theme, "sanal")]["accent"] != THEMES[(theme, "gercek")]["warn"]


@pytest.mark.parametrize("slug", ["gercek", "sanal"])
def test_pages_have_no_inline_style_or_script_and_exactly_one_h1(base: Settings, slug: str) -> None:
    client = web(base)

    for path in PAGES:
        page = client.get(f"/{slug}{path}", headers=ME).text
        assert " style=" not in page, path
        assert "<script" not in page, path
        assert page.count("<h1") == 1, path


def test_the_shell_offers_a_skip_link_and_marks_the_current_place(base: Settings) -> None:
    client = web(base)

    report = client.get("/gercek/raporlar/aylik", headers=ME).text
    allocation = client.get("/gercek/dagilim", headers=ME).text

    assert '<a class="skip" href="#icerik">İçeriğe geç</a>' in report
    assert '<main id="icerik">' in report
    assert re.search(r'href="/gercek/raporlar" aria-current="page">', report)
    assert re.search(r'href="/gercek/daha" aria-current="page">', allocation)


def test_the_more_page_lists_every_page_missing_from_the_tabs(base: Settings) -> None:
    page = web(base).get("/sanal/daha", headers=ME).text

    tab_paths = {href for href, *_ in TABS}
    for href, label, _ in MORE:
        assert href not in tab_paths
        assert f'<a href="/sanal{href}">' in page
        assert f"<span>{label}</span>" in page
    assert len(TABS) == 5
