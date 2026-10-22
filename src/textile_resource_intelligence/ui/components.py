"""Streamlit building blocks shared by the pages.

All calculations and validation live in the services and domain packages; this module
only collects input and displays results.
"""

from __future__ import annotations

import calendar
import logging
import zlib
from datetime import date

import pandas as pd
import streamlit as st

from ..config import AppSettings, configure_logging
from ..domain.types import Issue, Period
from ..domain.units import unit_display
from ..exceptions import DatabaseVersionError, ImportFileError, RepositoryError, ValidationFailed
from ..schemas import ImportReport
from ..services.container import AppContainer, build_container
from ..services.import_service import fields_for, suggest_mapping, template_csv
from . import charts
from .formatting import dimension_label, format_scope

logger = logging.getLogger(__name__)

MIN_DATE = date(1900, 1, 1)
MAX_DATE = date(2100, 12, 31)

PAGE_OVERVIEW = "pages/1_Overview.py"
PAGE_RESOURCES = "pages/2_Resource_Records.py"
PAGE_PRODUCTION = "pages/3_Production_Records.py"
PAGE_ANALYSIS = "pages/4_Analysis.py"
PAGE_REPORTS = "pages/5_Reports.py"
PAGE_SETTINGS = "pages/6_Settings.py"

PAGE_FOR_KEY = {
    "resource_records": PAGE_RESOURCES,
    "production_records": PAGE_PRODUCTION,
    "analysis": PAGE_ANALYSIS,
}


# ------------------------------------------------------------------ app container
@st.cache_resource(show_spinner="Opening the local database...")
def _container(database_path: str) -> AppContainer:
    settings = AppSettings.from_env()
    configure_logging(settings)
    return build_container(settings)


def get_container() -> AppContainer:
    """Return the shared services, or stop the page with a clear message."""
    try:
        settings = AppSettings.from_env()
        return _container(str(settings.database_path))
    except DatabaseVersionError as exc:
        st.error(str(exc))
    except Exception:  # noqa: BLE001 - the page must show a friendly message, details go to the log
        logger.exception("Application start-up failed")
        st.error(
            "The application could not open its local database. Check that the data folder is "
            "writable, then restart. Details were written to the application log."
        )
    st.stop()
    raise RuntimeError("unreachable")  # pragma: no cover


# ---------------------------------------------------------------------- messages
def flash(kind: str, message: str) -> None:
    """Queue a message that survives the rerun after a successful action."""
    st.session_state.setdefault("_flash", []).append((kind, message))


def show_flash() -> None:
    for kind, message in st.session_state.pop("_flash", []):
        getattr(st, kind)(message)


def show_issues(issues: list[Issue] | tuple[Issue, ...]) -> None:
    for issue in issues:
        prefix = f"Row {issue.row}: " if issue.row is not None else ""
        field = issue.field.replace("_", " ").capitalize()
        text = f"{prefix}**{field}** - {issue.message}"
        (st.error if issue.is_error else st.warning)(text)


def show_validation_error(exc: ValidationFailed) -> None:
    st.error("The record was not saved. Please correct the following:")
    show_issues(exc.issues)


def show_repository_error(exc: RepositoryError) -> None:
    st.error(str(exc))


def page_header(title: str, purpose: str) -> None:
    st.title(title)
    st.caption(purpose)


def demo_banner(demo_total: int) -> None:
    if demo_total:
        st.warning(
            f"This database contains {demo_total} **synthetic demonstration** record(s). They are "
            "artificial test values, not real factory data. Remove them in Settings > Demonstration data."
        )


def empty_state(message: str) -> None:
    st.info(message)


def page_link(page: str, label: str) -> None:
    """Link to another page; falls back to plain text if the page is not registered."""
    try:
        st.page_link(page, label=label)
    except Exception:  # noqa: BLE001 - e.g. when a page script is run on its own in tests
        st.caption(label)


# ------------------------------------------------------------------- period input
def period_selector(key: str, default_mode: str, anchor: date | None, label: str = "Reporting period") -> Period | None:
    """Month, single day or custom range. Returns ``None`` until a valid period is chosen."""
    anchor = anchor or date.today()
    modes = ["Month", "Day", "Custom range"]
    default_index = {"month": 0, "day": 1, "range": 2}.get(default_mode, 0)
    mode = st.radio(label, modes, index=default_index, horizontal=True, key=f"{key}_mode")
    if mode == "Month":
        c1, c2 = st.columns(2)
        year = c1.number_input("Year", min_value=1900, max_value=2100, value=anchor.year, step=1, key=f"{key}_year")
        month = c2.selectbox("Month", list(range(1, 13)), index=anchor.month - 1,
                             format_func=lambda m: calendar.month_name[m], key=f"{key}_month")
        last = calendar.monthrange(int(year), int(month))[1]
        return Period(date(int(year), int(month), 1), date(int(year), int(month), last))
    if mode == "Day":
        day = st.date_input("Date", value=anchor, min_value=MIN_DATE, max_value=MAX_DATE, key=f"{key}_day",
                            format="YYYY-MM-DD")
        return Period(day, day)
    value = st.date_input("Start and end date", value=(anchor.replace(day=1), anchor), min_value=MIN_DATE,
                          max_value=MAX_DATE, key=f"{key}_range", format="YYYY-MM-DD")
    if isinstance(value, (tuple, list)) and len(value) == 2:
        return Period(value[0], value[1])
    st.info("Select both a start date and an end date.")
    return None


