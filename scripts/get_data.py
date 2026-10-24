"""Download and unpack the La Haute Borne open dataset into ./data.

The data were published by ENGIE under the Etalab Open Licence 2.0 and are
redistributed as example data in NREL's OpenOA repository, which is where this
script fetches them from. See docs/DATASET.md for a full description.

Usage:  python scripts/get_data.py
"""
from __future__ import annotations

import sys
import urllib.request
import zipfile
from pathlib import Path

URL = "https://github.com/NREL/OpenOA/raw/main/examples/data/la_haute_borne.zip"
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
EXPECTED = [
    "la-haute-borne-data-2014-2015.csv",
    "la-haute-borne_asset_table.csv",
    "plant_data.csv",
    "era5_wind_la_haute_borne.csv",
    "merra2_la_haute_borne.csv",
    "SCADA_data_description.csv",
]


def main() -> None:
    DATA.mkdir(exist_ok=True)
    if all((DATA / f).exists() for f in EXPECTED):
        print("Data already present in", DATA)
        return
    archive = DATA / "la_haute_borne.zip"
    if not archive.exists():
        print("Downloading", URL)
        request = urllib.request.Request(URL, headers={"User-Agent": "wind-scada-performance-analytics"})
        with urllib.request.urlopen(request) as response, open(archive, "wb") as out:
            out.write(response.read())
    with zipfile.ZipFile(archive) as z:
        for member in z.namelist():
            if member.startswith("__MACOSX") or member.endswith("/"):
                continue
            target = DATA / Path(member).name
            with z.open(member) as src, open(target, "wb") as dst:
                dst.write(src.read())
    missing = [f for f in EXPECTED if not (DATA / f).exists()]
    if missing:
        sys.exit(f"Missing after unzip: {missing}")
    print("Data ready in", DATA)


if __name__ == "__main__":
    main()
