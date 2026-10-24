"""Build the interactive dashboard (docs/index.html) for GitHub Pages.

Runs the analysis under three derate thresholds, condenses the results into compact
JSON and embeds it in dashboard/template.html. The page needs no server: all
filtering happens in the visitor's browser.

Usage:  python scripts/build_dashboard.py --data data
Run python run_analysis.py first so outputs/results.json exists.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from windscada import aep, derates, losses, pipeline, qc  # noqa: E402

THRESHOLDS = [2.0, 2.5, 3.0]
SCATTER_PER_TURBINE = 3500
EVENTS_WITH_SERIES = 40
TEMP_BANDS = [-40, -5, 0, 5, 10, 15, 20, 25, 30, 50]
TEMP_LABELS = ["below -5", "-5 to 0", "0 to 5", "5 to 10", "10 to 15", "15 to 20", "20 to 25", "25 to 30",
               "above 30"]


def r(values, nd=1):
    arr = np.asarray(values, dtype=float)
    return [None if not np.isfinite(v) else round(float(v), nd) for v in arr]


def scenario_payload(df: pd.DataFrame, turbines: list[str], months: list[str]) -> dict:
    df = df.copy()
    df["date"] = df["time"].dt.tz_convert(None).dt.strftime("%Y-%m-%d")
    actual = (df["power_kw"].clip(lower=0.0) / 6.0).where(df["qc_valid"], 0.0)
    df["actual_kwh"] = actual
    dates = sorted(df["date"].unique())

    daily = {"dates": dates}
    grp_actual = df.groupby(["turbine", "date"])["actual_kwh"].sum()
    grp_lost = df[df["state"].isin(losses.LOSS_CLASSES)].groupby(["turbine", "date", "state"])["lost_kwh"].sum()
    for t in turbines:
        entry = {"actual": r(grp_actual.loc[t].reindex(dates).fillna(0) / 1000, 3)}
        for c in losses.LOSS_CLASSES:
            try:
                s = grp_lost.xs((t, c), level=("turbine", "state"))
            except KeyError:
                s = pd.Series(dtype=float)
            entry[c] = r(s.reindex(dates).fillna(0) / 1000, 3)
        daily[t] = entry

    # recurrence counts by turbine, month, hour and temperature band, so the page can filter
    sub = df[df["qc_valid"] & (df["expected_kw"] >= 50.0)].copy()
    local = sub["time"].dt.tz_convert("Europe/Paris")
    sub["hour"] = local.dt.hour
    sub["month"] = sub["time"].dt.tz_convert(None).dt.strftime("%Y-%m")
    sub["band"] = pd.cut(sub["temp_c"], TEMP_BANDS, labels=range(len(TEMP_LABELS))).astype("float")
    sub["hit"] = (sub["state"] == "derate").astype(int)
    rec = {}
    for t in turbines:
        st = sub[sub["turbine"] == t]
        hour_hits = st.pivot_table(index="month", columns="hour", values="hit", aggfunc="sum").reindex(
            index=months, columns=range(24)).fillna(0)
        hour_n = st.pivot_table(index="month", columns="hour", values="hit", aggfunc="size").reindex(
            index=months, columns=range(24)).fillna(0)
        stb = st.dropna(subset=["band"])
        band_hits = stb.pivot_table(index="month", columns="band", values="hit", aggfunc="sum").reindex(
            index=months, columns=[float(i) for i in range(len(TEMP_LABELS))]).fillna(0)
        band_n = stb.pivot_table(index="month", columns="band", values="hit", aggfunc="size").reindex(
            index=months, columns=[float(i) for i in range(len(TEMP_LABELS))]).fillna(0)
        rec[t] = {
            "hour_hits": hour_hits.astype(int).values.tolist(),
            "hour_n": hour_n.astype(int).values.tolist(),
            "band_hits": band_hits.astype(int).values.tolist(),
            "band_n": band_n.astype(int).values.tolist(),
        }

    events = derates.find_events(df)
    ev_list, series = [], {}
    pad = pd.Timedelta(hours=2)
    for i, ev in events.iterrows():
        eid = f"e{i}"
        ev_list.append({
            "id": eid, "turbine": ev["turbine"],
            "start": ev["start_utc"].tz_convert("Europe/Paris").strftime("%Y-%m-%d %H:%M"),
            "end": ev["end_utc"].tz_convert("Europe/Paris").strftime("%Y-%m-%d %H:%M"),
            "month": ev["start_utc"].tz_convert(None).strftime("%Y-%m"),
            "duration_h": round(float(ev["duration_h"]), 2),
            "wind": round(float(ev["mean_wind_ms"]), 1),
            "pitch": round(float(ev["mean_pitch_deg"]), 1),
            "power": round(float(ev["mean_power_kw"])),
            "expected": round(float(ev["mean_expected_kw"])),
            "temp": None if pd.isna(ev["mean_temp_c"]) else round(float(ev["mean_temp_c"]), 1),
            "lost_mwh": round(float(ev["lost_mwh"]), 3),
            "has_series": i < EVENTS_WITH_SERIES,
        })
        if i < EVENTS_WITH_SERIES:
            w = df[(df["turbine"] == ev["turbine"]) & (df["time"] >= ev["start_utc"] - pad)
                   & (df["time"] <= ev["end_utc"] + pad)]
            series[eid] = {
                "t": w["time"].dt.tz_convert("Europe/Paris").dt.strftime("%Y-%m-%d %H:%M").tolist(),
                "p": r(w["power_kw"], 0), "e": r(w["expected_kw"], 0),
                "ws": r(w["wind_norm_ms"], 2), "pitch": r(w["pitch_deg"], 1),
            }
    return {"daily": daily, "recurrence": rec, "events": ev_list, "event_count": int(len(events)),
            "series": series}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--draws", type=int, default=10000)
    ap.add_argument("--repo-url", default="https://github.com/onyichuks/wind-scada-performance-analytics")
    args = ap.parse_args()

    prep = pipeline.prepare(args.data)
    df = prep.df
    turbines = sorted(df["turbine"].unique())
    months = sorted(df["time"].dt.tz_convert(None).dt.strftime("%Y-%m").unique())

    avail = qc.monthly_availability(df)
    rng = np.random.default_rng(7)
    scatter = {}
    for t in turbines:
        sub = df[(df["turbine"] == t) & df["qc_valid"] & df["wind_norm_ms"].notna()]
        idx = rng.choice(len(sub), size=min(SCATTER_PER_TURBINE, len(sub)), replace=False)
        s = sub.iloc[np.sort(idx)]
        scatter[t] = {"ws": r(s["wind_norm_ms"], 2), "p": r(s["power_kw"], 0),
                      "n": prep.normal.loc[s.index].astype(int).tolist()}

    result, extra = aep.run_aep(args.data, prep.plant, n_draws=args.draws)
    monthly = extra["monthly"]
    counts, edges = np.histogram(result.draws_gwh, bins=50)
    results_file = ROOT / "outputs" / "results.json"
    summary = json.loads(results_file.read_text()) if results_file.exists() else {}

    payload = {
        "meta": {
            "turbines": turbines, "months": months, "thresholds": THRESHOLDS, "default_threshold": 2.5,
            "rated_kw": 2050, "capacity_mw": 8.2, "temp_labels": TEMP_LABELS,
            "loss_classes": losses.LOSS_CLASSES,
        },
        "summary": summary,
        "quality": {"months": [str(m) for m in avail.columns], "turbines": list(avail.index),
                    "valid_pct": [r(row, 2) for row in avail.values]},
        "curves": {"bins": r(prep.curves.index, 2),
                   **{t: r(prep.curves[t], 0) for t in turbines}},
        "scatter": scatter,
        "aep": {
            "months": [d.strftime("%Y-%m") for d in monthly.index],
            "gross_mwh_day": r(monthly["gross_kwh"] / monthly["days"] / 1000, 2),
            "ws_era5": r(monthly["ws_era5"], 2), "ws_merra2": r(monthly["ws_merra2"], 2),
            "fits": result.fits.round(4).to_dict(orient="records"),
            "hist_counts": counts.tolist(), "hist_edges": r(edges, 3),
            "p50": round(result.p50_gwh, 2), "p90_lt": round(result.p90_lt_gwh, 2),
            "p90_1yr": round(float(result.p90_1yr_gwh), 2), "p90_10yr": round(float(result.p90_10yr_gwh), 2),
            "unc_lt_pct": round(result.uncertainty_lt_pct, 2), "iav_pct": round(result.iav_pct, 2),
            "by_product": {k: round(v, 2) for k, v in result.product_p50_gwh.items()},
        },
        "scenarios": {},
    }
    for th in THRESHOLDS:
        print(f"Scenario: derate when pitch is {th} degrees above normal")
        payload["scenarios"][str(th)] = scenario_payload(pipeline.classify(prep, th), turbines, months)

    data = json.dumps(payload, separators=(",", ":"))
    template = (ROOT / "dashboard" / "template.html").read_text(encoding="utf-8")
    html = template.replace("/*__DATA__*/null", data)
    label = args.repo_url.replace("https://", "")
    html = html.replace("{{REPO_URL}}", args.repo_url).replace("{{REPO_LABEL}}", label)
    out = ROOT / "docs" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    (ROOT / "docs" / ".nojekyll").write_text("")
    print(f"Wrote {out} ({out.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
