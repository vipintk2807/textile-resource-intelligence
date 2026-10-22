"""Resource-category rules: types, default units and category validation."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import UnitError
from .types import Issue
from .units import normalize_unit, units_for

RESOURCE_TYPES = ("electricity", "water", "chemicals", "steam", "fuel", "waste", "other")

# Units a category of each type may use for new records (calculations doc, section 4).
DEFAULT_ALLOWED_UNITS: dict[str, tuple[str, ...]] = {
    "electricity": ("kWh", "MWh"),
    "water": ("L", "m3"),
    "fuel": ("L", "m3", "kg", "kWh", "MJ"),
    "steam": ("kg", "tonne", "kWh", "MJ"),
    "chemicals": ("kg", "g", "L", "m3"),
    "waste": ("kg", "tonne", "L", "m3"),
    "other": tuple(units_for("resource")),
}

DEFAULT_UNIT: dict[str, str] = {
    "electricity": "kWh",
    "water": "L",
    "fuel": "L",
    "steam": "kg",
    "chemicals": "kg",
    "waste": "kg",
    "other": "kg",
}


@dataclass(frozen=True)
class CategorySeed:
    name: str
    resource_type: str


# Configuration created on first launch. These are categories, not data records.
INITIAL_CATEGORIES = (
    CategorySeed("Electricity", "electricity"),
    CategorySeed("Water", "water"),
    CategorySeed("Chemicals", "chemicals"),
    CategorySeed("Steam", "steam"),
    CategorySeed("Fuel", "fuel"),
    CategorySeed("Waste", "waste"),
    CategorySeed("Other resources", "other"),
)

MAX_NAME_LENGTH = 80


def validate_category_fields(
    name: object,
    resource_type: object,
    default_unit: object,
    allowed_units: object,
) -> tuple[dict | None, list[Issue]]:
    """Validate category settings. Returns normalised values or a list of issues."""
    issues: list[Issue] = []

    clean_name = " ".join(str(name).split()) if isinstance(name, str) else ""
    if not clean_name:
        issues.append(Issue("name", "required", "Enter a category name."))
    elif len(clean_name) > MAX_NAME_LENGTH:
        issues.append(
            Issue("name", "too_long", f"Category name must be at most {MAX_NAME_LENGTH} characters.")
        )
    elif not any(ch.isalpha() for ch in clean_name):
        issues.append(
            Issue("name", "ambiguous", "Category name must contain at least one letter.")
        )

    if resource_type not in RESOURCE_TYPES:
        issues.append(
            Issue("resource_type", "unsupported", f"Choose one of: {', '.join(RESOURCE_TYPES)}.")
        )

    units: list[str] = []
    raw_units = list(allowed_units) if isinstance(allowed_units, (list, tuple)) else []
    if not raw_units:
        issues.append(Issue("allowed_units", "required", "Select at least one permitted unit."))
    for raw in raw_units:
        try:
            code = normalize_unit(raw)
        except UnitError as exc:
            issues.append(Issue("allowed_units", "unsupported_unit", str(exc)))
            continue
        if code not in units_for("resource"):
            issues.append(
                Issue("allowed_units", "not_resource_unit", f"'{raw}' cannot be used for resources.")
            )
        elif code not in units:
            units.append(code)

    default_code: str | None = None
    try:
        default_code = normalize_unit(default_unit)
    except UnitError as exc:
        issues.append(Issue("default_unit", "unsupported_unit", str(exc)))
    if default_code and units and default_code not in units:
        issues.append(
            Issue("default_unit", "not_allowed", "The default unit must be one of the permitted units.")
        )

    if any(i.is_error for i in issues):
        return None, issues
    return (
        {
            "name": clean_name,
            "resource_type": resource_type,
            "default_unit": default_code,
            "allowed_units": tuple(units),
        },
        issues,
    )
