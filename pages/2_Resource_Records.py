"""Resource records: browse, add, edit, delete and import."""

from __future__ import annotations

import math
from datetime import date

import streamlit as st

from textile_resource_intelligence.domain.numbers import decimal_to_text
from textile_resource_intelligence.domain.units import unit_display
from textile_resource_intelligence.exceptions import NotFound, RepositoryError, ValidationFailed
from textile_resource_intelligence.schemas import RecordQuery, ResourceRecordInput
from textile_resource_intelligence.ui import components as ui
from textile_resource_intelligence.ui.formatting import QUALITY_LABELS, format_raw_quantity
from textile_resource_intelligence.ui.tables import resource_records_frame

container = ui.get_container()
ui.show_flash()
ui.page_header("Resource Records", "Enter, review and correct consumption of electricity, water, chemicals, steam and other resources.")

categories = container.categories.list()
by_id = {c.id: c for c in categories}
active = [c for c in categories if c.is_active]
all_records = container.resources.list()
nonce = st.session_state.setdefault("rr_nonce", 0)

tab_list, tab_add, tab_edit, tab_import = st.tabs(["Records", "Add record", "Edit or delete", "Import CSV"])

# ------------------------------------------------------------------------ list
with tab_list:
    if not all_records:
        ui.empty_state("No resource records yet. Use 'Add record' or 'Import CSV'.")
    else:
        f1, f2, f3, f4 = st.columns(4)
        cat_id = f1.selectbox("Resource category", [None, *by_id], key="rr_f_cat",
                              format_func=lambda i: "All categories" if i is None else by_id[i].name)
        scope_keys = sorted({r.scope_key for r in all_records if r.scope_key})
        scope_choice = f2.selectbox("Scope", ["(all)", "(overall - no scope)", *scope_keys], key="rr_f_scope")
        source_label = f3.selectbox("Source", ["All", "Manual entry", "CSV import", "Synthetic demo"], key="rr_f_source")
        quality_choice = f4.selectbox("Data quality", ["All", *QUALITY_LABELS.values()], key="rr_f_quality")
        text = st.text_input("Search reference, notes or scope", key="rr_f_text")
        use_period = st.checkbox("Filter by period", key="rr_f_period_on")
        window = None
        if use_period:
            window = ui.period_selector("rr_f", "range", max(r.period.end for r in all_records))

        query = RecordQuery(
            date_from=window.start if window else None,
            date_to=window.end if window else None,
            category_id=cat_id,
            scope_mode="any" if scope_choice == "(all)" else ("overall" if scope_choice.startswith("(overall") else "key"),
            scope_key=None if scope_choice.startswith("(") else scope_choice,
            source_type={"Manual entry": "manual", "CSV import": "import", "Synthetic demo": "demo"}.get(source_label),
            text=text or None,
        )
        records = container.resources.list(query)
        quality = container.analysis.resource_quality()
        if quality_choice != "All":
            wanted = {v: k for k, v in QUALITY_LABELS.items()}[quality_choice]
            records = [r for r in records if quality.get(r.id) and quality[r.id].status == wanted]

        page_size = container.settings.page_size
        pages = max(1, math.ceil(len(records) / page_size))
        page = int(st.number_input("Page", 1, pages, 1, key="rr_page")) if pages > 1 else 1
        shown = records[(page - 1) * page_size: page * page_size]
        st.caption(f"{len(records)} record(s) match. Quantities and units are shown exactly as recorded.")
        if records:
            st.dataframe(resource_records_frame(shown, by_id, quality), hide_index=True)
        else:
            st.info("No records match the current filters.")

