#!/usr/bin/env python3
"""
Download NOAA CFSv2 operational forecast from AWS, crop to India, aggregate to
weekly means, save NetCDF. No account needed (anonymous S3). Live, daily,
runs to 9 months -> easily covers weeks 1-6.

Source : s3://noaa-cfs-pds  (Registry of Open Data on AWS), GRIB2, ~0.5 deg.
Layout : cfs.<YYYYMMDD>/<HH>/time_grib_01/<var>.01.<YYYYMMDDHH>.daily.grb2
         time_grib_01 holds per-VARIABLE time series for the whole run:
           tmp2m.01.<init>.daily.grb2   -> 2 m temperature (K)
           prate.01.<init>.daily.grb2   -> precip RATE (kg m-2 s-1 = mm/s)
CFSv2 operational is effectively ONE member per cycle (the 4 daily cycles form a
lagged ensemble); this pulls the 00 UTC member 01 by default.

Layout still settles occasionally, so this script DISCOVERS before it downloads.
Run --explore first to confirm the tree for your date.

SETUP : pip install boto3 cfgrib eccodes xarray netcdf4

USAGE
-----
    python download_cfsv2.py --date 2026-06-29 --explore         # show the tree
    python download_cfsv2.py --date 2026-06-29                   # -> weekly India NetCDF
    python download_cfsv2.py --date 2026-06-29 --cycle 00 --max-days 46
"""

import sys
import argparse
import numpy as np
import pandas as pd
import xarray as xr
import boto3
from botocore import UNSIGNED
from botocore.config import Config

from config import DATA_DIR, INDIA_BBOX
from utils import subset_to_india, save_netcdf
from s2s_utils import to_weekly

BUCKET = "noaa-cfs-pds"
CFSV2_DIR = DATA_DIR / "cfsv2"
CFSV2_DIR.mkdir(parents=True, exist_ok=True)
KG_M2_S_TO_MMDAY = 86400.0          # prate (mm/s) -> mm/day


def s3():
    return boto3.client("s3", config=Config(signature_version=UNSIGNED))


def list_prefix(prefix):
    cli = s3(); pag = cli.get_paginator("list_objects_v2")
    subs, files = [], []
    for pg in pag.paginate(Bucket=BUCKET, Prefix=prefix, Delimiter="/"):
        subs += [c["Prefix"] for c in pg.get("CommonPrefixes", [])]
        files += [(o["Key"], o["Size"]) for o in pg.get("Contents", []) if o["Key"] != prefix]
    return subs, files


def explore(prefix, depth=2):
    def walk(p, d, ind=""):
        subs, files = list_prefix(p)
        for sd in subs:
            print(f"{ind}{sd.rstrip('/').split('/')[-1]}/")
            if d > 1:
                walk(sd, d - 1, ind + "  ")
        for k, sz in files[:20]:
            print(f"{ind}{k.split('/')[-1]}  ({sz/1e6:.1f} MB)")
    print(f"s3://{BUCKET}/{prefix}")
    walk(prefix, depth)


def find_var_file(date, cycle, var):
    """Locate <var>.01.<init>.daily.grb2 under cfs.<date>/<cycle>/time_grib_01/."""
    d = pd.Timestamp(date)
    base = f"cfs.{d.strftime('%Y%m%d')}/{cycle}/time_grib_01/"
    _, files = list_prefix(base)
    cand = [k for k, _ in files if f"/{var}." in "/" + k.split("/")[-1] and k.endswith(".grb2")]
    # match files starting with '<var>.' to avoid e.g. tmpsfc vs tmp2m collisions
    cand = [k for k, _ in files if k.split("/")[-1].startswith(var + ".") and k.endswith(".grb2")]
    return cand[0] if cand else None


def download(key):
    dest = CFSV2_DIR / key.split("/")[-1]
    print(f"Downloading {key} ...")
    s3().download_file(BUCKET, key, str(dest))
    print(f"  -> {dest}  ({dest.stat().st_size/1e6:.1f} MB)")
    return dest


def open_series(path):
    ds = xr.open_dataset(path, engine="cfgrib")
    v = list(ds.data_vars)[0]
    da = subset_to_india(ds[v], INDIA_BBOX)
    # standardise lead coordinate to hours-from-init named 'lead_hours'
    sdim = [x for x in da.dims if x not in ("latitude", "longitude", "lat", "lon")]
    sdim = sdim[0] if sdim else "step"
    if "step" in da.coords and np.issubdtype(np.asarray(da["step"]).dtype, np.timedelta64):
        lead_h = (da["step"] / np.timedelta64(1, "h")).astype(int).values
    elif "valid_time" in da.coords:
        vt = pd.to_datetime(np.asarray(da["valid_time"]))
        lead_h = ((vt - vt[0]) / pd.Timedelta(hours=1)).astype(int)
    else:
        lead_h = (np.arange(da.sizes[sdim]) + 1) * 24
    return da.assign_coords(lead_hours=(sdim, np.asarray(lead_h).astype(int))).sortby("lead_hours"), sdim


def main():
    ap = argparse.ArgumentParser(description="Download CFSv2 for India, weekly NetCDF.")
    ap.add_argument("--date", required=True, help="Init date YYYY-MM-DD.")
    ap.add_argument("--cycle", default="00", help="Cycle HH (00/06/12/18; default 00).")
    ap.add_argument("--max-days", type=int, default=46)
    ap.add_argument("--explore", action="store_true")
    args = ap.parse_args()

    d = pd.Timestamp(args.date)
    if args.explore:
        explore(f"cfs.{d.strftime('%Y%m%d')}/{args.cycle}/", depth=2)
        return

    tkey = find_var_file(args.date, args.cycle, "tmp2m")
    pkey = find_var_file(args.date, args.cycle, "prate")
    if not (tkey and pkey):
        sys.exit(f"Could not find tmp2m/prate under cfs.{d.strftime('%Y%m%d')}/{args.cycle}/time_grib_01/. "
                 f"Run --explore to inspect (found tmp2m={tkey}, prate={pkey}).")

    tpath, ppath = download(tkey), download(pkey)
    maxh = args.max_days * 24

    t, _ = open_series(tpath)
    t = t.where(t["lead_hours"] <= maxh, drop=True)
    t2m = to_weekly(t, method="mean") - 273.15

    p, _ = open_series(ppath)
    p = p.where(p["lead_hours"] <= maxh, drop=True)
    precip = to_weekly(p, method="mean") * KG_M2_S_TO_MMDAY     # mean rate -> mm/day

    out = xr.Dataset({"t2m": t2m, "precip": precip},
                     attrs={"model": "CFSv2", "init_date": d.strftime("%Y%m%d"),
                            "kind": "forecast", "source": f"NOAA CFSv2 AWS ({args.cycle}Z member 01)"})
    out_path = CFSV2_DIR / f"cfsv2_{d.strftime('%Y%m%d')}_india_weekly.nc"
    save_netcdf(out, out_path)
    print(f"Done -> {out_path}")


if __name__ == "__main__":
    main()
