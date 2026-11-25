"""Create offline sample API responses so the project runs without internet.

The files in data/sample/ have exactly the same JSON structure as real DHIS2
analytics responses (headers, rows, metaData.items, metaData.ouHierarchy),
but the facilities and numbers are invented.

Run:  python src/generate_sample.py
"""
from __future__ import annotations

import json
import string

import numpy as np
import pandas as pd

from config import SAMPLE_DIR

SEED = 3
DISTRICTS = ["North", "South", "East", "West", "Central"]
FACILITIES_PER_DISTRICT = 8
MONTHS = pd.period_range("2025-11", "2026-10", freq="M")
DATASET_UID = "BfMAe6Itzgt"            # sample IDs follow DHIS2's 11-character format
DE_UID = "fbfJHSPpUQD"


def uid(rng) -> str:
    first = rng.choice(list(string.ascii_letters))
    rest = rng.choice(list(string.ascii_letters + string.digits), size=10)
    return first + "".join(rest)


def header(name, column, value_type="TEXT"):
    return {"name": name, "column": column, "valueType": value_type,
            "type": "java.lang.Double" if value_type == "NUMBER" else "java.lang.String",
            "hidden": False, "meta": value_type != "NUMBER"}


def main() -> None:
    rng = np.random.default_rng(SEED)
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    root = {"id": "ImspTQPwCqd", "name": "Sample Country"}
    items = {root["id"]: {"name": root["name"]}}
    hierarchy, facilities = {}, []
    for d in DISTRICTS:
        did = uid(rng); items[did] = {"name": f"{d} District"}
        for k in range(1, FACILITIES_PER_DISTRICT + 1):
            fid = uid(rng); name = f"{d} Health Centre {k:02d}"
            items[fid] = {"name": name}
            hierarchy[fid] = f"{root['id']}/{did}"
            facilities.append(fid)
    for p in MONTHS:
        items[p.strftime("%Y%m")] = {"name": p.strftime("%B %Y")}

    metrics = {m: f"{DATASET_UID}.{m}" for m in
               ["REPORTING_RATE", "REPORTING_RATE_ON_TIME", "ACTUAL_REPORTS",
                "ACTUAL_REPORTS_ON_TIME", "EXPECTED_REPORTS"]}
    items[DATASET_UID] = {"name": "Child Health"}
    items.update({v: {"name": f"Child Health - {k.replace('_', ' ').title()}"} for k, v in metrics.items()})
    items[DE_UID] = {"name": "ANC 1st visit"}

    # Facility behaviour: most are reliable; some report late; some stop reporting
    profile = rng.choice(["reliable", "late", "patchy"], size=len(facilities), p=[0.7, 0.15, 0.15])
    silent_from = {f: int(rng.integers(6, 10)) for f in rng.choice(facilities, 3, replace=False)}

    rep_rows, val_rows = [], []
    base_anc = {f: rng.uniform(15, 90) for f in facilities}
    for f, prof in zip(facilities, profile):
        for i, p in enumerate(MONTHS):
            pe = p.strftime("%Y%m")
            rep_rows.append([metrics["EXPECTED_REPORTS"], f, pe, "1.0"])
            p_report = {"reliable": 0.98, "late": 0.95, "patchy": 0.65}[prof]
            reported = rng.random() < p_report and not (f in silent_from and i >= silent_from[f])
            if not reported:
                continue                                    # DHIS2 omits empty cells from analytics rows
            on_time = rng.random() < {"reliable": 0.93, "late": 0.35, "patchy": 0.7}[prof]
            rep_rows += [[metrics["ACTUAL_REPORTS"], f, pe, "1.0"],
                         [metrics["REPORTING_RATE"], f, pe, "100.0"]]
            if on_time:
                rep_rows += [[metrics["ACTUAL_REPORTS_ON_TIME"], f, pe, "1.0"],
                             [metrics["REPORTING_RATE_ON_TIME"], f, pe, "100.0"]]
            value = rng.poisson(base_anc[f] * (1 + 0.1 * np.sin(i / 2)))
            val_rows.append([DE_UID, f, pe, f"{float(value):.1f}"])

    # Plant outliers: data-entry slips such as an extra zero
    planted = []
    for r in rng.choice(len(val_rows), 6, replace=False):
        original = float(val_rows[r][3])
        val_rows[r][3] = f"{original * 10 + 7:.1f}"
        planted.append({"ou": val_rows[r][1], "pe": val_rows[r][2], "original": original,
                        "planted_value": float(val_rows[r][3])})

    def payload(rows, dx):
        return {
            "headers": [header("dx", "Data"), header("ou", "Organisation unit"),
                        header("pe", "Period"), header("value", "Value", "NUMBER")],
            "metaData": {"items": items, "dimensions": {"dx": dx, "ou": facilities,
                                                        "pe": [p.strftime("%Y%m") for p in MONTHS]},
                         "ouHierarchy": hierarchy},
            "rows": rows, "height": len(rows), "width": 4,
        }

    (SAMPLE_DIR / "reporting.json").write_text(json.dumps(payload(rep_rows, list(metrics.values())), indent=1))
    (SAMPLE_DIR / "values.json").write_text(json.dumps(payload(val_rows, [DE_UID]), indent=1))
    (SAMPLE_DIR / "context.json").write_text(json.dumps({
        "root": root, "dataset": {"id": DATASET_UID, "name": "Child Health"},
        "data_element": {"id": DE_UID, "name": "ANC 1st visit"}, "source": "synthetic sample"}, indent=1))
    pd.DataFrame(planted).to_csv(SAMPLE_DIR / "planted_outliers.csv", index=False)
    pd.DataFrame({"ou": list(silent_from), "silent_from_month_index": list(silent_from.values())}
                 ).to_csv(SAMPLE_DIR / "planted_silent_facilities.csv", index=False)
    print(f"Sample: {len(facilities)} facilities x {len(MONTHS)} months; "
          f"{len(rep_rows)} reporting rows, {len(val_rows)} value rows, {len(planted)} planted outliers")


if __name__ == "__main__":
    main()
