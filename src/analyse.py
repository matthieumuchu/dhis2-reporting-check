"""Step 2: score every facility on completeness, timeliness, silence and outliers.

Definitions (the same ones DHIS2 uses in its reporting rate summary):
  completeness = reports received / reports expected
  timeliness   = reports received on time / reports expected
  silent       = the last SILENT_MONTHS (or more) expected reports are all missing
  outlier      = a monthly value whose modified z-score is above OUTLIER_Z
                 (modified z = 0.6745 x (value - median) / MAD, robust to the outliers themselves)

Run:  python src/analyse.py
"""
from __future__ import annotations

import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.graph_objects as go

from config import (COMPLETENESS_TARGET, DATA_DIR, IMAGE_DIR, OUTLIER_Z, OUTPUT_DIR, SILENT_MONTHS,
                    TIMELINESS_TARGET)

NAVY, RED, AMBER, GREEN, GREY = "#1F3864", "#C0392B", "#E67E22", "#2E7D32", "#BDC3C7"
MAX_HEATMAP_ROWS = 60     # a live national server has 1,000+ facilities: show only those needing follow-up
MAX_TABLE_ROWS = 200      # the HTML tables are capped; the Excel report always has every row


def trailing_missing(reported: pd.Series) -> int:
    """How many of the most recent months in a row have no report."""
    n = 0
    for r in reported[::-1]:
        if r:
            break
        n += 1
    return n


def facility_scores(rep: pd.DataFrame) -> pd.DataFrame:
    rep = rep.sort_values(["ou", "pe"])
    g = rep.groupby(["ou", "ou_name", "district"])
    f = g.agg(expected=("EXPECTED_REPORTS", "sum"), received=("ACTUAL_REPORTS", "sum"),
              on_time=("ACTUAL_REPORTS_ON_TIME", "sum")).reset_index()
    f["completeness"] = f.received / f.expected
    f["timeliness"] = f.on_time / f.expected
    f["months_silent"] = f.ou.map(rep.groupby("ou")["ACTUAL_REPORTS"].apply(lambda s: trailing_missing(s > 0)))
    problems = []
    for r in f.itertuples():
        p = []
        if r.months_silent >= SILENT_MONTHS:
            p.append(f"Silent: no report for the last {r.months_silent} months")
        if r.completeness < COMPLETENESS_TARGET:
            p.append(f"Completeness {r.completeness:.0%} (target {COMPLETENESS_TARGET:.0%})")
        if r.timeliness < TIMELINESS_TARGET:
            p.append(f"Timeliness {r.timeliness:.0%} (target {TIMELINESS_TARGET:.0%})")
        problems.append("; ".join(p))
    f["problems"] = problems
    f["priority"] = np.select([f.months_silent >= SILENT_MONTHS, f.problems != ""], ["1 - Urgent", "2 - Follow up"],
                              default="3 - OK")
    return f.sort_values(["priority", "completeness"])


def district_scores(rep: pd.DataFrame) -> pd.DataFrame:
    d = rep.groupby("district").agg(facilities=("ou", "nunique"), expected=("EXPECTED_REPORTS", "sum"),
                                    received=("ACTUAL_REPORTS", "sum"), on_time=("ACTUAL_REPORTS_ON_TIME", "sum"))
    d["completeness"] = d.received / d.expected
    d["timeliness"] = d.on_time / d.expected
    return d.reset_index().sort_values("completeness")


def monthly_scores(rep: pd.DataFrame) -> pd.DataFrame:
    m = rep.groupby("pe").agg(expected=("EXPECTED_REPORTS", "sum"), received=("ACTUAL_REPORTS", "sum"),
                              on_time=("ACTUAL_REPORTS_ON_TIME", "sum")).reset_index()
    m["completeness"] = m.received / m.expected
    m["timeliness"] = m.on_time / m.expected
    m["month"] = pd.to_datetime(m.pe.astype(str), format="%Y%m").dt.strftime("%b %Y")
    return m


def find_outliers(vals: pd.DataFrame, min_points: int = 6) -> pd.DataFrame:
    """Modified z-score per facility; needs at least `min_points` months to judge."""
    out = []
    for ou, g in vals.dropna(subset=["value"]).groupby("ou"):
        if len(g) < min_points:
            continue
        med = g.value.median()
        mad = (g.value - med).abs().median()
        if mad == 0:
            continue
        z = 0.6745 * (g.value - med) / mad
        hit = g[z.abs() > OUTLIER_Z].assign(facility_median=med, modified_z=z[z.abs() > OUTLIER_Z].round(1))
        out.append(hit)
    cols = ["district", "ou_name", "pe", "data_element", "value", "facility_median", "modified_z",
            "assessment", "ou"]
    if not out:
        return pd.DataFrame(columns=cols)
    res = pd.concat(out)
    res["assessment"] = np.where(res.modified_z.abs() > 10, "Likely data-entry error (e.g. extra digit)",
                                 "Unusual: confirm with the facility register")
    return res[cols].sort_values("modified_z", ascending=False)


