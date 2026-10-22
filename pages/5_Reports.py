"""Reports and CSV export of source records and derived results."""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from textile_resource_intelligence.exceptions import RepositoryError
from textile_resource_intelligence.schemas import RecordQuery
from textile_resource_intelligence.ui import components as ui
from textile_resource_intelligence.ui.formatting import dimension_label

container = ui.get_container()
ui.show_flash()
ui.page_header("Reports & Export", "Export your records or calculated results as CSV files for spreadsheets or sharing.")

prefs = container.preferences.get()
counts = container.analysis.record_counts()
ui.demo_banner(counts.demo_total)
if counts.total == 0:
    ui.empty_state("There is no data to export yet. Add or import records first.")
    st.stop()

SOURCE_RESOURCE = "Resource records (source data)"
SOURCE_PRODUCTION = "Production records (source data)"
TOTALS = "Resource totals for a period"
INTENSITY = "Resource intensity for a period"
QUALITY = "Data-quality warnings for a period"

choice = st.radio("What do you want to export?", [SOURCE_RESOURCE, SOURCE_PRODUCTION, TOTALS, INTENSITY, QUALITY],
                  key="rep_choice")

result = None
try:
    if choice in (SOURCE_RESOURCE, SOURCE_PRODUCTION):
        st.caption("Source exports use the same column names as the CSV importer, so they can be re-imported. "
                   "Text that looks like a spreadsheet formula is prefixed with an apostrophe for safety.")
        source = st.selectbox("Source", ["All", "Manual entry", "CSV import", "Synthetic demo"], key="rep_source")
        query = RecordQuery(source_type={"Manual entry": "manual", "CSV import": "import",
                                         "Synthetic demo": "demo"}.get(source))
        if st.checkbox("Limit to a period", key="rep_limit"):
            window = ui.period_selector("rep_src", "range", container.analysis.latest_record_date())
            if window is None:
                st.stop()
            query = RecordQuery(date_from=window.start, date_to=window.end, source_type=query.source_type)
        with st.spinner("Preparing export..."):
            result = (container.exports.resource_records(query) if choice == SOURCE_RESOURCE
                      else container.exports.production_records(query))
    else:
        window = ui.period_selector("rep_per", prefs.default_period_mode, container.analysis.latest_record_date())
        if window is None:
            st.stop()
        with st.spinner("Preparing export..."):
            if choice == TOTALS:
                result = container.exports.resource_summaries(window)
            elif choice == INTENSITY:
                dims = container.analysis.overview(window).available_production_dimensions
                basis = st.selectbox("Production basis", list(dims), format_func=dimension_label, key="rep_basis") if dims else None
                result = container.exports.intensities(window, basis)
            else:
                result = container.exports.data_quality(window)
except RepositoryError as exc:
    st.error(str(exc))
    st.stop()

if result is None or result.rows == 0:
    st.info("No data matches this selection, so there is nothing to export. Adjust the period or filters.")
else:
    st.success(f"Export ready: {result.rows} row(s), {len(result.columns)} column(s).")
    preview = pd.read_csv(io.BytesIO(result.content), dtype=str, keep_default_na=False, encoding="utf-8-sig")
    st.dataframe(preview.head(20), hide_index=True)
    if result.rows > 20:
        st.caption(f"Showing the first 20 of {result.rows} rows.")
    st.download_button("Download CSV", data=result.content, file_name=result.filename, mime="text/csv", key="rep_dl")
    st.caption("The file is UTF-8 with a byte-order mark so that Excel on Windows shows characters such as m³ correctly. "
               "Unavailable values are exported as empty cells, never as zero.")
