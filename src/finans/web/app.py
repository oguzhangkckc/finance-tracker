"""finans-web uygulaması; sayfalar salt okunur, kimlik ve başlıklar middleware'de (K-101…K-106)."""

from collections.abc import Callable

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
from finans.contracts.report import SANAL_NOTICE, Report
from finans.ports.clock import Clock
from finans.settings import Settings
from finans.web.security import BodyLimitMiddleware, IdentityMiddleware, SecurityHeadersMiddleware
from finans.web.views import (
    PAGE_ERRORS,
    PageError,
    general_staleness,
    load_report,
    stale_by_instrument,
)

NAV = (("/", "Özet"), ("/varliklar", "Varlıklar"), ("/dagilim", "Dağılım"))


class WebSetupError(Exception):
    pass


def _environment() -> Environment:
    env = Environment(
        loader=PackageLoader("finans.web", "templates"),
        autoescape=True,
        undefined=StrictUndefined,
    )
    env.filters.update(money=money, percent=percent, points=points, exact=exact)
    return env


def create_app(settings: Settings, *, clock: Clock | None = None) -> Starlette:
    if not settings.web_allowed_login or not settings.web_origin:
        raise WebSetupError(
            "FT_WEB_ALLOWED_LOGIN ve FT_WEB_ORIGIN tanımlı olmalı; web arayüzü başlamaz (K-123)."
        )
    time = clock or bootstrap.system_clock()
    templates = Jinja2Templates(env=_environment())

    def page(request: Request, name: str, status: int = 200, **context: object) -> Response:
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
    def report_page(name: str, kind: ReportKind = "weekly") -> Callable[[Request], Response]:
        def handler(request: Request) -> Response:
            try:
                report: Report = load_report(settings, time, kind=kind)
            except (PageError, *PAGE_ERRORS) as exc:
                return page(request, "hata.html", 503, message=str(exc))
            return page(
                request,
                name,
                report=report,
                stale=stale_by_instrument(report),
                stale_all=general_staleness(report),
            )

        return handler

    def summary(request: Request) -> Response:
        return report_page("ozet.html")(request)

    def holdings(request: Request) -> Response:
        # Lotlar yalnızca aylık raporda.
        return report_page("varliklar.html", "monthly")(request)

    def allocation(request: Request) -> Response:
        return report_page("dagilim.html")(request)

    return Starlette(
        routes=[
            Route("/", summary, methods=["GET"]),
            Route("/varliklar", holdings, methods=["GET"]),
            Route("/dagilim", allocation, methods=["GET"]),
            Mount("/static", StaticFiles(packages=[("finans.web", "static")]), name="static"),
        ],
        middleware=[
            Middleware(SecurityHeadersMiddleware),
            Middleware(IdentityMiddleware, allowed_login=settings.web_allowed_login),
            Middleware(BodyLimitMiddleware),
        ],
    )