def status_matrix(rep: pd.DataFrame) -> pd.DataFrame:
    """Facility x month: 2 = on time, 1 = late, 0 = missing."""
    rep = rep.assign(status=np.where(rep.ACTUAL_REPORTS_ON_TIME > 0, 2, np.where(rep.ACTUAL_REPORTS > 0, 1, 0)))
    return rep.pivot_table(index=["district", "ou_name"], columns="pe", values="status", aggfunc="max")


def build_outputs(fac, dist, mon, outl, matrix, context) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    total_exp, total_rec, total_ot = fac.expected.sum(), fac.received.sum(), fac.on_time.sum()
    summary = pd.DataFrame({"metric": [
        "Data source", "Data set", "Facilities", "Overall completeness", "Overall timeliness",
        "Facilities below completeness target", "Silent facilities", "Outlier values found"],
        "value": [context.get("source"), context["dataset"]["name"], len(fac),
                  f"{total_rec / total_exp:.1%}", f"{total_ot / total_exp:.1%}",
                  int((fac.completeness < COMPLETENESS_TARGET).sum()),
                  int((fac.months_silent >= SILENT_MONTHS).sum()), len(outl)]})
    with pd.ExcelWriter(OUTPUT_DIR / "dhis2_reporting_report.xlsx") as xw:
        summary.to_excel(xw, sheet_name="Summary", index=False)
        fac.drop(columns="ou").round(3).to_excel(xw, sheet_name="Facilities", index=False)
        dist.round(3).to_excel(xw, sheet_name="Districts", index=False)
        mon.round(3).to_excel(xw, sheet_name="Monthly", index=False)
        outl.drop(columns="ou").to_excel(xw, sheet_name="Outliers", index=False)
    fac.to_csv(OUTPUT_DIR / "facility_scores.csv", index=False)
    outl.to_csv(OUTPUT_DIR / "outliers.csv", index=False)

    # --- HTML dashboard -----------------------------------------------------
    heat_title = "Report status by facility and month"
    if len(matrix) > MAX_HEATMAP_ROWS:
        worst = fac[fac.priority != "3 - OK"].head(MAX_HEATMAP_ROWS)
        keep = set(zip(worst.district, worst.ou_name))
        matrix = matrix[[i in keep for i in matrix.index]] if keep else matrix.head(MAX_HEATMAP_ROWS)
        heat_title = f"Report status for the {len(matrix)} facilities needing follow-up most (of {len(fac)})"
    months = [pd.to_datetime(str(p), format="%Y%m").strftime("%b %y") for p in matrix.columns]
    labels = [f"{d.replace(' District', '')} | {n}" for d, n in matrix.index]
    heat = go.Figure(go.Heatmap(z=matrix.values, x=months, y=labels, zmin=0, zmax=2, xgap=2, ygap=2,
                                colorscale=[[0, RED], [0.33, RED], [0.34, AMBER], [0.66, AMBER], [0.67, GREEN], [1, GREEN]],
                                colorbar=dict(tickvals=[0.33, 1, 1.67], ticktext=["Missing", "Late", "On time"]),
                                hovertemplate="%{y}<br>%{x}<extra></extra>"))
    heat.update_layout(title=heat_title, height=max(420, 20 * len(labels) + 140), yaxis_autorange="reversed")
    trend = go.Figure()
    trend.add_scatter(x=mon.month, y=mon.completeness, name="Completeness", mode="lines+markers", line_color=NAVY)
    trend.add_scatter(x=mon.month, y=mon.timeliness, name="Timeliness", mode="lines+markers", line_color=AMBER)
    trend.add_hline(y=COMPLETENESS_TARGET, line_dash="dash", line_color=RED, annotation_text="Target")
    trend.update_layout(title="Completeness and timeliness by month", yaxis_tickformat=".0%", yaxis_range=[0, 1.05])
    dbar = go.Figure(go.Bar(x=dist.completeness, y=dist.district, orientation="h",
                            marker_color=[RED if v < COMPLETENESS_TARGET else NAVY for v in dist.completeness],
                            text=[f"{v:.0%}" for v in dist.completeness], textposition="outside"))
    dbar.update_layout(title="Completeness by district", xaxis_tickformat=".0%", xaxis_range=[0, 1.15])
    for f in (trend, dbar):
        f.update_layout(height=340)
    figs = [heat, trend, dbar]
    for f in figs:
        f.update_layout(template="plotly_white", margin=dict(l=40, r=30, t=60, b=40))
    # plotly.js is embedded once, in the first chart that appears on the page (the trend chart)
    h = [f.to_html(full_html=False, include_plotlyjs=(f is trend), config={"displaylogo": False})
         for f in figs]
    cards = "".join(f"<div class='card'><div class='lbl'>{m}</div><div class='val'>{v}</div></div>"
                    for m, v in zip(summary.metric[2:], summary.value[2:]))
    act = fac[fac.priority != "3 - OK"].head(MAX_TABLE_ROWS)
    act_rows = "".join(f"<tr><td>{r['priority']}</td><td>{r['district']}</td><td>{r['ou_name']}</td>"
                       f"<td>{r['completeness']:.0%}</td><td>{r['timeliness']:.0%}</td><td>{r['problems']}</td></tr>"
                       for r in act.to_dict("records"))
    out_rows = "".join(f"<tr><td>{r['district']}</td><td>{r['ou_name']}</td><td>{r['pe']}</td>"
                       f"<td>{r['value']:,.0f}</td><td>{r['facility_median']:,.0f}</td><td>{r['modified_z']}</td>"
                       f"<td>{r['assessment']}</td></tr>"
                       for r in outl.head(MAX_TABLE_ROWS).to_dict("records"))
    page = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>DHIS2 Reporting Check</title>
