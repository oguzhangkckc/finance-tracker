"""finans-web uygulaması; sayfalar salt okunur, kimlik ve başlıklar middleware'de (K-101…K-106)."""

from collections.abc import Callable
from datetime import datetime

from jinja2 import Environment, PackageLoader, StrictUndefined
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from finans import bootstrap
from finans.application.report import ReportKind
from finans.contracts.display import exact, money, percent, points
from finans.contracts.report import SANAL_NOTICE
from finans.ports.clock import BUSINESS_TZ, Clock
from finans.settings import Settings
from finans.web.security import BodyLimitMiddleware, IdentityMiddleware, SecurityHeadersMiddleware
from finans.web.views import (
    PAGE_ERRORS,
    PageError,
    general_staleness,
    load_report,
    payday_text,
    quiet_ended_on,
    report_text,
    stale_by_instrument,
    system_view,
    transactions,
)

NAV = (
    ("/", "Özet"),
    ("/varliklar", "Varlıklar"),
    ("/dagilim", "Dağılım"),
    ("/getiri", "Getiri"),
    ("/raporlar", "Raporlar"),
    ("/alarmlar", "Alarmlar"),
    ("/islemler", "İşlemler"),
    ("/sistem", "Sistem"),
)


class WebSetupError(Exception):
    pass


def _local(moment: datetime) -> str:
    """Saatler her zaman İstanbul'a göre (K-99)."""
    return f"{moment.astimezone(BUSINESS_TZ):%Y-%m-%d %H:%M}"


def _environment() -> Environment:
    env = Environment(
        loader=PackageLoader("finans.web", "templates"),
        autoescape=True,
        undefined=StrictUndefined,
    )
    env.filters.update(money=money, percent=percent, points=points, exact=exact, local=_local)
    return env


def create_app(settings: Settings, *, clock: Clock | None = None) -> Starlette:
    if not settings.web_allowed_login or not settings.web_origin:
        raise WebSetupError(
            "FT_WEB_ALLOWED_LOGIN ve FT_WEB_ORIGIN tanımlı olmalı; web arayüzü başlamaz (K-123)."
        )
    time = clock or bootstrap.system_clock()
    templates = Jinja2Templates(env=_environment())

    def page(
        request: Request, name: str, context: dict[str, object], *, status: int = 200
    ) -> Response:
        return templates.TemplateResponse(
            request,
            name,
            {
                "profile": settings.profile,
                "sanal_notice": SANAL_NOTICE,
                "viewer": request.state.display_name or settings.web_allowed_login,
                "nav": NAV,
                "path": request.url.path,
                **context,
            },
            status_code=status,
        )

    # Senkron uç noktalar Starlette'in iş parçacığı havuzunda çalışır; DB okuması döngüyü bekletmez.
    def view(name: str, load: Callable[[], dict[str, object]]) -> Callable[[Request], Response]:
        def handler(request: Request) -> Response:
            try:
                context = load()
            except (PageError, *PAGE_ERRORS) as exc:
                return page(request, "hata.html", {"message": str(exc)}, status=503)
            return page(request, name, context)

        return handler

    def report_context(kind: ReportKind) -> dict[str, object]:
        report = load_report(settings, time, kind=kind)
        return {
            "report": report,
            "stale": stale_by_instrument(report),
            "stale_all": general_staleness(report),
        }

    def text(title: str, load: Callable[[], str]) -> Callable[[], dict[str, object]]:
        return lambda: {"title": title, "text": load()}

    pages: list[tuple[str, str, Callable[[], dict[str, object]]]] = [
        ("/", "ozet.html", lambda: report_context("weekly")),
        # Lotlar ve para ağırlıklı getiri yalnızca aylık raporda.
        ("/varliklar", "varliklar.html", lambda: report_context("monthly")),
        ("/dagilim", "dagilim.html", lambda: report_context("weekly")),
        ("/getiri", "getiri.html", lambda: report_context("monthly")),
        ("/raporlar", "raporlar.html", lambda: {}),
        (
            "/raporlar/haftalik",
            "rapor.html",
            text("Haftalık rapor", lambda: report_text(settings, time, "weekly")),
        ),
        (
            "/raporlar/aylik",
            "rapor.html",
            text("Aylık rapor", lambda: report_text(settings, time, "monthly")),
        ),
        (
            "/raporlar/maas-gunu",
            "rapor.html",
            text("Maaş günü", lambda: payday_text(settings, time)),
        ),
        (
            "/alarmlar",
            "alarmlar.html",
            lambda: {**report_context("weekly"), "quiet_ended": quiet_ended_on(settings)},
        ),
        ("/islemler", "islemler.html", lambda: {"transactions": transactions(settings)}),
        ("/sistem", "sistem.html", lambda: {"system": system_view(settings, time)}),
    ]

    return Starlette(
        routes=[
            *(Route(path, view(name, load), methods=["GET"]) for path, name, load in pages),
            Mount("/static", StaticFiles(packages=[("finans.web", "static")]), name="static"),
        ],
        middleware=[
            Middleware(SecurityHeadersMiddleware),
            Middleware(IdentityMiddleware, allowed_login=settings.web_allowed_login),
            Middleware(BodyLimitMiddleware),
        ],
    )
