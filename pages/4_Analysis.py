"""Analysis: totals, intensity, baseline comparison and trends for one resource and scope."""

from __future__ import annotations

from datetime import date

import streamlit as st

from textile_resource_intelligence.domain.types import CalcStatus, Period
from textile_resource_intelligence.schemas import RecordQuery
from textile_resource_intelligence.ui import charts
from textile_resource_intelligence.ui import components as ui
from textile_resource_intelligence.ui.formatting import (
    comparison_direction,
    dimension_label,
    format_percent,
    format_quantity,
    format_scope,
    format_signed,
    status_text,
)
from textile_resource_intelligence.ui.tables import (
    intensities_frame,
    production_records_frame,
    production_totals_frame,
    resource_records_frame,
    totals_frame,
)

container = ui.get_container()
ui.show_flash()
ui.page_header("Analysis", "Examine one resource and scope in detail, compare it with a baseline period, and trace every value to its records.")

prefs = container.preferences.get()
places = prefs.display_decimals
categories = {c.id: c for c in container.categories.list()}
with_data = [cid for cid in categories if container.analysis.scopes_for_category(cid)]
if not with_data:
    ui.empty_state("No resource records exist yet. Add records, import a CSV file or load demonstration data from Settings.")
    st.stop()

ui.demo_banner(container.analysis.record_counts().demo_total)

c1, c2, c3 = st.columns(3)
category_id = c1.selectbox("Resource", with_data, format_func=lambda i: categories[i].name, key="an_cat")
scope = c2.selectbox("Scope", container.analysis.scopes_for_category(category_id), format_func=format_scope, key="an_scope")
resource_dims = container.analysis.resource_dimensions(category_id, scope)
resource_dim = resource_dims[0] if len(resource_dims) == 1 else c3.selectbox(
    "Measurement", resource_dims, format_func=dimension_label, key="an_rdim",
    help="Records of different physical types (for example kg and litres) are analysed separately.")
production_dims = container.analysis.production_dimensions(scope)
if production_dims:
    production_dim = production_dims[0] if len(production_dims) == 1 and "mass" not in production_dims else st.selectbox(
        "Production basis", production_dims, index=production_dims.index("mass") if "mass" in production_dims else 0,
        format_func=dimension_label, key="an_pdim",
        help="The production unit used as the denominator. Different bases are never combined.")
else:
    production_dim = "mass"
    st.warning(f"No production records exist for scope '{format_scope(scope)}'. Totals are shown, but intensity is unavailable.")

anchor = container.analysis.latest_record_date()
st.subheader("Period to analyse")
current = ui.period_selector("an_cur", prefs.default_period_mode, anchor, label="Current period")
if current is None:
    st.stop()

compare_on = st.checkbox("Compare with a baseline period", key="an_compare",
                         help="A baseline is a reference period you choose. It is not an industry benchmark.")
baseline = None
if compare_on:
    st.subheader("Baseline period")
    baseline = ui.period_selector("an_base", prefs.default_period_mode, anchor, label="Baseline period")

total, production, intensity = container.analysis.period_results(
    category_id, scope, current, resource_dimension=resource_dim, production_dimension=production_dim)

st.subheader(f"Results for {current.label()}")
m1, m2, m3 = st.columns(3)
m1.metric("Total consumption", format_quantity(total.value, total.unit, places) if total and total.is_available else "Unavailable")
m2.metric("Production", format_quantity(production.value, production.unit, places) if production and production.is_available else "Unavailable")
m3.metric("Resource intensity", format_quantity(intensity.value, intensity.unit, places) if intensity.is_available else "Unavailable")
st.caption(f"Intensity status: {status_text(intensity.status)}")
for result in (total, production, intensity):
    if result is None:
        continue
    if result.reason:
        st.info(result.reason)
    for warning in result.warnings:
        st.warning(warning)
if total is None:
    st.info("No resource records fall entirely inside this period for this selection.")

