"""Unit tests on small synthetic inputs. They need no downloaded data, so they run in CI."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from windscada import aep, derates, losses, qc  # noqa: E402
from windscada import power_curve as pc  # noqa: E402


def _frame(n=12, turbine="T1", **cols):
    t = pd.date_range("2015-07-01", periods=n, freq="10min", tz="UTC")
    base = {"turbine": turbine, "time": t, "power_kw": 500.0, "wind_ms": 7.0, "pitch_deg": -1.0,
            "temp_c": 15.0, "wind_dir_deg": 200.0, "vane_deg": 0.0, "nacelle_deg": 200.0}
    base.update(cols)
    return pd.DataFrame(base)


def test_qc_flags_missing_range_and_frozen_wind():
    df = _frame(12, wind_ms=[7.0] * 7 + [6.0, 6.5, 7.2, 8.0, np.nan], power_kw=[500.0] * 10 + [5000.0, 400.0])
    out = qc.apply_qc(df)
    assert out["qc_frozen_wind"].iloc[:7].all()  # seven identical readings is more than one hour
    assert not out["qc_frozen_wind"].iloc[7:11].any()
    assert out["qc_out_of_range"].iloc[10]  # 5000 kW is impossible for a 2.05 MW turbine
    assert out["qc_missing"].iloc[11]
    assert out["qc_valid"].sum() == 3


def test_qc_blanks_secondary_sensors_but_keeps_interval():
    df = _frame(3, temp_c=[15.0, -273.2, 14.0], pitch_deg=[-1.0, 262.0, -1.0], wind_ms=[6.0, 7.0, 8.0])
    out = qc.apply_qc(df)
    assert np.isnan(out.loc[1, "temp_c"]) and np.isnan(out.loc[1, "pitch_deg"])
    assert out.loc[1, "qc_valid"]
    assert out.attrs["secondary_values_blanked"]["temp_c"] == 1


def test_density_normalisation_follows_cube_root_rule():
    df = _frame(2, wind_ms=[8.0, 8.0])
    era5 = pd.DataFrame({"density": [1.1, 1.3]}, index=pd.DatetimeIndex(df["time"]))
    out = pc.add_air_density(df, era5)
    rho_ref = out.attrs["rho_ref"]
    assert rho_ref == pytest.approx(1.2)
    assert out.loc[0, "wind_norm_ms"] == pytest.approx(8.0 * (1.1 / 1.2) ** (1 / 3))
    assert out.loc[1, "wind_norm_ms"] > out.loc[0, "wind_norm_ms"]


def test_expected_power_is_zero_outside_operating_range():
    curves = pd.DataFrame({"T1": [100.0, 1000.0, 2000.0]}, index=[4.0, 8.0, 14.0])
    df = _frame(4, wind_norm_ms=[2.0, 6.0, 20.0, 26.0])
    exp = pc.expected_power(df, curves)
    assert exp.iloc[0] == 0.0  # below cut-in
    assert exp.iloc[1] == pytest.approx(550.0)  # linear between 4 and 8 m/s
    assert exp.iloc[2] == 2000.0  # above the last bin: rated
    assert exp.iloc[3] == 0.0  # above cut-out


def test_classification_and_lost_energy():
    df = _frame(4, power_kw=[0.0, 600.0, 1450.0, 900.0], pitch_deg=[90.0, 8.0, -1.0, -1.0], temp_c=15.0)
    df["wind_norm_ms"] = 9.0
    df["expected_kw"] = 1500.0
    df["qc_valid"] = True
    pitch_curve = pd.Series(-1.0, index=pc.BIN_CENTRES)
    sigma_curve = pd.Series(60.0, index=pc.BIN_CENTRES)
    no_curtail = pd.Series(dtype=float)
    df["state"] = losses.classify(df, pitch_curve, sigma_curve, no_curtail)
    assert list(df["state"]) == ["downtime", "derate", "normal", "underperformance"]
    df["lost_kwh"] = losses.lost_energy_kwh(df)
    assert df["lost_kwh"].tolist() == pytest.approx([250.0, 150.0, 0.0, 100.0])


def test_higher_derate_threshold_labels_fewer_derates():
    df = _frame(3, power_kw=600.0, pitch_deg=[1.2, 2.2, 3.5])
    df["wind_norm_ms"], df["expected_kw"], df["qc_valid"] = 9.0, 1500.0, True
    pitch_curve = pd.Series(-1.0, index=pc.BIN_CENTRES)
    sigma_curve = pd.Series(60.0, index=pc.BIN_CENTRES)
    counts = {th: (losses.classify(df, pitch_curve, sigma_curve, pd.Series(dtype=float), th) == "derate").sum()
              for th in (2.0, 2.5, 3.0)}
    assert counts[2.0] >= counts[2.5] >= counts[3.0]


def test_derate_events_bridge_short_gaps_and_drop_short_runs():
    states = ["derate"] * 3 + ["normal"] * 2 + ["derate"] * 2 + ["normal"] * 5 + ["derate"] * 2
    df = _frame(len(states))
    df["state"] = states
    for c in ["wind_norm_ms", "expected_kw"]:
        df[c] = 1.0
    df["lost_kwh"] = 10.0
    events = derates.find_events(df)
    assert len(events) == 1  # the two-interval gap is bridged; the final two-interval run is too short
    assert events.loc[0, "duration_h"] == pytest.approx(7 / 6)
    assert events.loc[0, "lost_mwh"] == pytest.approx(0.05)


def test_regression_fit_recovers_a_straight_line():
    x = np.array([4.0, 5.0, 6.0, 7.0])
    intercept, slope, r2 = aep._fit(x, 3.0 * x - 2.0)
    assert slope == pytest.approx(3.0) and intercept == pytest.approx(-2.0) and r2 == pytest.approx(1.0)
