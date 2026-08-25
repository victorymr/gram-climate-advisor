#!/usr/bin/env python3
"""
Collapse the kept GEFSv12 reforecast India grids to district weekly series.

Input : data/gefs_reforecast/refc_<init>_{days01-10,days10-35}_india.nc
        (download_reforecast.py; 11 members, t2m K instants + apcp mm buckets)
Output: backtest/collapsed_refc/<init>.nc  --  (district, member, week) x
        {refc_t2m [degC weekly mean], refc_precip [mm/day weekly mean]}, RAW values
        (anomalising vs a leave-one-year-out reforecast climatology happens at scoring
        time in score_reforecast.py, where all years are in view).
Also  : backtest/reforecast_inits.csv -- init list tagged with ENSO phase (JJAS ONI),
        consumed by build_truth.py --inits and the scoring stratification.

Method: each chunk's grid is collapsed to districts per step (one xr.dot against the
cached district weight tensor, per native grid -- week 1 keeps the 0.25 deg detail),
then the two chunks' step series are combined in time: t2m as a step-duration-weighted
weekly mean (3-hourly days 1-10, 6-hourly days 10-35), precip as the sum of bucket
accumulations in the week / 7. Every week's step durations are asserted to sum to
168 h, so a step gap can never silently thin a weekly mean (the operational-GEFS
truncation lesson).

    python backtest/collapse_reforecast.py --write-inits   # just (re)write the CSV
    python backtest/collapse_reforecast.py --limit 1       # smoke one init
    python backtest/collapse_reforecast.py                 # all inits (idempotent)
"""

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

HERE = Path(__file__).resolve().parent
FC = HERE.parent
sys.path.insert(0, str(FC)); sys.path.insert(0, str(HERE))
os.environ.setdefault("GRAM_GEO", "lgd")

from forecast_region import gadm_districts                     # noqa: E402
from build_truth import weight_tensor                          # noqa: E402
from download_reforecast import init_list, out_paths, CHUNKS   # noqa: E402

SRC = FC / "data" / "gefs_reforecast"
OUT = HERE / "collapsed_refc"
OUT.mkdir(exist_ok=True)
INITS_CSV = HERE / "reforecast_inits.csv"
DISTRICTS_CSV = FC.parent / "data" / "district_coordinates.csv"
WEEKS = 5
STEP_H = {"Days:1-10": 3, "Days:10-35": 6}     # step duration per chunk (hours)

# JJAS-mean ONI per monsoon year (vendored from CPC via enso-india/data/monsoon_oni.csv);
# phase threshold +-0.5 degC, matching the operational backtest's inits.csv tagging.
JJAS_ONI = {
    2000: -0.56, 2001: -0.13, 2002: 0.83, 2003: 0.10, 2004: 0.52, 2005: -0.05,
    2006: 0.23, 2007: -0.73, 2008: -0.36, 2009: 0.51, 2010: -1.16, 2011: -0.54,
    2012: 0.30, 2013: -0.30, 2014: 0.18, 2015: 1.74, 2016: -0.35, 2017: 0.04,
    2018: 0.25, 2019: 0.32,
}


def enso_phase(year):
    v = JJAS_ONI[year]
    return "el_nino" if v >= 0.5 else ("la_nina" if v <= -0.5 else "neutral")


def write_inits_csv():
    rows = []
    for init in init_list():
        y, m = int(init[:4]), int(init[4:6])
        rows.append(dict(init_date=f"{init[:4]}-{init[4:6]}-{init[6:]}", year=y, month=m,
                         phase="pre_monsoon" if m == 5 else "monsoon",
                         enso=enso_phase(y), monsoon_season_note=""))
    pd.DataFrame(rows).to_csv(INITS_CSV, index=False)
    print(f"wrote {INITS_CSV.name}: {len(rows)} inits "
          f"({pd.DataFrame(rows)['enso'].value_counts().to_dict()})")


