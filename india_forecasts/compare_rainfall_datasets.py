#!/usr/bin/env python3
"""
Compare gridded rainfall observation datasets over India: ERA5 vs CHIRPS vs IMD.

For a monsoon season (default JJAS 2024 — recent and complete in all three) it pulls each
dataset, regrids to a common 0.25 deg India grid, computes the seasonal rainfall total per
grid cell, and reports/plots the PAIRWISE correlation and bias between every pair. This is
the evidence for whether ERA5 (used by observed_departures.py) is systematically dry vs the
rainfall-specific products, informing the observed-data source choice.

Sources:
  ERA5   : Copernicus CDS derived-era5-single-levels-daily-statistics (daily_sum tp)  [needs ~/.cdsapirc]
  CHIRPS : UCSB CHC direct  data.chc.ucsb.edu/.../global_daily/netcdf/p25/  (IRI DL is flaky)
  IMD    : imdlib 0.25 deg gridded rainfall (India, land-only)

Output: plots/rainfall_dataset_comparison.png  (+ printed stats).

Usage:
    python compare_rainfall_datasets.py                 # JJAS 2024
    python compare_rainfall_datasets.py --year 2023 --months 6 7 8 9
"""

import sys
import zipfile
import argparse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from config import DATA_DIR, INDIA_BBOX, cds_area, ROOT
from utils import subset_to_india

PLOTS_DIR = ROOT / "plots"
OBS = DATA_DIR / "obs"
B = INDIA_BBOX


def _open_any(path):
    path = Path(path)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            ncs = [n for n in z.namelist() if n.endswith(".nc")]
            z.extractall(path.parent)
            path = path.parent / ncs[0]
    return xr.open_dataset(path)


def _std(da):
    """Rename to (lat, lon), ascending, and clip to the India box."""
    ren = {}
    for a, b in (("latitude", "lat"), ("longitude", "lon"), ("X", "lon"), ("Y", "lat")):
        if a in da.coords or a in da.dims:
            ren[a] = b
    da = da.rename(ren)
    if da["lat"][0] > da["lat"][-1]:
        da = da.sortby("lat")
    return da.sel(lat=slice(B["south"], B["north"]), lon=slice(B["west"], B["east"]))


def get_era5(year, months):
    import cdsapi
    cli = cdsapi.Client()
    raw = OBS / "_era5_cmp"; raw.mkdir(parents=True, exist_ok=True)
    tot = None
    for m in months:
        f = raw / f"tp_{year}{m:02d}.nc"
        if not f.exists():
            print(f"  ERA5 {year}-{m:02d} ...")
            cli.retrieve("derived-era5-single-levels-daily-statistics", {
                "product_type": "reanalysis", "variable": ["total_precipitation"],
                "year": [str(year)], "month": [f"{m:02d}"], "day": [f"{d:02d}" for d in range(1, 32)],
                "daily_statistic": "daily_sum", "time_zone": "utc+00:00", "frequency": "1_hourly",
                "area": cds_area(B), "data_format": "netcdf", "download_format": "unarchived"}, str(f))
        d = _open_any(f)
        p = d[next(v for v in ("tp", "total_precipitation") if v in d.data_vars)] * 1000.0
        tdim = next(t for t in ("valid_time", "time") if t in p.dims)
        s = p.sum(tdim)
        tot = s if tot is None else tot + s
    return _std(tot).rename("ERA5")


def get_chirps(year, months):
    f = OBS / f"chirps-v2.0.{year}.days_p25.nc"
    if not f.exists():
        url = f"https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/netcdf/p25/{f.name}"
        print(f"  CHIRPS download {url} ...")
        urllib.request.urlretrieve(url, f)
    ds = xr.open_dataset(f)
    p = ds["precip"].where(ds["precip"] >= 0)
    p = p.sel(time=p["time"].dt.month.isin(months))
    total = p.sum("time").where(p.notnull().any("time"))   # keep ocean/no-data as NaN
    return _std(total).rename("CHIRPS")


