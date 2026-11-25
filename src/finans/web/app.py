"""finans-web uygulaması; iki profil tek serviste (K-101…K-106, K-122, K-125, K-126)."""

import re
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from jinja2 import Environment, PackageLoader, StrictUndefined
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import BaseRoute, Route
from starlette.templating import Jinja2Templates

from finans import bootstrap
from finans.application.password import well_formed
from finans.application.report import ReportKind
from finans.contracts.display import (
    Case,
    class_label,
    day_label,
    exact,
    gap_text,
    money,
    month_label,
    percent,
    points,
    same_places,
)
from finans.contracts.report import SANAL_NOTICE, Report
from finans.ports.clock import BUSINESS_TZ, Clock
from finans.settings import PROFILES, Profile, Settings, profile_settings
from finans.web.assets import Assets
from finans.web.forms import read_form
from finans.web.icons import icon
from finans.web.lock import Attempt, WriteLock
from finans.web.security import BodyLimitMiddleware, IdentityMiddleware, SecurityHeadersMiddleware
from finans.web.session import SessionMiddleware, csrf_token
from finans.web.setting_routes import setting_routes
from finans.web.svg import allocation_bar, contribution_chart, value_chart
from finans.web.table import table
from finans.web.tables import (
    ALERT_EVENTS,
    HOLDINGS,
    LOTS,
    PAGE_PARAMS,
    RUN_STATUS,
    RUNS,
    TRANSACTIONS,
)
from finans.web.trade_routes import WriteContext, write_routes
from finans.web.views import (
    PAGE_ERRORS,
    PageError,
    alert_event_rows,
    ask_for_refresh,
    class_names,
    contribution_view,
    general_staleness,
    holding_rows,
    load_report,
    lot_rows,
    payday_text,
    quiet_ended_on,
    refresh_view,
    report_text,
    stale_by_instrument,
    system_view,
    transaction_rows,
    value_chart_view,
)

NAV: Final = (
    ("/", "Özet", "ozet"),
    ("/varliklar", "Varlıklar", "varliklar"),
    ("/islemler", "İşlemler", "islemler"),
    ("/dagilim", "Dağılım", "dagilim"),
    ("/getiri", "Getiri", "getiri"),
    ("/raporlar", "Raporlar", "raporlar"),
    ("/alarmlar", "Alarmlar", "alarmlar"),
    ("/ayarlar", "Ayarlar", "ayarlar"),
    ("/sistem", "Sistem", "sistem"),
)
# Telefonda alt sekmeler; geri kalanlar "Daha fazla" sayfasında (K-128).
TABS: Final = (*NAV[:3], NAV[5], ("/daha", "Daha fazla", "daha"))
MORE: Final = tuple(item for item in NAV if item not in TABS)
STATIC: Final = Path(__file__).parent / "static"
SLUGS: Final[dict[Profile, str]] = {"real": "gercek", "sanal": "sanal"}
PROFILE_LABELS: Final[dict[Profile, str]] = {"real": "Gerçek", "sanal": "Sanal"}
MIN_SESSION_KEY: Final = 32
# Kilitten sonra yalnız bu uygulamanın bir sayfasına dönülür; sorgu ve `..` taşınmaz.
NEXT_PAGE: Final = re.compile(rf"/(?:{'|'.join(SLUGS.values())})(?:/[a-z0-9-]+)*/?")
ATTEMPT_STATUS: Final = {"wrong": 403, "locked": 429, "disabled": 403}
# Yönlendirmede yalnız sabit bir anahtar taşınır; metin sayfaya istekten yansımaz.
NOTICES: Final = {
    "alindi": (
        "Güncelleme isteği alındı; fiyat işi birkaç dakika içinde çalışır. "
        "Bugünün fiyatları zaten tamamsa TEFAS'a istek atılmaz."
    ),
}
SAVED: Final = {
    "alis": "Alım #{no} kaydedildi.",
    "satis": "Satış #{no} kaydedildi.",
    "iptal": "#{no} numaralı işlem iptal edildi.",
    "maas-gunu": "Maaş günü planı uygulandı: {no} sanal alım.",
    "ayar": "Ayar sürümü #{no} kaydedildi.",
    "ayar-vazgec": "Ayar sürümü #{no} için vazgeçildi.",
}


class WebSetupError(Exception):
    pass


