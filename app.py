"""Streamlit entry point: Textile Resource Intelligence.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the ``src`` layout importable without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import streamlit as st  # noqa: E402

from textile_resource_intelligence import __version__  # noqa: E402
from textile_resource_intelligence.ui import components as ui  # noqa: E402

st.set_page_config(page_title="Textile Resource Intelligence", layout="wide")

container = ui.get_container()  # opens (or creates) the local database

navigation = st.navigation(
    [
        st.Page("pages/1_Overview.py", title="Overview", url_path="overview", default=True),
        st.Page("pages/2_Resource_Records.py", title="Resource Records", url_path="resource-records"),
        st.Page("pages/3_Production_Records.py", title="Production Records", url_path="production-records"),
        st.Page("pages/4_Analysis.py", title="Analysis", url_path="analysis"),
        st.Page("pages/5_Reports.py", title="Reports & Export", url_path="reports"),
        st.Page("pages/6_Settings.py", title="Settings", url_path="settings"),
    ]
)

with st.sidebar:
    st.markdown("**Textile Resource Intelligence**")
    st.caption(f"Version {__version__} · data stays on this computer")

navigation.run()
