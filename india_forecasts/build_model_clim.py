#!/usr/bin/env python3
"""
Build a MODEL climatology: each model's own mean forecast as a function of
(init day-of-year, lead-week, lat, lon) on the India grid.

Why: forecast_region_s2s.anomalise() currently subtracts one shared ERA5 climatology
from every model, so a model's mean offset vs ERA5 survives into the reported anomaly
-- and into the "wetter / drier than normal" wording. The backtest measured this: CFSv2
carried a -1.9 mm/day dry offset and reported "drier than normal" 58% of the time
against a 46% observed base rate. Referencing each model to its OWN history removes the
model-specific part of that. This script builds that reference.

Method
------
1. DOWNLOAD  Sample init dates every --step-days across --years and fetch each model's
   ENSEMBLE MEAN 35-day forecast (a climatology needs the mean, not the members -- far
   cheaper). Weekly India NetCDFs are small (~140 KB) so they are KEPT; only the heavy
   raw GRIB / Herbie cache is purged. Resumable: existing inits are skipped.
2. AGGREGATE For each output DOY node, average every sampled init whose day-of-year
   falls within +/- --window days (circular). Model bias varies smoothly in season and
   space, so this pooling gives a stable estimate without needing dense sampling.

Output: data/clim/<model>_model_clim.nc  with dims (doy, week, lat, lon), vars t2m/precip.

Sampling is ordered MONSOON-FIRST so a partial run is already useful for the season the
advisory serves.

Usage:
    python build_model_clim.py --model gefs --years 2021 2025          # download+aggregate
    python build_model_clim.py --model cfsv2 --aggregate-only
    python build_model_clim.py --model gefs --step-days 10 --window 15
"""

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from config import DATA_DIR                      # noqa: E402
from utils import save_netcdf                    # noqa: E402

CLIM_DIR = DATA_DIR / "clim"
CLIM_DIR.mkdir(parents=True, exist_ok=True)
PY = sys.executable

# monsoon-relevant window (pre-monsoon heat through withdrawal) -- sampled first
MONSOON_START_DOY, MONSOON_END_DOY = 91, 305      # ~Apr 1 .. ~Nov 1


def _child_env():
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"             # Herbie's status glyph breaks cp1252
    return env


def sample_inits(years, step_days, full_year):
    """Init dates every step_days, monsoon nodes first so partial runs are useful."""
    dates = []
    for y in range(years[0], years[1] + 1):
        d = pd.Timestamp(f"{y}-01-01")
        while d.year == y:
            doy = int(d.dayofyear)
            in_monsoon = MONSOON_START_DOY <= doy <= MONSOON_END_DOY
            if full_year or in_monsoon:
                dates.append((0 if in_monsoon else 1, d))
            d += pd.Timedelta(days=step_days)
    dates.sort(key=lambda t: (t[0], t[1]))        # monsoon block first, chronological
    return [d for _, d in dates]


def weekly_path(model, init):
    tag = init.strftime("%Y%m%d")
    return DATA_DIR / model / f"{model}_{tag}_india_weekly.nc"


def purge_raw(model, init):
    """Drop the heavy intermediates; keep the small weekly NetCDF."""
    tag = init.strftime("%Y%m%d")
    junk = list((DATA_DIR / "cfsv2").glob(f"*{tag}*.grb2")) + \
           list((DATA_DIR / "cfsv2").glob(f"*{tag}*.grb2.*")) + \
           list((DATA_DIR / "gefs").glob(f"gefs_{tag}_member_*.nc"))
    for f in junk:
        try:
            Path(f).unlink()
        except OSError:
            pass
    for hb in glob.glob(str(Path.home() / "data" / "**" / f"*{tag}*"), recursive=True):
        p = Path(hb)
        shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)


