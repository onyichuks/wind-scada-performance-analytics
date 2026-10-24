"""Classifying every 10-minute interval and estimating lost production.

Each valid interval is placed in exactly one class, checked in this order:

1. downtime        turbine not producing (power at or below 10 kW) while the wind
                   could have produced at least 50 kW
2. curtailment     the plant reports a curtailment loss for the interval
3. derate          pitch at least 2.5 degrees above the turbine's normal pitch for
                   that wind speed, with power below 90 percent of expected
                   (the turbine is limiting its own output)
4. suspected icing outdoor temperature at or below 2 C, power below 75 percent
                   of expected and more than three robust standard deviations
                   below it, with pitch at its normal value (blade performance loss)
5. underperformance power more than three robust standard deviations below
                   expected (and below 90 percent of it) for any other reason
6. normal          everything else

Lost energy for an interval is (expected power - actual power) / 6, in kWh,
counted only for classes 1 to 5. Small shortfalls inside normal operation are
treated as noise and not counted, which keeps the estimate conservative.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .power_curve import BIN_CENTRES, BIN_EDGES, PITCH_EXCESS_DEG

CLASSES = ["downtime", "curtailment", "derate", "suspected icing", "underperformance", "normal"]
LOSS_CLASSES = CLASSES[:-1]


def classify(
    df: pd.DataFrame,
    pitch_curve: pd.Series,
    sigma_curve: pd.Series,
    plant_curtailment: pd.Series,
    pitch_excess_deg: float = PITCH_EXCESS_DEG,
) -> pd.Series:
    """Label each interval. pitch_excess_deg sets how far above normal pitch counts as a derate."""
    wbin = pd.cut(df["wind_norm_ms"], BIN_EDGES, labels=BIN_CENTRES, include_lowest=True).astype(float)
    normal_pitch = wbin.map(pitch_curve)
    # above the binned range the turbine is at rated; use the last bin's normal pitch
    normal_pitch = normal_pitch.fillna(float(pitch_curve.iloc[-1]))
    pitch_excess = df["pitch_deg"] - normal_pitch
    sigma = wbin.map(sigma_curve).fillna(float(sigma_curve.iloc[-1]))

    exp = df["expected_kw"]
    p = df["power_kw"]
    curtailed = df["time"].map(plant_curtailment).fillna(0.0) > 0

    conditions = [
        (p <= 10.0) & (exp >= 50.0),
        curtailed & (p < 0.9 * exp),
        (pitch_excess >= pitch_excess_deg) & (p < 0.9 * exp) & (p > 10.0),
        (df["temp_c"] <= 2.0) & (p < 0.75 * exp) & (p < exp - 3 * sigma) & (pitch_excess < pitch_excess_deg) & (exp >= 50.0),
        (p < exp - 3 * sigma) & (p < 0.9 * exp) & (exp >= 50.0),
    ]
    label = np.select(conditions, LOSS_CLASSES, default="normal")
    label = pd.Series(label, index=df.index, dtype="object")
    label[~df["qc_valid"]] = "no data"
    return label


def lost_energy_kwh(df: pd.DataFrame) -> pd.Series:
    shortfall = (df["expected_kw"] - df["power_kw"]).clip(lower=0.0) / 6.0
    return shortfall.where(df["state"].isin(LOSS_CLASSES), 0.0).fillna(0.0)


def loss_table(df: pd.DataFrame) -> pd.DataFrame:
    """Actual energy, lost energy by class and energy-based availability, per turbine (MWh)."""
    actual = (df["power_kw"].clip(lower=0.0) / 6.0).where(df["qc_valid"], 0.0)
    t = df.assign(actual_kwh=actual).groupby(["turbine", "state"])[["lost_kwh"]].sum().unstack("state")
    t.columns = t.columns.droplevel(0)
    t = t.reindex(columns=LOSS_CLASSES, fill_value=0.0).fillna(0.0) / 1000.0
    t.insert(0, "actual", df.assign(a=actual).groupby("turbine")["a"].sum() / 1000.0)
    t["total_lost"] = t[LOSS_CLASSES].sum(axis=1)
    t["potential"] = t["actual"] + t["total_lost"]
    t["lost_pct_of_potential"] = 100.0 * t["total_lost"] / t["potential"]
    t["energy_availability_pct"] = 100.0 * (1.0 - t["downtime"] / t["potential"])
    total = t.sum(numeric_only=True)
    total["lost_pct_of_potential"] = 100.0 * total["total_lost"] / total["potential"]
    total["energy_availability_pct"] = 100.0 * (1.0 - total["downtime"] / total["potential"])
    t.loc["Wind farm"] = total
    return t.round(2)


def electrical_losses(df: pd.DataFrame, plant: pd.DataFrame) -> dict:
    """Compare summed turbine SCADA energy with the revenue meter, using only intervals
    where every turbine has valid data, so missing SCADA does not inflate the result."""
    wide = df.pivot(index="time", columns="turbine", values="power_kw")
    valid = df.pivot(index="time", columns="turbine", values="qc_valid").fillna(False).all(axis=1)
    scada_kwh = wide.clip(lower=0.0).sum(axis=1)[valid] / 6.0
    meter_kwh = plant["net_energy_kwh"].reindex(scada_kwh.index)
    ok = meter_kwh.notna()
    s, m = float(scada_kwh[ok].sum()), float(meter_kwh[ok].sum())
    return {"scada_mwh": round(s / 1000, 1), "meter_mwh": round(m / 1000, 1),
            "electrical_loss_pct": round(100 * (1 - m / s), 2), "intervals_compared": int(ok.sum())}


def monthly_losses(df: pd.DataFrame) -> pd.DataFrame:
    month = df["time"].dt.tz_convert(None).dt.to_period("M")
    m = df[df["state"].isin(LOSS_CLASSES)].groupby([month, "state"])["lost_kwh"].sum().unstack("state")
    return (m.reindex(columns=LOSS_CLASSES).fillna(0.0) / 1000.0).round(2)
