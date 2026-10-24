"""Data quality checks for 10-minute turbine SCADA data.

Rules are deliberately simple and documented so that every flag can be explained:

* missing: power or wind speed absent for the interval
* out of range: physically implausible power or wind speed
* frozen anemometer: wind speed identical for one hour or more while the turbine reports data
* secondary sensors (pitch, temperature, direction): implausible values are blanked,
  but the interval stays usable for power and wind analysis
"""
from __future__ import annotations

import numpy as np
import pandas as pd

PRIMARY_LIMITS = {"power_kw": (-50.0, 2300.0), "wind_ms": (0.0, 40.0)}
SECONDARY_LIMITS = {"pitch_deg": (-5.0, 95.0), "temp_c": (-40.0, 50.0), "wind_dir_deg": (0.0, 360.0)}
FROZEN_INTERVALS = 6  # one hour of identical wind speed readings


def _run_length(values: pd.Series) -> pd.Series:
    """Length of the run of identical consecutive values that each element belongs to."""
    change = values.ne(values.shift()).cumsum()
    return values.groupby(change).transform("size")


def apply_qc(scada: pd.DataFrame) -> pd.DataFrame:
    df = scada.copy()

    df["qc_missing"] = df[["power_kw", "wind_ms"]].isna().any(axis=1)

    out_of_range = pd.Series(False, index=df.index)
    for col, (lo, hi) in PRIMARY_LIMITS.items():
        out_of_range |= df[col].notna() & ~df[col].between(lo, hi)
    df["qc_out_of_range"] = out_of_range

    frozen = pd.Series(False, index=df.index)
    for _, idx in df.groupby("turbine").groups.items():
        ws = df.loc[idx, "wind_ms"]
        runs = _run_length(ws.fillna(-999.0))
        frozen.loc[idx] = ws.notna() & (runs >= FROZEN_INTERVALS) & (ws > 0)
    df["qc_frozen_wind"] = frozen

    blanked = {}
    for col, (lo, hi) in SECONDARY_LIMITS.items():
        bad = df[col].notna() & ~df[col].between(lo, hi)
        blanked[col] = int(bad.sum())
        df.loc[bad, col] = np.nan
    df.attrs["secondary_values_blanked"] = blanked
    df.attrs["duplicates_removed"] = scada.attrs.get("duplicates_removed", 0)

    df["qc_valid"] = ~(df["qc_missing"] | df["qc_out_of_range"] | df["qc_frozen_wind"])
    return df


def qc_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Share of intervals failing each rule, per turbine."""
    cols = ["qc_missing", "qc_out_of_range", "qc_frozen_wind", "qc_valid"]
    summary = df.groupby("turbine")[cols].mean().mul(100).round(2)
    summary.columns = ["missing_pct", "out_of_range_pct", "frozen_wind_pct", "valid_pct"]
    return summary


def monthly_availability(df: pd.DataFrame) -> pd.DataFrame:
    """Percent of valid 10-minute intervals per turbine and month (for the data availability heatmap)."""
    month = df["time"].dt.tz_convert(None).dt.to_period("M")
    return df.groupby(["turbine", month])["qc_valid"].mean().mul(100).unstack("time")
