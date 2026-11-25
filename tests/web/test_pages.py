import hashlib
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from finans import bootstrap
from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.application.transactions import add_transaction, void_transaction
from finans.contracts.display import exact, money, percent, points
from finans.domain.models import PricePoint, Side, Transaction
from finans.settings import Settings
from finans.web.app import create_app
from tests.fakes.clock import FixedClock
from tests.support import report_scenario as scenario
from tests.support.web_client import WebClient

ME = {"Tailscale-User-Login": "kisi@example.com"}
SUNDAY = date(2026, 11, 29)
SUNDAY_EVENING = FixedClock(datetime(2026, 11, 29, 17, 30, tzinfo=UTC))
PAGES = (
    "/gercek/",
    "/gercek/varliklar",
    "/gercek/dagilim",
    "/gercek/getiri",
    "/gercek/raporlar",
    "/gercek/raporlar/haftalik",
    "/gercek/raporlar/aylik",
    "/gercek/raporlar/maas-gunu",
    "/gercek/alarmlar",
    "/gercek/islemler",
    "/gercek/sistem",
)
PORTFOLIO = """
[targets]
hisse = 0.6
dusuk_risk = 0.4

[sinif_adlari]
dusuk_risk = "Düşük risk"

[contribution]
monthly = 1000
payday = 15

[[instruments]]
code = "XHT"
kind = "TEFAS_YAT"
asset_class = "hisse"

[[instruments]]
code = "XPP"
kind = "TEFAS_YAT"
asset_class = "dusuk_risk"
category = "para_piyasasi"

[[instruments]]
code = "XAC"
kind = "TEFAS_YAT"
asset_class = "acil_durum"
allocation = false
"""


def _client(
    db: Path, tmp_path: Path, clock: FixedClock = SUNDAY_EVENING, **extra: object
) -> WebClient:
    portfolio = tmp_path / "portfolio.toml"
    portfolio.write_text(PORTFOLIO, encoding="utf-8")
    settings = Settings(
        db_path=db,
        portfolio_path=portfolio,
        web_allowed_login="kisi@example.com",
        web_origin="https://cihaz.ornek.ts.net",
        web_session_key="k" * 64,
        **extra,  # type: ignore[arg-type]
    )
    return WebClient(create_app(settings, clock=clock))


def test_summary_shows_the_same_numbers_as_the_text_report(
    migrated_db: Path, tmp_path: Path
) -> None:
    scenario.seed(migrated_db)
    expected = scenario.report(migrated_db, "weekly", SUNDAY)

    page = _client(migrated_db, tmp_path).get("/gercek/", headers=ME).text

    assert f"Değerleme günü {SUNDAY}" in page
    assert money(expected.summary.values.total) in page
    assert money(expected.summary.values.out_of_allocation) in page
    for holding in expected.holdings:
        assert holding.price is not None
        assert f"{exact(holding.price)}</span> TL ({holding.price_date})" in page


def test_holdings_page_has_lots_and_card_labels(migrated_db: Path, tmp_path: Path) -> None:
    scenario.seed(migrated_db)
    expected = scenario.report(migrated_db, "monthly", SUNDAY)

    page = _client(migrated_db, tmp_path).get("/gercek/varliklar", headers=ME).text

    assert expected.lots
    assert "<h2>Lotlar</h2>" in page
    for holding in expected.holdings:
        assert f'data-label="Adet" class="num">{exact(holding.units)}</td>' in page


def test_allocation_page_shows_weights_and_open_alerts(migrated_db: Path, tmp_path: Path) -> None:
    scenario.seed(migrated_db, alarm=True)
    expected = scenario.report(migrated_db, "weekly", SUNDAY)

    page = _client(migrated_db, tmp_path).get("/gercek/dagilim", headers=ME).text

    for line in expected.allocation:
        assert percent(line.weight, places=1) in page
        assert points(line.deviation) in page
    assert expected.alerts
    assert "Açık alarm yok." not in page


def test_a_missing_price_is_stated_and_allocation_is_skipped(
    migrated_db: Path, tmp_path: Path
) -> None:
    scenario.seed(migrated_db, priced=("XHT", "XAC"))
    client = _client(migrated_db, tmp_path)

    summary = client.get("/gercek/", headers=ME).text
    allocation = client.get("/gercek/dagilim", headers=ME).text

    assert "Fiyatı eksik: XPP" in summary
    assert "fiyat yok" in summary
    assert "Dağılım hesaplanmadı; fiyatı eksik: XPP." in allocation


LATER = FixedClock(datetime(2026, 12, 15, 9, 0, tzinfo=UTC))


def test_a_manual_price_and_a_stale_fund_are_marked(migrated_db: Path, tmp_path: Path) -> None:
    scenario.seed(migrated_db)
    with SqliteUnitOfWork(migrated_db) as uow:
        for day in range(1, 16):
            on = date(2026, 12, day)
            if on.weekday() < 5:
                uow.prices.upsert(
                    PricePoint("XHT", on, scenario.D(12), "tefas"), fetched_at=scenario.NOW
                )
        manual = PricePoint("XAC", date(2026, 12, 15), scenario.D("50.6"), "manual")
        uow.prices.upsert(manual, fetched_at=scenario.NOW)

    page = _client(migrated_db, tmp_path, LATER).get("/gercek/", headers=ME).text

    assert '50,6</span> TL (2026-12-15) <span class="tag">elle</span>' in page
    assert '20,2</span> TL (2026-11-27) <span class="warn">bayat:' in page
    assert "Fiyatlar bayat:" not in page