def get_imd(year, months):
    import imdlib as imd
    d = imd.get_data("rain", year, year, fn_format="yearwise", file_dir=str(OBS / "imd"))
    ds = d.get_xarray()
    r = ds["rain"].where(ds["rain"] >= 0)                 # -999 fill -> NaN (ocean)
    r = r.sel(time=r["time"].dt.month.isin(months))
    total = r.sum("time").where(r.notnull().any("time"))  # keep ocean/no-data as NaN
    return _std(total).rename("IMD")


def _pair_stats(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    x, y = a[m], b[m]
    r = float(np.corrcoef(x, y)[0, 1])
    bias = float(np.mean(x) - np.mean(y))               # a - b (mm, seasonal)
    bias_pct = 100.0 * bias / float(np.mean(y))
    return r, bias, bias_pct, x, y


def main():
    ap = argparse.ArgumentParser(description="ERA5 vs CHIRPS vs IMD rainfall comparison over India.")
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--months", type=int, nargs="+", default=[6, 7, 8, 9])
    ap.add_argument("--out", default=str(PLOTS_DIR / "rainfall_dataset_comparison.png"))
    args = ap.parse_args()
    season = "".join("JFMAMJJASOND"[m - 1] for m in args.months)
    print(f"Comparing ERA5 / CHIRPS / IMD  —  {season} {args.year}")

    era5, chirps, imd = get_era5(args.year, args.months), get_chirps(args.year, args.months), get_imd(args.year, args.months)
    # common grid = ERA5; regrid the others, keep only cells valid in all three (land)
    chirps = chirps.interp(lat=era5["lat"], lon=era5["lon"])
    imd = imd.interp(lat=era5["lat"], lon=era5["lon"])
    valid = np.isfinite(era5) & np.isfinite(chirps) & np.isfinite(imd)
    E, C, I = (d.where(valid).values.ravel() for d in (era5, chirps, imd))

    pairs = [("ERA5", E, "CHIRPS", C), ("ERA5", E, "IMD", I), ("CHIRPS", C, "IMD", I)]
    print(f"\n{season} {args.year} seasonal rainfall, {int(np.isfinite(E).sum())} common land cells:")
    fig, axes = plt.subplots(1, 3, figsize=(15, 5.2), constrained_layout=True)
    for ax, (na, a, nb, b) in zip(axes, pairs):
        r, bias, bpct, x, y = _pair_stats(a, b)
        print(f"  {na} vs {nb}:  r={r:.3f}   bias({na}-{nb})={bias:+.0f} mm ({bpct:+.0f}%)   "
              f"mean {na}={np.mean(x):.0f}, {nb}={np.mean(y):.0f} mm")
        hi = float(np.nanpercentile(np.concatenate([x, y]), 99))
        ax.scatter(y, x, s=4, alpha=0.25, color="#2b6cb0", edgecolors="none")
        ax.plot([0, hi], [0, hi], color="#c0392b", lw=1.2, ls="--", label="1:1")
        ax.set_xlim(0, hi); ax.set_ylim(0, hi); ax.set_aspect("equal")
        ax.set_xlabel(f"{nb}  (mm, {season} {args.year})")
        ax.set_ylabel(f"{na}  (mm)")
        ax.set_title(f"{na} vs {nb}\nr = {r:.2f}   bias = {bpct:+.0f}%", fontsize=11)
        ax.legend(loc="lower right", fontsize=8)
        ax.grid(True, lw=0.3, alpha=0.4)
    fig.suptitle(f"India rainfall datasets — {season} {args.year} seasonal totals (grid-cell)",
                 fontsize=13, fontweight="bold")
    Path(args.out).parent.mkdir(exist_ok=True)
    fig.savefig(args.out, dpi=140, bbox_inches="tight")
    print(f"\nsaved -> {args.out}")


if __name__ == "__main__":
    main()
