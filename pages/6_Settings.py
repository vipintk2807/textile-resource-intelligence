"""Settings: categories, preferences, demonstration data, database and backup, about."""

from __future__ import annotations

import streamlit as st

from textile_resource_intelligence import __version__
from textile_resource_intelligence.backup import backup_database
from textile_resource_intelligence.domain.categories import DEFAULT_ALLOWED_UNITS, DEFAULT_UNIT, RESOURCE_TYPES
from textile_resource_intelligence.domain.units import unit_display, units_for
from textile_resource_intelligence.exceptions import NotFound, RepositoryError, ValidationFailed
from textile_resource_intelligence.schemas import CategoryInput
from textile_resource_intelligence.ui import components as ui

container = ui.get_container()
ui.show_flash()
ui.page_header("Settings", "Configure resource categories and preferences, manage demonstration data and back up your database.")

tab_cat, tab_pref, tab_demo, tab_db, tab_about = st.tabs(
    ["Resource categories", "Preferences", "Demonstration data", "Database and backup", "About and limitations"]
)

# ------------------------------------------------------------------ categories
with tab_cat:
    categories = container.categories.list()
    by_id = {c.id: c for c in categories}
    st.dataframe([
        {"Category": c.name, "Type": c.resource_type, "Default unit": unit_display(c.default_unit),
         "Permitted units": ", ".join(unit_display(u) for u in c.allowed_units),
         "Status": "Active" if c.is_active else "Inactive"} for c in categories], hide_index=True)
    st.caption("Each category is analysed on its own: different chemicals or resources are never added together. "
               "Deactivating a category keeps its history but stops new records being added to it.")

    st.markdown("**Add a category**")
    new_type = st.selectbox("Resource type", RESOURCE_TYPES, key="set_new_type")
    with st.form("set_add_category"):
        name = st.text_input("Name", key="set_new_name", help="For example 'Reactive dye A' or 'Boiler fuel'.")
        permitted = DEFAULT_ALLOWED_UNITS[new_type]
        units = st.multiselect("Permitted units", units_for("resource"), default=list(permitted),
                               format_func=unit_display, key=f"set_new_units_{new_type}")
        default = st.selectbox("Default unit", units_for("resource"),
                               index=units_for("resource").index(DEFAULT_UNIT[new_type]),
                               format_func=unit_display, key=f"set_new_default_{new_type}")
        add = st.form_submit_button("Add category", type="primary")
    if add:
        try:
            created = container.categories.create(CategoryInput(name, new_type, default, units))
        except ValidationFailed as exc:
            ui.show_validation_error(exc)
        except RepositoryError as exc:
            ui.show_repository_error(exc)
        else:
            ui.flash("success", f"Added category '{created.name}'.")
            st.rerun()

    if categories:
        st.markdown("**Edit a category**")
        cid = st.selectbox("Category", [c.id for c in categories], format_func=lambda i: by_id[i].name, key="set_edit_cat")
        cat = by_id[cid]
        with st.form(f"set_edit_category_{cid}"):
            name = st.text_input("Name", value=cat.name, key=f"set_edit_name_{cid}")
            units = st.multiselect("Permitted units", units_for("resource"), default=list(cat.allowed_units),
                                   format_func=unit_display, key=f"set_edit_units_{cid}")
            default = st.selectbox("Default unit", units_for("resource"),
                                   index=units_for("resource").index(cat.default_unit),
                                   format_func=unit_display, key=f"set_edit_default_{cid}")
            active = st.checkbox("Active", value=cat.is_active, key=f"set_edit_active_{cid}")
            save = st.form_submit_button("Save category")
        if save:
            try:
                container.categories.update(cid, CategoryInput(name, cat.resource_type, default, units), is_active=active)
            except ValidationFailed as exc:
                ui.show_validation_error(exc)
            except (NotFound, RepositoryError) as exc:
                st.error(str(exc))
            else:
                ui.flash("success", "Category saved. Existing records keep their recorded quantities and units.")
                st.rerun()

