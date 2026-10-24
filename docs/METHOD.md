# Technical note: La Haute Borne operational performance, 2014 to 2015

Prepared by Onyi Chuks. Code and outputs in this repository reproduce every number below (`python run_analysis.py`).

## 1. Purpose and scope

Assess how the four-turbine La Haute Borne wind farm performed over 2014 and 2015 using 10-minute SCADA data, quantify lost production by cause, identify recurring derates, and estimate long-term annual energy production (AEP) with P50 and P90 values. The dataset is described in [DATASET.md](DATASET.md).

## 2. Data quality

* 420,480 turbine intervals; 99.38 percent passed the checks (missing values 0.43 to 1.16 percent by turbine; no out-of-range power or wind speed; no frozen anemometer periods of an hour or more).
* 48 duplicate records around daylight saving changes removed; 34 sentinel temperature readings and 43 implausible pitch values blanked without discarding the interval.
* Missing data are kept as explicit rows so that availability figures are not flattered by absent records.

## 3. Power curves

Nacelle wind speed was normalised to the site mean air density (1.195 kg/m3, ERA5 at 100 m) using V_n = V (rho / rho_ref)^(1/3). Reference curves are bin medians in 0.5 m/s bins from normal operation only (74 percent of valid intervals): turbine producing, no plant-reported availability or curtailment loss, pitch within 2.5 degrees of the normal pitch for the wind speed, and power within three robust standard deviations of the bin median. The four curves agree closely; rated power (about 2,020 kW in the data) is reached near 15 to 16 m/s.

Limitation: no warranted power curve or met mast is available, so each turbine is compared with its own normal operation. This finds losses and derates well but cannot test warranty compliance.

## 4. Lost production

Each valid interval is placed in one class: downtime, curtailment, derate, suspected icing, underperformance or normal (rules in `src/windscada/losses.py`). Lost energy is expected minus actual power for the five loss classes.

| Turbine | Actual MWh | Downtime | Curtailment | Derate | Suspected icing | Underperformance | Lost, percent of potential | Energy availability |
|---|---|---|---|---|---|---|---|---|
| R80711 | 6,955 | 72.4 | 1.3 | 10.9 | 3.7 | 7.5 | 1.36 | 98.97 |
| R80721 | 5,442 | 42.9 | 1.0 | 11.2 | 2.3 | 3.8 | 1.11 | 99.22 |
| R80736 | 5,950 | 58.0 | 1.1 | 10.4 | 0.5 | 3.4 | 1.22 | 99.04 |
| R80790 | 6,300 | 103.5 | 1.1 | 12.9 | 2.1 | 15.8 | 2.10 | 98.39 |
| **Wind farm** | **24,647** | **276.7** | **4.5** | **45.4** | **8.6** | **30.4** | **1.46** | **98.89** |

Findings:

* Downtime is three quarters of all lost energy. R80790 has the most downtime and the most underperformance, and is the first turbine to review.
* Cross-check: the downtime estimate (277 MWh) is 90 percent of the availability loss the operator reported for the plant (308 MWh). The gap is expected because the operator's figure also includes plant-level events and uses its own expected-power method.
* Electrical losses between the turbines and the revenue meter are 2.09 percent, comparing summed turbine energy with the meter over the 103,735 intervals where all four turbines had valid data.

## 5. Recurring derates

A derate is an interval where pitch sits more than 2.5 degrees above the normal pitch for that wind speed while power is below 90 percent of expected. The dashboard lets the reader switch the threshold between 2.0, 2.5 and 3.0 degrees to see how sensitive the result is.

* Derates are strongly tied to temperature: 8.7 percent of producing intervals above 30 C were derated, against 0.5 percent at 10 to 15 C, about 17 times as often. They peak at 11:00 to 14:00 local time and in June to August.
* That pattern (hot afternoons, summer) is the signature of thermal protection, where the controller limits power to keep the generator, gearbox or converter within temperature limits. A random fault would not follow the ambient temperature this closely.
* Recommended next step with the operator: compare these events with component temperature signals and the alarm log, and check cooling system maintenance before the next summer.
* The largest single event (R80721, 2 January 2015, 4.2 hours, 1.9 MWh) is different: power was held flat near 1,150 kW, where the wind should have given about 1,630 kW, just after a restart in near-freezing weather, which points to a power limit setpoint (for example after an ice-related stop) rather than heat.

## 6. Long-term corrected AEP

Monthly revenue meter energy, grossed up for reported availability and curtailment losses, was regressed on monthly mean reanalysis wind speed (ERA5: R squared 0.87; MERRA-2: R squared 0.95) and applied to 20 complete years (ERA5 2000 to 2019; MERRA-2 1999 to 2018). Measured availability and curtailment losses (1.33 percent) were subtracted for net AEP. A 10,000 draw Monte Carlo varied the reanalysis product, meter error (0.5 percent), loss error (5 percent of loss), the regression (bootstrapped months) and the long-term years (bootstrapped).

| Result | GWh per year |
|---|---|
| P50 | 12.59 |
| P90, uncertainty of the long-term mean | 12.06 |
| P90, ten-year | 11.92 |
| P90, one-year (adds 8.3 percent inter-annual variability) | 11.15 |
| P50 by product: ERA5 / MERRA-2 | 12.48 / 12.67 |

Capacity factor at P50 is 17.5 percent. Long-term uncertainty is 3.2 percent of P50.

**Validation.** NREL's OpenOA MonteCarloAEP, run on the same data (`scripts/validate_with_openoa.py`, 2,000 simulations), gives a P50 of 12.27 GWh, 2.6 percent below this estimate. OpenOA's spread is wider (P90 10.81 GWh) because it also varies the length of the long-term window and keeps inter-annual variability inside its distribution; its P90 is closest to the one-year P90 here (11.15 GWh). The two independent methods agree on the central estimate within the stated uncertainty.

## 7. Limitations and what would improve the assessment

* Two years of operation give only 24 monthly points for the regression; daily resolution with outlier screening, or a longer operating record, would tighten the uncertainty.
* Nacelle anemometry is affected by the rotor; a nacelle transfer function or a met mast would be needed for warranty-grade power curves.
* Component temperatures and alarm logs are not in the open data; with them, the thermal derate diagnosis could be confirmed directly.
* A full wake loss analysis would need more turbines or a free-stream reference.
