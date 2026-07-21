#!/usr/bin/env python3
"""
Build an EC46 (ECMWF extended-range, 46-day) MODEL CLIMATOLOGY from the S2S reforecasts
on the ECMWF Data Store (ECDS) -- the piece that lets EC46 be anomalised against its own
history instead of ERA5 (which currently forces a fallback + a hard anomaly clip because
Open-Meteo gives no hindcast).

Route (verified): dataset 's2s-reforecasts', origin='ecmwf', 1.5 deg, 46 days, CC-BY,
reforecasts unrestricted. One request pulls all 20 hindcast years for a given real-time
model-cycle date (Mon/Thu) at once: `year/month/day` = the cycle date, `hyear` = the past
years for the same month/day.

Per sampled cycle date we fetch the control forecast (1 member; a climatology needs the
mean, not the spread) for 2m temperature (daily-averaged) and total precipitation
(accumulated), aggregate to weekly means per hindcast year, and keep the small NetCDF
(dims hyear x week x lat x lon) -- reusable for a future EC46 backtest. The heavy GRIB is
deleted. `--aggregate` then pools the hindcast years by init day-of-year into
data/clim/ec46_model_clim.nc, matching gefs/cfsv2_model_clim.nc so model_clim() picks it
up automatically.

Credentials: reads the ecds.ecmwf.int entry from ~/.cdsapirc (which may also hold a CDS
entry) and passes it explicitly, so a multi-block .cdsapirc still works.

Usage:
    python download_ec46_reforecast.py --limit 1     # one date end-to-end (probe)
    python download_ec46_reforecast.py               # full monsoon sample + aggregate
    python download_ec46_reforecast.py --aggregate-only
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from config import DATA_DIR, INDIA_BBOX
from utils import save_netcdf

EC46_DIR = DATA_DIR / "ec46"
CLIM_DIR = DATA_DIR / "clim"
EC46_DIR.mkdir(parents=True, exist_ok=True)
CLIM_DIR.mkdir(parents=True, exist_ok=True)

WEEKS = 5                                        # forecast weeks kept (1..5 -> 35 days)
AREA = [INDIA_BBOX["north"], INDIA_BBOX["west"], INDIA_BBOX["south"], INDIA_BBOX["east"]]
T2M_STEPS = [f"{24 * i}_{24 * (i + 1)}" for i in range(7 * WEEKS)]     # daily-avg groups
TP_STEPS = [str(168 * w) for w in range(WEEKS + 1)]                    # weekly boundaries (h)


def ecds_credentials(rc=None):
    """(url, key) for the ecds.ecmwf.int entry in a possibly multi-block .cdsapirc."""
    rc = Path(rc or (Path.home() / ".cdsapirc"))
    pairs, cur = [], None
    for line in rc.read_text().splitlines():
        s = line.strip()
        if s.startswith("url:"):
            cur = s.split(":", 1)[1].strip()
        elif s.startswith("key:") and cur:
            pairs.append((cur, s.split(":", 1)[1].strip()))
            cur = None
    for u, k in pairs:
        if "ecds.ecmwf.int" in u:
            return u, k
    raise SystemExit("No ecds.ecmwf.int entry found in ~/.cdsapirc")


def cycle_dates(year, step_days):
    """ECMWF extended-run days (Mon/Thu) in the monsoon window, thinned to ~step_days."""
    days = pd.date_range(f"{year}-04-01", f"{year}-11-01", freq="D")
    monthu = [d for d in days if d.weekday() in (0, 3)]     # Monday=0, Thursday=3
    picked, last = [], None
    for d in monthu:
        if last is None or (d - last).days >= step_days:
            picked.append(d); last = d
    return picked


def _to_weekly_t2m(ds):
    """(hyear, step-day) daily-avg t2m [K] -> (hyear, week) weekly-mean [degC]."""
    da = ds["t2m"] - 273.15
    days = (da["step"] / np.timedelta64(1, "D")).round().astype(int)   # 1..35
    da = da.assign_coords(week=("step", ((days - 1) // 7 + 1).values))
    return da.groupby("week").mean("step")


def _to_weekly_precip(ds):
    """(hyear, boundary) accumulated tp [kg m-2 == mm] -> (hyear, week) weekly mean [mm/day]."""
    tp = ds["tp"].sortby("step")                                       # already mm, accumulated
    diffs = tp.diff("step") / 7.0                                      # mm/day per week
    diffs = diffs.where(diffs >= 0, 0.0)                               # guard tiny numeric negatives
    return diffs.assign_coords(week=("step", np.arange(1, diffs.sizes["step"] + 1))) \
                .swap_dims({"step": "week"}).drop_vars("step", errors="ignore")


def _retrieve(client, rt, variable, ftype, steps, hyears, target):
    client.retrieve("s2s-reforecasts", {
        "origin": "ecmwf",
        "year": f"{rt.year}", "month": f"{rt.month:02d}", "day": f"{rt.day:02d}",
        "time": "00:00",
        "hyear": [str(y) for y in hyears], "hmonth": f"{rt.month:02d}", "hday": f"{rt.day:02d}",
        "variable": variable, "forecast_type": ftype, "level_type": "single_level",
        "leadtime_hour": steps, "area": AREA, "data_format": "grib",
    }, str(target))


def fetch_date(client, rt, hyears):
    """Fetch + weekly-aggregate one cycle date -> Dataset(t2m, precip) dims (hyear, week, lat, lon)."""
    gt, gp = EC46_DIR / f"_ec46_{rt:%Y%m%d}_t2m.grib", EC46_DIR / f"_ec46_{rt:%Y%m%d}_tp.grib"
    _retrieve(client, rt, "2_m_temperature", "control_forecast", T2M_STEPS, hyears, gt)
    _retrieve(client, rt, "total_precipitation", "control_forecast", TP_STEPS, hyears, gp)
    ds_t = xr.open_dataset(gt, engine="cfgrib", backend_kwargs={"indexpath": ""})
    ds_p = xr.open_dataset(gp, engine="cfgrib", backend_kwargs={"indexpath": ""})
    t2m = _to_weekly_t2m(ds_t)
    precip = _to_weekly_precip(ds_p)
    # hindcast year as an integer coord from the 'time' dim
    hy = pd.to_datetime(np.atleast_1d(ds_t["time"].values)).year
    out = xr.Dataset({"t2m": t2m, "precip": precip})
    out = out.rename({"time": "hyear"}).assign_coords(hyear=("hyear", hy))
    ds_t.close(); ds_p.close()
    for g in (gt, gp):
        g.unlink(missing_ok=True)
    return out


def download(dates, hyears, limit=None):
    import cdsapi
    url, key = ecds_credentials()
    print(f"ECDS endpoint: {url}")
    client = cdsapi.Client(url=url, key=key)
    dates = dates[:limit] if limit else dates
    got = 0
    for i, rt in enumerate(dates, 1):
        out = EC46_DIR / f"ec46rf_{rt:%m%d}_india_weekly.nc"
        if out.exists():
            print(f"[{i}/{len(dates)}] {rt:%Y-%m-%d}: cached"); got += 1; continue
        print(f"[{i}/{len(dates)}] {rt:%Y-%m-%d} (doy {rt.dayofyear}) x {len(hyears)} hindcast yrs ...",
              flush=True)
        try:
            ds = fetch_date(client, rt, hyears)
            ds.attrs.update(model="EC46", kind="reforecast_weekly", cycle_date=f"{rt:%Y-%m-%d}",
                            source="ECMWF S2S reforecast (ECDS), control, 1.5deg")
            save_netcdf(ds, out)
            print(f"    -> {out.name}  dims {dict(ds.sizes)}")
            got += 1
        except Exception as e:
            print(f"    FAILED: {type(e).__name__}: {e}", flush=True)
    print(f"\n{got}/{len(dates)} dates available")


def _circ(a, b, period=365.25):
    d = np.abs(a - b)
    return np.minimum(d, period - d)


def aggregate(window=8):
    """Pool hindcast years by init DOY into data/clim/ec46_model_clim.nc (doy, week, lat, lon)."""
    files = sorted(EC46_DIR.glob("ec46rf_*_india_weekly.nc"))
    if not files:
        sys.exit("No EC46 reforecast files; run the download phase first.")
    doys, das = [], []
    for f in files:
        ds = xr.open_dataset(f)
        mmdd = f.name.split("_")[1]
        doy = int(pd.Timestamp(f"2001-{mmdd[:2]}-{mmdd[2:]}").dayofyear)
        doys.append(doy)
        das.append(ds[["t2m", "precip"]].mean("hyear"))     # mean over the 20 hindcast years
        ds.close()
    doys = np.asarray(doys)
    stack = xr.concat(das, dim=pd.Index(np.arange(len(das)), name="node"))
    counts_per_date = [xr.open_dataset(f).sizes["hyear"] for f in files]

    nodes = sorted(set(doys))
    out, keep, nsamp = [], [], []
    for node in nodes:
        sel = np.where(_circ(doys, node) <= window)[0]
        if sel.size == 0:
            continue
        out.append(stack.isel(node=sel).mean("node"))
        keep.append(int(node))
        nsamp.append(int(sum(counts_per_date[i] for i in sel)))
    clim = xr.concat(out, dim=pd.Index(keep, name="doy"))
    clim["n_samples"] = ("doy", np.asarray(nsamp))
    clim.attrs.update(model="EC46", kind="model_climatology",
                      source="ECMWF S2S reforecast (ECDS), control, 1.5deg, 20-yr hindcast",
                      window_days=window, n_dates=len(files))
    path = CLIM_DIR / "ec46_model_clim.nc"
    save_netcdf(clim, path)
    print(f"EC46 clim: {len(files)} dates -> {len(keep)} DOY nodes "
          f"(median {int(np.median(nsamp))} samples/node) -> {path}")


def main():
    ap = argparse.ArgumentParser(description="EC46 model climatology from ECMWF S2S reforecasts.")
    ap.add_argument("--year", type=int, default=2024, help="Real-time cycle year (current IFS).")
    ap.add_argument("--step-days", type=int, default=10, help="Cycle-date thinning (days).")
    ap.add_argument("--hyears", type=int, nargs=2, default=[2004, 2023], metavar=("START", "END"))
    ap.add_argument("--window", type=int, default=8, help="DOY pooling half-width (days).")
    ap.add_argument("--limit", type=int, default=None, help="Only the first N dates (probe).")
    ap.add_argument("--aggregate-only", action="store_true")
    args = ap.parse_args()

    hyears = list(range(args.hyears[0], args.hyears[1] + 1))
    dates = cycle_dates(args.year, args.step_days)
    print(f"EC46 reforecast: {len(dates)} cycle dates ({args.year} monsoon, Mon/Thu ~{args.step_days}d) "
          f"x {len(hyears)} hindcast yrs")
    if not args.aggregate_only:
        download(dates, hyears, limit=args.limit)
    aggregate(args.window)


if __name__ == "__main__":
    main()