def collapse_init(init, tensors, districts):
    parts = []
    for chunk, path in out_paths(init).items():
        ds = xr.open_dataset(SRC / path.name)
        W, latn, lonn = tensors[chunk]
        coll = xr.Dataset({
            "t2m": xr.dot(W, ds["t2m"].astype("float64"), dims=[latn, lonn]) - 273.15,
            "apcp": xr.dot(W, ds["apcp"].astype("float64"), dims=[latn, lonn]),
        }).assign_coords(lead_hours=("step", ds["lead_hours"].values))
        coll["dt"] = ("step", np.full(ds.sizes["step"], STEP_H[chunk], dtype="float64"))
        parts.append(coll)
        ds.close()
    s = xr.concat(parts, dim="step").sortby("lead_hours")
    lead = s["lead_hours"].values
    t_weeks, p_weeks = [], []
    for wk in range(1, WEEKS + 1):
        m = (lead > 168 * (wk - 1)) & (lead <= 168 * wk)
        dt = s["dt"].values[m]
        if dt.sum() != 168.0:
            raise RuntimeError(f"{init} week {wk}: step durations sum to {dt.sum()} h, not 168")
        sub = s.isel(step=m)
        t_weeks.append((sub["t2m"] * sub["dt"]).sum("step") / 168.0)
        p_weeks.append(sub["apcp"].sum("step") / 7.0)
    week_ix = pd.Index(range(1, WEEKS + 1), name="week")
    out = xr.Dataset({
        "refc_t2m": xr.concat(t_weeks, dim=week_ix),
        "refc_precip": xr.concat(p_weeks, dim=week_ix),
    }).transpose("district", "member", "week")
    out = out.assign_coords(state=("district", districts["state"].to_numpy()),
                            district_name=("district", districts["district"].to_numpy()))
    out.attrs.update(init=init, doy=int(pd.Timestamp(init).dayofyear),
                     source="GEFSv12 reforecast (collapse_reforecast.py)", units="degC, mm/day")
    if not (np.isfinite(out["refc_precip"]).all() and np.isfinite(out["refc_t2m"]).all()):
        raise RuntimeError(f"{init}: non-finite collapsed values")
    # Corruption guard only -- genuine monsoon extremes (Western Ghats / Meghalaya cells)
    # reach several hundred mm/day for a district weekly mean, so the bar sits at 1000.
    if float(out["refc_precip"].max()) > 1000 or abs(float(out["refc_t2m"].mean())) > 60:
        raise RuntimeError(f"{init}: implausible collapsed magnitudes")
    out.to_netcdf(OUT / f"{init}.nc", engine="netcdf4",
                  encoding={v: {"zlib": True, "complevel": 4} for v in out.data_vars})


def main():
    ap = argparse.ArgumentParser(description="Collapse reforecast grids to district weekly series.")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--write-inits", action="store_true", help="Only (re)write reforecast_inits.csv.")
    args = ap.parse_args()

    write_inits_csv()
    if args.write_inits:
        return
    inits = [i for i in init_list()
             if all((SRC / p.name).exists() for p in out_paths(i).values())]
    pending = [i for i in inits if not (OUT / f"{i}.nc").exists()]
    print(f"{len(inits)} downloaded inits, {len(pending)} to collapse")
    if args.limit:
        pending = pending[:args.limit]
    if not pending:
        return
    districts = pd.read_csv(DISTRICTS_CSV)
    gadm = gadm_districts()
    tensors = {}
    for chunk in CHUNKS:
        probe = xr.open_dataset(SRC / out_paths(pending[0])[chunk].name)["t2m"].isel(member=0, step=0)
        print(f"building weight tensor for {chunk} grid {probe.sizes} ...", flush=True)
        tensors[chunk] = weight_tensor(probe, districts, gadm)
    import time
    t0 = time.time()
    failed = []
    for k, init in enumerate(pending, 1):
        try:
            collapse_init(init, tensors, districts)
        except Exception as e:
            failed.append(init)
            print(f"  {init}: FAILED - {type(e).__name__}: {str(e)[:150]} (continuing)", flush=True)
        if k % 20 == 0 or k == len(pending):
            print(f"  [{k}/{len(pending)}] {init}  ({time.time()-t0:.0f}s)", flush=True)
    print(f"done -> {OUT}" + (f"; {len(failed)} FAILED: {failed}" if failed else ""))


if __name__ == "__main__":
    main()
