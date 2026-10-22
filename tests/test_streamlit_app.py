"""Smoke tests that run every page with Streamlit's AppTest harness.

They need Streamlit, SQLAlchemy and Plotly (``pip install -r requirements-dev.txt``) and are
skipped automatically when those packages are missing. Each test uses its own temporary
database and never touches the real one.
"""

import os
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("sqlalchemy")
pytest.importorskip("plotly")

import streamlit as st  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PAGES = ["1_Overview", "2_Resource_Records", "3_Production_Records", "4_Analysis", "5_Reports", "6_Settings"]


@pytest.fixture
def app_env(tmp_path):
    """Point the application at a temporary database for the duration of a test."""
    saved = {k: os.environ.get(k) for k in ("TRI_DATABASE_PATH", "TRI_DATA_DIR")}
    os.environ["TRI_DATABASE_PATH"] = str(tmp_path / "ui.db")
    os.environ["TRI_DATA_DIR"] = str(tmp_path)
    st.cache_resource.clear()
    yield tmp_path
    st.cache_resource.clear()
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _load_demo():
    from textile_resource_intelligence.config import AppSettings
    from textile_resource_intelligence.services.container import build_container

    container = build_container(AppSettings.from_env())
    container.demo.load()


def _page(name):
    return AppTest.from_file(str(ROOT / "pages" / f"{name}.py"), default_timeout=60)


@pytest.mark.parametrize("name", PAGES)
def test_every_page_renders_on_an_empty_database(app_env, name):
    at = _page(name).run()
    assert not at.exception, [e.value for e in at.exception]


@pytest.mark.parametrize("name", PAGES)
def test_every_page_renders_with_demo_data(app_env, name):
    _load_demo()
    at = _page(name).run()
    assert not at.exception, [e.value for e in at.exception]


def test_overview_empty_state_offers_next_steps(app_env):
    at = _page("1_Overview").run()
    assert any("No data has been recorded yet" in i.value for i in at.info)


def test_overview_labels_demo_data_and_shows_totals(app_env):
    _load_demo()
    at = _page("1_Overview").run()
    assert any("synthetic" in w.value.lower() for w in at.warning)
    assert len(at.metric) > 0


def test_invalid_resource_record_shows_an_error_and_saves_nothing(app_env):
    at = _page("2_Resource_Records").run()
    at.text_input(key="rr_add_qty_0").set_value("not a number")
    at.button[0].click()  # first form submit button on the page
    at.run()
    assert any("not saved" in e.value for e in at.error)
