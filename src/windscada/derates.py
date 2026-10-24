"""Turning interval-level derate flags into events and looking for recurring patterns.

An event is a run of derate intervals on one turbine; gaps of up to 20 minutes are
bridged so that one event is not split by a single normal reading. Events shorter
than 30 minutes are dropped. Recurrence is examined by hour of day, month and wind
direction sector, because a derate that repeats on a schedule or in a sector usually
has an operational cause (noise or wildlife curtailment, sector management, a
control setting) rather than a random fault.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

GAP_BRIDGE = 2  # intervals
MIN_EVENT = 3  # intervals


def find_events(df: pd.DataFrame, state: str = "derate") -> pd.DataFrame:
    rows = []
    for turbine, sub in df.sort_values("time").groupby("turbine"):
        flag = (sub["state"] == state).to_numpy()
        n = len(flag)
        i = 0
        while i < n:
            if not flag[i]:
                i += 1
                continue
            start = i
            end = i
            j = i + 1
            gap = 0
            while j < n:
                if flag[j]:
                    end = j
                    gap = 0
                else:
                    gap += 1
                    if gap > GAP_BRIDGE:
                        break
                j += 1
            seg = sub.iloc[start : end + 1]
            hits = seg[seg["state"] == state]
            if len(hits) >= MIN_EVENT:
                rows.append(
                    {
                        "turbine": turbine,
                        "start_utc": seg["time"].iloc[0],
                        "end_utc": seg["time"].iloc[-1] + pd.Timedelta(minutes=10),
                        "duration_h": len(seg) / 6.0,
                        "mean_wind_ms": hits["wind_norm_ms"].mean(),
                        "mean_pitch_deg": hits["pitch_deg"].mean(),
                        "mean_power_kw": hits["power_kw"].mean(),
                        "mean_expected_kw": hits["expected_kw"].mean(),
                        "mean_temp_c": hits["temp_c"].mean(),
                        "mean_wind_dir_deg": _circular_mean(hits["wind_dir_deg"]),
                        "lost_mwh": hits["lost_kwh"].sum() / 1000.0,
                    }
                )
            i = end + 1
    events = pd.DataFrame(rows)
    if not events.empty:
        events = events.sort_values("lost_mwh", ascending=False).reset_index(drop=True)
    return events


def _circular_mean(deg: pd.Series) -> float:
    rad = np.deg2rad(deg.dropna())
    if rad.empty:
        return float("nan")
    return float(np.rad2deg(np.arctan2(np.sin(rad).mean(), np.cos(rad).mean())) % 360)


def recurrence(df: pd.DataFrame, state: str = "derate") -> dict[str, pd.DataFrame]:
    """Share of producing intervals in the given state, by hour, month and direction sector."""
    sub = df[df["qc_valid"] & (df["expected_kw"] >= 50.0)].copy()
    local = sub["time"].dt.tz_convert("Europe/Paris")
    sub["hour_local"] = local.dt.hour
    sub["month"] = local.dt.month
    sub["sector"] = ((sub["wind_dir_deg"] + 15) // 30 % 12 * 30).astype("Int64")
    sub["temp_band_c"] = pd.cut(sub["temp_c"], [-40, -5, 0, 5, 10, 15, 20, 25, 30, 50],
                                labels=["below -5", "-5 to 0", "0 to 5", "5 to 10", "10 to 15", "15 to 20",
                                        "20 to 25", "25 to 30", "above 30"])
    sub["hit"] = sub["state"] == state
    out = {}
    for key in ["hour_local", "month", "sector", "temp_band_c"]:
        g = sub.groupby(key, observed=True)["hit"].agg(["mean", "sum", "size"])
        g["mean"] = g["mean"] * 100
        out[key] = g.rename(columns={"mean": "pct_of_intervals", "sum": "intervals", "size": "eligible"})
    by_turbine = sub.groupby(["turbine", "hour_local"])["hit"].mean().mul(100).unstack("hour_local")
    out["turbine_by_hour"] = by_turbine
    return out
