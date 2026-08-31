#!/usr/bin/env python3
"""
Re-reference the already-collapsed backtest forecasts from the shared ERA5 climatology
to each model's OWN climatology, without re-downloading anything.

The collapsed files store, per (district, [member,] week):
    anom_era5 = collapse(forecast - ERA5_clim)
We want:
    anom_own  = collapse(forecast - model_own_clim)
Collapse is linear, so:
    anom_own  = anom_era5 - collapse(model_own_clim - ERA5_clim)
The correction delta is model-only (no members), computed once per model grid and
selected at each init's day-of-year node -- exactly the reference model_clim() uses at
run time (data/clim/<model>_model_clim.nc). Models without an own climatology (EC46) or
where the guard would reject the nearest node are left on ERA5 (delta = 0).

Writes collapsed_reref/<init>.nc (same structure as collapsed/). Then:
    BACKTEST_COLL=<...>/collapsed_reref python backtest/metrics.py
scores the re-referenced forecasts.

Usage:
    python backtest/rereference.py
"""

import glob
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

HERE = Path(__file__).resolve().parent
FC = HERE.parent
sys.path.insert(0, str(FC))
os.environ.setdefault("GRAM_GEO", "lgd")

from config import DATA_DIR                                            # noqa: E402
from forecast_region import gadm_districts                            # noqa: E402
from forecast_region_s2s import anomalise, model_clim, VARS           # noqa: E402
from build_truth import weight_tensor                                 # noqa: E402  (district collapse)

COLL = HERE / "collapsed"
OUT = HERE / "collapsed_reref"
OUT.mkdir(exist_ok=True)
DISTRICTS_CSV = FC.parent / "data" / "district_coordinates.csv"
CLIM_DIR = DATA_DIR / "clim"
MODELS = ("gefs", "cfsv2")


def era5_for_init(init):
    p = CLIM_DIR / f"era5_weekly_init{init[4:8]}_india_weekly.nc"
    return xr.open_dataset(p) if p.exists() else None


def collapse_delta(model, init, districts, gadm, wcache):
    """District-collapsed (model_own_clim - ERA5_clim) per (district, week), or None if
    this model/init keeps the ERA5 reference (delta = 0)."""
    era5 = era5_for_init(init)
    if era5 is None:
        return None
    clim, label = model_clim(model, init, era5)
    if label.startswith("ERA5"):           # guard rejected / no own clim -> no change
        era5.close()
        return None
    out = {}
    for v in VARS:
        if v not in clim or v not in era5:
            continue
        # (model_clim - ERA5_clim) on the model grid, using anomalise() to align/regrid
        # ERA5 onto the model clim's grid exactly as the run-time path does.
        d = anomalise(clim[v], era5[v])                  # (week, lat, lon) on model grid
        lonn, latn = _lonlat_local(d)
        key = (latn, lonn, d[latn].size, d[lonn].size,
               round(float(d[latn].values[0]), 3), round(float(d[lonn].values[0]), 3))
        if key not in wcache:
            W, _la, _lo = weight_tensor(d, districts, gadm)
            wcache[key] = (W, _la, _lo)
        W, la, lo = wcache[key]
        out[v] = xr.dot(W, d, dims=[la, lo])             # (district, week)
    era5.close()
    return out, label


def _lonlat_local(da):
    lat = "latitude" if "latitude" in da.dims else "lat"
    lon = "longitude" if "longitude" in da.dims else "lon"
    return lon, lat


def main():
    districts = pd.read_csv(DISTRICTS_CSV)
    gadm = gadm_districts()
    wcache = {}
    inits = [Path(p).stem for p in sorted(glob.glob(str(COLL / "*.nc")))]
    print(f"re-referencing {len(inits)} inits x {MODELS} ...")
    used = {m: 0 for m in MODELS}
    for init in inits:
        fc = xr.open_dataset(COLL / f"{init}.nc").load()
        new = fc.copy(deep=True)
        for model in MODELS:
            res = collapse_delta(model, init, districts, gadm, wcache)
            if res is None:
                continue
            delta, label = res
            for v in VARS:
                var = f"{model}_{v}_anom"
                if var in new and v in delta:
                    # delta is (district, week); broadcasts over member automatically
                    new[var] = new[var] - delta[v]
            used[model] += 1
        new.to_netcdf(OUT / f"{init}.nc")
        fc.close()
    print(f"wrote {len(inits)} files -> {OUT}")
    for m in MODELS:
        print(f"  {m}: own-climatology correction applied to {used[m]}/{len(inits)} inits")
    print(f"\nNow score them:\n  BACKTEST_COLL={OUT} python backtest/metrics.py")


if __name__ == "__main__":
    main()
