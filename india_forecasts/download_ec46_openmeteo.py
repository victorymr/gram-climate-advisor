#!/usr/bin/env python3
"""
Fetch ECMWF EC46 (live 46-day extended ensemble) from the Open-Meteo Seasonal
Forecast API over an India grid, aggregate to weekly means, save NetCDF.
This is the LIVE, no-embargo path to ECMWF extended-range (unlike the S2S/ECDS
route which is delayed ~3 weeks).

Open-Meteo is a POINT API, so this samples a regular India lat/lon grid (default
0.5 deg), batches the points into requests, then reshapes the per-point daily
series back into a (week, lat, lon) raster. Values come back already in degC and
mm, so weekly t2m = mean of daily means, weekly precip (mm/day) = mean of daily sums.

>>> I could not reach Open-Meteo from my build environment, so the endpoint and
>>> variable names below are my best understanding. RUN --probe FIRST: it queries
>>> one point and prints the JSON so you (or I) can confirm/adjust API_URL, MODEL,
>>> and the daily variable names. They're all CLI-overridable. <<<

SETUP : pip install requests xarray netcdf4
USAGE
-----
    python download_ec46_openmeteo.py --probe                 # confirm API shape, stop
    python download_ec46_openmeteo.py                         # India grid -> weekly NetCDF
    python download_ec46_openmeteo.py --res 0.5 --forecast-days 46
    python download_ec46_openmeteo.py --url <endpoint> --model <name> --tvar <v> --pvar <v>
"""

import sys
import json
import argparse
import numpy as np
import pandas as pd
import xarray as xr

from config import DATA_DIR, INDIA_BBOX
from utils import save_netcdf
from s2s_utils import to_weekly

EC46_DIR = DATA_DIR / "ec46"
EC46_DIR.mkdir(parents=True, exist_ok=True)

API_URL = "https://seasonal-api.open-meteo.com/v1/seasonal"   # confirm with --probe
MODEL = "ecmwf_ec46"
TVAR = "temperature_2m_mean"      # degC
PVAR = "precipitation_sum"        # mm/day (daily total)


def india_grid(res):
    lat = np.arange(INDIA_BBOX["south"], INDIA_BBOX["north"] + 1e-6, res)
    lon = np.arange(INDIA_BBOX["west"], INDIA_BBOX["east"] + 1e-6, res)
    return np.round(lat, 3), np.round(lon, 3)


def query(lats, lons, args, timeout=60):
    import requests
    params = {
        "latitude": ",".join(f"{v:.3f}" for v in lats),
        "longitude": ",".join(f"{v:.3f}" for v in lons),
        "daily": f"{args.tvar},{args.pvar}",
        "models": args.model,
        "forecast_days": args.forecast_days,
        "timezone": "UTC",
    }
    r = requests.get(args.url, params=params, timeout=timeout)
    r.raise_for_status()
    js = r.json()
    return js if isinstance(js, list) else [js]   # multi-location -> list; single -> dict


def probe(args):
    lat = (INDIA_BBOX["north"] + INDIA_BBOX["south"]) / 2
    lon = (INDIA_BBOX["west"] + INDIA_BBOX["east"]) / 2
    print(f"Probing {args.url}  model={args.model}  point=({lat:.1f},{lon:.1f})")
    js = query([lat], [lon], args)
    rec = js[0]
    print("top-level keys:", list(rec.keys()))
    daily = rec.get("daily", {})
    print("daily keys:", list(daily.keys()))
    t = daily.get("time", [])
    print(f"n days: {len(t)};  first/last: {t[:1]} ... {t[-1:]}")
    print(json.dumps({k: (v[:3] if isinstance(v, list) else v) for k, v in daily.items()}, indent=2)[:800])
    print("\nIf keys differ, re-run the real fetch with --tvar/--pvar/--model/--url overrides.")


def main():
    ap = argparse.ArgumentParser(description="Live EC46 from Open-Meteo over India, weekly NetCDF.")
    ap.add_argument("--res", type=float, default=0.5, help="India grid resolution in deg (default 0.5).")
    ap.add_argument("--forecast-days", type=int, default=46)
    ap.add_argument("--batch", type=int, default=150, help="Grid points per API request.")
    ap.add_argument("--url", default=API_URL)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--tvar", default=TVAR)
    ap.add_argument("--pvar", default=PVAR)
    ap.add_argument("--probe", action="store_true", help="Query one point, print JSON shape, stop.")
    args = ap.parse_args()

    if args.probe:
        probe(args)
        return

    lats, lons = india_grid(args.res)
    LON, LAT = np.meshgrid(lons, lats)
    flat_lat, flat_lon = LAT.ravel(), LON.ravel()
    n = flat_lat.size
    print(f"India grid {len(lats)}x{len(lons)} = {n} points; {args.forecast_days}-day EC46 ...")

    tcol, pcol, times = [None] * n, [None] * n, None
    for i in range(0, n, args.batch):
        sl = slice(i, i + args.batch)
        recs = query(flat_lat[sl], flat_lon[sl], args)
        for j, rec in enumerate(recs):
            daily = rec["daily"]
            if times is None:
                times = pd.to_datetime(daily["time"])
            tcol[i + j] = np.asarray(daily[args.tvar], float)
            pcol[i + j] = np.asarray(daily[args.pvar], float)
        print(f"  {min(i+args.batch, n)}/{n} points")

    nt = len(times)
    t_arr = np.array(tcol, float).reshape(len(lats), len(lons), nt).transpose(2, 0, 1)
    p_arr = np.array(pcol, float).reshape(len(lats), len(lons), nt).transpose(2, 0, 1)
    lead_h = (np.arange(nt) + 1) * 24
    coords = {"lead_hours": ("step", lead_h), "latitude": lats, "longitude": lons}
    t = xr.DataArray(t_arr, dims=("step", "latitude", "longitude"), coords=coords)
    p = xr.DataArray(p_arr, dims=("step", "latitude", "longitude"), coords=coords)

    t2m = to_weekly(t, method="mean")          # already degC
    precip = to_weekly(p, method="mean")       # daily sums (mm) -> weekly mean mm/day
    init = pd.Timestamp(times[0])              # day-1 valid date ~ init+1; label by day-1 date
    out = xr.Dataset({"t2m": t2m, "precip": precip},
                     attrs={"model": "EC46", "init_date": init.strftime("%Y%m%d"),
                            "kind": "forecast", "source": f"Open-Meteo {args.model}"})
    out_path = EC46_DIR / f"ec46om_{init.strftime('%Y%m%d')}_india_weekly.nc"
    save_netcdf(out, out_path)
    print(f"Done -> {out_path}")


if __name__ == "__main__":
    main()
