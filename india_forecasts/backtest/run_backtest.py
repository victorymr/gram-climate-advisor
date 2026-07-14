#!/usr/bin/env python3
"""
Backtest harness: for each sampled init, fetch the model members, region-collapse
them to the 666 advisor districts as weekly anomalies (reusing the operational
weight tensor + ERA5 climatology), store the small collapsed array, and optionally
purge the large raw download. Idempotent: an init whose collapsed file exists is skipped.

Kept per init  : collapsed/<init>.nc  — district x week x member anomalies (~1-2 MB).
Transient      : the model raw download (GEFS Herbie GRIB cache, CFSv2 grb2), deletable
                 with --purge-raw once the collapse is written.

Usage
-----
    python backtest/run_backtest.py --limit 1                 # one init (smoke / measure)
    python backtest/run_backtest.py                           # all inits in inits.csv
    python backtest/run_backtest.py --purge-raw               # delete raw after each collapse
    python backtest/run_backtest.py --models GEFS             # subset models
"""

import argparse
import glob
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

HERE = Path(__file__).resolve().parent
FC = HERE.parent                       # india_forecasts/
sys.path.insert(0, str(FC))

# The backtest is pinned to the original GADM 666-district geometry + a frozen coords
# snapshot, so it stays self-consistent even after the operational pipeline swaps to the
# newer LGD 785-district boundaries (which changes the default the loader returns).
os.environ.setdefault("GRAM_GEO", "gadm")

from config import DATA_DIR             # noqa: E402
from forecast_region import gadm_districts, region_weights          # noqa: E402
from forecast_region_s2s import anomalise, resolve_geom, _lonlat, VARS  # noqa: E402

COLL = HERE / "collapsed"
COLL.mkdir(exist_ok=True)
INITS_CSV = HERE / "inits.csv"
DISTRICTS_CSV = HERE / "districts_gadm666.csv"     # frozen GADM 666 snapshot (see above)
CLIM_DIR = DATA_DIR / "clim"
PY = sys.executable


def _child_env():
    # Herbie prints unicode (✅) status; Windows' cp1252 console crashes the fetch
    # threads without this, which silently stalls the whole download.
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return env

# model -> (subdir, weekly filename stem, has_members)
MODELS = {
    "GEFS":  ("gefs",  "gefs",   True),
    "CFSv2": ("cfsv2", "cfsv2",  False),
}


def weekly_path(model, init, members=False):
    sub, stem, _ = MODELS[model]
    suffix = "_india_weekly_members.nc" if members else "_india_weekly.nc"
    return DATA_DIR / sub / f"{stem}_{init}{suffix}"


def ensure_download(model, init_dash, init):
    """Fetch the model for this init if its weekly file isn't already present."""
    sub, _, has_members = MODELS[model]
    want = weekly_path(model, init, members=has_members)
    if want.exists():
        return want
    if model == "GEFS":
        cmd = [PY, "download_gefs.py", "--date", init_dash, "--members", "all"]
    elif model == "CFSv2":
        cmd = [PY, "download_cfsv2.py", "--date", init_dash]
    else:
        raise ValueError(model)
    print(f"    [{model}] downloading {init_dash} ...", flush=True)
    r = subprocess.run(cmd, cwd=str(FC), env=_child_env())
    if r.returncode != 0 or not want.exists():
        print(f"    [{model}] download FAILED for {init_dash}")
        return None
    return want


def ensure_clim(init, init_dash):
    """ERA5 weekly climatology for this init's day-of-year (MMDD; reused across years)."""
    clim = CLIM_DIR / f"era5_weekly_init{init[4:8]}_india_weekly.nc"
    if not clim.exists():
        print(f"    [clim] building {clim.name} ...", flush=True)
        subprocess.run([PY, "build_era5_clim.py", "--date", init_dash], cwd=str(FC), env=_child_env())
    return clim if clim.exists() else None


def build_weight_tensor(latvals, lonvals, latn, lonn, districts, gadm):
    """district x (lat,lon) normalised weight tensor -> collapse is one xr.dot."""
    Wnp = np.zeros((len(districts), latvals.size, lonvals.size))
    for i, d in enumerate(districts.itertuples(index=False)):
        geom, _ = resolve_geom(gadm, d.state, d.district, d.latitude, d.longitude)
        w, _, _ = region_weights(latvals, lonvals, latn, lonn, geom)
        wv = np.asarray(w.fillna(0.0).values)
        tot = wv.sum()
        if tot > 0:
            Wnp[i] = wv / tot
    return xr.DataArray(Wnp, dims=("district", latn, lonn),
                        coords={latn: latvals, lonn: lonvals})


