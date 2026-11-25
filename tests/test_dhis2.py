"""Tests for the DHIS2 reporting check (no internet needed).  Run:  python -m pytest -q"""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import dhis2_client  # noqa: E402
from analyse import facility_scores, find_outliers, trailing_missing  # noqa: E402
from fetch import load_offline, tidy  # noqa: E402


def sample_tables():
    return tidy(*load_offline())


def test_analytics_json_becomes_named_table():
    payload = json.loads((ROOT / "data/sample/values.json").read_text())
    df = dhis2_client.analytics_to_frame(payload)
    assert {"dx", "ou", "pe", "value", "ou_name", "district"} <= set(df.columns)
    assert df.district.str.endswith("District").all()


def test_missing_reports_count_as_zero():
    rep, _ = sample_tables()
    assert (rep.EXPECTED_REPORTS == 1).all()                 # one expected report per facility-month
    assert set(rep.ACTUAL_REPORTS.unique()) <= {0.0, 1.0}


def test_trailing_missing():
    assert trailing_missing(pd.Series([True, True, False, False, False])) == 3
    assert trailing_missing(pd.Series([False, True])) == 0


def test_planted_silent_facilities_are_urgent():
    rep, _ = sample_tables()
    fac = facility_scores(rep).set_index("ou")
    for ou in pd.read_csv(ROOT / "data/sample/planted_silent_facilities.csv").ou:
        assert fac.loc[ou, "priority"] == "1 - Urgent"


def test_planted_outliers_are_found():
    _, vals = sample_tables()
    found = set(zip(find_outliers(vals).ou, find_outliers(vals).pe.astype(str)))
    planted = pd.read_csv(ROOT / "data/sample/planted_outliers.csv", dtype={"pe": str})
    assert all((r.ou, r.pe) in found for r in planted.itertuples())


def test_client_builds_the_right_analytics_request(monkeypatch):
    seen = {}

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"headers": [], "rows": []}

    def fake_get(url, params=None, timeout=None):
        seen["url"], seen["params"] = url, params
        return FakeResp()

    api = dhis2_client.DHIS2("https://example.org/", "admin", "district")
    monkeypatch.setattr(api.session, "get", fake_get)
    api.analytics(["ds1.REPORTING_RATE", "ds1.EXPECTED_REPORTS"], "root;LEVEL-4", "LAST_12_MONTHS")
    assert seen["url"] == "https://example.org/api/analytics"
    assert seen["params"]["dimension"] == ["dx:ds1.REPORTING_RATE;ds1.EXPECTED_REPORTS",
                                           "ou:root;LEVEL-4", "pe:LAST_12_MONTHS"]
    assert api.session.auth == ("admin", "district")


def test_html_login_page_gives_a_clear_error(monkeypatch):
    """Old demo addresses redirect to a web page; the client must explain how to fix it."""
    import pytest

    class HtmlResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): raise ValueError("not JSON")

    api = dhis2_client.DHIS2("https://play.dhis2.org/demo", "admin", "district")
    monkeypatch.setattr(api.session, "get", lambda *a, **k: HtmlResp())
    with pytest.raises(SystemExit, match="play.im.dhis2.org"):
        api.get("me")
