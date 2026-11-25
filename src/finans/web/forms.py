"""POST formu: aynı köken, oturuma bağlı CSRF belirteci, her alan tek değer (K-105, K-123)."""

from typing import Final
from urllib.parse import parse_qs

from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from finans.web.security import same_origin
from finans.web.session import CSRF_FIELD, valid_csrf

REFUSED: Final = "İstek reddedildi."
UNREADABLE: Final = "Form okunamadı."
MAX_FIELDS: Final = 24


async def read_form(
    request: Request, *, origin: str, key: bytes, max_fields: int = MAX_FIELDS
) -> dict[str, str] | Response:
    """Belirteç denetlenip çıkarılmış alanlar ya da ret yanıtı."""
    if not same_origin(request.headers, origin):
        return PlainTextResponse(REFUSED, status_code=403)
    try:
        parsed = parse_qs(
            (await request.body()).decode("ascii"),
            keep_blank_values=True,
            max_num_fields=max_fields,
        )
    except ValueError:
        return PlainTextResponse(UNREADABLE, status_code=400)
    tokens = parsed.pop(CSRF_FIELD, [])
    if len(tokens) != 1 or not valid_csrf(key, request.state.session, tokens[0]):
        return PlainTextResponse(REFUSED, status_code=403)
    if any(len(values) != 1 for values in parsed.values()):
        return PlainTextResponse(UNREADABLE, status_code=400)
    return {name: values[0] for name, values in parsed.items()}
