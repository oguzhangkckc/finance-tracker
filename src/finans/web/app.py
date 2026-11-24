"""finans-web uygulaması; sayfalar salt okunur, kimlik ve başlıklar middleware'de (K-101…K-106)."""

from jinja2 import Environment, PackageLoader, StrictUndefined
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from finans.contracts.report import SANAL_NOTICE
from finans.settings import Settings
from finans.web.security import BodyLimitMiddleware, IdentityMiddleware, SecurityHeadersMiddleware


class WebSetupError(Exception):
    pass


def create_app(settings: Settings) -> Starlette:
    if not settings.web_allowed_login or not settings.web_origin:
        raise WebSetupError(
            "FT_WEB_ALLOWED_LOGIN ve FT_WEB_ORIGIN tanımlı olmalı; web arayüzü başlamaz (K-123)."
        )
    templates = Jinja2Templates(
        env=Environment(
            loader=PackageLoader("finans.web", "templates"),
            autoescape=True,
            undefined=StrictUndefined,
        )
    )

    def page(request: Request, name: str, **context: object) -> Response:
        return templates.TemplateResponse(
            request,
            name,
            {
                "profile": settings.profile,
                "sanal_notice": SANAL_NOTICE,
                "viewer": request.state.display_name or settings.web_allowed_login,
                **context,
            },
        )

    async def summary(request: Request) -> Response:
        return page(request, "ozet.html")

    return Starlette(
        routes=[
            Route("/", summary, methods=["GET"]),
            Mount("/static", StaticFiles(packages=[("finans.web", "static")]), name="static"),
        ],
        middleware=[
            Middleware(SecurityHeadersMiddleware),
            Middleware(IdentityMiddleware, allowed_login=settings.web_allowed_login),
            Middleware(BodyLimitMiddleware),
        ],
    )
