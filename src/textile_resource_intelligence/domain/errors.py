"""Domain-level exceptions."""

from __future__ import annotations


class DomainError(ValueError):
    """Base class for expected, user-correctable domain errors."""


class QuantityError(DomainError):
    """A quantity is missing, malformed, non-finite or out of range."""


class UnitError(DomainError):
    """Base class for unit problems."""


class UnknownUnitError(UnitError):
    """The unit is not in the registry."""


class IncompatibleUnitsError(UnitError):
    """Two units cannot be converted into each other."""


class CalculationUnavailableError(DomainError):
    """A calculation cannot be performed with the supplied inputs."""