def _notice(params: Mapping[str, str]) -> str | None:
    """Kayıttan sonra işlem numarası yalnız rakamsa gösterilir; başka metin sayfaya yansımaz."""
    if (text := NOTICES.get(params.get("istek", ""))) is not None:
        return text
    number = params.get("no", "")
    template = SAVED.get(params.get("islem", ""))
    if template is None or not (number.isascii() and number.isdigit() and len(number) <= 9):
        return None
    return template.format(no=int(number))


def _entered(value: Decimal) -> str:
    """Girilen basamaklarla; dekonttaki fiyat önizlemede aynen görünsün (K-64)."""
    return f"{value:f}".replace(".", ",")


def _is_current(href: str, subpath: str) -> bool:
    """Alt sayfa (ör. /raporlar/aylik) üst menü öğesini de seçili yapar."""
    return href == subpath or (href != "/" and subpath.startswith(f"{href}/"))


def _is_tab_current(href: str, subpath: str) -> bool:
    if href == "/daha":
        return subpath == "/daha" or any(_is_current(other, subpath) for other, *_ in MORE)
    return _is_current(href, subpath)


def _environment() -> Environment:
    env = Environment(
        loader=PackageLoader("finans.web", "templates"),
        autoescape=True,
        undefined=StrictUndefined,
    )
    env.filters.update(
        money=money,
        percent=percent,
        points=points,
        exact=exact,
        entered=_entered,
        ay=month_label,
        sapma=gap_text,
    )
    env.globals.update(
        icon=icon,
        allocation_bar=allocation_bar,
        is_current=_is_current,
        is_tab_current=_is_tab_current,
        more=MORE,
        tabs=TABS,
    )
    return env


