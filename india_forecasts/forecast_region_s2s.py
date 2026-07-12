#!/usr/bin/env python3
"""
Area-averaged SUBSEASONAL (weekly) forecast for Indian districts -- multi-model mean.

The subseasonal analogue of forecast_region.py. forecast_region.py collapses the
*seasonal* (monthly) SEAS5/SFS grids to a region; this collapses the *weekly* S2S
grids (GEFS / CFSv2 / EC46) the same way and averages the available models into one
consensus per district.

For each district it:
  1. takes each model's weekly ANOMALY grid (forecast minus the common ERA5 weekly
     climatology, built by build_era5_clim.py),
  2. collapses it to a single regional value per lead week -- cosine-latitude weighted
     over the grid cells whose centre lies in the district polygon (GADM level-2),
     with a nearest-cell fallback for districts smaller than a grid cell,
  3. averages across whichever models cover that week (multi-model mean).

Output: plots/s2s_region_weekly.csv with per-district, per-week
  precip_anom_mm_day, t2m_anom_degC, n_models
consumed by gram-climate-advisor/scripts/import_model_forecasts.py.

Prerequisites (see build_era5_clim.py):
  python build_era5_clim.py --date YYYY-MM-DD      # common ERA5 weekly climatology

Usage:
    python forecast_region_s2s.py                                  # auto: newest init, all models present
    python forecast_region_s2s.py --init 20260629
    python forecast_region_s2s.py --districts /path/to/district_coordinates.csv
    python forecast_region_s2s.py --model GEFS=data/gefs/gefs_20260629_india_weekly.nc \
                                  --model CFSv2=data/cfsv2/cfsv2_20260629_india_weekly.nc \
                                  --clim data/clim/era5_weekly_init0629_india_weekly.nc
"""

import os
import re
import sys
import csv
import glob
import argparse

import numpy as np
import pandas as pd
import xarray as xr

from config import DATA_DIR, ROOT
# Reuse the substantive geo logic from the seasonal producer.
from forecast_region import gadm_districts, region_weights, _norm, _slug

PLOTS_DIR = ROOT / "plots"
PLOTS_DIR.mkdir(exist_ok=True)

# model name -> data subdir
MODEL_DIRS = {"GEFS": "gefs", "CFSv2": "cfsv2", "EC46": "ec46"}
# advisor's district list ships next to the app; this pipeline is vendored at
# gram-climate-advisor/india_forecasts, so the advisor root is ROOT.parent.
DEFAULT_DISTRICTS = ROOT.parent / "data" / "district_coordinates.csv"


# --------------------------------------------------------------------------
# small NetCDF helpers (local copies so this CSV producer needs no cartopy /
# plotting import chain -- same behaviour as plot_s2s_multi.py)
# --------------------------------------------------------------------------
def _lonlat(da):
    lon = next((c for c in ("longitude", "lon", "x") if c in da.coords), None)
    lat = next((c for c in ("latitude", "lat", "y") if c in da.coords), None)
    if lon is None or lat is None:
        raise KeyError(f"lon/lat not in {list(da.coords)}")
    return lon, lat


def _newest(subdir, exclude="clim"):
    fs = [f for f in sorted(glob.glob(str(DATA_DIR / subdir / "*weekly*.nc")))
          if exclude not in os.path.basename(f).lower()]
    return fs[-1] if fs else None


def anomalise(da, clim_da):
    """da - clim, with clim aligned on week and regridded to da's grid if needed."""
    lon, lat = _lonlat(da)
    clon, clat = _lonlat(clim_da)
    cl = clim_da.rename({clat: lat, clon: lon}) if (clat, clon) != (lat, lon) else clim_da
    cl = cl.sel(week=da["week"])
    if not (np.array_equal(cl[lat].values, da[lat].values)
            and np.array_equal(cl[lon].values, da[lon].values)):
        cl = cl.interp({lat: da[lat], lon: da[lon]})
    return da - cl


# --------------------------------------------------------------------------
# model + climatology discovery
# --------------------------------------------------------------------------
def _init_of(path):
    with xr.open_dataset(path) as ds:
        return str(ds.attrs.get("init_date", "")) or None


def _file_for_init(sub, init):
    """Weekly file in data/<sub>/ whose filename init matches, else None."""
    for f in sorted(glob.glob(str(DATA_DIR / sub / "*_india_weekly.nc"))):
        m = re.search(r"_(\d{8})_india_weekly", os.path.basename(f))
        if m and m.group(1) == init:
            return f
    return None


