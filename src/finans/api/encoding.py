"""Yanıt JSON'u: Decimal K-52'deki kanonik metin olarak yazılır, rapor kontratı dahil (K-138).

Pydantic'in JSON kipi Decimal'i `str()` ile yazar; `0E-10` gibi üstel gösterim istemciye giderdi.
FastAPI bir `Response` döndüren ucu yeniden serileştirmez, bu yüzden Decimal taşıyan uçlar
`CanonicalJSONResponse` döndürür; `response_model` yalnız şema içindir."""

import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel
from starlette.responses import JSONResponse

from finans.api.models import ErrorBody
from finans.domain.numeric import canonical_text


def plain(value: object) -> object:
    if isinstance(value, BaseModel):
        return plain(value.model_dump(mode="python"))
    if isinstance(value, Decimal):
        return canonical_text(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if value is None or isinstance(value, str | int):
        return value
    if isinstance(value, Mapping):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return [plain(item) for item in value]
    raise TypeError(f"JSON'a yazılamayan tip: {type(value).__name__}")


class CanonicalJSONResponse(JSONResponse):
    """JSONResponse'tan türer, çünkü FastAPI yanıt modelinin şemasını yalnız ona yazar."""

    def render(self, content: object) -> bytes:
        text = json.dumps(
            plain(content), ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
        return text.encode()


def error_response(
    status: int,
    message: str,
    fields: Mapping[str, str] | None = None,
    headers: Mapping[str, str] | None = None,
) -> CanonicalJSONResponse:
    body = ErrorBody(error=message, fields=dict(fields or {}))
    return CanonicalJSONResponse(body, status_code=status, headers=headers)