with st.expander("Calculation details and traceability"):
    if total:
        st.dataframe(totals_frame([total], places), hide_index=True)
    if production:
        st.dataframe(production_totals_frame([production], places), hide_index=True)
    st.dataframe(intensities_frame([intensity], places), hide_index=True)
    st.caption("Intensity = total resource consumption ÷ total production for the same period and scope, after unit conversion.")
    st.write("Resource record IDs:", ", ".join(map(str, intensity.record_ids)) or "none")
    st.write("Production record IDs:", ", ".join(map(str, intensity.production_record_ids)) or "none")

if baseline is not None:
    st.subheader("Comparison with baseline")
    view = container.analysis.compare(category_id, scope, current, baseline, resource_dimension=resource_dim,
                                      production_dimension=production_dim, threshold_pct=prefs.intensity_threshold_pct)
    st.caption(f"{view.intensity_comparison.current_reference} · {view.intensity_comparison.baseline_reference}")
    for label, cmp in (("Total consumption", view.total_comparison), ("Production", view.production_comparison),
                       ("Resource intensity", view.intensity_comparison)):
        col_a, col_b = st.columns([2, 3])
        if cmp.status is CalcStatus.UNAVAILABLE:
            col_a.metric(label, "Unavailable")
            col_b.info(cmp.reason or "Comparison unavailable.")
            continue
        delta = format_signed(cmp.absolute_difference, cmp.unit, places)
        if cmp.percent_change is not None:
            delta += f" ({format_percent(cmp.percent_change)})"
        col_a.metric(label, format_quantity(cmp.current_value, cmp.unit, places), delta=delta, delta_color="off",
                     help=f"Baseline value: {format_quantity(cmp.baseline_value, cmp.unit, places)}")
        col_b.write(f"{label} is **{comparison_direction(cmp.percent_change if cmp.percent_change is not None else cmp.absolute_difference)}** "
                    f"than the baseline of {format_quantity(cmp.baseline_value, cmp.unit, places)}.")
        if cmp.percent_reason:
            col_b.caption(cmp.percent_reason)
        for warning in cmp.warnings:
            col_b.caption(f"Note: {warning}")
    figure = charts.comparison_figure(view.intensity_comparison, "Intensity: baseline versus current")
    if figure is not None:
        st.plotly_chart(figure, key="an_compare_chart")
    if view.prompts:
        st.markdown("**Items to review**")
        for prompt in view.prompts:
            st.info(prompt)
    st.caption("A difference between periods is an observation from the recorded data. It does not by itself identify "
               "a cause, and this application does not estimate savings or financial impact.")
    export = container.exports.comparison(view)
    st.download_button("Download this comparison (CSV)", data=export.content, file_name=export.filename,
                       mime="text/csv", key="an_compare_dl")

st.subheader("Trend over time")
t1, t2 = st.columns([3, 1])
default_end = anchor or date.today()
trend_range = t1.date_input("Trend range", value=(default_end.replace(month=1, day=1), default_end),
                            min_value=ui.MIN_DATE, max_value=ui.MAX_DATE, key="an_trend_range", format="YYYY-MM-DD")
granularity = t2.radio("Group by", ["month", "day"], horizontal=True, key="an_gran")
if isinstance(trend_range, (tuple, list)) and len(trend_range) == 2:
    ui.render_trend(container, category_id, scope, Period(trend_range[0], trend_range[1]), resource_dim,
                    production_dim, granularity, categories[category_id].name)
else:
    st.info("Select both a start and an end date for the trend.")

with st.expander("Records behind these results"):
    r_query = RecordQuery(date_from=current.start, date_to=current.end, category_id=category_id,
                          scope_mode="overall" if scope is None else "key", scope_key=scope)
    p_query = RecordQuery(date_from=current.start, date_to=current.end,
                          scope_mode="overall" if scope is None else "key", scope_key=scope)
    st.markdown("**Resource records overlapping the period**")
    st.dataframe(resource_records_frame(container.resources.list(r_query), categories,
                                        container.analysis.resource_quality()), hide_index=True)
    st.markdown("**Production records overlapping the period**")
    st.dataframe(production_records_frame(container.production.list(p_query),
                                          container.analysis.production_quality()), hide_index=True)
