"""Cross-check the long-term AEP against NREL's open-source OpenOA reference implementation.

Builds an OpenOA PlantData object from the same files (same UTC conversion and
duplicate handling as this project) and runs OpenOA's MonteCarloAEP. The point is
not to match to the decimal; the two methods differ in detail (OpenOA varies the
long-term window length and filters outlier months). The point is to show the
result sits where an independent, widely used method puts it.

Usage:  python scripts/validate_with_openoa.py --data data --out outputs
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def build_plant(data_dir: Path, meta_file: Path):
    from openoa import PlantData
    from openoa.utils import met_data_processing as met

    scada = pd.read_csv(data_dir / "la-haute-borne-data-2014-2015.csv")
    scada["Date_time"] = pd.to_datetime(scada["Date_time"], utc=True).dt.tz_localize(None)
    scada = scada.drop_duplicates(subset=["Date_time", "Wind_turbine_name"], keep="first")
    scada = scada[(scada["Ot_avg"] >= -15.0) & (scada["Ot_avg"] <= 45.0)]
    scada["Ba_avg"] = scada["Ba_avg"] % 360
    scada.loc[scada["Ba_avg"] > 180.0, "Ba_avg"] -= 360.0

    plant = pd.read_csv(data_dir / "plant_data.csv")
    plant["time"] = pd.to_datetime(plant["time_utc"]).dt.tz_localize(None)
    meter = plant[["time", "net_energy_kwh"]].copy()
    curtail = plant[["time", "availability_kwh", "curtailment_kwh"]].copy()

    merra2 = pd.read_csv(data_dir / "merra2_la_haute_borne.csv")
    merra2["datetime"] = pd.to_datetime(merra2["datetime"], utc=True).dt.tz_localize(None)
    merra2["winddirection_deg"] = met.compute_wind_direction(merra2["u_50"], merra2["v_50"])
    merra2 = merra2.drop(columns=["Unnamed: 0"])

    era5 = pd.read_csv(data_dir / "era5_wind_la_haute_borne.csv")
    era5 = era5.loc[:, ~era5.columns.duplicated()].copy()
    era5["datetime"] = pd.to_datetime(era5["datetime"], utc=True).dt.tz_localize(None)
    era5 = era5.set_index(pd.DatetimeIndex(era5["datetime"])).asfreq("1h")
    era5["datetime"] = era5.index
    era5["winddirection_deg"] = met.compute_wind_direction(era5["u_100"], era5["v_100"]).values
    era5 = era5.drop(columns=["Unnamed: 0"])

    asset = pd.read_csv(data_dir / "la-haute-borne_asset_table.csv")
    asset["type"] = "turbine"

    return PlantData(
        analysis_type="MonteCarloAEP",
        metadata=str(meta_file),
        scada=scada,
        meter=meter,
        curtail=curtail,
        asset=asset,
        reanalysis={"era5": era5, "merra2": merra2},
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="outputs")
    ap.add_argument("--sims", type=int, default=2000)
    args = ap.parse_args()

    from openoa.analysis.aep import MonteCarloAEP

    data_dir = Path(args.data)
    meta = Path(__file__).resolve().parent / "plant_meta.yml"
    plant = build_plant(data_dir, meta)
    np.random.seed(42)
    pa = MonteCarloAEP(plant, reanalysis_products=["era5", "merra2"])
    pa.run(num_sim=args.sims, reanalysis_products=["era5", "merra2"])
    aep = pa.results["aep_GWh"]
    summary = {
        "openoa_p50_gwh": float(aep.median()),
        "openoa_mean_gwh": float(aep.mean()),
        "openoa_p90_gwh": float(aep.quantile(0.10)),
        "openoa_uncertainty_pct": float(100 * aep.std() / aep.mean()),
        "openoa_simulations": int(args.sims),
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "openoa_validation.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
