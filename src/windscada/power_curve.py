"""Empirical power curves and expected power.

Method (kept close to IEC 61400-12-1 practice where the data allows):

1. Air density correction. Nacelle wind speed is normalised to the site mean air
   density with V_n = V * (rho / rho_ref) ** (1/3), the form used for pitch-regulated
   turbines. Air density comes from ERA5 at 100 m (close to the 80 m hub height),
   interpolated from hourly to 10-minute values.
2. Normal operation filter. Keep valid intervals where the turbine is producing,
   the plant reports no availability or curtailment loss, pitch is at its normal
   value for the wind speed, and power sits within a robust band of the bin median.
3. Binning. 0.5 m/s bins from 3 to 20 m/s; median power per bin per turbine, with a
   minimum bin count. The curve is forced to rise monotonically up to rated power.

There is no manufacturer warranted power curve in the open data, so each turbine is
compared with its own normal-operation curve. That makes the method good at finding
lost production and derates, but it cannot judge whether a turbine meets its warranty.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

RATED_KW = 2050.0
CUT_IN_MS = 3.5
CUT_OUT_MS = 25.0
BIN_WIDTH = 0.5
BIN_EDGES = np.arange(3.0, 20.0 + BIN_WIDTH, BIN_WIDTH)
BIN_CENTRES = BIN_EDGES[:-1] + BIN_WIDTH / 2
MIN_BIN_COUNT = 20
PITCH_EXCESS_DEG = 2.5
MAD_LIMIT = 3.0


def add_air_density(df: pd.DataFrame, era5: pd.DataFrame) -> pd.DataFrame:
    """Attach air density (kg/m3) and density-normalised wind speed."""
    out = df.copy()
    times = pd.DatetimeIndex(out["time"].unique()).sort_values()
    dens = era5["density"].reindex(era5.index.union(times)).interpolate("time").reindex(times)
    out["density"] = out["time"].map(dens)
    rho_ref = float(out["density"].mean())
    out["wind_norm_ms"] = out["wind_ms"] * (out["density"] / rho_ref) ** (1.0 / 3.0)
    out.attrs.update(df.attrs)
    out.attrs["rho_ref"] = rho_ref
    return out


def _bin(ws: pd.Series) -> pd.Series:
    return pd.cut(ws, BIN_EDGES, labels=BIN_CENTRES, include_lowest=True).astype(float)


def normal_operation_mask(df: pd.DataFrame, plant_flags: pd.Series) -> pd.Series:
    """True where the interval represents normal, unconstrained operation."""
    producing = df["power_kw"] > 10.0
    in_range = df["wind_norm_ms"].between(CUT_IN_MS, 20.0)
    plant_ok = ~df["time"].map(plant_flags).fillna(False).astype(bool)
    base = df["qc_valid"] & producing & in_range & plant_ok

    wbin = _bin(df["wind_norm_ms"])
    pitch_normal = df[base].groupby(wbin[base])["pitch_deg"].median()
    pitch_ok = (df["pitch_deg"] - wbin.map(pitch_normal)).fillna(0.0) <= PITCH_EXCESS_DEG

    keep = base & pitch_ok
    # robust band around the bin median, per turbine
    band_ok = pd.Series(False, index=df.index)
    for _, idx in df[keep].groupby("turbine").groups.items():
        sub = df.loc[idx]
        b = wbin.loc[idx]
        med = sub.groupby(b)["power_kw"].transform("median")
        mad = (sub["power_kw"] - med).abs().groupby(b).transform("median") * 1.4826
        band_ok.loc[idx] = (sub["power_kw"] - med).abs() <= MAD_LIMIT * mad.clip(lower=10.0)
    return keep & band_ok


def reference_curves(df: pd.DataFrame, normal: pd.Series) -> pd.DataFrame:
    """Median power per wind speed bin for each turbine, built from normal operation only."""
    sub = df[normal]
    wbin = _bin(sub["wind_norm_ms"])
    grouped = sub.groupby(["turbine", wbin])["power_kw"].agg(["median", "size"])
    grouped = grouped[grouped["size"] >= MIN_BIN_COUNT]["median"].unstack("turbine")
    grouped = grouped.reindex(BIN_CENTRES).interpolate(limit_area="inside")
    grouped = grouped.cummax().clip(upper=RATED_KW)
    grouped.index.name = "wind_bin_ms"
    return grouped


def normal_pitch_curve(df: pd.DataFrame, normal: pd.Series) -> pd.Series:
    """Median pitch angle per wind speed bin in normal operation (all turbines)."""
    sub = df[normal]
    curve = sub.groupby(_bin(sub["wind_norm_ms"]))["pitch_deg"].median()
    return curve.reindex(BIN_CENTRES).interpolate(limit_direction="both")


def residual_sigma_curve(df: pd.DataFrame, normal: pd.Series, expected: pd.Series) -> pd.Series:
    """Robust spread (1.4826 x median absolute deviation) of power about expected, per wind bin.

    Used to tell a real shortfall from normal scatter: at low wind speeds a 15 percent
    gap is ordinary noise, at mid wind speeds it is not.
    """
    resid = (df["power_kw"] - expected)[normal]
    wbin = _bin(df.loc[normal, "wind_norm_ms"])
    sigma = resid.abs().groupby(wbin).median() * 1.4826
    return sigma.reindex(BIN_CENTRES).interpolate(limit_direction="both").clip(lower=10.0)


def expected_power(df: pd.DataFrame, curves: pd.DataFrame) -> pd.Series:
    """Power each turbine should have produced at the measured, density-normalised wind speed."""
    expected = pd.Series(np.nan, index=df.index)
    for turbine, idx in df.groupby("turbine").groups.items():
        curve = curves[turbine].dropna()
        ws = df.loc[idx, "wind_norm_ms"]
        p = np.interp(ws, curve.index.values, curve.values, left=0.0, right=float(curve.iloc[-1]))
        p = np.where(ws < CUT_IN_MS, 0.0, p)
        p = np.where(ws > CUT_OUT_MS, 0.0, p)
        expected.loc[idx] = np.where(ws.isna(), np.nan, p)
    return expected
