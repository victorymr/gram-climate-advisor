#!/usr/bin/env python3
"""
Download NOAA GEFS 35-day (extended) ensemble-mean forecasts from AWS, crop to
India, aggregate to weekly means, save NetCDF. No account needed (anonymous S3).

Source : s3://noaa-gefs-pds  (Registry of Open Data on AWS), 0.5 deg, 00 UTC cycle
         runs to +840 h (35 days). We pull the ensemble-mean files (geavg,
         ...pgrb2a.0p50...) and only the TMP:2 m and APCP:surface fields, via
         Herbie's GRIB index byte-range subsetting (small downloads).
Overlap with EC46 is weeks 1-5 (GEFS stops at day 35).

SETUP
-----
    pip install herbie-data xarray cfgrib eccodes netcdf4
    # Herbie handles the AWS GEFS paths + .idx byte-range subsetting.

USAGE
-----
    python download_gefs.py --date 2026-05-24                 # ens-mean -> weekly India NetCDF
    python download_gefs.py --date 2026-05-24 --step-hours 6  # finer sampling (default 6h)
    python download_gefs.py --date 2026-05-24 --inspect       # list one Herbie inventory, stop

PRECIP NOTE: GEFS APCP is delivered in accumulation buckets. We sum buckets per
week -> mm/day (default). If your build serves run-accumulated APCP instead, pass
--precip-accum cumulative (boundary differences). Check with --inspect.

CLIMATOLOGY / ANOMALY: the operational forecast can't supply its own climatology.
For weekly anomalies, GEFS needs the GEFSv12 REFORECAST (2000-2019), which only
runs to 35 days once weekly (Wednesdays, 5/11 members) -- see --reforecast notes
at the bottom. Without a GEFS climatology the compare plot falls back to absolute.
"""

import sys
import argparse
import numpy as np
import pandas as pd
import xarray as xr

from config import DATA_DIR, INDIA_BBOX
from utils import subset_to_india, save_netcdf
from s2s_utils import to_weekly

GEFS_DIR = DATA_DIR / "gefs"
GEFS_DIR.mkdir(parents=True, exist_ok=True)

MAX_LEAD_H = 840          # 35 days
SEARCH_T = ":TMP:2 m above ground:"
SEARCH_P = ":APCP:surface:"


def fxx_list(step_hours):
    return list(range(step_hours, MAX_LEAD_H + 1, step_hours))


def fetch(date, member, step_hours, inspect=False):
    """Return (t_da, p_da) each dims (step, lat, lon) with coord lead_hours, on the
    global GEFS grid (cropped to India), using Herbie + FastHerbie."""
    from herbie import FastHerbie

    fxx = fxx_list(step_hours)
    FH = FastHerbie([pd.Timestamp(date)], model="gefs", fxx=fxx,
                    member=member, product="atmos.5")
    if inspect:
        H0 = FH.objects[0]
        print(H0.inventory().head(40).to_string())
        return None, None

    dt = FH.xarray(f"{SEARCH_T}|{SEARCH_P}")   # one dataset (or list) with t2m + tp
    dss = dt if isinstance(dt, list) else [dt]

    def grab(short_options):
        parts = []
        for d in dss:
            v = next((s for s in short_options if s in d.data_vars), None)
            if v is None:
                continue
            da = subset_to_india(d[v], INDIA_BBOX)
            # standardise the lead coordinate to hours
            lead = da["step"] if "step" in da.coords else da["lead_time"]
            lead_h = (lead / np.timedelta64(1, "h")).astype(int) if np.issubdtype(
                np.asarray(lead).dtype, np.timedelta64) else np.asarray(lead).astype(int)
            stepdim = [x for x in da.dims if x not in ("latitude", "longitude", "lat", "lon")]
            sdim = stepdim[0] if stepdim else "step"
            parts.append(da.assign_coords(lead_hours=(sdim, np.atleast_1d(lead_h))))
        if not parts:
            return None
        out = xr.concat(parts, dim=parts[0].dims[0]) if len(parts) > 1 else parts[0]
        return out.sortby("lead_hours")

    t = grab(["t2m", "2t"])
    p = grab(["tp", "apcp", "unknown"])
    if t is None or p is None:
        sys.exit(f"Could not extract TMP/APCP. Vars seen: "
                 f"{[list(d.data_vars) for d in dss]}. Use --inspect.")
    return t, p


def to_weekly_fields(t, p, precip_accum):
    t2m = to_weekly(t, method="mean") - 273.15            # K -> degC, weekly mean
    if precip_accum == "bucket":
        precip = to_weekly(p, method="sum_per_day")        # sum buckets -> mm/day
    else:  # cumulative: weekly mean rate from boundary differences
        weeks = [int(w) for w in t2m["week"].values]
        lh = p["lead_hours"]; sdim = lh.dims[0]
        pw = []
        for w in weeks:
            hi, lo = w * 168, (w - 1) * 168
            end = p.sel({sdim: lh == hi}).squeeze(sdim, drop=True)
            start = (p.sel({sdim: lh == lo}).squeeze(sdim, drop=True) if lo > 0
                     else xr.zeros_like(end))
            pw.append(((end - start) / 7.0).assign_coords(week=w))
        precip = xr.concat(pw, dim="week")
    return t2m, precip


