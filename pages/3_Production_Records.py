"""Production records: browse, add, edit, delete and import."""

from __future__ import annotations

import math
from datetime import date

import streamlit as st

from textile_resource_intelligence.domain.numbers import decimal_to_text
from textile_resource_intelligence.domain.units import unit_display, units_for
from textile_resource_intelligence.exceptions import NotFound, RepositoryError, ValidationFailed
from textile_resource_intelligence.schemas import ProductionRecordInput, RecordQuery
from textile_resource_intelligence.ui import components as ui
from textile_resource_intelligence.ui.formatting import QUALITY_LABELS, format_raw_quantity
from textile_resource_intelligence.ui.tables import production_records_frame

container = ui.get_container()
ui.show_flash()
ui.page_header("Production Records", "Record production so resource use can be related to output. Production units (kg, metres, pieces) are never mixed.")

PRODUCTION_UNITS = units_for("production")
all_records = container.production.list()
nonce = st.session_state.setdefault("pr_nonce", 0)

tab_list, tab_add, tab_edit, tab_import = st.tabs(["Records", "Add record", "Edit or delete", "Import CSV"])

with tab_list:
    if not all_records:
        ui.empty_state("No production records yet. Use 'Add record' or 'Import CSV'.")
    else:
        f1, f2, f3 = st.columns(3)
        scope_keys = sorted({r.scope_key for r in all_records if r.scope_key})
        scope_choice = f1.selectbox("Scope", ["(all)", "(overall - no scope)", *scope_keys], key="pr_f_scope")
        source_label = f2.selectbox("Source", ["All", "Manual entry", "CSV import", "Synthetic demo"], key="pr_f_source")
        quality_choice = f3.selectbox("Data quality", ["All", *QUALITY_LABELS.values()], key="pr_f_quality")
        text = st.text_input("Search reference, notes or scope", key="pr_f_text")
        use_period = st.checkbox("Filter by period", key="pr_f_period_on")
        window = ui.period_selector("pr_f", "range", max(r.period.end for r in all_records)) if use_period else None
        query = RecordQuery(
            date_from=window.start if window else None,
            date_to=window.end if window else None,
            scope_mode="any" if scope_choice == "(all)" else ("overall" if scope_choice.startswith("(overall") else "key"),
            scope_key=None if scope_choice.startswith("(") else scope_choice,
            source_type={"Manual entry": "manual", "CSV import": "import", "Synthetic demo": "demo"}.get(source_label),
            text=text or None,
        )
        records = container.production.list(query)
        quality = container.analysis.production_quality()
        if quality_choice != "All":
            wanted = {v: k for k, v in QUALITY_LABELS.items()}[quality_choice]
            records = [r for r in records if quality.get(r.id) and quality[r.id].status == wanted]
        page_size = container.settings.page_size
        pages = max(1, math.ceil(len(records) / page_size))
        page = int(st.number_input("Page", 1, pages, 1, key="pr_page")) if pages > 1 else 1
        st.caption(f"{len(records)} record(s) match. Quantities and units are shown exactly as recorded.")
        if records:
            st.dataframe(production_records_frame(records[(page - 1) * page_size: page * page_size], quality), hide_index=True)
        else:
            st.info("No records match the current filters.")

