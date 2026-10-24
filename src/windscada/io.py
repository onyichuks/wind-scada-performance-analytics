"""Loading the La Haute Borne open dataset into tidy, time-zone aware tables.

All timestamps are converted to UTC. The raw SCADA file stores local French time
with an offset, which creates a handful of duplicate records around daylight
saving changes; those are removed (first record kept) and the count is reported.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

SCADA_FILE = "la-haute-borne-data-2014-2015.csv"
ASSET_FILE = "la-haute-borne_asset_table.csv"
PLANT_FILE = "plant_data.csv"
ERA5_FILE = "era5_wind_la_haute_borne.csv"
MERRA2_FILE = "merra2_la_haute_borne.csv"

SCADA_COLUMNS = {
    "Wind_turbine_name": "turbine",
    "Ba_avg": "pitch_deg",
    "P_avg": "power_kw",
    "Ws_avg": "wind_ms",
    "Va_avg": "vane_deg",
    "Ot_avg": "temp_c",
    "Ya_avg": "nacelle_deg",
    "Wa_avg": "wind_dir_deg",
}

REANALYSIS = {
    # product: (file, wind speed column, air density column, height note)
    "era5": (ERA5_FILE, "ws_100m", "dens_100m", "100 m"),
    "merra2": (MERRA2_FILE, "ws_50m", "dens_50m", "50 m"),
}


def load_scada(data_dir: str | Path) -> pd.DataFrame:
    """Return 10-minute SCADA data on a complete grid (one row per turbine and interval).

    Missing intervals are kept as rows with empty values so that data availability
    can be measured honestly instead of being hidden by absent rows.
    """
    raw = pd.read_csv(Path(data_dir) / SCADA_FILE)
    raw["time"] = pd.to_datetime(raw["Date_time"], utc=True)
    df = raw.drop(columns="Date_time").rename(columns=SCADA_COLUMNS)

    n_before = len(df)
    df = df.drop_duplicates(subset=["turbine", "time"], keep="first")
    duplicates = n_before - len(df)

    grid = pd.MultiIndex.from_product(
        [sorted(df["turbine"].unique()), pd.date_range(df["time"].min(), df["time"].max(), freq="10min")],
        names=["turbine", "time"],
    )
    df = df.set_index(["turbine", "time"]).reindex(grid).reset_index()
    df.attrs["duplicates_removed"] = duplicates
    return df


def load_assets(data_dir: str | Path) -> pd.DataFrame:
    assets = pd.read_csv(Path(data_dir) / ASSET_FILE)
    return assets.rename(
        columns={
            "Wind_turbine_name": "turbine",
            "Rated_power": "rated_kw",
            "Hub_height_m": "hub_height_m",
            "Rotor_diameter_m": "rotor_diameter_m",
        }
    )


def load_plant(data_dir: str | Path) -> pd.DataFrame:
    """Plant revenue meter, availability loss and curtailment loss, 10-minute, in kWh."""
    plant = pd.read_csv(Path(data_dir) / PLANT_FILE)
    plant["time"] = pd.to_datetime(plant["time_utc"], utc=True)
    return plant.drop(columns="time_utc").set_index("time").sort_index()


def load_reanalysis(data_dir: str | Path, product: str) -> pd.DataFrame:
    """Hourly reanalysis wind speed and air density for one product, indexed by UTC time."""
    file, ws_col, dens_col, _ = REANALYSIS[product]
    rean = pd.read_csv(Path(data_dir) / file)
    rean["time"] = pd.to_datetime(rean["datetime"], utc=True)
    rean = rean.set_index("time").sort_index()
    return rean[[ws_col, dens_col]].rename(columns={ws_col: "ws", dens_col: "density"})
