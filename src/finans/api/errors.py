"""Hata biçimi (K-138): `{"error": ileti, "fields": {alan: ileti}}`; ayrıntı yalnız günlükte."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Final

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import Response

from finans.api.encoding import error_response
from finans.api.middleware import SECURITY_HEADERS
from finans.ports.unit_of_work import StorageBusyError
from finans.sunum.views import PAGE_ERRORS, PageError

INVALID: Final = "Girdi geçersiz."
UNREADABLE: Final = "İstek gövdesi JSON olarak okunamadı."
UNEXPECTED: Final = "Beklenmeyen hata; ayrıntı sunucu günlüğünde."
BUSY: Final = (
    "Şu an zamanlanmış bir iş çalışıyor; hiçbir şey kaydedilmedi. Birkaç saniye sonra aynı isteği"
    " yeniden gönder."
)
BUSY_RETRY_SECONDS: Final = 5
HTTP_MESSAGES: Final = {404: "Bulunamadı.", 405: "Bu yöntem desteklenmiyor."}
FIELD_MESSAGES: Final = {
    "missing": "zorunlu",
    "extra_forbidden": "bilinmeyen alan",
    "string_type": "metin olmalı",
    "string_too_short": "boş olamaz",
    "string_too_long": "çok uzun",
    "int_type": "tamsayı olmalı",
    "int_parsing": "tamsayı olmalı",
    "bool_type": "doğru ya da yanlış olmalı",
    "bool_parsing": "doğru ya da yanlış olmalı",
    "literal_error": "izin verilen değerlerden biri değil",
    "model_attributes_type": "nesne olmalı",
    "dict_type": "nesne olmalı",
}
_LOCATIONS: Final = frozenset({"body", "query", "path", "header"})


class ApiError(Exception):
    """Ucun bilerek döndürdüğü hata; ileti kullanıcıya gösterilir."""

    def __init__(self, status: int, message: str, fields: Mapping[str, str] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.fields = dict(fields or {})


def install_error_handlers(app: FastAPI) -> None:
    app.exception_handler(RequestValidationError)(_invalid)
    app.exception_handler(HTTPException)(_http)
    app.exception_handler(ApiError)(_api)
    app.exception_handler(StorageBusyError)(_busy)
    app.exception_handler(Exception)(_unexpected)


def field_errors(errors: list[dict[str, object]]) -> tuple[bool, dict[str, str]]:
    """Gövde okunamadıysa ilk değer doğrudur; alan adı konum önekinden arındırılır."""
    unreadable = False
    fields: dict[str, str] = {}
    for error in errors:
        kind = str(error.get("type", ""))
        if kind == "json_invalid":
            unreadable = True
            continue
        location = error.get("loc", ())
        parts = [str(part) for part in location] if isinstance(location, tuple | list) else []
        if parts and parts[0] in _LOCATIONS:
            parts = parts[1:]
        fields.setdefault(".".join(parts) or "gövde", FIELD_MESSAGES.get(kind, "geçersiz"))
    return unreadable, fields


@contextmanager
def page_errors() -> Iterator[None]:
    """Sayfa verisi yüklenemezse (ör. hatalı portföy dosyası) 503 ve nedeni; web'deki gibi."""
    try:
        yield
    except (PageError, *PAGE_ERRORS) as exc:
        raise ApiError(503, str(exc)) from exc


async def _invalid(_request: Request, exc: RequestValidationError) -> Response:
    errors = list(exc.errors())
    # Adresin kendisi geçersizse (bilinmeyen profil ya da sayı olmayan numara) adres yoktur.
    if any(_location(error) == "path" for error in errors):
        return error_response(404, HTTP_MESSAGES[404])
    unreadable, fields = field_errors(errors)
    return error_response(422, UNREADABLE if unreadable else INVALID, fields)


def _location(error: Mapping[str, object]) -> str:
    location = error.get("loc", ())
    return str(location[0]) if isinstance(location, tuple | list) and location else ""


async def _http(_request: Request, exc: HTTPException) -> Response:
    message = HTTP_MESSAGES.get(exc.status_code, "İstek reddedildi.")
    return error_response(exc.status_code, message, headers=exc.headers)


async def _api(_request: Request, exc: ApiError) -> Response:
    return error_response(exc.status, exc.message, exc.fields)


async def _busy(_request: Request, _exc: StorageBusyError) -> Response:
    """Yazma işlemi geri alındı ve nonce harcanmadı; aynı onay yeniden gönderilebilir."""
    return error_response(503, BUSY, headers={"Retry-After": str(BUSY_RETRY_SECONDS)})


async def _unexpected(_request: Request, _exc: Exception) -> Response:
    # Bu yanıt en dıştaki katmandan gider, güvenlik başlıkları burada eklenir; hatayı sunucu
    # ayrıca günlüğe yazar.
    return error_response(500, UNEXPECTED, headers=SECURITY_HEADERS)