with tab_add:
    use_range = st.checkbox("This record covers a date range (untick for a single date)", value=True,
                            key=f"pr_add_range_{nonce}")
    with st.form(f"pr_add_form_{nonce}"):
        quantity = st.text_input("Production quantity", key=f"pr_add_qty_{nonce}", placeholder="e.g. 600",
                                 help="Zero is allowed (it records that nothing was produced) but cannot be used as a denominator.")
        unit = st.selectbox("Unit", PRODUCTION_UNITS, format_func=unit_display, key=f"pr_add_unit_{nonce}")
        start = st.date_input("Period start", value=date.today(), min_value=ui.MIN_DATE, max_value=ui.MAX_DATE,
                              key=f"pr_add_start_{nonce}", format="YYYY-MM-DD")
        end = st.date_input("Period end (inclusive)", value=date.today(), min_value=ui.MIN_DATE,
                            max_value=ui.MAX_DATE, key=f"pr_add_end_{nonce}", format="YYYY-MM-DD") if use_range else None
        scope = st.text_input("Scope key (optional)", key=f"pr_add_scope_{nonce}",
                              help="Must match the scope key of the resource records it is compared with. Blank = overall.")
        reference = st.text_input("Reference (optional)", key=f"pr_add_ref_{nonce}")
        notes = st.text_area("Notes (optional)", key=f"pr_add_notes_{nonce}")
        submitted = st.form_submit_button("Save record", type="primary")
    if submitted:
        try:
            result = container.production.create(ProductionRecordInput(quantity, unit, start, end, scope, reference, notes))
        except ValidationFailed as exc:
            ui.show_validation_error(exc)
        except RepositoryError as exc:
            ui.show_repository_error(exc)
        else:
            ui.flash("success", f"Saved production record #{result.record.id}.")
            for warning in result.warnings:
                ui.flash("warning", warning.message)
            st.session_state["pr_nonce"] = nonce + 1
            st.rerun()

with tab_edit:
    if not all_records:
        ui.empty_state("There are no records to edit.")
    else:
        ordered = list(reversed(all_records))
        labels = {r.id: f"#{r.id} · {r.period.label()} · {format_raw_quantity(r.quantity)} {unit_display(r.unit)}"
                        f"{' · ' + r.scope_key if r.scope_key else ''}" for r in ordered}
        rid = st.selectbox("Record", [r.id for r in ordered], format_func=labels.get, key="pr_edit_select")
        try:
            rec = container.production.get(rid)
        except NotFound as exc:
            st.error(str(exc))
            st.stop()
        use_range = st.checkbox("This record covers a date range", value=not rec.period.is_single_date,
                                key=f"pr_edit_range_{rid}")
        units = list(dict.fromkeys([*PRODUCTION_UNITS, rec.unit]))
        with st.form(f"pr_edit_form_{rid}"):
            quantity = st.text_input("Production quantity", value=decimal_to_text(rec.quantity), key=f"pr_edit_qty_{rid}")
            unit = st.selectbox("Unit", units, index=units.index(rec.unit), format_func=unit_display,
                                key=f"pr_edit_unit_{rid}")
            start = st.date_input("Period start", value=rec.period.start, min_value=ui.MIN_DATE, max_value=ui.MAX_DATE,
                                  key=f"pr_edit_start_{rid}", format="YYYY-MM-DD")
            end = st.date_input("Period end (inclusive)", value=rec.period.end, min_value=ui.MIN_DATE,
                                max_value=ui.MAX_DATE, key=f"pr_edit_end_{rid}", format="YYYY-MM-DD") if use_range else None
            scope = st.text_input("Scope key (optional)", value=rec.scope_key or "", key=f"pr_edit_scope_{rid}")
            reference = st.text_input("Reference (optional)", value=rec.reference or "", key=f"pr_edit_ref_{rid}")
            notes = st.text_area("Notes (optional)", value=rec.notes or "", key=f"pr_edit_notes_{rid}")
            saved = st.form_submit_button("Save changes", type="primary")
        if saved:
            try:
                result = container.production.update(rid, ProductionRecordInput(quantity, unit, start, end, scope, reference, notes))
            except ValidationFailed as exc:
                ui.show_validation_error(exc)
            except (NotFound, RepositoryError) as exc:
                st.error(str(exc))
            else:
                ui.flash("success", f"Updated production record #{rid}. All results recalculate from the new values.")
                for warning in result.warnings:
                    ui.flash("warning", warning.message)
                st.rerun()
        st.divider()
        confirm = st.checkbox(f"I understand that deleting record #{rid} cannot be undone.", key=f"pr_del_confirm_{rid}")
        if st.button("Delete record", disabled=not confirm, key=f"pr_del_{rid}"):
            try:
                container.production.delete(rid)
            except (NotFound, RepositoryError) as exc:
                st.error(str(exc))
            else:
                ui.flash("success", f"Deleted production record #{rid}.")
                st.rerun()

with tab_import:
    ui.render_import_tab(container, "production", "pr_import")