def download(model, inits, keep_raw=False):
    got, failed = 0, 0
    for i, init in enumerate(inits, 1):
        out = weekly_path(model, init)
        if out.exists():
            got += 1
            continue
        dash = init.strftime("%Y-%m-%d")
        cmd = ([PY, "download_gefs.py", "--date", dash, "--member", "avg"] if model == "gefs"
               else [PY, "download_cfsv2.py", "--date", dash])
        print(f"[{i}/{len(inits)}] {model} {dash} ...", flush=True)
        r = subprocess.run(cmd, cwd=str(HERE), env=_child_env(),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not keep_raw:
            purge_raw(model, init)
        if out.exists():
            got += 1
        else:
            failed += 1
            print(f"    -> FAILED (rc={r.returncode}); continuing", flush=True)
    print(f"\n{model}: {got} init(s) available, {failed} failed")
    return got


def _circ_dist(a, b, period=365.25):
    d = np.abs(a - b)
    return np.minimum(d, period - d)


def aggregate(model, step_days, window, full_year):
    """Pool sampled inits into a (doy, week, lat, lon) climatology."""
    files = sorted(f for f in glob.glob(str(DATA_DIR / model / f"{model}_*_india_weekly.nc"))
                   if "_members" not in f)
    if not files:
        sys.exit(f"No weekly files for {model}; run the download phase first.")
    doys, das = [], []
    for f in files:
        m = re.search(rf"{model}_(\d{{8}})_india_weekly", Path(f).name)
        if not m:
            continue
        init = pd.Timestamp(m.group(1))
        ds = xr.open_dataset(f)
        if not {"t2m", "precip"} <= set(ds.data_vars):
            ds.close(); continue
        doys.append(int(init.dayofyear))
        das.append(ds[["t2m", "precip"]].load())
        ds.close()
    if not das:
        sys.exit(f"No usable weekly files for {model}.")
    doys = np.asarray(doys)
    stack = xr.concat(das, dim=pd.Index(np.arange(len(das)), name="sample"))

    nodes = list(range(1, 366, step_days)) if full_year else \
        list(range(MONSOON_START_DOY, MONSOON_END_DOY + 1, step_days))
    out, keep, counts = [], [], []
    for node in nodes:
        sel = np.where(_circ_dist(doys, node) <= window)[0]
        if sel.size == 0:
            continue
        out.append(stack.isel(sample=sel).mean("sample"))
        keep.append(node); counts.append(int(sel.size))
    if not out:
        sys.exit(f"No DOY node had samples within +/-{window} days for {model}.")
    clim = xr.concat(out, dim=pd.Index(keep, name="doy"))
    clim["n_samples"] = ("doy", np.asarray(counts))
    clim.attrs.update(model=model.upper(), kind="model_climatology",
                      years=f"{pd.Timestamp(files[0][-24:-16]).year}-",
                      step_days=step_days, window_days=window,
                      n_inits=len(das),
                      note="Each model's own mean forecast by (init DOY, lead week); "
                           "subtract from a forecast to anomalise vs the model's own history.")
    path = CLIM_DIR / f"{model}_model_clim.nc"
    save_netcdf(clim, path)
    print(f"{model}: {len(das)} inits -> {len(keep)} DOY nodes "
          f"(median {int(np.median(counts))} samples/node) -> {path}")
    return path


def main():
    ap = argparse.ArgumentParser(description="Build each model's own climatology.")
    ap.add_argument("--model", choices=["gefs", "cfsv2"], required=True)
    ap.add_argument("--years", type=int, nargs=2, metavar=("START", "END"), default=[2021, 2025])
    ap.add_argument("--step-days", type=int, default=10, help="Init sampling interval (days).")
    ap.add_argument("--window", type=int, default=15, help="DOY pooling half-width (days).")
    ap.add_argument("--monsoon-only", action="store_true",
                    help="Sample only ~Apr-Nov instead of the full year.")
    ap.add_argument("--aggregate-only", action="store_true", help="Skip downloading.")
    ap.add_argument("--keep-raw", action="store_true")
    args = ap.parse_args()

    full_year = not args.monsoon_only
    inits = sample_inits(args.years, args.step_days, full_year)
    print(f"{args.model}: {len(inits)} sampled inits "
          f"({args.years[0]}-{args.years[1]}, every {args.step_days} d, "
          f"{'full year' if full_year else 'monsoon only'}), monsoon-first")
    if not args.aggregate_only:
        download(args.model, inits, keep_raw=args.keep_raw)
    aggregate(args.model, args.step_days, args.window, full_year)


if __name__ == "__main__":
    main()