# --------------------------------------------------------------------- CSV import
def render_import_tab(container: AppContainer, kind: str, key: str) -> None:
    """Upload -> map columns -> validate (dry run) -> confirm import."""
    noun = "resource" if kind == "resource" else "production"
    st.markdown(
        f"Import {noun} records from a CSV file (UTF-8). Dates must be written **YYYY-MM-DD**. "
        "Nothing is saved until you confirm, and if any row has an error **no rows are imported**."
    )
    st.download_button("Download CSV template", data=template_csv(kind), file_name=f"{noun}_import_template.csv",
                       mime="text/csv", key=f"{key}_template")
    upload = st.file_uploader("CSV file", type=["csv"], key=f"{key}_upload")
    if upload is None:
        st.session_state.pop(f"{key}_report", None)
        return
    content = upload.getvalue()
    try:
        table = container.imports.inspect(content)
    except ImportFileError as exc:
        st.error(str(exc))
        return

    st.write(f"File **{upload.name}**: {len(table.rows)} data row(s), {len(table.columns)} column(s). "
             "Row numbers below count data rows after the header.")
    st.dataframe(pd.DataFrame(list(table.rows[:5])), hide_index=True)
    suggested = suggest_mapping(table.columns, kind)
    st.markdown("**Match your columns to the application fields**")
    none_label = "(not in file)"
    signature = zlib.crc32("|".join(table.columns).encode("utf-8"))  # new file layout -> fresh widgets
    mapping: dict[str, str | None] = {}
    for field, required in fields_for(kind):
        options = [none_label, *table.columns]
        default = options.index(suggested[field]) if suggested.get(field) in options else 0
        choice = st.selectbox(f"{field}{' (required)' if required else ''}", options, index=default,
                              key=f"{key}_map_{field}_{signature}")
        mapping[field] = None if choice == none_label else choice

    if st.button("Validate file", key=f"{key}_validate"):
        try:
            report = container.imports.run(content, kind, mapping, dry_run=True)
        except (ImportFileError, RepositoryError) as exc:
            st.error(str(exc))
            return
        st.session_state[f"{key}_report"] = (report, content, mapping)

    stored = st.session_state.get(f"{key}_report")
    if not stored:
        return
    report, stored_content, stored_mapping = stored
    _render_report(report)
    if report.can_commit:
        if st.button(f"Import {report.valid_rows} record(s)", type="primary", key=f"{key}_commit"):
            try:
                result = container.imports.run(stored_content, kind, stored_mapping, dry_run=False)
            except (ImportFileError, RepositoryError) as exc:
                st.error(str(exc))
                return
            st.session_state.pop(f"{key}_report", None)
            if result.committed:
                flash("success", f"Imported {result.inserted} {noun} record(s). "
                                 f"{result.skipped_duplicates} duplicate row(s) were skipped.")
                st.rerun()
            else:
                st.session_state[f"{key}_report"] = (result, stored_content, stored_mapping)
                st.rerun()


def _render_report(report: ImportReport) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rows in file", report.total_rows)
    c2.metric("Ready to import", report.valid_rows)
    c3.metric("Rows with errors", report.rejected_rows)
    c4.metric("Skipped duplicates", report.skipped_duplicates)
    if report.ignored_columns:
        st.caption("Ignored columns: " + ", ".join(report.ignored_columns))
    if report.errors:
        st.error("The file cannot be imported until the errors below are fixed. Nothing has been saved.")
    elif report.valid_rows == 0:
        st.warning("No importable rows were found.")
    else:
        st.success("Validation passed. Review any warnings, then confirm the import.")
    if report.issues:
        frame = pd.DataFrame([{
            "Row": i.row if i.row is not None else "",
            "Field": i.field,
            "Level": "Error" if i.is_error else "Warning",
            "Message": i.message,
        } for i in report.issues])
        st.dataframe(frame, hide_index=True)


# ------------------------------------------------------------------------ trends
def render_trend(container: AppContainer, category_id: int, scope_key: str | None, window: Period,
                 resource_dimension: str, production_dimension: str, granularity: str, name: str) -> None:
    try:
        trend = container.analysis.trend(category_id, scope_key, window, resource_dimension=resource_dimension,
                                         production_dimension=production_dimension, granularity=granularity)
    except ValueError as exc:
        st.warning(str(exc))
        return
    scope_text = format_scope(scope_key)
    st.plotly_chart(charts.total_trend_figure(trend, f"{name} consumption - {scope_text}"),
                    key=f"trend_total_{category_id}_{scope_key}_{granularity}")
    st.plotly_chart(charts.production_trend_figure(trend, f"Production ({dimension_label(production_dimension)} basis)"),
                    key=f"trend_prod_{category_id}_{scope_key}_{granularity}")
    st.plotly_chart(charts.intensity_trend_figure(trend, f"{name} intensity per unit of production"),
                    key=f"trend_int_{category_id}_{scope_key}_{granularity}")
    missing = sum(1 for b in trend.buckets if not b.intensity.is_available)
    if missing:
        st.caption(f"{missing} period(s) have no valid intensity and appear as gaps, not as zero. "
                   "Diamond markers indicate values calculated with warnings.")
    overall = trend.overall
    if overall.is_available:
        st.write(f"**Overall intensity for the range:** {overall.value:,.3f} {unit_display_pair(overall.unit)} "
                 "(total consumption divided by total production of the valid periods; not an average of ratios).")
        for warning in overall.warnings:
            st.caption(f"Note: {warning}")
    else:
        st.write(f"**Overall intensity unavailable.** {overall.reason or ''}")


def unit_display_pair(unit: str | None) -> str:
    if not unit:
        return ""
    return "/".join(unit_display(part) for part in unit.split("/"))