def discover_models(explicit, init):
    """Return (specs, init) where specs = [(name, path)] all sharing one init date.
    explicit: list of 'NAME=PATH'. init: 'YYYYMMDD' or None (auto = most recent)."""
    if explicit:
        specs = [tuple(s.split("=", 1)) for s in explicit]
        inits = {_init_of(p) for _, p in specs}
        if len(inits) > 1:
            print(f"  warning: mixed init dates across --model files: {inits}")
        return specs, (init or next(iter(inits)))

    # target init: given, or the most recent across all model dirs' newest files
    newest = {name: _newest(sub) for name, sub in MODEL_DIRS.items()}
    newest = {n: p for n, p in newest.items() if p}
    if not newest:
        sys.exit("No weekly model files found in data/{gefs,cfsv2,ec46}/. "
                 "Run the download_*.py scripts first.")
    target = init or max(_init_of(p) for p in newest.values() if _init_of(p))

    # for that init, pick EACH dir's matching file (a dir may hold a newer init too)
    specs = [(name, _file_for_init(sub, target))
             for name, sub in MODEL_DIRS.items() if _file_for_init(sub, target)]
    if not specs:
        sys.exit(f"No weekly files for init {target} in data/{{gefs,cfsv2,ec46}}/.")
    missing = [n for n, sub in MODEL_DIRS.items() if n in newest and not _file_for_init(sub, target)]
    if missing:
        print(f"  init {target}: using {[n for n, _ in specs]}; no {target} file for {missing}")
    return specs, target


def find_clim(init, explicit):
    if explicit:
        return explicit
    mmdd = pd.Timestamp(init).strftime("%m%d")
    cand = DATA_DIR / "clim" / f"era5_weekly_init{mmdd}_india_weekly.nc"
    if not cand.exists():
        sys.exit(f"Common ERA5 weekly climatology not found: {cand}\n"
                 f"  Build it once for this init:\n"
                 f"    python build_era5_clim.py --date {pd.Timestamp(init).strftime('%Y-%m-%d')}")
    return str(cand)


# --------------------------------------------------------------------------
# region geometry (no sys.exit: unmatched districts fall back to a point)
# --------------------------------------------------------------------------
def resolve_geom(gadm, state, district, lat, lon):
    """(geom, matched_gadm_bool). Point fallback when no GADM polygon matches;
    region_weights() then uses its nearest-cell fallback for the point."""
    from shapely.geometry import Point
    sel = gadm[gadm["NAME_2"].map(_norm) == _norm(district)]
    if state and not sel.empty:
        s2 = sel[sel["NAME_1"].map(_norm) == _norm(state)]
        sel = s2 if not s2.empty else sel
    if sel.empty:
        return Point(float(lon), float(lat)), False
    geom = sel.geometry.union_all() if hasattr(sel.geometry, "union_all") else sel.geometry.unary_union
    return geom, True


# --------------------------------------------------------------------------
# core
# --------------------------------------------------------------------------
VARS = {"t2m": "t2m_anom_degC", "precip": "precip_anom_mm_day"}


def load_anomaly_grids(specs, clim_path):
    """Return {model_name: {var: weekly anomaly DataArray}} on each model's grid."""
    clim = xr.open_dataset(clim_path)
    grids = {}
    for name, path in specs:
        ds = xr.open_dataset(path)
        gv = {}
        for var in VARS:
            if var in ds and var in clim:
                gv[var] = anomalise(ds[var], clim[var])
        if gv:
            grids[name] = gv
        else:
            print(f"  warning: {name} has none of {list(VARS)}; skipped")
    if not grids:
        sys.exit("No models could be anomalised (check variable names / climatology).")
    return grids


def regional_series(anom, geom):
    """Weighted regional mean per week -> dict{week:int -> value:float}, plus (n_cells, fallback)."""
    lon, lat = _lonlat(anom)
    weights, ncell, fb = region_weights(anom[lat].values, anom[lon].values, lat, lon, geom)
    series = anom.weighted(weights.fillna(0.0)).mean((lat, lon))
    out = {int(w): float(series.sel(week=w).values) for w in series["week"].values}
    return out, ncell, fb


