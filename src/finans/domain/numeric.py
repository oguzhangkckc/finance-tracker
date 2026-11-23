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
