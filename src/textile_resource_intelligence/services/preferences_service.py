"""Essential application preferences stored in the local database."""

from __future__ import annotations

from decimal import Decimal

from ..domain.errors import QuantityError
from ..domain.numbers import decimal_to_text, parse_decimal
from ..domain.types import Issue
from ..exceptions import ValidationFailed
from ..schemas import Preferences
from .ports import UnitOfWorkFactory

PERIOD_MODES = ("day", "month", "range")
MAX_THRESHOLD_PCT = Decimal(1000)

_KEY_MODE = "default_period_mode"
_KEY_THRESHOLD = "intensity_threshold_pct"
_KEY_DECIMALS = "display_decimals"


class PreferencesService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow = uow_factory

    def get(self) -> Preferences:
        with self._uow() as repo:
            mode = repo.get_preference(_KEY_MODE)
            threshold = repo.get_preference(_KEY_THRESHOLD)
            decimals = repo.get_preference(_KEY_DECIMALS)
        defaults = Preferences()
        parsed_threshold: Decimal | None = None
        if threshold:
            try:
                parsed_threshold = parse_decimal(threshold)
            except QuantityError:
                parsed_threshold = None
        try:
            places = int(decimals) if decimals is not None else defaults.display_decimals
        except ValueError:
            places = defaults.display_decimals
        return Preferences(
            default_period_mode=mode if mode in PERIOD_MODES else defaults.default_period_mode,
            intensity_threshold_pct=parsed_threshold,
            display_decimals=places if 0 <= places <= 6 else defaults.display_decimals,
        )

    def save(
        self,
        *,
        default_period_mode: object,
        intensity_threshold_pct: object,
        display_decimals: object,
    ) -> Preferences:
        """Validate and store preferences. A blank threshold disables threshold prompts."""
        issues: list[Issue] = []
        if default_period_mode not in PERIOD_MODES:
            issues.append(
                Issue("default_period_mode", "invalid", f"Choose one of: {', '.join(PERIOD_MODES)}.")
            )
        threshold: Decimal | None = None
        blank = intensity_threshold_pct is None or (
            isinstance(intensity_threshold_pct, str) and not intensity_threshold_pct.strip()
        )
        if not blank:
            try:
                threshold = parse_decimal(intensity_threshold_pct, label="Threshold")
            except QuantityError as exc:
                issues.append(Issue("intensity_threshold_pct", "invalid", str(exc)))
            else:
                if threshold <= 0 or threshold > MAX_THRESHOLD_PCT:
                    issues.append(
                        Issue(
                            "intensity_threshold_pct",
                            "out_of_range",
                            "Threshold must be greater than 0 and at most 1000 (percent).",
                        )
                    )
        places = None
        try:
            places = int(display_decimals)  # type: ignore[call-overload]
            if not 0 <= places <= 6:
                raise ValueError
        except (TypeError, ValueError):
            issues.append(
                Issue("display_decimals", "invalid", "Display decimals must be a whole number from 0 to 6.")
            )
        if issues:
            raise ValidationFailed(issues)
        with self._uow() as repo:
            repo.set_preference(_KEY_MODE, str(default_period_mode))
            repo.set_preference(
                _KEY_THRESHOLD, decimal_to_text(threshold) if threshold is not None else None
            )
            repo.set_preference(_KEY_DECIMALS, str(places))
        return self.get()
