"""Run the full analysis: data quality, power curves, lost production, derates and long-term AEP.

Usage:
    python scripts/get_data.py            # once, downloads and unzips the open dataset into ./data
    python run_analysis.py                # writes tables to ./outputs and figures to ./figures
    python run_analysis.py --data path/to/data --draws 10000
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from windscada import aep, derates, io, losses, plots, qc  # noqa: E402
from windscada import power_curve as pc  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--out", default=str(ROOT / "outputs"))
    ap.add_argument("--figures", default=str(ROOT / "figures"))
    ap.add_argument("--draws", type=int, default=10000)
    args = ap.parse_args()

    data_dir, out, figs = Path(args.data), Path(args.out), Path(args.figures)
    (out / "tables").mkdir(parents=True, exist_ok=True)
    figs.mkdir(parents=True, exist_ok=True)

    print("1/6 Loading and checking data")
    scada = io.load_scada(data_dir)
    plant = io.load_plant(data_dir)
    era5 = io.load_reanalysis(data_dir, "era5")
    df = qc.apply_qc(scada)
    qc_table = qc.qc_summary(df)
    qc_table.to_csv(out / "tables" / "01_data_quality_by_turbine.csv")
    avail = qc.monthly_availability(df)
    plots.data_availability(avail, figs / "fig01_data_availability.png")

    print("2/6 Building power curves")
    df = pc.add_air_density(df, era5)
    plant_flags = (plant["availability_kwh"] > 0) | (plant["curtailment_kwh"] > 0)
    normal = pc.normal_operation_mask(df, plant_flags)
    curves = pc.reference_curves(df, normal)
    curves.round(1).to_csv(out / "tables" / "02_reference_power_curves_kw.csv")
    pitch_curve = pc.normal_pitch_curve(df, normal)
    df["expected_kw"] = pc.expected_power(df, curves)
    sigma_curve = pc.residual_sigma_curve(df, normal, df["expected_kw"])
    plots.power_curves(df, normal, curves, figs / "fig02_power_curves.png")

    print("3/6 Classifying intervals and estimating lost production")
    df["state"] = losses.classify(df, pitch_curve, sigma_curve, plant["curtailment_kwh"])
    df["lost_kwh"] = losses.lost_energy_kwh(df)
    loss_table = losses.loss_table(df)
    loss_table.to_csv(out / "tables" / "03_lost_production_by_turbine_mwh.csv")
    losses.monthly_losses(df).to_csv(out / "tables" / "04_lost_production_by_month_mwh.csv")
    df["state"].value_counts().rename("intervals").to_csv(out / "tables" / "05_interval_classes.csv")
    elec = losses.electrical_losses(df, plant)
    plots.losses_by_turbine(loss_table, losses.LOSS_CLASSES, figs / "fig03_lost_production.png")

    print("4/6 Finding derate events and recurring patterns")
    events = derates.find_events(df)
    # round the numeric columns only (newer pandas warns when asked to round the timestamps)
    events.round({c: 3 for c in events.select_dtypes("number").columns}).to_csv(
        out / "tables" / "06_derate_events.csv", index=False)
    rec = derates.recurrence(df)
    for key, table in rec.items():
        table.round(3).to_csv(out / "tables" / f"07_derate_recurrence_{key}.csv")
    plots.derate_recurrence(rec, figs / "fig04_derate_recurrence.png")
    if not events.empty:
        plots.derate_event(df, events.iloc[0], figs / "fig05_largest_derate_event.png")

    print("5/6 Long-term corrected AEP with Monte Carlo uncertainty")
    result, extra = aep.run_aep(data_dir, plant, n_draws=args.draws)
    result.fits.round(4).to_csv(out / "tables" / "08_aep_regression_fits.csv", index=False)
    extra["monthly"].round(3).to_csv(out / "tables" / "09_monthly_energy_and_wind.csv")
    plots.aep_regression(extra["monthly"], result.fits, figs / "fig06_aep_regression.png")
    openoa_file = out / "openoa_validation.json"
    openoa = json.loads(openoa_file.read_text()) if openoa_file.exists() else None
    plots.aep_distribution(result, openoa["openoa_p50_gwh"] if openoa else None, figs / "fig07_aep_distribution.png")

    print("6/6 Writing summary")
    farm = loss_table.loc["Wind farm"]
    summary = {
        "data": {
            "turbines": int(df["turbine"].nunique()),
            "period_utc": [str(df["time"].min()), str(df["time"].max())],
            "intervals": int(len(df)),
            "duplicates_removed": int(df.attrs.get("duplicates_removed", 0)),
            "secondary_values_blanked": df.attrs.get("secondary_values_blanked", {}),
            "valid_pct": round(float(df["qc_valid"].mean() * 100), 2),
            "reference_air_density_kg_m3": round(float(df.attrs["rho_ref"]), 4),
            "normal_operation_pct_of_valid": round(float(normal.sum() / df["qc_valid"].sum() * 100), 1),
        },
        "production_2014_2015_mwh": {
            "actual_scada": round(float(farm["actual"]), 1),
            "lost_total": round(float(farm["total_lost"]), 1),
            "lost_by_class": {c: round(float(farm[c]), 1) for c in losses.LOSS_CLASSES},
            "lost_pct_of_potential": round(float(farm["lost_pct_of_potential"]), 2),
            "energy_availability_pct": round(float(farm["energy_availability_pct"]), 2),
            "plant_reported_availability_loss": round(float(plant["availability_kwh"].sum() / 1000), 1),
            "plant_reported_curtailment_loss": round(float(plant["curtailment_kwh"].sum() / 1000), 1),
            "revenue_meter_net": round(float(plant["net_energy_kwh"].sum() / 1000), 1),
            "electrical_losses": elec,
        },
        "derates": {
            "events": int(len(events)),
            "event_lost_mwh": round(float(events["lost_mwh"].sum()), 1) if not events.empty else 0.0,
            "peak_hour_local": int(rec["hour_local"]["pct_of_intervals"].idxmax()),
            "share_above_30c_pct": round(float(rec["temp_band_c"].loc["above 30", "pct_of_intervals"]), 2),
            "share_10_to_15c_pct": round(float(rec["temp_band_c"].loc["10 to 15", "pct_of_intervals"]), 2),
        },
        "aep": {
            "p50_gwh": round(result.p50_gwh, 2),
            "p90_long_term_gwh": round(result.p90_lt_gwh, 2),
            "p90_one_year_gwh": round(float(result.p90_1yr_gwh), 2),
            "p90_ten_year_gwh": round(float(result.p90_10yr_gwh), 2),
            "long_term_uncertainty_pct": round(result.uncertainty_lt_pct, 2),
            "interannual_variability_pct": round(result.iav_pct, 2),
            "availability_and_curtailment_loss_pct": round(float(result.loss_ratio_pct), 2),
            "p50_by_product_gwh": {k: round(v, 2) for k, v in result.product_p50_gwh.items()},
            "capacity_factor_pct": round(result.p50_gwh * 1000 / (8.2 * 8766) * 100, 1),
            "draws": args.draws,
        },
    }
    if openoa:
        summary["aep"]["openoa_p50_gwh"] = round(openoa["openoa_p50_gwh"], 2)
        summary["aep"]["openoa_p90_gwh"] = round(openoa["openoa_p90_gwh"], 2)
        summary["aep"]["difference_vs_openoa_pct"] = round(
            100 * (result.p50_gwh - openoa["openoa_p50_gwh"]) / openoa["openoa_p50_gwh"], 2)
    (out / "results.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
