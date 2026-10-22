"""Overview: totals, production, intensity and data-quality warnings for a period."""

from __future__ import annotations

import streamlit as st

from textile_resource_intelligence.ui import components as ui
from textile_resource_intelligence.ui.formatting import dimension_label, format_quantity, format_scope
from textile_resource_intelligence.ui.tables import intensities_frame, production_totals_frame, totals_frame

container = ui.get_container()
ui.show_flash()
ui.page_header(
    "Overview",
    "Resource consumption, production and resource intensity for the selected period.",
)

prefs = container.preferences.get()
places = prefs.display_decimals
anchor = container.analysis.latest_record_date()
window = ui.period_selector("overview", prefs.default_period_mode, anchor)
if window is None:
    st.stop()

data = container.analysis.overview(window)
ui.demo_banner(data.counts.demo_total)

if not data.has_any_data:
    ui.empty_state(
        "No data has been recorded yet. Add resource and production records, import a CSV file, "
        "or load the clearly labelled synthetic demonstration data from Settings."
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        ui.page_link(ui.PAGE_RESOURCES, "Add resource records")
    with c2:
        ui.page_link(ui.PAGE_PRODUCTION, "Add production records")
    with c3:
        ui.page_link(ui.PAGE_SETTINGS, "Settings and demonstration data")
    st.stop()

if not data.has_data_in_window:
    st.info(
        f"No records fall inside {window.label()}. Choose another period, or check that records "
        "lie entirely within the period (records are never split across period boundaries)."
    )

if len(data.available_production_dimensions) > 1:
    basis = st.selectbox(
        "Production basis for intensity",
        list(data.available_production_dimensions),
        index=list(data.available_production_dimensions).index(data.production_dimension),
        format_func=dimension_label,
        key="overview_basis",
        help="Different production units (for example kg and metres) are never added together.",
    )
    if basis != data.production_dimension:
        data = container.analysis.overview(window, basis)

st.subheader(f"Period summary: {window.label()}")
available_totals = [t for t in data.resource_totals if t.is_available]
if available_totals:
    cols = st.columns(min(4, len(available_totals)))
    for col, total in zip(cols, available_totals[:4], strict=False):
        label = f"{total.category_name} · {format_scope(total.scope_key)}"
        col.metric(label, format_quantity(total.value, total.unit, places),
                   help=f"{total.record_count} record(s); covers {total.coverage_days} of {window.days} days.")
available_production = [p for p in data.production_totals if p.is_available]
if available_production:
    cols = st.columns(min(4, len(available_production)))
    for col, prod in zip(cols, available_production[:4], strict=False):
        col.metric(f"Production · {format_scope(prod.scope_key)} · {dimension_label(prod.dimension)}",
                   format_quantity(prod.value, prod.unit, places),
                   help=f"{prod.record_count} record(s); covers {prod.coverage_days} of {window.days} days.")

tab_totals, tab_intensity, tab_trend, tab_quality = st.tabs(
    ["Totals", "Resource intensity", "Trend", "Data quality"]
)

with tab_totals:
    st.markdown("**Resource consumption**")
    if data.resource_totals:
        st.dataframe(totals_frame(data.resource_totals, places), hide_index=True)
    else:
        st.caption("No resource records in this period.")
    st.markdown("**Recorded production**")
    if data.production_totals:
        st.dataframe(production_totals_frame(data.production_totals, places), hide_index=True)
    else:
        st.caption("No production records in this period.")

with tab_intensity:
    if data.intensities:
        basis_text = dimension_label(data.production_dimension or "")
        st.caption(
            f"Intensity = total resource consumption ÷ total production ({basis_text.lower()} basis) for the "
            "same period and scope. Quantities are converted to common units first. An unavailable value "
            "is never shown as zero."
        )
        st.dataframe(intensities_frame(data.intensities, places), hide_index=True)
    else:
        st.info("No intensity can be calculated: record both resource consumption and production for the same period and scope.")

with tab_trend:
    categories = {c.id: c for c in container.categories.list()}
    with_data = [cid for cid in categories if container.analysis.scopes_for_category(cid)]
    if not with_data:
        st.info("Record resource consumption to see a trend.")
    else:
        t1, t2, t3 = st.columns(3)
        cid = t1.selectbox("Resource", with_data, format_func=lambda i: categories[i].name, key="ov_trend_cat")
        scopes = container.analysis.scopes_for_category(cid)
        scope = t2.selectbox("Scope", scopes, format_func=format_scope, key="ov_trend_scope")
        granularity = t3.radio("Group by", ["month", "day"], horizontal=True, key="ov_trend_gran")
        rdims = container.analysis.resource_dimensions(cid, scope)
        pdims = container.analysis.production_dimensions(scope)
        if not rdims:
            st.info("No records for this selection.")
        elif not pdims:
            st.info("No production records exist for this scope, so no intensity trend can be shown.")
        else:
            rdim = rdims[0] if len(rdims) == 1 else st.selectbox(
                "Measurement", rdims, format_func=dimension_label, key="ov_trend_rdim")
            pdim = data.production_dimension if data.production_dimension in pdims else pdims[0]
            ui.render_trend(container, cid, scope, window, rdim, pdim, granularity, categories[cid].name)

with tab_quality:
    q = data.quality_counts
    c1, c2, c3 = st.columns(3)
    c1.metric("Records without issues", q.get("valid", 0))
    c2.metric("Records needing review", q.get("review", 0))
    c3.metric("Records requiring correction", q.get("invalid", 0))
    if data.warnings:
        for warning in data.warnings:
            st.warning(warning.message)
        c1, c2, c3 = st.columns(3)
        with c1:
            ui.page_link(ui.PAGE_RESOURCES, "Review resource records")
        with c2:
            ui.page_link(ui.PAGE_PRODUCTION, "Review production records")
        with c3:
            ui.page_link(ui.PAGE_ANALYSIS, "Open analysis")
    else:
        st.success("No data-quality warnings for this period.")
