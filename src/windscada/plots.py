"""Static figures for the README and technical memo (matplotlib, light theme).

Colours come from one validated categorical order, assigned in fixed order and never
cycled; text stays in neutral ink; grids and axes are kept quiet.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
BLUE_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
MUTED_POINT = "#c9c8c2"

plt.rcParams.update(
    {
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.edgecolor": GRID,
        "axes.labelcolor": INK_2,
        "axes.titlecolor": INK,
        "axes.titlesize": 11,
        "axes.titleweight": "bold",
        "axes.titlelocation": "left",
        "xtick.color": INK_2,
        "ytick.color": INK_2,
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "legend.frameon": False,
        "legend.labelcolor": INK_2,
    }
)


def _save(fig, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def data_availability(avail: pd.DataFrame, path: Path) -> None:
    from matplotlib.colors import ListedColormap

    fig, ax = plt.subplots(figsize=(10, 2.6))
    cmap = ListedColormap(BLUE_RAMP)
    im = ax.imshow(avail.values, aspect="auto", cmap=cmap, vmin=90, vmax=100)
    ax.set_yticks(range(len(avail.index)), avail.index)
    labels = [str(c) for c in avail.columns]
    ax.set_xticks(range(0, len(labels), 3), labels[::3], rotation=0)
    ax.grid(False)
    ax.set_title("Valid 10-minute SCADA intervals by turbine and month (percent)")
    cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.01)
    cb.outline.set_visible(False)
    cb.ax.tick_params(colors=INK_2)
    _save(fig, path)


def power_curves(df: pd.DataFrame, normal: pd.Series, curves: pd.DataFrame, path: Path) -> None:
    turbines = list(curves.columns)
    fig, axes = plt.subplots(2, 2, figsize=(10, 7), sharex=True, sharey=True)
    rng = np.random.default_rng(0)
    for ax, t in zip(axes.flat, turbines):
        sub = df[(df["turbine"] == t) & df["qc_valid"]]
        idx = rng.choice(len(sub), size=min(len(sub), 25000), replace=False)
        s = sub.iloc[idx]
        n = normal.loc[s.index]
        ax.scatter(s.loc[~n, "wind_norm_ms"], s.loc[~n, "power_kw"], s=2, color=MUTED_POINT, linewidths=0,
                   label="Excluded (downtime, derate, curtailment, outliers)", rasterized=True)
        ax.scatter(s.loc[n, "wind_norm_ms"], s.loc[n, "power_kw"], s=2, color=SERIES[0], alpha=0.35,
                   linewidths=0, label="Normal operation", rasterized=True)
        c = curves[t].dropna()
        ax.plot(c.index, c.values, color=INK, linewidth=2, label="Reference power curve (bin median)")
        ax.set_title(t)
        ax.set_xlim(0, 20)
        ax.set_ylim(-50, 2200)
    for ax in axes[1]:
        ax.set_xlabel("Wind speed, density normalised (m/s)")
    for ax in axes[:, 0]:
        ax.set_ylabel("Active power (kW)")
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3, markerscale=5, bbox_to_anchor=(0.5, -0.01))
    fig.suptitle("Power curves: normal operation filter and reference curve per turbine", x=0.01, ha="left",
                 fontweight="bold", color=INK)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(path, dpi=150)
    plt.close(fig)


def losses_by_turbine(table: pd.DataFrame, classes: list[str], path: Path) -> None:
    t = table.drop(index="Wind farm")[classes]
    fig, ax = plt.subplots(figsize=(10, 3.4))
    left = np.zeros(len(t))
    for i, c in enumerate(classes):
        vals = t[c].values
        ax.barh(t.index, vals, left=left, color=SERIES[i], edgecolor=SURFACE, linewidth=2, label=c.capitalize(),
                height=0.6)
        left += vals
    for y, total in enumerate(left):
        ax.text(total + 3, y, f"{total:,.0f} MWh", va="center", color=INK_2, fontsize=9)
    ax.set_xlabel("Lost energy, 2014 to 2015 (MWh)")
    ax.set_title("Lost production by cause and turbine")
    ax.grid(axis="y", visible=False)
    ax.invert_yaxis()
    ax.set_xlim(0, left.max() * 1.18)
    ax.legend(loc="lower center", ncol=len(classes), bbox_to_anchor=(0.5, -0.45))
    _save(fig, path)


def derate_recurrence(rec: dict, path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
    h = rec["hour_local"]
    axes[0].bar(h.index, h["pct_of_intervals"], color=SERIES[0], width=0.75)
    axes[0].set_xlabel("Hour of day (local time)")
    axes[0].set_ylabel("Share of producing intervals in derate (%)")
    axes[0].set_title("Derates cluster in the early afternoon")
    axes[0].set_xticks(range(0, 24, 3))
    tb = rec["temp_band_c"]
    axes[1].bar(range(len(tb)), tb["pct_of_intervals"], color=SERIES[0], width=0.75)
    axes[1].set_xticks(range(len(tb)), [str(x) for x in tb.index], rotation=35, ha="right")
    axes[1].set_xlabel("Outdoor temperature (C)")
    axes[1].set_ylabel("Share of producing intervals in derate (%)")
    axes[1].set_title("and rise sharply with outdoor temperature")
    for ax in axes:
        ax.grid(axis="x", visible=False)
    _save(fig, path)


def derate_event(df: pd.DataFrame, event: pd.Series, path: Path) -> None:
    pad = pd.Timedelta(hours=3)
    sub = df[(df["turbine"] == event["turbine"]) & (df["time"] >= event["start_utc"] - pad)
             & (df["time"] <= event["end_utc"] + pad)].copy()
    sub["t"] = sub["time"].dt.tz_convert("Europe/Paris").dt.tz_localize(None)
    fig, axes = plt.subplots(3, 1, figsize=(10, 6.4), sharex=True, gridspec_kw={"height_ratios": [2, 1, 1]})
    axes[0].plot(sub["t"], sub["expected_kw"], color=SERIES[1], linewidth=2, label="Expected from reference curve")
    axes[0].plot(sub["t"], sub["power_kw"], color=SERIES[0], linewidth=2, label="Actual")
    axes[0].set_ylabel("Power (kW)")
    axes[0].legend(loc="upper right")
    axes[1].plot(sub["t"], sub["wind_norm_ms"], color=SERIES[0], linewidth=2)
    axes[1].set_ylabel("Wind (m/s)")
    axes[2].plot(sub["t"], sub["pitch_deg"], color=SERIES[0], linewidth=2)
    axes[2].set_ylabel("Pitch (deg)")
    s = event["start_utc"].tz_convert("Europe/Paris").tz_localize(None)
    e = event["end_utc"].tz_convert("Europe/Paris").tz_localize(None)
    for ax in axes:
        ax.axvspan(s, e, color=GRID, alpha=0.7, linewidth=0)
    axes[0].set_title(f"Largest derate event: {event['turbine']}, {s:%d %b %Y}, {event['duration_h']:.1f} h, "
                      f"{event['lost_mwh']:.1f} MWh lost (shaded)")
    import matplotlib.dates as mdates
    axes[2].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    axes[2].set_xlabel(f"Local time, {s:%d %b %Y}")
    _save(fig, path)


def aep_regression(monthly: pd.DataFrame, fits: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7, 4.6))
    y = monthly["gross_kwh"] / monthly["days"] / 1000
    for i, (name, label) in enumerate([("era5", "ERA5 (100 m)"), ("merra2", "MERRA-2 (50 m)")]):
        x = monthly[f"ws_{name}"]
        f = fits[fits["product"] == name].iloc[0]
        ax.scatter(x, y, s=48, color=SERIES[i], edgecolor=SURFACE, linewidth=1.5,
                   label=f"{label}, R squared {f['r_squared']:.2f}", zorder=3)
        xs = np.linspace(x.min() - 0.2, x.max() + 0.2, 20)
        ax.plot(xs, (f["intercept_kwh_per_day"] + f["slope_kwh_per_day_per_ms"] * xs) / 1000, color=SERIES[i],
                linewidth=2)
    ax.set_xlabel("Monthly mean reanalysis wind speed (m/s)")
    ax.set_ylabel("Gross plant energy (MWh per day)")
    ax.set_title("Monthly energy against reanalysis wind, 2014 to 2015")
    ax.legend(loc="upper left")
    _save(fig, path)


def aep_distribution(result, openoa_p50: float | None, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.hist(result.draws_gwh, bins=60, color=SERIES[0], edgecolor=SURFACE, linewidth=0.5)
    ymax = ax.get_ylim()[1]
    marks = [(result.p50_gwh, f"P50 {result.p50_gwh:.2f}"), (result.p90_lt_gwh, f"P90 {result.p90_lt_gwh:.2f}")]
    for x, label in marks:
        ax.axvline(x, color=INK, linewidth=1.5)
        ax.text(x, ymax * 0.97, f" {label}", color=INK, va="top", fontsize=9)
    if openoa_p50 is not None:
        ax.axvline(openoa_p50, color=INK_2, linewidth=1.5, linestyle="--")
        ax.text(openoa_p50, ymax * 0.80, f"OpenOA P50 {openoa_p50:.2f} ", color=INK_2, va="top", ha="right",
                fontsize=9)
    ax.set_xlabel("Net annual energy production (GWh per year)")
    ax.set_ylabel("Monte Carlo draws")
    ax.set_title("Long-term corrected AEP: distribution of 10,000 draws")
    ax.grid(axis="x", visible=False)
    _save(fig, path)