def valid_week_label(init, week):
    start = pd.Timestamp(init) + pd.Timedelta(days=(week - 1) * 7 + 1)
    end = start + pd.Timedelta(days=6)
    return f"{start.strftime('%b %d')} - {end.strftime('%b %d')}"


# --------------------------------------------------------------------------
# probabilistic weekly odds (from ensemble members) -- thresholds in anomaly
# space, tied to rules.py so the odds and the scenario logic stay consistent.
# --------------------------------------------------------------------------
WET_MM, DRY_MM = 1.0, -1.0     # "wetter / drier than normal" lean
HEAVY_MM = 7.0                 # heavy-rain week (matches the excess-rain rule)
DRYSPELL_MM = -3.0             # dry week / dry spell (matches the below-normal signal)
HOT_C = 1.5                    # hot week (matches the app's temp threshold)

PROB_FIELDS = ["region", "state", "district", "week", "p_wetter", "p_near", "p_drier",
               "p_heavy", "p_dryspell", "p_hot", "n_members", "models", "init_date"]


def find_member_files(init, explicit=None):
    """Every model member-resolved weekly NetCDF for this init (GEFS, EC46, ...) — pooled
    into one multi-model ensemble for the odds. Returns [(model_name, path), ...]."""
    if explicit:
        return [("members", explicit)]
    out = []
    for name, sub in MODEL_DIRS.items():
        for f in sorted(glob.glob(str(DATA_DIR / sub / f"*_{init}_india_weekly_members.nc"))):
            out.append((name, f))
    return out


def compute_probs(member_files, clim_path, districts, gadm, init):
    """Per district/week threshold-exceedance probabilities from the POOLED multi-model
    ensemble. Each model's members are anomalised vs the ERA5 weekly clim and region-
    collapsed; members are pooled across whichever models are available for this init, and
    the fraction crossing each threshold is the forecast probability."""
    clim = xr.open_dataset(clim_path)
    models = []
    for mname, path in member_files:
        ds = xr.open_dataset(path)
        anom = {v: anomalise(ds[v], clim[v]) for v in VARS if v in ds and v in clim}
        if anom:
            models.append((mname, anom))
    rows = []
    for _, d in districts.iterrows():
        state, name = d["state"], d["district"]
        geom, _ = resolve_geom(gadm, state, name, d["latitude"], d["longitude"])
        pooled = {"precip": {}, "t2m": {}}   # var -> {week: [member values...]}
        contrib = set()
        for mname, anom in models:
            for v, a in anom.items():
                lon, lat = _lonlat(a)
                w, _, _ = region_weights(a[lat].values, a[lon].values, lat, lon, geom)
                coll = a.weighted(w.fillna(0.0)).mean((lat, lon))    # (member, week)
                for wk in coll["week"].values:
                    vals = np.asarray(coll.sel(week=int(wk)).values).ravel()
                    pooled[v].setdefault(int(wk), []).extend(vals[np.isfinite(vals)].tolist())
                contrib.add(mname)
        for w in sorted(pooled["precip"].keys()):
            pa = np.array(pooled["precip"].get(w, []))
            ta = np.array(pooled["t2m"].get(w, []))

            def frac(arr, mask):
                return round(float(mask.mean()), 3) if arr.size else ""

            p_wetter = frac(pa, pa >= WET_MM)
            p_drier = frac(pa, pa <= DRY_MM)
            p_near = round(1.0 - p_wetter - p_drier, 3) if pa.size else ""
            rows.append({
                "region": f"{name}, {state}", "state": state, "district": name, "week": w,
                "p_wetter": p_wetter, "p_near": p_near, "p_drier": p_drier,
                "p_heavy": frac(pa, pa >= HEAVY_MM),
                "p_dryspell": frac(pa, pa <= DRYSPELL_MM),
                "p_hot": frac(ta, ta >= HOT_C),
                "n_members": int(pa.size), "models": ",".join(sorted(contrib)), "init_date": init,
            })
    return rows