def create_app(settings: Settings, *, clock: Clock | None = None) -> Starlette:
    """`settings` profili çözülmemiş ayarlardır; `settings.profile` açılış profilidir (K-125)."""
    if not settings.web_allowed_login or not settings.web_origin:
        raise WebSetupError(
            "FT_WEB_ALLOWED_LOGIN ve FT_WEB_ORIGIN tanımlı olmalı; web arayüzü başlamaz (K-123)."
        )
    secret = settings.web_session_key
    key = secret.get_secret_value().encode() if secret is not None else b""
    if len(key) < MIN_SESSION_KEY:
        raise WebSetupError(
            f"ft_web_session_key tanımlı ve en az {MIN_SESSION_KEY} karakter olmalı; "
            "web arayüzü başlamaz (K-123)."
        )
    origin = settings.web_origin.rstrip("/")
    viewer_login = settings.web_allowed_login
    time = clock or bootstrap.system_clock()
    password = settings.web_password
    stored = password.get_secret_value().strip() if password is not None else None
    if stored is not None and not well_formed(stored):
        raise WebSetupError(
            "ft_web_password bir şifre özeti değil; `ft web sifre` ile üretin. "
            "Yazmayı kapatmak için dosya boş bırakılır (K-126)."
        )
    lock = WriteLock(stored, time)
    assets = Assets(STATIC)
    templates = Jinja2Templates(env=_environment())
    templates.env.globals.update(
        asset=assets.url,
        same_places=same_places,
        value_chart=value_chart,
        contribution_chart=contribution_chart,
    )

    def day(value: date | str, case: Case = "", year: bool | None = None) -> str:
        """Bugünün yılı uygulamanın saatinden; saatler her zaman İstanbul'a göre (K-99).
        Adres parametresindeki ISO gün de kabul edilir (ör. filtre etiketleri)."""
        shown = date.fromisoformat(value) if isinstance(value, str) else value
        return day_label(shown, today=time.today(), case=case, year=year)

    def local(moment: datetime) -> str:
        here = moment.astimezone(BUSINESS_TZ)
        return f"{day(here.date())} {here:%H:%M}"

    def local_day(moment: datetime) -> str:
        return day(moment.astimezone(BUSINESS_TZ).date())

    templates.env.filters.update(gun=day, local=local, local_gun=local_day)

    def profile_routes(profile: Profile, conf: Settings, sanal: Settings) -> list[BaseRoute]:
        prefix = f"/{SLUGS[profile]}"

        def page(
            request: Request, name: str, context: dict[str, object], *, status: int = 200
        ) -> Response:
            subpath = request.url.path.removeprefix(prefix) or "/"
            here = request.url.path if NEXT_PAGE.fullmatch(request.url.path) else f"{prefix}/"
            switch = [
                (PROFILE_LABELS[other], f"/{SLUGS[other]}{subpath}", other == profile)
                for other in PROFILES
            ]
            return templates.TemplateResponse(
                request,
                name,
                {
                    "profile": profile,
                    "profile_label": PROFILE_LABELS[profile],
                    "prefix": prefix,
                    "subpath": subpath,
                    "switch": switch,
                    "sanal_notice": SANAL_NOTICE,
                    "viewer": request.state.display_name or viewer_login,
                    "nav": NAV,
                    "csrf": csrf_token(key, request.state.session),
                    "lock": lock.state(request.state.session),
                    "lock_href": f"{prefix}/kilit?sonra={here}",
                    "notice": _notice(request.query_params),
                    **context,
                },
                status_code=status,
            )

        # Senkron uç noktalar iş parçacığı havuzunda çalışır; DB okuması döngüyü bekletmez.
        def view(name: str, load: Callable[[], dict[str, object]]) -> Callable[[Request], Response]:
            def handler(request: Request) -> Response:
                try:
                    context = load()
                except (PageError, *PAGE_ERRORS) as exc:
                    return page(request, "hata.html", {"message": str(exc)}, status=503)
                return page(request, name, context)

            return handler

        def report_parts(kind: ReportKind) -> tuple[Report, Mapping[str, str], dict[str, object]]:
            report = load_report(conf, time, kind=kind)
            labels = class_names(conf)
            context: dict[str, object] = {
                "report": report,
                "stale": stale_by_instrument(report),
                "stale_all": general_staleness(report),
                "cls": lambda code: class_label(code, labels),
            }
            return report, labels, context

        def report_context(kind: ReportKind) -> dict[str, object]:
            return report_parts(kind)[2]

        def listing(
            name: str, load: Callable[[], tuple[Sequence[Any], dict[str, object]]], spec: Any
        ) -> Callable[[Request], Response]:
            """Tablolu sayfa: satırlar adres parametreleriyle süzülür ve sıralanır (K-129)."""

            def handler(request: Request) -> Response:
                try:
                    rows, context = load()
                except (PageError, *PAGE_ERRORS) as exc:
                    return page(request, "hata.html", {"message": str(exc)}, status=503)
                view = table(rows, request.query_params, spec, passthrough=PAGE_PARAMS)
                return page(request, name, {**context, "table": view})

            return handler

        def holdings() -> tuple[Sequence[Any], dict[str, object]]:
            # Lotlar ve para ağırlıklı getiri yalnızca aylık raporda.
            report, labels, context = report_parts("monthly")
            return holding_rows(report, labels), context

        def lots() -> tuple[Sequence[Any], dict[str, object]]:
            report, _, context = report_parts("monthly")
            return lot_rows(report), context

        def alert_history() -> tuple[Sequence[Any], dict[str, object]]:
            context = {**report_context("weekly"), "quiet_ended": quiet_ended_on(conf)}
            return alert_event_rows(conf), context

        def system() -> tuple[Sequence[Any], dict[str, object]]:
            view = system_view(conf, time)
            return view.runs, {"system": view, "run_status": RUN_STATUS}

        def text(title: str, load: Callable[[], str]) -> Callable[[], dict[str, object]]:
            return lambda: {"title": title, "text": load()}

        pages: list[tuple[str, str, Callable[[], dict[str, object]]]] = [
            (
                "/",
                "ozet.html",
                lambda: {
                    **report_context("weekly"),
                    "refresh": refresh_view(conf, time),
                    "chart": value_chart_view(conf, time),
                },
            ),
            ("/dagilim", "dagilim.html", lambda: report_context("weekly")),
            (
                "/getiri",
                "getiri.html",
                lambda: {
                    **report_context("monthly"),
                    "chart": value_chart_view(conf, time),
                    "contributions": contribution_view(conf, time),
                },
            ),
            ("/raporlar", "raporlar.html", lambda: {}),
            (
                "/raporlar/haftalik",
                "rapor.html",
                text("Haftalık rapor", lambda: report_text(conf, time, "weekly")),
            ),
            (
                "/raporlar/aylik",
                "rapor.html",
                text("Aylık rapor", lambda: report_text(conf, time, "monthly")),
            ),
            (
                "/raporlar/maas-gunu",
                "rapor.html",
                text("Maaş günü", lambda: payday_text(conf, time)),
            ),
            ("/daha", "daha.html", lambda: {}),
        ]

        async def refresh(request: Request) -> Response:
            form = await read_form(request, origin=origin, key=key, max_fields=4)
            if isinstance(form, Response):
                return form
            try:
                status = await run_in_threadpool(ask_for_refresh, conf, time)
            except (PageError, *PAGE_ERRORS) as exc:
                return page(request, "hata.html", {"message": str(exc)}, status=503)
            except OSError:
                message = "Güncelleme isteği yazılamadı; Sistem sayfasına bakın."
                return page(request, "hata.html", {"message": message}, status=503)
            target = f"{prefix}/?istek=alindi" if status.decision.allowed else f"{prefix}/"
            return RedirectResponse(target, status_code=303)

        def transactions_page(request: Request) -> Response:
            try:
                rows = transaction_rows(conf)
            except (PageError, *PAGE_ERRORS) as exc:
                return page(request, "hata.html", {"message": str(exc)}, status=503)
            view = table(rows, request.query_params, TRANSACTIONS, passthrough=PAGE_PARAMS)
            return page(request, "islemler.html", {"table": view})

        def next_page(raw: str | None) -> str:
            return raw if raw and NEXT_PAGE.fullmatch(raw) else f"{prefix}/"

        def unlock_page(
            request: Request, back: str, attempt: Attempt | None = None, *, status: int = 200
        ) -> Response:
            lockout = attempt.until if attempt is not None else lock.lockout_until()
            context: dict[str, object] = {"next": back, "attempt": attempt, "lockout": lockout}
            return page(request, "kilit.html", context, status=status)

        def unlock_form(request: Request) -> Response:
            return unlock_page(request, next_page(request.query_params.get("sonra")))

        async def unlock(request: Request) -> Response:
            form = await read_form(request, origin=origin, key=key, max_fields=4)
            if isinstance(form, Response):
                return form
            back = next_page(form.get("sonra"))
            # scrypt yavaş; olay döngüsünü bekletmesin.
            password = form.get("sifre", "")
            attempt = await run_in_threadpool(lock.try_unlock, request.state.session, password)
            if attempt.status == "ok":
                return RedirectResponse(back, status_code=303)
            return unlock_page(request, back, attempt, status=ATTEMPT_STATUS[attempt.status])

        writing = WriteContext(profile, prefix, conf, key, origin, lock, time, page, unlock_page)
        return [
            *(
                Route(f"{prefix}{path}", view(name, load), methods=["GET"])
                for path, name, load in pages
            ),
            Route(f"{prefix}/islemler", transactions_page, methods=["GET"]),
            Route(f"{prefix}/varliklar", listing("varliklar.html", holdings, HOLDINGS)),
            Route(f"{prefix}/varliklar/lotlar", listing("lotlar.html", lots, LOTS)),
            Route(f"{prefix}/alarmlar", listing("alarmlar.html", alert_history, ALERT_EVENTS)),
            Route(f"{prefix}/sistem", listing("sistem.html", system, RUNS)),
            Route(f"{prefix}/fiyat-guncelle", refresh, methods=["POST"]),
            Route(f"{prefix}/kilit", unlock_form, methods=["GET"]),
            Route(f"{prefix}/kilit", unlock, methods=["POST"]),
            *write_routes(writing),
            *setting_routes(writing, sanal=sanal),
        ]

    def home(_request: Request) -> Response:
        return RedirectResponse(f"/{SLUGS[settings.profile]}/", status_code=307)

    profiles = profile_settings(settings)
    return Starlette(
        routes=[
            Route("/", home, methods=["GET"]),
            *(
                route
                for profile, conf in profiles.items()
                for route in profile_routes(profile, conf, profiles["sanal"])
            ),
            Route("/static/{served:path}", assets.serve, methods=["GET"]),
        ],
        middleware=[
            Middleware(SecurityHeadersMiddleware),
            Middleware(IdentityMiddleware, allowed_login=viewer_login),
            Middleware(BodyLimitMiddleware),
            Middleware(SessionMiddleware, key=key),
        ],
    )
