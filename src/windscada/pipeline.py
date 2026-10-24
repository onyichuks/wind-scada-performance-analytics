"""Shared steps used by run_analysis.py and the dashboard builder."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import io, losses, qc
from . import power_curve as pc


@dataclass
class Prepared:
    df: pd.DataFrame
    plant: pd.DataFrame
    normal: pd.Series
    curves: pd.DataFrame
    pitch_curve: pd.Series
    sigma_curve: pd.Series


def prepare(data_dir) -> Prepared:
    """Load, quality check, density correct, build reference curves and expected power."""
    scada = io.load_scada(data_dir)
    plant = io.load_plant(data_dir)
    era5 = io.load_reanalysis(data_dir, "era5")
    df = qc.apply_qc(scada)
    df = pc.add_air_density(df, era5)
    plant_flags = (plant["availability_kwh"] > 0) | (plant["curtailment_kwh"] > 0)
    normal = pc.normal_operation_mask(df, plant_flags)
    curves = pc.reference_curves(df, normal)
    pitch_curve = pc.normal_pitch_curve(df, normal)
    df["expected_kw"] = pc.expected_power(df, curves)
    sigma_curve = pc.residual_sigma_curve(df, normal, df["expected_kw"])
    return Prepared(df, plant, normal, curves, pitch_curve, sigma_curve)


def classify(prep: Prepared, pitch_excess_deg: float) -> pd.DataFrame:
    """Return a copy of the interval table labelled under one derate threshold."""
    df = prep.df.copy()
    df["state"] = losses.classify(df, prep.pitch_curve, prep.sigma_curve, prep.plant["curtailment_kwh"],
                                  pitch_excess_deg=pitch_excess_deg)
    df["lost_kwh"] = losses.lost_energy_kwh(df)
    return df