def expand_members(spec):
    """'all' -> c00 + p01..p30 (31 members); else a comma list like 'c00,p01,p02'."""
    if spec.lower() == "all":
        return ["c00"] + [f"p{i:02d}" for i in range(1, 31)]
    return [s.strip() for s in spec.split(",") if s.strip()]


def main():
    ap = argparse.ArgumentParser(description="Download GEFS 35-day for India, weekly NetCDF.")
    ap.add_argument("--date", required=True, help="Init date YYYY-MM-DD (00 UTC cycle).")
    ap.add_argument("--member", default="avg", help="Single GEFS member ('avg' ensemble mean; or c00/p01..p30).")
    ap.add_argument("--members", default=None,
                    help="Member-resolved output: 'all' (c00+p01..p30) or a comma list. "
                         "Writes gefs_<date>_india_weekly_members.nc (dims member,week,lat,lon).")
    ap.add_argument("--step-hours", type=int, default=6, help="Lead sampling cadence (default 6h).")
    ap.add_argument("--precip-accum", choices=["bucket", "cumulative"], default="bucket")
    ap.add_argument("--inspect", action="store_true", help="Print one GEFS inventory and stop.")
    args = ap.parse_args()

    d = pd.Timestamp(args.date)

    # --- member-resolved ensemble (for probabilistic products) ---
    # Resumable: each member is saved to its own file as soon as it lands (cached
    # members are skipped, transient failures retried), then all present per-member
    # files are reassembled into the members NetCDF. Robust to network resets / a
    # capped run time -- rerun the same command to continue where it left off.
    if args.members:
        import glob
        import re as _re
        members = expand_members(args.members)
        tag = d.strftime("%Y%m%d")
        for m in members:
            mf = GEFS_DIR / f"gefs_{tag}_member_{m}.nc"
            if mf.exists():
                print(f"  member {m}: cached"); continue
            for attempt in (1, 2):
                try:
                    t, p = fetch(args.date, m, args.step_hours)
                    t2m, precip = to_weekly_fields(t, p, args.precip_accum)
                    save_netcdf(xr.Dataset({"t2m": t2m, "precip": precip},
                                           attrs={"model": "GEFS", "init_date": tag, "member": m}), mf)
                    print(f"  member {m}: saved (try {attempt})")
                    break
                except Exception as e:
                    print(f"  member {m}: {type(e).__name__} (try {attempt}); "
                          f"{'retrying' if attempt == 1 else 'skipping'}")

        parts = sorted(glob.glob(str(GEFS_DIR / f"gefs_{tag}_member_*.nc")))
        if not parts:
            sys.exit("No members downloaded yet (all attempts failed).")
        das = []
        for f in parts:
            mid = _re.search(r"_member_([A-Za-z0-9]+)\.nc$", f).group(1)
            das.append(xr.open_dataset(f).assign_coords(member=mid))
        out = xr.concat(das, dim="member")
        out.attrs.update(model="GEFS", init_date=tag, kind="forecast_members",
                         n_members=len(das), source="NOAA GEFS 35-day (AWS)")
        out_path = GEFS_DIR / f"gefs_{tag}_india_weekly_members.nc"
        save_netcdf(out, out_path)
        print(f"Done -> {out_path}  ({len(das)} members total)")
        return

    # --- single member / ensemble mean (existing behaviour) ---
    t, p = fetch(args.date, args.member, args.step_hours, inspect=args.inspect)
    if args.inspect:
        return
    t2m, precip = to_weekly_fields(t, p, args.precip_accum)
    out = xr.Dataset({"t2m": t2m, "precip": precip},
                     attrs={"model": "GEFS", "init_date": d.strftime("%Y%m%d"),
                            "kind": "forecast", "source": "NOAA GEFS 35-day (AWS)"})
    out_path = GEFS_DIR / f"gefs_{d.strftime('%Y%m%d')}_india_weekly.nc"
    save_netcdf(out, out_path)
    print(f"Done -> {out_path}")


# -----------------------------------------------------------------------------
# REFORECAST CLIMATOLOGY (for anomalies) -- outline, run on your machine.
#
# The GEFSv12 reforecast (s3://noaa-gefs-reforecast, 2000-2019) only reaches 35
# days on its once-weekly (Wednesday) 11-member runs. To build a weekly clim that
# matches a given init:
#   1. Find the reforecast Wednesdays near your init's calendar day, across years.
#   2. For each, pull TMP:2m and APCP via Herbie (model="gefs", the reforecast
#      template) to 840 h, crop to India, weekly-aggregate as above.
#   3. Average over members AND years -> weekly climatology; save as
#      data/gefs/gefs_clim_init<MMDD>_india_weekly.nc  (vars t2m, precip; dims week,lat,lon).
# The compare plot auto-detects that file and switches GEFS to anomalies.
# (Left as a documented step: the Wednesday/init-matching choices are yours to make.)
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    main()
