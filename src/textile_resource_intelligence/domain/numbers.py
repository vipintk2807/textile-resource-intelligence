"""Strict, lossless numeric parsing and the shared Decimal arithmetic context."""

from __future__ import annotations

import math
import re
from decimal import Context, Decimal, InvalidOperation

from .errors import QuantityError

# Technical (not domain) limits so that stored values stay representable.
MAX_ADJUSTED_EXPONENT = 17  # accepted values are below 1e18 in magnitude
MAX_DECIMAL_PLACES = 12

# All domain arithmetic uses this context so sums are not silently rounded to the
# default 28 significant digits.
CTX = Context(prec=50)

_PLAIN_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")

_INVALID = "Enter a valid numeric quantity (digits with an optional decimal point, e.g. 1200.5)."
_NOT_FINITE = "must be a finite number (not NaN or infinity)."


def parse_decimal(value: object, *, label: str = "Quantity", enforce_limits: bool = True) -> Decimal:
    """Convert ``value`` to a finite Decimal or raise :class:`QuantityError`.

    Strings are parsed exactly (no float round trip). Thousands separators,
    underscores, NaN and infinity are rejected rather than guessed at.

    ``enforce_limits`` applies the storage limits (magnitude and decimal places) that
    guard *user input*. Calculation code passes ``False`` because derived values such
    as ratios legitimately have many decimal places.
    """
    if value is None:
        raise QuantityError(f"{label} is required.")
    if isinstance(value, bool):
        raise QuantityError(_INVALID)
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise QuantityError(f"{label} {_NOT_FINITE}")
        number = Decimal(repr(value))
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise QuantityError(f"{label} is required.")
        if "," in text:
            raise QuantityError(
                "Remove thousands separators and use a point for decimals "
                "(write 1200.5, not 1,200.5)."
            )
        if not _PLAIN_NUMBER.match(text):
            if text.lower().lstrip("+-") in {"nan", "inf", "infinity"}:
                raise QuantityError(f"{label} {_NOT_FINITE}")
            raise QuantityError(_INVALID)
        try:
            number = Decimal(text)
        except InvalidOperation as exc:  # pragma: no cover - the regex screens input
            raise QuantityError(_INVALID) from exc
    else:
        raise QuantityError(_INVALID)

    if not number.is_finite():
        raise QuantityError(f"{label} {_NOT_FINITE}")
    if number.is_zero():
        return Decimal(0)
    if not enforce_limits:
        return number
    if number.adjusted() > MAX_ADJUSTED_EXPONENT:
        raise QuantityError(f"{label} is too large to be stored reliably (limit: below 1e18).")
    if number.normalize().as_tuple().exponent < -MAX_DECIMAL_PLACES:  # type: ignore[operator]
        raise QuantityError(f"{label} has more than {MAX_DECIMAL_PLACES} decimal places.")
    return number


def decimal_to_text(value: Decimal) -> str:
    """Canonical plain-text form used for storage and export (never scientific)."""
    return format(value, "f")
