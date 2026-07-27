#!/usr/bin/env python3
"""
Plot EC46 (ECMWF extended) and GEFS (35-day) WEEKLY forecasts SIDE BY SIDE over
India, for the overlapping lead weeks (weeks 1-5; GEFS stops at day 35, EC46
reaches day 46). Rows = weeks, columns = EC46 | GEFS. Two PNGs: temperature and
precipitation.

DEFAULT = ANOMALY (forecast - that model's own reforecast climatology), on a
shared diverging scale per variable so the two models compare like-for-like.
Pass --absolute for raw weekly means.

Inputs are the weekly India NetCDFs written by download_ec46.py / download_gefs.py:
    vars  : t2m  [degC]  (weekly mean), precip [mm/day] (weekly mean)
    dims  : (week, lat, lon);  attrs: model, init_date
Climatology files (same structure) are auto-detected as *_clim_*.nc next to each
forecast, or given with --left-clim / --right-clim.

Usage:
    python plot_s2s_compare.py                       # newest EC46 vs newest GEFS, anomalies
    python plot_s2s_compare.py --absolute
    python plot_s2s_compare.py --left F --right F --left-clim F --right-clim F
"""

import os
import sys
import glob
import argparse
import numpy as np
import xarray as xr
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature

from config import DATA_DIR, INDIA_BBOX, ROOT
from s2s_utils import weekly_anomaly, overlap_weeks

EC46_DIR = DATA_DIR / "ec46"
GEFS_DIR = DATA_DIR / "gefs"
PLOTS_DIR = ROOT / "plots"
PLOTS_DIR.mkdir(exist_ok=True)

# var -> (label, absolute cmap, anomaly cmap, unit)
STYLE = {
    "t2m":    ("2 m temperature", "RdYlBu_r", "RdBu_r", "degC"),
    "precip": ("precipitation",   "YlGnBu",   "BrBG",   "mm/day"),
}


def _lonlat(da):
    lon = next((c for c in ("longitude", "lon", "x") if c in da.coords), None)
    lat = next((c for c in ("latitude", "lat", "y") if c in da.coords), None)
    if lon is None or lat is None:
        raise KeyError(f"lon/lat not found in coords {list(da.coords)}")
    return lon, lat


def _newest(pattern, exclude="clim"):
    files = [f for f in sorted(glob.glob(pattern)) if exclude not in os.path.basename(f).lower()]
    return files[-1] if files else None


def _find_clim(directory):
    c = sorted(glob.glob(str(directory / "*clim*weekly*.nc"))) or \
        sorted(glob.glob(str(directory / "*clim*.nc")))
    return c[-1] if c else None


def load_model(fc_path, clim_path, absolute):
    """Return (ds_for_plot, kind) where ds has t2m/precip on (week,lat,lon).
    kind is 'anomaly' or 'absolute'."""
    fc = xr.open_dataset(fc_path)
    if absolute or clim_path is None:
        return fc, "absolute"
    cl = xr.open_dataset(clim_path)
    out = xr.Dataset(attrs=fc.attrs)
    for v in ("t2m", "precip"):
        if v in fc and v in cl:
            out[v] = weekly_anomaly(fc[v], cl[v])
    return out, "anomaly"


def panel_limits(arrs, anomaly, robust=98):
    vals = np.concatenate([a.values.ravel() for a in arrs])
    vals = vals[np.isfinite(vals)]
    if anomaly:
        m = np.nanpercentile(np.abs(vals), robust)
        return -m, m
    return np.nanpercentile(vals, 100 - robust), np.nanpercentile(vals, robust)


def add_map(ax, proj, extent):
    # Force the Natural Earth fetch inside the guard: cartopy downloads lazily at
    # draw time, so we trigger it here to skip cleanly when offline (it is cached
    # after the first successful fetch on a connected machine).
    for feat, lw in ((cfeature.COASTLINE, 0.6), (cfeature.BORDERS, 0.4)):
        try:
            list(feat.geometries())
            ax.add_feature(feat, linewidth=lw)
        except Exception:
            pass
    ax.set_extent(extent, crs=proj)


