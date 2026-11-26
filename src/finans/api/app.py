"""finans-api uygulaması (K-136…K-138)."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Final

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from finans import bootstrap
from finans.api.auth import AccessVerifier, KeyCache
from finans.api.context import ApiContext
from finans.api.encoding import CanonicalJSONResponse
from finans.api.errors import install_error_handlers
from finans.api.middleware import BodyLimit, RequireAccess, RequireSameOrigin, SecurityHeaders
from finans.api.routes import ayar, islem, okuma, ortak
from finans.ports.access import AccessKeySource
from finans.ports.clock import Clock
from finans.settings import ApiSettings, Settings, profile_settings

TITLE: Final = "finans-api"
SCHEMA_VERSION: Final = "1"
type Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def _application(lifespan: Lifespan | None = None) -> FastAPI:
    # Şema repodadır ve tiplerin kaynağıdır (K-138); çalışan serviste şema ve belge sayfası yok.
    app = FastAPI(
        title=TITLE,
        version=SCHEMA_VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        default_response_class=CanonicalJSONResponse,
        lifespan=lifespan,
    )
    app.include_router(ortak.public)
    app.include_router(ortak.router)
    app.include_router(okuma.router)
    app.include_router(islem.router)
    app.include_router(ayar.router)
    install_error_handlers(app)
    return app


def openapi_document() -> dict[str, Any]:
    return _application().openapi()


def create_app(
    settings: Settings,
    api: ApiSettings,
    *,
    keys: AccessKeySource | None = None,
    clock: Clock | None = None,
) -> FastAPI:
    """`settings` profili çözülmemiş ayarlardır. Kurulum ağa çıkmaz; anahtarlar açılışta çekilir."""
    time = clock or bootstrap.system_clock()
    cache = KeyCache(keys or bootstrap.access_keys(api), time)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await run_in_threadpool(cache.prefetch)
        yield

    app = _application(lifespan)
    app.state.context = ApiContext(settings, api, time, profile_settings(settings))
    # Son eklenen en dışta çalışır.
    app.add_middleware(RequireSameOrigin, origin=api.origin)
    app.add_middleware(BodyLimit)
    app.add_middleware(RequireAccess, verifier=AccessVerifier(api, cache, time))
    app.add_middleware(SecurityHeaders)
    return app
