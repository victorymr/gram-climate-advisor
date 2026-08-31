"""Deep links: ?state=&district=&lang= (plus optional context params) pre-select the sidebar
and show the advisory; the URL is kept in sync with the current selection."""
import pytest
from streamlit.testing.v1 import AppTest

APP = "app.py"


def _at(**params):
    at = AppTest.from_file(APP, default_timeout=180)
    for k, v in params.items():
        at.query_params[k] = v
    return at


def _sb(at, label):
    return next(s for s in at.sidebar.selectbox if (s.label or "").startswith(label))


def _banner(at):
    return next((m.value for m in at.markdown if 'class="risk-banner"' in m.value), None)


def _qp(at):
    """Query params as {key: str} (AppTest stores written values as lists)."""
    return {k: (v[0] if isinstance(v, list) else v) for k, v in at.query_params.items()}


def test_deeplink_selects_district_and_shows_advisory():
    at = _at(state="Bihar", district="Gaya").run()
    assert not at.exception
    assert _sb(at, "Select State").value == "Bihar"
    assert _sb(at, "Select District").value == "Gaya"
    assert "Gaya, Bihar" in (_banner(at) or "")
    assert _qp(at)["state"] == "Bihar" and _qp(at)["district"] == "Gaya"
    assert _qp(at)["lang"] == "en"


def test_deeplink_is_case_and_space_insensitive_and_sets_language_and_context():
    at = _at(state="uttar-pradesh", district="VARANASI", lang="hi",
             user="farmer", crop="rice", irrigation="rainfed", stage="vegetative").run()
    assert not at.exception
    assert _sb(at, "Language").value == "हिन्दी"
    assert _sb(at, "राज्य").value == "Uttar Pradesh"
    assert _sb(at, "जिला").value == "Varanasi"
    assert _sb(at, "उपयोगकर्ता").value == "किसान"
    assert _sb(at, "फसल का प्रकार").value == "Rice"
    assert _sb(at, "सिंचाई").value == "वर्षा आधारित"
    assert _sb(at, "फसल की अवस्था").value == "वानस्पतिक अवस्था"
    assert "Varanasi, Uttar Pradesh" in (_banner(at) or "")
    # write-back canonicalises the values
    assert _qp(at) == {"state": "Uttar Pradesh", "district": "Varanasi",
                                         "lang": "hi", "crop": "Rice", "stage": "Vegetative"}


def test_unknown_district_falls_back_without_showing_advisory():
    at = _at(state="Bihar", district="Atlantis").run()
    assert not at.exception
    assert _sb(at, "Select State").value == "Bihar"
    assert _banner(at) is None
    assert _qp(at)["district"] != "Atlantis"      # URL now reflects the real selection


def test_user_change_after_deeplink_wins_and_updates_url():
    at = _at(state="Bihar", district="Gaya").run()
    _sb(at, "Select District").set_value("Patna")
    at.run()
    assert not at.exception
    assert _sb(at, "Select District").value == "Patna"
    assert _qp(at)["district"] == "Patna"
    assert "Patna, Bihar" in (_banner(at) or "")