# -------------------------------------------------------------------------- add
with tab_add:
    if not active:
        st.warning("There is no active resource category. Activate or create one in Settings first.")
    else:
        cat_id = st.selectbox("Resource category", [c.id for c in active], format_func=lambda i: by_id[i].name,
                              key=f"rr_add_cat_{nonce}")
        category = by_id[cat_id]
        use_range = st.checkbox("This record covers a date range (untick for a single date)", value=True,
                                key=f"rr_add_range_{nonce}")
        units = list(category.allowed_units)
        with st.form(f"rr_add_form_{nonce}"):
            quantity = st.text_input("Quantity", key=f"rr_add_qty_{nonce}", placeholder="e.g. 1200.5",
                                     help="Digits with an optional decimal point; no thousands separators.")
            unit = st.selectbox("Unit", units, index=units.index(category.default_unit) if category.default_unit in units else 0,
                                format_func=unit_display, key=f"rr_add_unit_{nonce}_{cat_id}")
            start = st.date_input("Period start", value=date.today(), min_value=ui.MIN_DATE, max_value=ui.MAX_DATE,
                                  key=f"rr_add_start_{nonce}", format="YYYY-MM-DD")
            end = st.date_input("Period end (inclusive)", value=date.today(), min_value=ui.MIN_DATE,
                                max_value=ui.MAX_DATE, key=f"rr_add_end_{nonce}", format="YYYY-MM-DD") if use_range else None
            scope = st.text_input("Scope key (optional)", key=f"rr_add_scope_{nonce}",
                                  help="Use the same key on matching production records, e.g. 'dyeing-1'. Blank = overall.")
            reference = st.text_input("Reference (optional)", key=f"rr_add_ref_{nonce}",
                                      help="Meter, batch or document identifier. Makes re-imports safe from duplicates.")
            notes = st.text_area("Notes (optional)", key=f"rr_add_notes_{nonce}")
            submitted = st.form_submit_button("Save record", type="primary")
        if submitted:
            try:
                result = container.resources.create(ResourceRecordInput(
                    cat_id, quantity, unit, start, end, scope, reference, notes))
            except ValidationFailed as exc:
                ui.show_validation_error(exc)
            except RepositoryError as exc:
                ui.show_repository_error(exc)
            else:
                ui.flash("success", f"Saved resource record #{result.record.id}.")
                for warning in result.warnings:
                    ui.flash("warning", warning.message)
                st.session_state["rr_nonce"] = nonce + 1
                st.rerun()

# ------------------------------------------------------------------------- edit
with tab_edit:
    if not all_records:
        ui.empty_state("There are no records to edit.")
    else:
        ordered = list(reversed(all_records))
        labels = {r.id: f"#{r.id} · {r.period.label()} · {by_id[r.category_id].name if r.category_id in by_id else '?'} · "
                        f"{format_raw_quantity(r.quantity)} {unit_display(r.unit)}" for r in ordered}
        rid = st.selectbox("Record", [r.id for r in ordered], format_func=labels.get, key="rr_edit_select")
        try:
            rec = container.resources.get(rid)
        except NotFound as exc:
            st.error(str(exc))
            st.stop()
        choices = [c.id for c in categories if c.is_active or c.id == rec.category_id]
        cat_id = st.selectbox("Resource category", choices, index=choices.index(rec.category_id),
                              format_func=lambda i: by_id[i].name, key=f"rr_edit_cat_{rid}")
        category = by_id[cat_id]
        units = list(dict.fromkeys([*category.allowed_units, rec.unit]))
        use_range = st.checkbox("This record covers a date range", value=not rec.period.is_single_date,
                                key=f"rr_edit_range_{rid}")
        with st.form(f"rr_edit_form_{rid}"):
            quantity = st.text_input("Quantity", value=decimal_to_text(rec.quantity), key=f"rr_edit_qty_{rid}")
            unit = st.selectbox("Unit", units, index=units.index(rec.unit) if rec.unit in units else 0,
                                format_func=unit_display, key=f"rr_edit_unit_{rid}_{cat_id}")
            start = st.date_input("Period start", value=rec.period.start, min_value=ui.MIN_DATE,
                                  max_value=ui.MAX_DATE, key=f"rr_edit_start_{rid}", format="YYYY-MM-DD")
            end = st.date_input("Period end (inclusive)", value=rec.period.end, min_value=ui.MIN_DATE,
                                max_value=ui.MAX_DATE, key=f"rr_edit_end_{rid}", format="YYYY-MM-DD") if use_range else None
            scope = st.text_input("Scope key (optional)", value=rec.scope_key or "", key=f"rr_edit_scope_{rid}")
            reference = st.text_input("Reference (optional)", value=rec.reference or "", key=f"rr_edit_ref_{rid}")
            notes = st.text_area("Notes (optional)", value=rec.notes or "", key=f"rr_edit_notes_{rid}")
            saved = st.form_submit_button("Save changes", type="primary")
        if saved:
            try:
                result = container.resources.update(rid, ResourceRecordInput(
                    cat_id, quantity, unit, start, end, scope, reference, notes))
            except ValidationFailed as exc:
                ui.show_validation_error(exc)
            except (NotFound, RepositoryError) as exc:
                st.error(str(exc))
            else:
                ui.flash("success", f"Updated resource record #{rid}. All results recalculate from the new values.")
                for warning in result.warnings:
                    ui.flash("warning", warning.message)
                st.rerun()
        st.divider()
        st.markdown("**Delete this record**")
        confirm = st.checkbox(f"I understand that deleting record #{rid} cannot be undone.", key=f"rr_del_confirm_{rid}")
        if st.button("Delete record", disabled=not confirm, key=f"rr_del_{rid}"):
            try:
                container.resources.delete(rid)
            except (NotFound, RepositoryError) as exc:
                st.error(str(exc))
            else:
                ui.flash("success", f"Deleted resource record #{rid}.")
                st.rerun()

# ----------------------------------------------------------------------- import
with tab_import:
    ui.render_import_tab(container, "resource", "rr_import")
