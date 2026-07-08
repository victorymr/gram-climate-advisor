#!/usr/bin/env python3
"""
Plot N subseasonal models SIDE BY SIDE over India for the overlapping lead weeks.
Rows = weeks (intersection across models), columns = models (e.g. GEFS | CFSv2 |
EC46). Two PNGs: 2 m temperature and precipitation.

ANOMALY MODE (default when a climatology is available): each model is shown as
forecast - climatology on a shared diverging scale, so models compare like-for-
like. Anomaly source per model, in priority order:
  1. --common-clim FILE  (one reference, e.g. ERA5 weekly clim) applied to ALL
     models -> the cleanest cross-model comparison (regridded to each model).
  2. a per-model climatology file (its own reforecast), auto-found as *clim*weekly*.
If no model can be anomalised, falls back to ABSOLUTE (shared sequential scale).
Use --absolute to force raw weekly means.

Each model file is a weekly India NetCDF (vars t2m [degC], precip [mm/day];
dims week,lat/longitude) from the download_*.py scripts.

Usage:
    python plot_s2s_multi.py --model "GEFS=data/gefs/gefs_20260629_india_weekly.nc" \
                             --model "CFSv2=data/cfsv2/cfsv2_20260629_india_weekly.nc" \
                             --model "EC46=data/ec46/ec46_20260629_india_weekly.nc" \
                             --common-clim data/clim/era5_weekly_init0629_india.nc
    python plot_s2s_multi.py --auto                 # newest file in each of gefs/cfsv2/ec46
    python plot_s2s_multi.py --auto --absolute
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
from s2s_utils import overlap_weeks

PLOTS_DIR = ROOT / "plots"
PLOTS_DIR.mkdir(exist_ok=True)

STYLE = {  # var -> (label, absolute cmap, anomaly cmap, unit)
    "t2m":    ("2 m temperature", "RdYlBu_r", "RdBu_r", "degC"),
    "precip": ("precipitation",   "YlGnBu",   "BrBG",   "mm/day"),
}
AUTO_DIRS = [("GEFS", "gefs"), ("CFSv2", "cfsv2"), ("EC46", "ec46")]


def _lonlat(da):
    lon = next((c for c in ("longitude", "lon", "x") if c in da.coords), None)
    lat = next((c for c in ("latitude", "lat", "y") if c in da.coords), None)
    if lon is None or lat is None:
        raise KeyError(f"lon/lat not in {list(da.coords)}")
    return lon, lat


def _newest(d, exclude="clim"):
    fs = [f for f in sorted(glob.glob(str(DATA_DIR / d / "*weekly*.nc"))) if exclude not in os.path.basename(f).lower()]
    return fs[-1] if fs else None


def _find_model_clim(d):
    c = sorted(glob.glob(str(DATA_DIR / d / "*clim*weekly*.nc")))
    return c[-1] if c else None


def anomalise(da, clim_da):
    """da - clim, with clim regridded to da's grid if needed."""
    lon, lat = _lonlat(da)
    clon, clat = _lonlat(clim_da)
    cl = clim_da.rename({clat: lat, clon: lon}) if (clat, clon) != (lat, lon) else clim_da
    # align weeks, interpolate clim onto the model grid
    cl = cl.sel(week=da["week"])
    if not (np.array_equal(cl[lat], da[lat]) and np.array_equal(cl[lon], da[lon])):
        cl = cl.interp({lat: da[lat], lon: da[lon]})
    return da - cl


def load_models(specs, common_clim, force_absolute):
    """specs: list of (name, fc_path, clim_path_or_None). Returns
    (models, kind) where models = [(name, ds_for_plot)] and kind in
    {'anomaly','absolute'}."""
    common = xr.open_dataset(common_clim) if common_clim else None
    loaded = [(name, xr.open_dataset(p), clim) for name, p, clim in specs]

    if not force_absolute:
        # a model is anomalisable if we have a common clim or its own clim
        def clim_for(clim_path):
            if common is not None:
                return common
            return xr.open_dataset(clim_path) if clim_path else None
        if all(clim_for(c) is not None for _, _, c in loaded):
            out = []
            for name, ds, clim_path in loaded:
                cl = common if common is not None else xr.open_dataset(clim_path)
                d = xr.Dataset(attrs=ds.attrs)
                for v in ("t2m", "precip"):
                    if v in ds and v in cl:
                        d[v] = anomalise(ds[v], cl[v])
                out.append((name, d))
            return out, "anomaly"

    return [(name, ds) for name, ds, _ in loaded], "absolute"


