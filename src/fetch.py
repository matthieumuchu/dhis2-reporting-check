"""Step 1: pull reporting data from DHIS2 (or load the offline sample).

Live:     python src/fetch.py               (uses DHIS2_URL / DHIS2_USER / DHIS2_PASS)
Offline:  python src/fetch.py --offline     (uses data/sample/*.json)

Writes two tidy tables for the analysis step:
  data/reporting.csv   facility x month x metric (expected, actual, on-time reports)
  data/values.csv      facility x month value of the chosen data element
"""
from __future__ import annotations

import argparse
import json

import pandas as pd

from config import (DATA_DIR, DATA_ELEMENT_NAME, DATASET_NAME, DHIS2_PASS, DHIS2_URL, DHIS2_USER,
                    FACILITY_LEVEL, PERIOD, RAW_DIR, SAMPLE_DIR)
from dhis2_client import DHIS2, analytics_to_frame

METRICS = ["REPORTING_RATE", "REPORTING_RATE_ON_TIME", "ACTUAL_REPORTS", "ACTUAL_REPORTS_ON_TIME",
           "EXPECTED_REPORTS"]


def fetch_live() -> tuple[dict, dict, dict]:
    api = DHIS2(DHIS2_URL, DHIS2_USER, DHIS2_PASS)
    print(f"Connecting to {DHIS2_URL} as {DHIS2_USER}...")
    root = api.root_org_unit()
    dataset = api.find_one("dataSets", DATASET_NAME)
    element = api.find_one("dataElements", DATA_ELEMENT_NAME)
    ou = f"{root['id']};LEVEL-{FACILITY_LEVEL}"            # every facility under the user's root
    print(f"Root: {root['name']} | data set: {dataset['name']} | data element: {element['name']}")
    reporting = api.analytics([f"{dataset['id']}.{m}" for m in METRICS], ou, PERIOD)
    values = api.analytics([element["id"]], ou, PERIOD)
    context = {"root": root, "dataset": dataset, "data_element": element, "source": DHIS2_URL}
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for name, obj in [("reporting", reporting), ("values", values), ("context", context)]:
        (RAW_DIR / f"{name}.json").write_text(json.dumps(obj))
    return reporting, values, context


def load_offline() -> tuple[dict, dict, dict]:
    return tuple(json.loads((SAMPLE_DIR / f"{n}.json").read_text()) for n in ["reporting", "values", "context"])


def tidy(reporting: dict, values: dict, context: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    rep = analytics_to_frame(reporting)
    rep["metric"] = rep["dx"].str.split(".").str[-1]
    wide = (rep.pivot_table(index=["ou", "ou_name", "district", "pe"], columns="metric",
                            values="value", aggfunc="sum").reset_index())
    for m in ["EXPECTED_REPORTS", "ACTUAL_REPORTS", "ACTUAL_REPORTS_ON_TIME"]:
        if m not in wide:
            wide[m] = 0.0
    wide[["ACTUAL_REPORTS", "ACTUAL_REPORTS_ON_TIME"]] = wide[["ACTUAL_REPORTS", "ACTUAL_REPORTS_ON_TIME"]].fillna(0)
    wide = wide[wide.EXPECTED_REPORTS.fillna(0) > 0]        # only months where a report was expected
    vals = analytics_to_frame(values)[["ou", "ou_name", "district", "pe", "value"]]
    vals["data_element"] = context["data_element"]["name"]
    return wide, vals


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="use the sample files instead of a live server")
    args = ap.parse_args()
    reporting, values, context = load_offline() if args.offline else fetch_live()
    wide, vals = tidy(reporting, values, context)
    wide.to_csv(DATA_DIR / "reporting.csv", index=False)
    vals.to_csv(DATA_DIR / "values.csv", index=False)
    (DATA_DIR / "context.json").write_text(json.dumps(context, indent=1))
    print(f"Saved {len(wide):,} facility-months of reporting and {len(vals):,} values "
          f"for {wide.ou.nunique()} facilities ({context['source']}).")


if __name__ == "__main__":
    main()
