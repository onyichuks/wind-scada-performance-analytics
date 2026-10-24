"""Long-term corrected annual energy production (AEP) with Monte Carlo uncertainty.

This follows the usual operational assessment approach:

1. Monthly plant energy from the revenue meter is grossed up by the reported
   availability and curtailment losses, so the regression sees what the plant
   would have produced with no downtime or curtailment.
2. Energy per day is regressed on the monthly mean reanalysis wind speed for the
   same months (a measure, correlate and predict step at monthly resolution).
3. The fitted relationship is applied to 20 complete years of reanalysis wind to
   predict a long-term average year.
4. Long-term availability and curtailment losses are taken from the measured
   loss ratio and subtracted to give net AEP.

Uncertainty is propagated with a Monte Carlo loop. Each draw:
  * picks a reanalysis product (ERA5 or MERRA-2) with equal weight
  * applies a revenue meter error (0.5 percent standard deviation)
  * applies an error to the reported losses (5 percent of the loss, standard deviation)
  * resamples the 24 operational months with replacement and refits the regression
  * resamples the 20 long-term years with replacement (long-term variability)

P50 is the median of the draws. P90 (long-term) is the value exceeded by 90 percent
of draws, describing uncertainty in the long-term mean. One-year and ten-year P90
values add inter-annual variability of the wind resource.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .io import load_reanalysis

LT_YEARS = {"era5": (2000, 2019), "merra2": (1999, 2018)}
METER_SD = 0.005
LOSS_SD = 0.05
Z90 = 1.2816


def monthly_plant(plant: pd.DataFrame) -> pd.DataFrame:
    m = plant.resample("MS").sum()
    m["days"] = m.index.days_in_month
    m["gross_kwh"] = m["net_energy_kwh"] + m["availability_kwh"] + m["curtailment_kwh"]
    m.index = m.index.tz_convert(None)
    return m


def monthly_wind(rean: pd.DataFrame) -> pd.Series:
    s = rean["ws"].resample("MS").mean()
    s.index = s.index.tz_convert(None)
    return s


def _fit(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    slope, intercept = np.polyfit(x, y, 1)
    pred = intercept + slope * x
    ss_res = float(((y - pred) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    return float(intercept), float(slope), 1.0 - ss_res / ss_tot


@dataclass
class AEPResult:
    draws_gwh: np.ndarray
    p50_gwh: float
    p90_lt_gwh: float
    p90_1yr_gwh: float
    p90_10yr_gwh: float
    uncertainty_lt_pct: float
    iav_pct: float
    loss_ratio_pct: float
    fits: pd.DataFrame
    product_p50_gwh: dict


def run_aep(data_dir, plant: pd.DataFrame, n_draws: int = 10000, seed: int = 42) -> tuple[AEPResult, dict]:
    rng = np.random.default_rng(seed)
    mp = monthly_plant(plant)

    products = {}
    fits = []
    for product in ["era5", "merra2"]:
        rean = load_reanalysis(data_dir, product)
        mw = monthly_wind(rean)
        y0, y1 = LT_YEARS[product]
        lt = mw[(mw.index.year >= y0) & (mw.index.year <= y1)]
        ws_op = mw.reindex(mp.index)
        intercept, slope, r2 = _fit(ws_op.values, (mp["gross_kwh"] / mp["days"]).values)
        fits.append({"product": product, "intercept_kwh_per_day": intercept, "slope_kwh_per_day_per_ms": slope,
                     "r_squared": r2, "lt_mean_ws_ms": lt.mean(), "op_mean_ws_ms": ws_op.mean()})
        lt_table = pd.DataFrame({"ws": lt.values, "year": lt.index.year, "month": lt.index.month,
                                 "days": lt.index.days_in_month})
        matrix = lt_table.pivot(index="year", columns="month", values="ws").to_numpy()
        month_days = lt_table.groupby("month")["days"].mean().to_numpy()
        products[product] = {"ws_op": ws_op.values, "lt": lt_table, "matrix": matrix, "month_days": month_days}

    net = mp["net_energy_kwh"].values
    loss = (mp["availability_kwh"] + mp["curtailment_kwh"]).values
    days = mp["days"].values
    n_months = len(net)

    draws = np.empty(n_draws)
    gross_lt_draws = np.empty(n_draws)
    names = list(products)
    for k in range(n_draws):
        prod = products[names[rng.integers(len(names))]]
        meter = 1.0 + rng.normal(0.0, METER_SD)
        loss_err = 1.0 + rng.normal(0.0, LOSS_SD)
        gross = net * meter + loss * loss_err
        idx = rng.integers(0, n_months, n_months)
        x = prod["ws_op"][idx]
        y = (gross / days)[idx]
        slope, intercept = np.polyfit(x, y, 1)

        matrix = prod["matrix"]
        pick = rng.integers(0, matrix.shape[0], matrix.shape[0])
        e_day = intercept + slope * matrix[pick]
        gross_lt = float((e_day.mean(axis=0) * prod["month_days"]).sum())
        loss_ratio = loss.sum() * loss_err / gross.sum()
        gross_lt_draws[k] = gross_lt
        draws[k] = gross_lt * (1.0 - loss_ratio) / 1e6

    # inter-annual variability of predicted gross energy, from the central fit per product
    iav = []
    product_p50 = {}
    for name, prod in products.items():
        f = next(f for f in fits if f["product"] == name)
        lt = prod["lt"].copy()
        lt["e"] = (f["intercept_kwh_per_day"] + f["slope_kwh_per_day_per_ms"] * lt["ws"]) * lt["days"]
        annual = lt.groupby("year")["e"].sum()
        iav.append(annual.std() / annual.mean())
        product_p50[name] = float(annual.mean() * (1 - loss.sum() / (net.sum() + loss.sum())) / 1e6)
    iav_frac = float(np.mean(iav))

    p50 = float(np.median(draws))
    sd_lt = float(np.std(draws))
    result = AEPResult(
        draws_gwh=draws,
        p50_gwh=p50,
        p90_lt_gwh=float(np.percentile(draws, 10)),
        p90_1yr_gwh=p50 - Z90 * np.sqrt(sd_lt**2 + (iav_frac * p50) ** 2),
        p90_10yr_gwh=p50 - Z90 * np.sqrt(sd_lt**2 + (iav_frac * p50) ** 2 / 10),
        uncertainty_lt_pct=100 * sd_lt / p50,
        iav_pct=100 * iav_frac,
        loss_ratio_pct=100 * loss.sum() / (net.sum() + loss.sum()),
        fits=pd.DataFrame(fits),
        product_p50_gwh=product_p50,
    )
    monthly = mp.assign(**{f"ws_{n}": p["ws_op"] for n, p in products.items()})
    return result, {"monthly": monthly}
