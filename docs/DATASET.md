# The La Haute Borne dataset

This project uses public operating data from **La Haute Borne**, a four-turbine onshore wind farm in north-eastern France (Grand Est region, around 48.45 N, 5.59 E). It is one of very few real wind farm datasets published with turbine SCADA data, a plant revenue meter, availability and curtailment losses, and matching reanalysis wind data. Together these are what an operational energy assessment needs, which is why it was chosen.

## Where the data comes from

| Item | Detail |
|---|---|
| Original publisher | ENGIE, through its open data portal for renewables (opendata-renewables.engie.com), data updated 9 October 2019 |
| Licence | Etalab Open Licence 2.0 (French government open licence). Reuse, including commercial reuse, is allowed with attribution to the source |
| Packaged copy used here | `examples/data/la_haute_borne.zip` in NREL's open-source OpenOA repository (github.com/NREL/OpenOA), which adds ERA5 and MERRA-2 reanalysis for the site and a plant-level meter and loss table |
| How to get it | `python scripts/get_data.py` downloads the zip and unpacks it into `data/`. The data are not stored in this repository |

Attribution: *Contains La Haute Borne wind farm data published by ENGIE under the Etalab Open Licence 2.0, as packaged in the NREL OpenOA example data.*

## The wind farm

| Turbine | Latitude | Longitude | Model | Rated power | Hub height | Rotor diameter |
|---|---|---|---|---|---|---|
| R80711 | 48.4569 | 5.5847 | Senvion MM82 | 2,050 kW | 80 m | 82 m |
| R80721 | 48.4497 | 5.5869 | Senvion MM82 | 2,050 kW | 80 m | 82 m |
| R80736 | 48.4461 | 5.5925 | Senvion MM82 | 2,050 kW | 80 m | 82 m |
| R80790 | 48.4536 | 5.5875 | Senvion MM82 | 2,050 kW | 80 m | 82 m |

Installed capacity is 8.2 MW. Site elevation is about 411 m. The MM82 is a pitch-regulated, variable-speed turbine, which matters for the power curve method (density correction and pitch-based derate detection).

## Files

| File | Rows | Time step | What it holds |
|---|---|---|---|
| `la-haute-borne-data-2014-2015.csv` | 420,480 (105,120 per turbine) | 10 minutes | Turbine SCADA averages, 1 January 2014 to 31 December 2015 |
| `la-haute-borne_asset_table.csv` | 4 | n/a | Turbine coordinates, model, rated power, hub height, rotor diameter |
| `plant_data.csv` | 105,120 | 10 minutes | Plant revenue meter energy and the operator's availability and curtailment losses |
| `era5_wind_la_haute_borne.csv` | about 187,000 | 1 hour | ERA5 reanalysis for the site, 1999 to May 2020 |
| `merra2_la_haute_borne.csv` | about 195,000 | 1 hour | MERRA-2 reanalysis for the site, 1997 to April 2019 |
| `SCADA_data_description.csv` | 9 | n/a | Variable names and units from the original publication |

### Turbine SCADA columns (10-minute averages)

| Column | Meaning | Unit | Name used in this project |
|---|---|---|---|
| `Wind_turbine_name` | Turbine identifier | text | `turbine` |
| `Date_time` | Interval timestamp in French local time with UTC offset | ISO 8601 | `time` (converted to UTC) |
| `P_avg` | Active power | kW | `power_kw` |
| `Ws_avg` | Nacelle anemometer wind speed | m/s | `wind_ms` |
| `Ba_avg` | Blade pitch angle | degrees | `pitch_deg` |
| `Wa_avg` | Absolute wind direction | degrees | `wind_dir_deg` |
| `Va_avg` | Wind vane position relative to the nacelle | degrees | `vane_deg` |
| `Ya_avg` | Nacelle (yaw) angle | degrees | `nacelle_deg` |
| `Ot_avg` | Outdoor temperature | C | `temp_c` |

The original ENGIE release also has torque and generator speed, and minimum, maximum and standard deviation values for each variable. The OpenOA package keeps the averages listed above.

### Plant columns (10-minute)

| Column | Meaning | Unit |
|---|---|---|
| `time_utc` | Interval timestamp | UTC |
| `net_energy_kwh` | Energy measured at the plant revenue meter | kWh per interval |
| `availability_kwh` | Energy lost to turbine unavailability, as calculated by the operator | kWh per interval |
| `curtailment_kwh` | Energy lost to curtailment (external power limits), as calculated by the operator | kWh per interval |

### Reanalysis columns (hourly)

Reanalysis products are global weather models fitted to historical observations. In wind energy they provide the long, consistent wind record needed to put a short operating period into long-term context.

| Product | Provider | Columns used | Height |
|---|---|---|---|
| ERA5 | European Centre for Medium-Range Weather Forecasts (Copernicus) | `ws_100m` wind speed, `dens_100m` air density (also `u_100`, `v_100`, `t_2m`, `surf_pres`) | 100 m |
| MERRA-2 | NASA Global Modeling and Assimilation Office | `ws_50m` wind speed, `dens_50m` air density (also `u_50`, `v_50`, `temp_2m`, `surface_pressure`) | 50 m |

Timestamps are UTC. ERA5 air density at 100 m is used for the turbine density correction, since 100 m is close to the 80 m hub height.

## Known data issues and how they are handled

| Issue | What was found | Handling |
|---|---|---|
| Daylight saving duplicates | 48 duplicate turbine records (12 per turbine) after converting local time to UTC | First record kept, the same choice OpenOA makes |
| Missing intervals | 0.62 percent of turbine intervals have no power or wind speed; R80721 has gaps in February and March 2015, and all turbines have a gap in June 2015 | Kept as explicit empty rows so availability is measured honestly; excluded from analysis |
| Sentinel temperatures | 34 readings of about -273 C (sensor fault code) | Blanked; the interval stays usable for power and wind |
| Pitch outliers | 43 pitch values outside -5 to 95 degrees | Blanked |
| Stopped turbine readings | Power at or below zero with pitch at 45 or 90 degrees (feathered) | Treated as downtime when the wind could have produced power |
| Nacelle anemometer bias | Nacelle wind speed is measured behind the rotor | Acceptable for monitoring and loss estimation; not used for warranty power curve testing |

## What the data can and cannot support

It supports power curve monitoring, lost production and availability analysis, derate and fault pattern detection, electrical loss estimation (turbines against the revenue meter) and a long-term corrected energy estimate with uncertainty.

It cannot support warranty power curve verification (no met mast or manufacturer curve), a pre-construction wind resource assessment (no measurement campaign), or detailed wake modelling (only four turbines and no free-stream reference).