def collapse_model(ds, clim, districts, gadm, wcache):
    """Anomalise each var vs clim and collapse the grid to districts. Returns
    {var: DataArray} with a leading 'district' dim (+ 'member' for ensembles)."""
    out = {}
    for v in VARS:                       # 't2m', 'precip'
        if v not in ds or v not in clim:
            continue
        a = anomalise(ds[v], clim[v])
        lonn, latn = _lonlat(a)
        key = (latn, lonn, a[latn].size, a[lonn].size,
               round(float(a[latn].values[0]), 3), round(float(a[lonn].values[0]), 3))
        if key not in wcache:
            wcache[key] = build_weight_tensor(a[latn].values, a[lonn].values,
                                              latn, lonn, districts, gadm)
        out[v] = xr.dot(wcache[key], a, dims=[latn, lonn])   # (district, [member,] week)
    return out


def process_init(init, init_dash, models, districts, gadm, wcache, purge_raw):
    out_path = COLL / f"{init}.nc"
    if out_path.exists():
        print(f"  {init_dash}: collapsed exists -> skip")
        return "skip"
    clim_path = ensure_clim(init, init_dash)
    if clim_path is None:
        print(f"  {init_dash}: no climatology -> skip")
        return "no_clim"
    clim = xr.open_dataset(clim_path)

    dvars, raw_files = {}, []
    for model in models:
        sub, _, has_members = MODELS[model]
        f = ensure_download(model, init_dash, init)
        if f is None:
            continue
        raw_files.append(f)
        ds = xr.open_dataset(f)
        coll = collapse_model(ds, clim, districts, gadm, wcache)
        ds.close()
        for v, da in coll.items():
            dvars[f"{model.lower()}_{v}_anom"] = da

    if not dvars:
        print(f"  {init_dash}: no model data collapsed -> skip")
        return "no_data"

    ds_out = xr.Dataset(dvars)
    ds_out = ds_out.assign_coords(
        state=("district", districts["state"].to_numpy()),
        district_name=("district", districts["district"].to_numpy()),
    )
    ds_out.attrs["init"] = init
    ds_out.to_netcdf(out_path)
    print(f"  {init_dash}: wrote {out_path.name} "
          f"({out_path.stat().st_size/1e6:.2f} MB; vars {list(dvars)})")

    if purge_raw:
        # the reassembled weekly files, plus the heavy intermediates: GEFS per-member
        # NetCDFs, CFSv2 global grb2 (~137 MB/init), and the Herbie GRIB cache.
        junk = list(raw_files)
        junk += list((DATA_DIR / "gefs").glob(f"gefs_{init}_member_*.nc"))
        junk += list((DATA_DIR / "cfsv2").glob(f"*{init}*.grb2"))
        junk += list((DATA_DIR / "cfsv2").glob(f"*{init}*.grb2.*"))
        for f in junk:
            try:
                Path(f).unlink()
            except OSError:
                pass
        for hb in glob.glob(str(Path.home() / "data" / "**" / f"*{init}*"), recursive=True):
            p = Path(hb)
            (shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True))
    return "ok"


def main():
    ap = argparse.ArgumentParser(description="District-level ensemble backtest harness.")
    ap.add_argument("--inits", default=str(INITS_CSV))
    ap.add_argument("--models", nargs="+", default=list(MODELS), choices=list(MODELS))
    ap.add_argument("--limit", type=int, default=None, help="Process only the first N inits.")
    ap.add_argument("--purge-raw", action="store_true", help="Delete raw downloads after collapse.")
    args = ap.parse_args()

    inits = pd.read_csv(args.inits)
    if args.limit:
        inits = inits.head(args.limit)
    districts = pd.read_csv(DISTRICTS_CSV)
    print(f"backtest: {len(inits)} init(s) x {len(districts)} districts; models {args.models}")
    gadm = gadm_districts()
    wcache = {}

    t0 = time.time()
    summary = {}
    for row in inits.itertuples(index=False):
        init_dash = str(row.init_date)
        init = init_dash.replace("-", "")
        print(f"[{init_dash}] {getattr(row, 'phase', '')}/{getattr(row, 'enso', '')}", flush=True)
        status = process_init(init, init_dash, args.models, districts, gadm, wcache, args.purge_raw)
        summary[status] = summary.get(status, 0) + 1
    print(f"\ndone in {time.time()-t0:.0f}s  {summary}")


if __name__ == "__main__":
    main()
