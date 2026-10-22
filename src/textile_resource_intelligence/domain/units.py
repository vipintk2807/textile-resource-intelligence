"""Central unit registry and explicit, dimension-checked unit conversion.

Only multiplicative conversions inside one physical dimension are supported.
Conversions that need extra information (density, fuel energy content, steam
enthalpy, fabric width ...) are rejected with an explanation instead of guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .errors import IncompatibleUnitsError, UnknownUnitError
from .numbers import CTX, parse_decimal


@dataclass(frozen=True)
class UnitDef:
    """A supported unit and its exact factor to the canonical unit of its dimension.

    ``canonical_quantity = quantity * factor_num / factor_den``.
    """

    code: str
    label: str
    dimension: str
    factor_num: Decimal
    factor_den: Decimal
    resource: bool
    production: bool


DIMENSION_LABELS = {
    "energy": "Energy",
    "volume": "Volume",
    "mass": "Mass",
    "length": "Length",
    "count": "Count",
}

# Canonical unit per dimension (calculations doc, section 5.4).
CANONICAL_UNITS = {
    "energy": "kWh",
    "volume": "L",
    "mass": "kg",
    "length": "m",
    "count": "pcs",
}


def _unit(code, label, dimension, num, den, *, resource, production) -> UnitDef:
    return UnitDef(code, label, dimension, Decimal(num), Decimal(den), resource, production)


_UNIT_LIST = (
    _unit("kWh", "kWh", "energy", 1, 1, resource=True, production=False),
    _unit("MWh", "MWh", "energy", 1000, 1, resource=True, production=False),
    # 1 kWh = 3.6 MJ  ->  1 MJ = 5/18 kWh (kept as an exact fraction)
    _unit("MJ", "MJ", "energy", 5, 18, resource=True, production=False),
    _unit("L", "L", "volume", 1, 1, resource=True, production=False),
    _unit("m3", "m³", "volume", 1000, 1, resource=True, production=False),
    _unit("kg", "kg", "mass", 1, 1, resource=True, production=True),
    _unit("g", "g", "mass", 1, 1000, resource=True, production=True),
    _unit("tonne", "tonne", "mass", 1000, 1, resource=True, production=True),
    _unit("m", "m", "length", 1, 1, resource=False, production=True),
    _unit("pcs", "pcs", "count", 1, 1, resource=False, production=True),
)

UNITS: dict[str, UnitDef] = {u.code: u for u in _UNIT_LIST}

_ALIASES = {
    "m³": "m3",
    "tonnes": "tonne",
    "t": "tonne",
    "litre": "L",
    "litres": "L",
    "liter": "L",
    "liters": "L",
    "metre": "m",
    "metres": "m",
    "meter": "m",
    "meters": "m",
    "piece": "pcs",
    "pieces": "pcs",
    "pc": "pcs",
}

_LOOKUP: dict[str, str] = {code.casefold(): code for code in UNITS}
_LOOKUP.update({alias.casefold(): code for alias, code in _ALIASES.items()})


def unit_display(code: str) -> str:
    """User-facing label for a unit code (e.g. ``m3`` -> ``m³``)."""
    unit = UNITS.get(code)
    return unit.label if unit else code


def unit_label(unit: str | None) -> str:
    """Display form of a unit or compound unit, e.g. ``m3/kg`` -> ``m³/kg``."""
    if not unit:
        return ""
    return "/".join(unit_display(part) for part in unit.split("/"))


def normalize_unit(text: object) -> str:
    """Return the canonical unit code for user text, or raise UnknownUnitError."""
    if not isinstance(text, str) or not text.strip():
        raise UnknownUnitError("Select a supported unit.")
    code = _LOOKUP.get(text.strip().casefold())
    if code is None:
        supported = ", ".join(unit_display(c) for c in UNITS)
        raise UnknownUnitError(f"Unsupported unit '{text.strip()}'. Supported units: {supported}.")
    return code


def get_unit(code: str) -> UnitDef:
    """Look up a unit definition by its (already normalised) code."""
    try:
        return UNITS[code]
    except KeyError as exc:
        raise UnknownUnitError(f"Unsupported unit '{code}'.") from exc


def dimension_of(code: str) -> str:
    """Physical dimension of a unit (energy, volume, mass, length or count)."""
    return get_unit(normalize_unit(code)).dimension


def canonical_unit_for(dimension: str) -> str:
    """Canonical unit code for a dimension."""
    return CANONICAL_UNITS[dimension]


def units_for(kind: str) -> list[str]:
    """Unit codes usable for ``"resource"`` or ``"production"`` records."""
    if kind not in {"resource", "production"}:
        raise ValueError("kind must be 'resource' or 'production'")
    return [u.code for u in _UNIT_LIST if (u.resource if kind == "resource" else u.production)]


def are_compatible(source: str, target: str) -> bool:
    """True when both units are known and share a physical dimension."""
    try:
        return dimension_of(source) == dimension_of(target)
    except UnknownUnitError:
        return False


def explain_incompatibility(source: str, target: str) -> str:
    """Explain why two known units cannot be converted."""
    src = get_unit(normalize_unit(source))
    tgt = get_unit(normalize_unit(target))
    pair = {src.dimension, tgt.dimension}
    base = (
        f"Conversion rejected: {src.label} ({src.dimension}) cannot be converted "
        f"to {tgt.label} ({tgt.dimension})."
    )
    if pair == {"mass", "volume"}:
        return base + " A density basis would be required and none is configured."
    if pair == {"volume", "energy"}:
        return base + " Converting a volume (e.g. fuel) to energy needs a fuel-specific energy basis."
    if pair == {"mass", "energy"}:
        return (
            base + " Converting mass (e.g. steam or fuel) to energy needs "
            "thermodynamic or fuel-specific information."
        )
    if pair & {"length", "count"}:
        return base + " Production units are not interchangeable without product information."
    return base


def convert_quantity(quantity: object, source_unit: str, target_unit: str) -> Decimal:
    """Convert ``quantity`` between two units of the same dimension.

    Raises UnknownUnitError for unknown units and IncompatibleUnitsError when the
    dimensions differ. The input is never modified; a new Decimal is returned.
    """
    value = parse_decimal(quantity, enforce_limits=False)
    src = get_unit(normalize_unit(source_unit))
    tgt = get_unit(normalize_unit(target_unit))
    if src.dimension != tgt.dimension:
        raise IncompatibleUnitsError(explain_incompatibility(src.code, tgt.code))
    if src.code == tgt.code:
        return value
    numerator = CTX.multiply(CTX.multiply(value, src.factor_num), tgt.factor_den)
    denominator = CTX.multiply(src.factor_den, tgt.factor_num)
    return CTX.divide(numerator, denominator)


def to_canonical(quantity: object, unit: str) -> tuple[Decimal, str]:
    """Convert to the canonical unit of the unit's dimension."""
    target = canonical_unit_for(dimension_of(unit))
    return convert_quantity(quantity, unit, target), target