# ----------------------------------------------------------------- preferences
with tab_pref:
    prefs = container.preferences.get()
    with st.form("set_preferences"):
        modes = ["month", "day", "range"]
        mode = st.selectbox("Default reporting period", modes, index=modes.index(prefs.default_period_mode),
                            format_func={"month": "Month", "day": "Single day", "range": "Custom range"}.get, key="set_mode")
        threshold = st.text_input(
            "Review threshold for intensity increases (%)",
            value="" if prefs.intensity_threshold_pct is None else str(prefs.intensity_threshold_pct), key="set_threshold",
            help="Optional. When an intensity is higher than its baseline by more than this percentage, Analysis "
                 "shows a prompt to review the records. Blank disables it. No default is assumed because "
                 "suitable thresholds depend on your process.")
        decimals = st.number_input("Decimal places shown", min_value=0, max_value=6, value=prefs.display_decimals, step=1,
                                   key="set_decimals", help="Display only; calculations keep full precision.")
        saved = st.form_submit_button("Save preferences", type="primary")
    if saved:
        try:
            container.preferences.save(default_period_mode=mode, intensity_threshold_pct=threshold,
                                       display_decimals=int(decimals))
        except ValidationFailed as exc:
            ui.show_validation_error(exc)
        except RepositoryError as exc:
            ui.show_repository_error(exc)
        else:
            ui.flash("success", "Preferences saved.")
            st.rerun()

# ------------------------------------------------------------------------ demo
with tab_demo:
    counts = container.analysis.record_counts()
    st.markdown(
        "The demonstration dataset is **synthetic**: artificial values chosen to show specific behaviours "
        "(valid intensities, a month with no production, zero production, partial coverage, unit conversion, "
        "separate scopes and a zero baseline). It does not describe any real factory and is not a benchmark. "
        "Every demo record is labelled 'Synthetic demo' and can be removed without touching your own data."
    )
    if counts.demo_total:
        st.warning(f"{counts.demo_resource} demo resource record(s) and {counts.demo_production} demo production record(s) are loaded.")
        confirm = st.checkbox("I understand this deletes only the synthetic demonstration records.", key="set_demo_confirm")
        if st.button("Remove demonstration data", disabled=not confirm, key="set_demo_remove"):
            try:
                removed = container.demo.remove()
            except RepositoryError as exc:
                st.error(str(exc))
            else:
                ui.flash("success", f"Removed {removed[0]} demo resource and {removed[1]} demo production record(s).")
                st.rerun()
    else:
        if st.button("Load synthetic demonstration data", key="set_demo_load"):
            try:
                loaded = container.demo.load()
            except ValidationFailed as exc:
                ui.show_validation_error(exc)
            except RepositoryError as exc:
                ui.show_repository_error(exc)
            else:
                ui.flash("success", f"Loaded {loaded[0]} synthetic resource and {loaded[1]} synthetic production record(s).")
                st.rerun()

# -------------------------------------------------------------------- database
with tab_db:
    settings = container.settings
    counts = container.analysis.record_counts()
    path = settings.database_path
    size_kb = path.stat().st_size / 1024 if path.exists() else 0
    st.markdown(f"**Database file:** `{path}`")
    st.markdown(f"**Backups folder:** `{settings.backup_dir}`")
    st.markdown(f"**Log file:** `{settings.log_file}`")
    c1, c2, c3 = st.columns(3)
    c1.metric("Resource records", counts.resource)
    c2.metric("Production records", counts.production)
    c3.metric("Schema version", container.database.schema_version())
    st.caption(f"Database size: {size_kb:,.1f} KB. All data stays on this computer; the application makes no network connections of its own.")
    if st.button("Create a backup now", key="set_backup"):
        try:
            target = backup_database(path, settings.backup_dir)
        except (FileNotFoundError, RuntimeError, OSError) as exc:
            st.error(f"The backup failed: {exc}")
        else:
            st.success(f"Backup created and verified: `{target}`")
    st.caption("To restore: close the application, then replace the database file with a copy from the backups folder.")

# ----------------------------------------------------------------------- about
with tab_about:
    st.markdown(f"**Textile Resource Intelligence** version {__version__}")
    st.markdown(
        """
**What it does:** records resource consumption and production, relates them, and shows resource intensity
(consumption per unit of production) with traceable calculations.

**Not included in this release**
- Cumulative meter readings (only interval consumption is accepted).
- Cost, carbon, benchmarking or savings estimates.
- Automated cause diagnosis; comparisons are observations, not explanations.
- Conversions needing extra data (density, fuel energy content, steam enthalpy).
- Multi-user access, authentication, or cloud services.

**Data handling:** one local SQLite file; no telemetry; no outbound connections by the application.
"""
    )
