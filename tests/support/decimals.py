from decimal import Decimal

REL_TOL = Decimal("1e-6")
ABS_TOL = Decimal("1e-8")


def is_close(
    actual: Decimal, expected: Decimal, *, rel_tol: Decimal = REL_TOL, abs_tol: Decimal = ABS_TOL
) -> bool:
    """math.isclose formülü; float'a çevirmeden."""
    return abs(actual - expected) <= max(rel_tol * max(abs(actual), abs(expected)), abs_tol)
