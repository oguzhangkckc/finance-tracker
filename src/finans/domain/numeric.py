from collections.abc import Callable
from decimal import (
    ROUND_HALF_EVEN,
    Context,
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


def in_domain_context[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        with localcontext(DOMAIN_CONTEXT):
            return fn(*args, **kwargs)

    return wrapper
