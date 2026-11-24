import re
from collections.abc import Callable
from decimal import (
    MAX_PREC,
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    FloatOperation,
    InvalidOperation,
    Overflow,
    localcontext,
)
from functools import wraps
from typing import Final

DOMAIN_CONTEXT: Final = Context(
    prec=28,
    rounding=ROUND_HALF_EVEN,
    traps=[FloatOperation, InvalidOperation, DivisionByZero, Overflow],
)


_EXACT = Context(prec=MAX_PREC)
_EXPONENT: Final = re.compile(r"[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)[eE][+-]?\d+")


def is_exponent_notation(text: str) -> bool:
    """Ondalık ayırıcı nokta da virgül de olabilir; Excel `1,23457E+11` yazar (K-115)."""
    return _EXPONENT.fullmatch(text.strip()) is not None


def canonical_text(value: Decimal) -> str:
    """Üstel gösterimsiz, sondaki sıfırları atılmış metin; -0 → 0. Yuvarlamaz."""
    if value.is_zero():
        return "0"
    return format(value.normalize(_EXACT), "f")


def in_domain_context[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        with localcontext(DOMAIN_CONTEXT):
            return fn(*args, **kwargs)

    return wrapper
