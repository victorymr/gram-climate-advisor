#!/usr/bin/env python3
"""
Download gridded LAND observations over India for the hindcast skill mask, and
save tidy monthly NetCDFs (dims time, lat, lon) in data/obs/.

  Temperature : GHCN-CAMS 2 m air temperature  (NOAA PSL OPeNDAP, 0.5 deg)
                -> data/obs/ghcncams_t2m_india.nc   (var t2m, degC)
  Precipitation: CHIRPS v2.0 monthly            (UCSB, via IRI Data Library)
                 server-side cropped to India and regridded to 0.5 deg
                -> data/obs/chirps_precip_india.nc  (var precip, mm/month)

Both are land-only (ocean = NaN), which is fine for an over-land skill mask.
Subsetting happens server-side (OPeNDAP), so the downloads are only a few MB.

Usage:
    python download_obs.py                 # both, default year range from config
    python download_obs.py --start 1991 --end 2025
    python download_obs.py --only temp     # or: --only precip
"""

import argparse
import sys

import numpy as np
import pandas as pd
import xarray as xr

from config import OBS_DIR, INDIA_BBOX, GHCNCAMS_URL, CHIRPS_IRIDL, OBS_YEARS
from utils import subset_to_india, save_netcdf

MONTH = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
         7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}


def _month_start(times):
    """Normalise any monthly time axis to first-of-month timestamps."""
    return pd.to_datetime(times).to_period("M").to_timestamp()


def download_temp(start, end):
    print(f"GHCN-CAMS 2 m temperature {start}-{end} ...")
    ds = xr.open_dataset(GHCNCAMS_URL)
    sub = subset_to_india(ds, INDIA_BBOX)
    sub = sub.sel(time=slice(f"{start}-01-01", f"{end}-12-31"))
    t2m = (sub["air"] - 273.15).astype("float32")     # degK -> degC
    t2m.attrs.update(units="degC", long_name="GHCN-CAMS 2 m air temperature")
    out = xr.Dataset({"t2m": t2m})
    out = out.assign_coords(time=_month_start(out["time"].values))
    out.attrs["source"] = GHCNCAMS_URL
    save_netcdf(out.load(), OBS_DIR / "ghcncams_t2m_india.nc")
    ds.close()


def download_precip(start, end):
    print(f"CHIRPS v2.0 precipitation {start}-{end} (IRI DL, regrid to 0.5 deg) ...")
    b = INDIA_BBOX
    grid = f"X/{b['west']}/0.5/{b['east']}/GRID/Y/{b['south']}/0.5/{b['north']}/GRID/"
    trange = f"T/%28{MONTH[1]}%20{start}%29/%28{MONTH[12]}%20{end}%29/RANGE/"
    url = CHIRPS_IRIDL + grid + trange + "dods"
    ds = xr.open_dataset(url, decode_times=False)     # IRI T uses a 360-day calendar
    ds = ds.rename({"X": "lon", "Y": "lat", "T": "time", "precipitation": "precip"})
    n = ds.sizes["time"]
    time = pd.date_range(f"{start}-01-01", periods=n, freq="MS")  # contiguous monthly
    ds = ds.assign_coords(time=time)
    ds["precip"] = ds["precip"].astype("float32")
    ds["precip"].attrs.update(units="mm/month", long_name="CHIRPS v2.0 precipitation")
    ds.attrs["source"] = url
    save_netcdf(ds[["precip"]].load(), OBS_DIR / "chirps_precip_india.nc")
    ds.close()


def main():
    p = argparse.ArgumentParser(description="Download India land observations (GHCN-CAMS temp, CHIRPS precip) for skill verification.")
    p.add_argument("--start", type=int, default=OBS_YEARS[0], help=f"First year (default {OBS_YEARS[0]}).")
    p.add_argument("--end", type=int, default=OBS_YEARS[1], help=f"Last year (default {OBS_YEARS[1]}).")
    p.add_argument("--only", choices=["temp", "precip"], default=None, help="Download just one variable.")
    args = p.parse_args()

    if args.only != "precip":
        download_temp(args.start, args.end)
    if args.only != "temp":
        download_precip(args.start, args.end)
    print("Done.")


if __name__ == "__main__":
    main()