def main():
    ap = argparse.ArgumentParser(description="Multi-model subseasonal weekly forecast for advisor districts.")
    ap.add_argument("--districts", default=str(DEFAULT_DISTRICTS),
                    help="CSV with columns state,district,latitude,longitude (advisor's district_coordinates.csv).")
    ap.add_argument("--model", action="append", default=[], metavar="NAME=PATH",
                    help="Repeatable. Weekly NetCDF for a model; overrides auto-discovery.")
    ap.add_argument("--clim", default=None, help="Common ERA5 weekly climatology NetCDF (else auto by init MMDD).")
    ap.add_argument("--init", default=None, help="Init date YYYYMMDD to select (auto = most recent).")
    ap.add_argument("--out", default=str(PLOTS_DIR / "s2s_region_weekly.csv"), help="Output CSV path.")
    ap.add_argument("--probs", action="store_true",
                    help="Also compute weekly threshold-exceedance probabilities from GEFS members.")
    ap.add_argument("--members-file", default=None, help="GEFS member-resolved weekly NetCDF (else auto by init).")
    ap.add_argument("--probs-out", default=str(PLOTS_DIR / "s2s_region_probs.csv"), help="Probabilities CSV path.")
    args = ap.parse_args()

    specs, init = discover_models(args.model, args.init)
    clim_path = find_clim(init, args.clim)
    print(f"init {init}  models {[n for n, _ in specs]}  clim {clim_path}")

    grids = load_anomaly_grids(specs, clim_path)
    gadm = gadm_districts()
    districts = pd.read_csv(args.districts)

    rows = []
    for _, d in districts.iterrows():
        state, name = d["state"], d["district"]
        geom, matched = resolve_geom(gadm, state, name, d["latitude"], d["longitude"])
        label = f"{name}, {state}"

        # per model -> per var -> {week: value}
        per_model = {}
        fb_any = False
        for model, gv in grids.items():
            per_var = {}
            for var in VARS:
                if var in gv:
                    ser, ncell, fb = regional_series(gv[var], geom)
                    per_var[var] = ser
                    fb_any = fb_any or fb
            per_model[model] = per_var

        weeks = sorted({w for pv in per_model.values() for ser in pv.values() for w in ser})

        def _v(pv, var, w):
            x = pv.get(var, {}).get(w)
            return round(float(x), 3) if (x is not None and np.isfinite(x)) else ""

        def _emit(model, w, precip, t2m, nmods):
            rows.append({
                "region": label, "state": state, "district": name,
                "week": w, "valid_week": valid_week_label(init, w), "model": model,
                "precip_anom_mm_day": precip, "t2m_anom_degC": t2m,
                "n_models": nmods, "init_date": init,
                "geom": "gadm" if matched else "point",
            })

        for w in weeks:
            # one row per individual model that reaches this week ...
            for model in sorted(per_model):
                pv = per_model[model]
                if any(w in pv.get(var, {}) for var in VARS):
                    _emit(model, w, _v(pv, "precip", w), _v(pv, "t2m", w), 1)
            # ... plus the multi-model mean (mean over models covering the week)
            agg, hits = {}, set()
            for var in VARS:
                vals = [pv[var][w] for pv in per_model.values()
                        if var in pv and w in pv[var] and np.isfinite(pv[var][w])]
                agg[var] = round(float(np.mean(vals)), 3) if vals else ""
                hits |= {m for m, pv in per_model.items()
                         if var in pv and w in pv[var] and np.isfinite(pv[var][w])}
            _emit("MME", w, agg["precip"], agg["t2m"], len(hits))
        note = "" if matched else "  [point/nearest-cell: no GADM polygon]"
        wk_txt = ",".join(str(w) for w in weeks)
        print(f"  {label:<32} weeks {wk_txt}{note}")

    fields = ["region", "state", "district", "week", "valid_week", "model",
              "precip_anom_mm_day", "t2m_anom_degC", "n_models", "init_date", "geom"]
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=fields)
        wr.writeheader()
        wr.writerows(rows)
    print(f"\nsaved -> {args.out}  ({len(rows)} rows, {len(districts)} districts)")

    # probabilistic odds from the pooled multi-model ensemble (auto when member files exist)
    mfiles = find_member_files(init, args.members_file)
    if args.probs or mfiles:
        if not mfiles:
            print("  [probs] no member files for this init; skip "
                  "(run: download_gefs.py --members all, and/or download_ec46_openmeteo.py)")
        else:
            prob_rows = compute_probs(mfiles, clim_path, districts, gadm, init)
            with open(args.probs_out, "w", newline="", encoding="utf-8") as fh:
                wr = csv.DictWriter(fh, fieldnames=PROB_FIELDS)
                wr.writeheader()
                wr.writerows(prob_rows)
            print(f"saved -> {args.probs_out}  ({len(prob_rows)} rows) "
                  f"from {[m for m, _ in mfiles]}")


if __name__ == "__main__":
    main()
