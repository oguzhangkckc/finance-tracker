"""finans-web uygulaması; iki profil tek serviste, tek yazma fiyat güncelleme isteğidir
(K-101…K-106, K-122, K-125)."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Final
from urllib.parse import parse_qs

from jinja2 import Environment, PackageLoader, StrictUndefined
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.routing import BaseRoute, Route
from starlette.templating import Jinja2Templates

from finans import bootstrap
from finans.application.report import ReportKind
from finans.contracts.display import class_label, exact, money, percent, points
from finans.contracts.report import SANAL_NOTICE
from finans.ports.clock import BUSINESS_TZ, Clock
from finans.settings import PROFILES, Profile, Settings, profile_settings
from finans.web.assets import Assets
from finans.web.icons import icon
from finans.web.security import (
    BodyLimitMiddleware,
    IdentityMiddleware,
    SecurityHeadersMiddleware,
    same_origin,
)
from finans.web.session import CSRF_FIELD, SessionMiddleware, csrf_token, valid_csrf
from finans.web.svg import allocation_bar
from finans.web.views import (
    PAGE_ERRORS,
    PageError,
    ask_for_refresh,
    class_names,
    general_staleness,
    load_report,
    payday_text,
    quiet_ended_on,
    refresh_view,
    report_text,
    stale_by_instrument,
    system_view,
    transactions,
)

NAV: Final = (
    ("/", "Özet", "ozet"),
    ("/varliklar", "Varlıklar", "varliklar"),
    ("/islemler", "İşlemler", "islemler"),
    ("/dagilim", "Dağılım", "dagilim"),
    ("/getiri", "Getiri", "getiri"),
    ("/raporlar", "Raporlar", "raporlar"),
    ("/alarmlar", "Alarmlar", "alarmlar"),
    ("/sistem", "Sistem", "sistem"),
)
# Telefonda alt sekmeler; geri kalanlar "Daha fazla" sayfasında (K-128).
TABS: Final = (*NAV[:3], NAV[5], ("/daha", "Daha fazla", "daha"))
MORE: Final = tuple(item for item in NAV if item not in TABS)
STATIC: Final = Path(__file__).parent / "static"
SLUGS: Final[dict[Profile, str]] = {"real": "gercek", "sanal": "sanal"}
PROFILE_LABELS: Final[dict[Profile, str]] = {"real": "Gerçek", "sanal": "Sanal"}
MIN_SESSION_KEY: Final = 32
REFUSED: Final = "İstek reddedildi."
# Yönlendirmede yalnız sabit bir anahtar taşınır; metin sayfaya istekten yansımaz.
NOTICES: Final = {
    "alindi": (
        "Güncelleme isteği alındı; fiyat işi birkaç dakika içinde çalışır. "
        "Bugünün fiyatları zaten tamamsa TEFAS'a istek atılmaz."
    ),
}


class WebSetupError(Exception):
    pass


def _local(moment: datetime) -> str:
    """Saatler her zaman İstanbul'a göre (K-99)."""
    return f"{moment.astimezone(BUSINESS_TZ):%Y-%m-%d %H:%M}"


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
    env.filters.update(money=money, percent=percent, points=points, exact=exact, local=_local)
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
    assets = Assets(STATIC)
    templates = Jinja2Templates(env=_environment())
    templates.env.globals["asset"] = assets.url

    def profile_routes(profile: Profile, conf: Settings) -> list[BaseRoute]:
        prefix = f"/{SLUGS[profile]}"

        def page(
            request: Request, name: str, context: dict[str, object], *, status: int = 200
        ) -> Response:
            subpath = request.url.path.removeprefix(prefix) or "/"
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
                    "notice": NOTICES.get(request.query_params.get("istek", "")),
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

        def report_context(kind: ReportKind) -> dict[str, object]:
            report = load_report(conf, time, kind=kind)
            labels = class_names(conf)
            return {
                "report": report,
                "stale": stale_by_instrument(report),
                "stale_all": general_staleness(report),
                "cls": lambda code: class_label(code, labels),
            }

        def text(title: str, load: Callable[[], str]) -> Callable[[], dict[str, object]]:
            return lambda: {"title": title, "text": load()}

        pages: list[tuple[str, str, Callable[[], dict[str, object]]]] = [
            (
                "/",
                "ozet.html",
                lambda: {**report_context("weekly"), "refresh": refresh_view(conf, time)},
            ),
            # Lotlar ve para ağırlıklı getiri yalnızca aylık raporda.
            ("/varliklar", "varliklar.html", lambda: report_context("monthly")),
            ("/dagilim", "dagilim.html", lambda: report_context("weekly")),
            ("/getiri", "getiri.html", lambda: report_context("monthly")),
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
            (
                "/alarmlar",
                "alarmlar.html",
                lambda: {**report_context("weekly"), "quiet_ended": quiet_ended_on(conf)},
            ),
            ("/islemler", "islemler.html", lambda: {"transactions": transactions(conf)}),
            ("/sistem", "sistem.html", lambda: {"system": system_view(conf, time)}),
            ("/daha", "daha.html", lambda: {}),
        ]

        async def refresh(request: Request) -> Response:
            if not same_origin(request.headers, origin):
                return PlainTextResponse(REFUSED, status_code=403)
            try:
                form = parse_qs((await request.body()).decode("ascii"), max_num_fields=4)
            except ValueError:
                return PlainTextResponse("Form okunamadı.", status_code=400)
            tokens = form.get(CSRF_FIELD, [])
            if len(tokens) != 1 or not valid_csrf(key, request.state.session, tokens[0]):
                return PlainTextResponse(REFUSED, status_code=403)
            try:
                status = await run_in_threadpool(ask_for_refresh, conf, time)
            except (PageError, *PAGE_ERRORS) as exc:
                return page(request, "hata.html", {"message": str(exc)}, status=503)
            except OSError:
                message = "Güncelleme isteği yazılamadı; Sistem sayfasına bakın."
                return page(request, "hata.html", {"message": message}, status=503)
            target = f"{prefix}/?istek=alindi" if status.decision.allowed else f"{prefix}/"
            return RedirectResponse(target, status_code=303)

        return [
            *(
                Route(f"{prefix}{path}", view(name, load), methods=["GET"])
                for path, name, load in pages
            ),
            Route(f"{prefix}/fiyat-guncelle", refresh, methods=["POST"]),
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
                for route in profile_routes(profile, conf)
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
