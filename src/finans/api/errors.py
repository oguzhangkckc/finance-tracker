"""Hata biçimi (K-138): `{"error": ileti, "fields": {alan: ileti}}`; ayrıntı yalnız günlükte."""

from collections.abc import Mapping
from typing import Final

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import Response

from finans.api.encoding import error_response
from finans.api.middleware import SECURITY_HEADERS

INVALID: Final = "Girdi geçersiz."
UNREADABLE: Final = "İstek gövdesi JSON olarak okunamadı."
UNEXPECTED: Final = "Beklenmeyen hata; ayrıntı sunucu günlüğünde."
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


async def _invalid(_request: Request, exc: RequestValidationError) -> Response:
    unreadable, fields = field_errors(list(exc.errors()))
    return error_response(422, UNREADABLE if unreadable else INVALID, fields)


async def _http(_request: Request, exc: HTTPException) -> Response:
    message = HTTP_MESSAGES.get(exc.status_code, "İstek reddedildi.")
    return error_response(exc.status_code, message, headers=exc.headers)


async def _api(_request: Request, exc: ApiError) -> Response:
    return error_response(exc.status, exc.message, exc.fields)


async def _unexpected(_request: Request, _exc: Exception) -> Response:
    # Bu yanıt en dıştaki katmandan gider, güvenlik başlıkları burada eklenir; hatayı sunucu
    # ayrıca günlüğe yazar.
    return error_response(500, UNEXPECTED, headers=SECURITY_HEADERS)