def make_figure(var, left, right, lname, rname, kind, init_str, out):
    label, abs_cmap, anom_cmap, unit = STYLE[var]
    anomaly = (kind == "anomaly")
    cmap = anom_cmap if anomaly else abs_cmap
    if var not in left or var not in right:
        print(f"  {var}: missing in one model, skipped")
        return
    L, R = left[var], right[var]
    weeks = overlap_weeks(L, R)
    if not weeks:
        print(f"  {var}: no overlapping weeks, skipped")
        return
    vmin, vmax = panel_limits([L.sel(week=weeks), R.sel(week=weeks)], anomaly)

    proj = ccrs.PlateCarree()
    extent = [INDIA_BBOX["west"], INDIA_BBOX["east"], INDIA_BBOX["south"], INDIA_BBOX["north"]]
    nrow = len(weeks)
    fig, axes = plt.subplots(nrow, 2, figsize=(8.0, 3.1 * nrow),
                             constrained_layout=True, subplot_kw={"projection": proj})
    axes = np.atleast_2d(axes)
    im = None
    for r, w in enumerate(weeks):
        for c, (da, name) in enumerate(((L, lname), (R, rname))):
            ax = axes[r, c]
            field = da.sel(week=w)
            lonn, latn = _lonlat(field)
            im = ax.pcolormesh(field[lonn], field[latn], field.values, cmap=cmap,
                               vmin=vmin, vmax=vmax, shading="auto", transform=proj)
            add_map(ax, proj, extent)
            if r == 0:
                ax.set_title(name, fontsize=12, fontweight="bold")
            if c == 0:
                ax.text(-0.08, 0.5, f"Week {w}", transform=ax.transAxes,
                        rotation=90, va="center", ha="center", fontsize=11)
    cbar = fig.colorbar(im, ax=axes.ravel().tolist(), shrink=0.6, pad=0.02)
    cbar.set_label(f"{unit}{' anomaly' if anomaly else ''}")
    kind_str = "anomaly" if anomaly else "weekly mean"
    fig.suptitle(f"EC46 vs GEFS {label} {kind_str} - init {init_str} (weeks {weeks[0]}-{weeks[-1]})",
                 fontsize=13, fontweight="bold")
    fig.savefig(out, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved -> {out}")


def main():
    ap = argparse.ArgumentParser(description="Side-by-side EC46 vs GEFS weekly maps over India.")
    ap.add_argument("--left", default=None, help="EC46 weekly NetCDF (default newest in data/ec46).")
    ap.add_argument("--right", default=None, help="GEFS weekly NetCDF (default newest in data/gefs).")
    ap.add_argument("--left-clim", default=None)
    ap.add_argument("--right-clim", default=None)
    ap.add_argument("--left-name", default="EC46 (ECMWF)")
    ap.add_argument("--right-name", default="GEFS (NOAA)")
    ap.add_argument("--absolute", action="store_true", help="Raw weekly means instead of anomalies.")
    args = ap.parse_args()

    left_fc = args.left or _newest(str(EC46_DIR / "*weekly*.nc"))
    right_fc = args.right or _newest(str(GEFS_DIR / "*weekly*.nc"))
    if not left_fc or not right_fc:
        sys.exit(f"Need both forecasts. EC46={left_fc}, GEFS={right_fc}. "
                 "Run download_ec46.py and download_gefs.py first.")

    left_clim = args.left_clim or (None if args.absolute else _find_clim(EC46_DIR))
    right_clim = args.right_clim or (None if args.absolute else _find_clim(GEFS_DIR))

    left, klind = load_model(left_fc, left_clim, args.absolute)
    right, krind = load_model(right_fc, right_clim, args.absolute)
    kind = "anomaly" if (klind == "anomaly" and krind == "anomaly") else "absolute"
    if kind == "absolute" and not args.absolute:
        print("  note: climatology missing for one/both models -> plotting ABSOLUTE. "
              "Run the downloaders' --reforecast mode for anomalies.")
    init_str = str(left.attrs.get("init_date", "?"))

    print(f"EC46={left_fc}\nGEFS={right_fc}\nmode={kind}")
    for var in ("t2m", "precip"):
        make_figure(var, left, right, args.left_name, args.right_name, kind, init_str,
                    PLOTS_DIR / f"s2s_compare_{var}_{init_str}_{kind}.png")
    print("Done.")


if __name__ == "__main__":
    main()