def test_when_no_fund_gets_a_price_the_general_rule_is_shown(
    migrated_db: Path, tmp_path: Path
) -> None:
    scenario.seed(migrated_db)

    page = _client(migrated_db, tmp_path, LATER).get("/gercek/", headers=ME).text

    assert "Fiyatlar bayat: hiçbir fona 18 gündür yeni fiyat gelmedi." in page


@pytest.mark.usefixtures("system_zone")
def test_dates_follow_istanbul_not_the_system_zone(migrated_db: Path, tmp_path: Path) -> None:
    scenario.seed(migrated_db)
    # İstanbul'da 30 Kasım 00:30, UTC'de hâlâ 29 Kasım.
    midnight = FixedClock(datetime(2026, 11, 29, 21, 30, tzinfo=UTC))

    page = _client(migrated_db, tmp_path, midnight).get("/gercek/", headers=ME).text

    assert "Değerleme günü 2026-11-30" in page


def test_visiting_every_page_changes_nothing_in_the_database(
    migrated_db: Path, tmp_path: Path
) -> None:
    scenario.seed(migrated_db, alarm=True)
    before = hashlib.sha256(migrated_db.read_bytes()).hexdigest()
    client = _client(migrated_db, tmp_path)

    statuses = [client.get(path, headers=ME).status_code for path in PAGES]

    assert statuses == [200] * len(PAGES)
    assert hashlib.sha256(migrated_db.read_bytes()).hexdigest() == before


def test_a_missing_portfolio_shows_an_error_page(migrated_db: Path) -> None:
    settings = Settings(
        db_path=migrated_db,
        web_allowed_login="kisi@example.com",
        web_origin="https://cihaz.ornek.ts.net",
        web_session_key="k" * 64,
    )

    response = WebClient(create_app(settings, clock=SUNDAY_EVENING)).get("/gercek/", headers=ME)

    assert response.status_code == 503
    assert "FT_PORTFOLIO_PATH tanımlı değil." in response.text


def test_stylesheet_is_mobile_first() -> None:
    css = (Path(__file__).resolve().parents[2] / "src/finans/web/static/site.css").read_text(
        encoding="utf-8"
    )

    assert "font-variant-numeric: tabular-nums" in css
    assert "--tap: 44px" in css
    assert "@media (prefers-color-scheme: dark)" in css
    assert "content: attr(data-label)" in css
    assert css.index("table.cards thead { display: none; }") < css.index("@media (min-width")


def test_returns_page_shows_the_monthly_figures(migrated_db: Path, tmp_path: Path) -> None:
    scenario.seed(migrated_db)
    expected = scenario.report(migrated_db, "monthly", SUNDAY)
    figure = expected.summary.money_weighted

    page = _client(migrated_db, tmp_path).get("/gercek/getiri", headers=ME).text

    assert figure is not None
    assert figure.status == "ok"
    assert figure.rate is not None
    assert percent(figure.rate) in page


@pytest.mark.parametrize(
    ("path", "kind"),
    [("/gercek/raporlar/haftalik", "weekly"), ("/gercek/raporlar/aylik", "monthly")],
)
def test_report_pages_show_the_text_sent_to_telegram(
    migrated_db: Path, tmp_path: Path, path: str, kind: str
) -> None:
    scenario.seed(migrated_db)
    text = bootstrap.report_renderer("text").report(
        scenario.report(migrated_db, kind, SUNDAY)  # type: ignore[arg-type]
    )

    page = _client(migrated_db, tmp_path).get(path, headers=ME).text

    for line in text.splitlines()[:4]:
        assert line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") in page


def test_payday_page_shows_the_last_payday_plan(migrated_db: Path, tmp_path: Path) -> None:
    scenario.seed(migrated_db)

    page = _client(migrated_db, tmp_path).get("/gercek/raporlar/maas-gunu", headers=ME).text

    assert "Maaş günü (2026-11-15)" in page


def test_alerts_page_shows_open_alerts_and_the_quiet_period_end(
    migrated_db: Path, tmp_path: Path
) -> None:
    scenario.seed(migrated_db, alarm=True)

    page = _client(migrated_db, tmp_path).get("/gercek/alarmlar", headers=ME).text

    assert "Sessiz dönem" in page
    assert "tarihinde bitti" in page
    assert "Açık alarm yok." not in page


def test_transactions_are_listed_with_voids_and_notes_are_escaped(
    migrated_db: Path, tmp_path: Path
) -> None:
    scenario.seed(migrated_db)
    with SqliteUnitOfWork(migrated_db) as uow:
        tx = Transaction("XHT", date(2026, 11, 26), Side.BUY, scenario.D(1), scenario.D(11))
        txn_id = add_transaction(uow, tx, ref=None, note="<script>x</script>", now=scenario.NOW)
        void_transaction(uow, txn_id, reason="yanlış <b>gün</b>", now=scenario.NOW)

    page = _client(migrated_db, tmp_path).get("/gercek/islemler", headers=ME).text

    assert "<script>" not in page
    assert "&lt;script&gt;x&lt;/script&gt;" in page
    assert "İptal: yanlış &lt;b&gt;gün&lt;/b&gt;" in page
    assert 'class="voided"' in page


def test_system_page_shows_checks_and_runs_but_no_secret(migrated_db: Path, tmp_path: Path) -> None:
    scenario.seed(migrated_db)
    secret = "123456:gizli-bot-anahtari"  # noqa: S105 - sahte test değeri

    page = (
        _client(migrated_db, tmp_path, telegram_bot_token=secret, telegram_chat_id="42")
        .get("/gercek/sistem", headers=ME)
        .text
    )

    assert "Telegram" in page
    assert "Veritabanı şeması" in page
    assert "gizli-bot-anahtari" not in page
    assert "Son 7 günün işleri" in page