<style>body{{font-family:'Segoe UI',Arial,sans-serif;margin:0;background:#F4F6F9;color:#222}}
header{{background:{NAVY};color:#fff;padding:18px 28px}} header h1{{margin:0;font-size:22px}}
header p{{margin:4px 0 0;opacity:.85}} main{{padding:20px 28px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:16px}}
.card{{background:#fff;border-radius:8px;padding:12px 14px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
.lbl{{font-size:12px;color:#666}} .val{{font-size:22px;font-weight:600;margin-top:4px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}} .panel{{background:#fff;border-radius:8px;padding:6px}}
.full{{grid-column:1/-1}} table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{padding:6px 8px;border-bottom:1px solid #eee;text-align:left}} th{{background:#FAFAFA}}
@media(max-width:900px){{.grid{{grid-template-columns:1fr}}}}</style></head><body>
<header><h1>DHIS2 Facility Reporting Check: {context['dataset']['name']}</h1>
<p>Source: {context.get('source')} &middot; {context['root']['name']} &middot; value checked: {context['data_element']['name']}</p></header>
<main><div class="cards">{cards}</div><div class="grid">
<div class="panel">{h[1]}</div><div class="panel">{h[2]}</div>
<div class="panel full" style="padding:12px 16px"><h3 style="margin:4px 0 10px">Facilities to follow up</h3>
<table><tr><th>Priority</th><th>District</th><th>Facility</th><th>Completeness</th><th>Timeliness</th><th>Problems</th></tr>{act_rows}</table></div>
<div class="panel full" style="padding:12px 16px"><h3 style="margin:4px 0 10px">Values to verify with the facility (outliers)</h3>
<table><tr><th>District</th><th>Facility</th><th>Month</th><th>Reported value</th><th>Facility's usual (median)</th><th>Modified z</th><th>Assessment</th></tr>{out_rows}</table></div>
<div class="panel full">{h[0]}</div></div></main></body></html>"""
    (OUTPUT_DIR / "dhis2_reporting_dashboard.html").write_text(page, encoding="utf-8")

    # --- README image: reporting status heatmap ---------------------------------
    from matplotlib.colors import ListedColormap
    fig, ax = plt.subplots(figsize=(9, max(4, 0.2 * len(labels) + 1)))
    ax.imshow(matrix.fillna(0).values, cmap=ListedColormap([RED, AMBER, GREEN]), aspect="auto", vmin=0, vmax=2)
    ax.set_xticks(range(len(months)), months, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(labels)), labels, fontsize=7)
    ax.set_title("Report status: green on time, amber late, red missing", loc="left", fontweight="bold")
    fig.tight_layout(); fig.savefig(IMAGE_DIR / "status_heatmap.png", dpi=140); plt.close(fig)


def main() -> None:
    rep = pd.read_csv(DATA_DIR / "reporting.csv", dtype={"pe": str})
    vals = pd.read_csv(DATA_DIR / "values.csv", dtype={"pe": str})
    context = json.loads((DATA_DIR / "context.json").read_text())
    fac, dist, mon = facility_scores(rep), district_scores(rep), monthly_scores(rep)
    outl = find_outliers(vals)
    build_outputs(fac, dist, mon, outl, status_matrix(rep), context)
    print(f"Overall completeness {fac.received.sum() / fac.expected.sum():.1%}, "
          f"timeliness {fac.on_time.sum() / fac.expected.sum():.1%}")
    print(fac.priority.value_counts().sort_index().to_string())
    print(f"Outliers: {len(outl)}")
    print(outl[["ou_name", "pe", "value", "facility_median", "modified_z"]].to_string(index=False))
    print(f"Saved report and dashboard to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