def panel_limits(arrs, anomaly, robust=98):
    vals = np.concatenate([a.values.ravel() for a in arrs])
    vals = vals[np.isfinite(vals)]
    if anomaly:
        m = np.nanpercentile(np.abs(vals), robust)
        return -m, m
    return np.nanpercentile(vals, 100 - robust), np.nanpercentile(vals, robust)


def add_map(ax, proj, extent):
    for feat, lw in ((cfeature.COASTLINE, 0.6), (cfeature.BORDERS, 0.4)):
        try:
            list(feat.geometries()); ax.add_feature(feat, linewidth=lw)
        except Exception:
            pass
    ax.set_extent(extent, crs=proj)


def make_figure(var, models, kind, init_str, out):
    label, abs_cmap, anom_cmap, unit = STYLE[var]
    anomaly = (kind == "anomaly")
    cmap = anom_cmap if anomaly else abs_cmap
    cols = [(n, ds[var]) for n, ds in models if var in ds]
    if len(cols) < 1:
        print(f"  {var}: not present, skipped"); return
    weeks = overlap_weeks(*[da for _, da in cols])
    if not weeks:
        print(f"  {var}: no overlapping weeks, skipped"); return
    vmin, vmax = panel_limits([da.sel(week=weeks) for _, da in cols], anomaly)

    proj = ccrs.PlateCarree()
    extent = [INDIA_BBOX["west"], INDIA_BBOX["east"], INDIA_BBOX["south"], INDIA_BBOX["north"]]
    nrow, ncol = len(weeks), len(cols)
    fig, axes = plt.subplots(nrow, ncol, figsize=(3.7 * ncol, 3.0 * nrow),
                             constrained_layout=True, squeeze=False,
                             subplot_kw={"projection": proj})
    im = None
    for r, w in enumerate(weeks):
        for c, (name, da) in enumerate(cols):
            ax = axes[r][c]
            f = da.sel(week=w); lon, lat = _lonlat(f)
            im = ax.pcolormesh(f[lon], f[lat], f.values, cmap=cmap, vmin=vmin, vmax=vmax,
                               shading="auto", transform=proj)
            add_map(ax, proj, extent)
            if r == 0:
                ax.set_title(name, fontsize=12, fontweight="bold")
            if c == 0:
                ax.text(-0.1, 0.5, f"Week {w}", transform=ax.transAxes, rotation=90,
                        va="center", ha="center", fontsize=11)
    cbar = fig.colorbar(im, ax=axes.ravel().tolist(), shrink=0.6, pad=0.02)
    cbar.set_label(f"{unit}{' anomaly' if anomaly else ''}")
    kstr = "anomaly" if anomaly else "weekly mean"
    fig.suptitle(f"{label} {kstr} - init {init_str} (weeks {weeks[0]}-{weeks[-1]})",
                 fontsize=13, fontweight="bold")
    fig.savefig(out, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved -> {out}")


def main():
    ap = argparse.ArgumentParser(description="Side-by-side N-model weekly maps over India.")
    ap.add_argument("--model", action="append", default=[], metavar="NAME=PATH",
                    help="Repeatable. Weekly NetCDF for a model.")
    ap.add_argument("--clim", action="append", default=[], metavar="NAME=PATH",
                    help="Repeatable. Per-model climatology NetCDF.")
    ap.add_argument("--common-clim", default=None, help="One reference clim for ALL models (e.g. ERA5).")
    ap.add_argument("--auto", action="store_true", help="Use newest file in data/{gefs,cfsv2,ec46}.")
    ap.add_argument("--absolute", action="store_true", help="Raw weekly means instead of anomalies.")
    args = ap.parse_args()

    climmap = dict(s.split("=", 1) for s in args.clim)
    specs = []
    if args.auto:
        for name, d in AUTO_DIRS:
            fc = _newest(d)
            if fc:
                specs.append((name, fc, climmap.get(name) or _find_model_clim(d)))
    for s in args.model:
        name, path = s.split("=", 1)
        specs.append((name, path, climmap.get(name)))
    if not specs:
        sys.exit("No models. Use --auto or --model NAME=PATH (repeatable).")

    models, kind = load_models(specs, args.common_clim, args.absolute)
    if kind == "absolute" and not args.absolute:
        print("  note: not all models have a climatology -> plotting ABSOLUTE. "
              "Provide --common-clim (e.g. ERA5 weekly) for a clean anomaly comparison.")
    init_str = str(models[0][1].attrs.get("init_date", "?"))
    print("models:", [n for n, _ in models], "| mode:", kind)
    for var in ("t2m", "precip"):
        make_figure(var, models, kind, init_str,
                    PLOTS_DIR / f"s2s_multi_{var}_{init_str}_{kind}.png")
    print("Done.")


if __name__ == "__main__":
    main()
