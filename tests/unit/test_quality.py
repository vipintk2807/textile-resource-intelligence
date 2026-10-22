"""Derived data-quality status of stored records."""

from datetime import date
from decimal import Decimal as D

from textile_resource_intelligence.domain.quality import (
    assess_production_records,
    assess_resource_records,
    summarize,
)
from textile_resource_intelligence.domain.types import Period, ProductionRecord, ResourceRecord

JAN = Period(date(2025, 1, 1), date(2025, 1, 31))


def test_record_with_covering_positive_production_is_valid():
    res = [ResourceRecord(1, 1, D(10), "kWh", JAN)]
    prod = [ProductionRecord(1, D(5), "kg", JAN)]
    assert assess_resource_records(res, prod)[1].status == "valid"


def test_record_without_production_needs_review_and_says_why():
    a = assess_resource_records([ResourceRecord(1, 1, D(10), "kWh", JAN)], [])[1]
    assert a.status == "review" and "production" in a.reasons[0]


def test_zero_production_does_not_count_as_coverage():
    res = [ResourceRecord(1, 1, D(10), "kWh", JAN)]
    prod = [ProductionRecord(1, D(0), "kg", JAN)]
    assert assess_resource_records(res, prod)[1].status == "review"


def test_production_in_another_scope_does_not_cover():
    res = [ResourceRecord(1, 1, D(10), "kWh", JAN, "a")]
    prod = [ProductionRecord(1, D(5), "kg", JAN, None)]
    assert assess_resource_records(res, prod)[1].status == "review"


def test_possible_duplicates_are_flagged_but_not_removed():
    res = [ResourceRecord(1, 1, D(10), "kWh", JAN), ResourceRecord(2, 1, D(10), "kWh", JAN)]
    prod = [ProductionRecord(1, D(5), "kg", JAN)]
    out = assess_resource_records(res, prod)
    assert all("Possible duplicate" in " ".join(a.reasons) for a in out.values()) and len(out) == 2


def test_distinct_references_are_not_possible_duplicates():
    res = [ResourceRecord(1, 1, D(10), "kWh", JAN, None, "A"), ResourceRecord(2, 1, D(10), "kWh", JAN, None, "B")]
    prod = [ProductionRecord(1, D(5), "kg", JAN)]
    assert all(a.status == "valid" for a in assess_resource_records(res, prod).values())


def test_overlapping_different_intervals_are_flagged():
    week = Period(date(2025, 1, 1), date(2025, 1, 7))
    res = [ResourceRecord(1, 1, D(10), "kWh", JAN), ResourceRecord(2, 1, D(1), "kWh", week)]
    prod = [ProductionRecord(1, D(5), "kg", JAN)]
    assert "Overlaps" in " ".join(assess_resource_records(res, prod)[1].reasons)


def test_unknown_unit_is_invalid():
    a = assess_resource_records([ResourceRecord(1, 1, D(10), "bushel", JAN)], [])[1]
    assert a.status == "invalid"


def test_zero_production_record_is_reviewed():
    a = assess_production_records([ProductionRecord(1, D(0), "kg", JAN)])[1]
    assert a.status == "review" and "denominator" in a.reasons[0]


def test_summary_counts_by_status():
    out = assess_production_records([ProductionRecord(1, D(0), "kg", JAN), ProductionRecord(2, D(5), "kg", JAN, "x")])
    assert summarize(out) == {"valid": 1, "review": 1, "invalid": 0}
