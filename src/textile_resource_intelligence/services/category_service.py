"""Resource-category configuration."""

from __future__ import annotations

from ..domain.categories import (
    DEFAULT_ALLOWED_UNITS,
    DEFAULT_UNIT,
    INITIAL_CATEGORIES,
    validate_category_fields,
)
from ..domain.types import Category, Issue
from ..exceptions import NotFound, ValidationFailed
from ..schemas import CategoryDraft, CategoryInput
from .ports import Repository, UnitOfWorkFactory


def seed_initial_categories(repo: Repository) -> None:
    """Create the initial categories when none exist (configuration, not data)."""
    if repo.list_categories():
        return
    for seed in INITIAL_CATEGORIES:
        repo.add_category(
            CategoryDraft(
                name=seed.name,
                resource_type=seed.resource_type,
                default_unit=DEFAULT_UNIT[seed.resource_type],
                allowed_units=DEFAULT_ALLOWED_UNITS[seed.resource_type],
                is_active=True,
            )
        )


class CategoryService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow = uow_factory

    def list(self, *, include_inactive: bool = True) -> list[Category]:
        with self._uow() as repo:
            categories = repo.list_categories()
        return [c for c in categories if include_inactive or c.is_active]

    def get(self, category_id: int) -> Category:
        with self._uow() as repo:
            category = repo.get_category(category_id)
        if category is None:
            raise NotFound("The resource category no longer exists.")
        return category

    def create(self, data: CategoryInput) -> Category:
        fields, issues = validate_category_fields(
            data.name, data.resource_type, data.default_unit, data.allowed_units
        )
        if fields is None:
            raise ValidationFailed(issues)
        with self._uow() as repo:
            if repo.find_category_by_name(fields["name"]) is not None:
                raise ValidationFailed(
                    [Issue("name", "duplicate", f"A category named '{fields['name']}' already exists.")]
                )
            return repo.add_category(CategoryDraft(is_active=True, **fields))

    def update(self, category_id: int, data: CategoryInput, *, is_active: bool) -> Category:
        """Rename, change permitted units or (de)activate a category.

        Existing records keep their stored quantity and unit; the category id never
        changes, so history stays linked after a rename.
        """
        fields, issues = validate_category_fields(
            data.name, data.resource_type, data.default_unit, data.allowed_units
        )
        if fields is None:
            raise ValidationFailed(issues)
        with self._uow() as repo:
            current = repo.get_category(category_id)
            if current is None:
                raise NotFound("The resource category no longer exists.")
            clash = repo.find_category_by_name(fields["name"])
            if clash is not None and clash.id != category_id:
                raise ValidationFailed(
                    [Issue("name", "duplicate", f"A category named '{fields['name']}' already exists.")]
                )
            if fields["resource_type"] != current.resource_type:
                if repo.count_resource_records_in_category(category_id) > 0:
                    raise ValidationFailed(
                        [
                            Issue(
                                "resource_type",
                                "type_locked",
                                "The resource type cannot be changed once records exist for this "
                                "category, because that would reinterpret them.",
                            )
                        ]
                    )
            updated = repo.update_category(category_id, CategoryDraft(is_active=is_active, **fields))
            if updated is None:
                raise NotFound("The resource category no longer exists.")
            return updated

    def set_active(self, category_id: int, active: bool) -> Category:
        current = self.get(category_id)
        return self.update(
            category_id,
            CategoryInput(
                current.name, current.resource_type, current.default_unit, list(current.allowed_units)
            ),
            is_active=active,
        )
