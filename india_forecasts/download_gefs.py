#!/usr/bin/env python3
"""
Download NOAA GEFS 35-day (extended) ensemble-mean forecasts from AWS, crop to
India, aggregate to weekly means, save NetCDF. No account needed (anonymous S3).

Source : s3://noaa-gefs-pds  (Registry of Open Data on AWS), 0.5 deg, 00 UTC cycle
         runs to +840 h (35 days). We pull the ensemble-mean files (geavg,
         ...pgrb2a.0p50...) and only the TMP:2 m and APCP:surface fields, via
         GRIB .idx byte-range requests on one keep-alive session (small, fast).
Overlap with EC46 is weeks 1-5 (GEFS stops at day 35).

SETUP
-----
    pip install requests xarray eccodes netcdf4

USAGE
-----
    python download_gefs.py --date 2026-05-24                 # ens-mean -> weekly India NetCDF
    python download_gefs.py --date 2026-05-24 --step-hours 6  # finer sampling (default 6h)
    python download_gefs.py --date 2026-05-24 --inspect       # print one GRIB .idx inventory, stop

PRECIP NOTE: GEFS APCP is delivered in accumulation buckets. We sum buckets per
week -> mm/day (default). If your build serves run-accumulated APCP instead, pass
--precip-accum cumulative (boundary differences). Check with --inspect.

CLIMATOLOGY / ANOMALY: the operational forecast can't supply its own climatology.
For weekly anomalies, GEFS needs the GEFSv12 REFORECAST (2000-2019), which only
runs to 35 days once weekly (Wednesdays, 5/11 members) -- see --reforecast notes
at the bottom. Without a GEFS climatology the compare plot falls back to absolute.
"""

import re
import sys
import argparse
import threading
import numpy as np
import pandas as pd
import xarray as xr

from config import DATA_DIR, INDIA_BBOX
from utils import subset_to_india, save_netcdf
from s2s_utils import to_weekly

GEFS_DIR = DATA_DIR / "gefs"
GEFS_DIR.mkdir(parents=True, exist_ok=True)

MAX_LEAD_H = 840          # 35 days


def fxx_list(step_hours):
    return list(range(step_hours, MAX_LEAD_H + 1, step_hours))


FXX_RETRIES = 3          # extra rounds for leads that failed (5xx / reset / not yet published)
FETCH_THREADS = 16       # concurrent leads per member over one pooled HTTPS session
N_WEEKS = MAX_LEAD_H // 168

S3_BASE = "https://noaa-gefs-pds.s3.amazonaws.com"
_FIELD_RE = re.compile(r":(TMP:2 m above ground|APCP:surface):")
# eccodes is not thread-safe: concurrent decodes from --workers threads crash the whole
# process natively ("fatal flex scanner internal error", exit 2), so decode one at a time.
_ECCODES_LOCK = threading.Lock()


def _missing_leads(da, fxx):
    got = set(int(x) for x in np.asarray(da["lead_hours"].values).ravel())
    return [f for f in fxx if f not in got]


def _session(threads=FETCH_THREADS):
    """One keep-alive HTTPS session for all requests. This is the whole speed-up over
    Herbie, which opens a fresh connection (TLS handshake) for every .idx and byte-range
    GET: ~100 s/member via Herbie vs ~5 s here for the same ~45 MB."""
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    s = requests.Session()
    retry = Retry(total=5, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(pool_connections=threads, pool_maxsize=threads, max_retries=retry))
    return s


def _lead_url(date, member, f):
    return (f"{S3_BASE}/gefs.{pd.Timestamp(date):%Y%m%d}/00/atmos/pgrb2ap5/"
            f"ge{member}.t00z.pgrb2a.0p50.f{f:03d}")


def _fetch_lead(sess, date, member, f):
    """GRIB bytes of the TMP:2m + APCP messages for one lead (byte-range subset via the
    .idx), or None if the lead is not on S3 (yet). Network errors propagate."""
    url = _lead_url(date, member, f)
    r = sess.get(url + ".idx", timeout=30)
    if r.status_code in (403, 404):
        return None
    r.raise_for_status()
    lines = r.text.strip().splitlines()
    starts = [int(ln.split(":")[1]) for ln in lines]
    out = b""
    for i, ln in enumerate(lines):
        if _FIELD_RE.search(ln):
            end = starts[i + 1] - 1 if i + 1 < len(lines) else ""
            g = sess.get(url, headers={"Range": f"bytes={starts[i]}-{end}"}, timeout=60)
            g.raise_for_status()
            out += g.content
    return out


def _decode(blobs):
    """{lead: grib bytes} -> (t, p) DataArrays (step, latitude, longitude), cropped to
    India per message with eccodes (no cfgrib index files / global-grid concat).
    Serialised on _ECCODES_LOCK; the network fetch before it still overlaps across members."""
    with _ECCODES_LOCK:
        return _decode_locked(blobs)


def _decode_locked(blobs):
    import eccodes
    t_rows, p_rows, grid = {}, {}, None
    for f, blob in blobs.items():
        mv = memoryview(blob)
        pos = 0
        while (k := blob.find(b"GRIB", pos)) >= 0:
            n = int.from_bytes(blob[k + 8:k + 16], "big")       # GRIB2 total message length
            gid = eccodes.codes_new_from_message(bytes(mv[k:k + n]))
            try:
                if grid is None:
                    ny, nx = eccodes.codes_get(gid, "Nj"), eccodes.codes_get(gid, "Ni")
                    # per-point coords are in value order whatever the scan mode
                    lat = eccodes.codes_get_array(gid, "latitudes").reshape(ny, nx)[:, 0]
                    lon = eccodes.codes_get_array(gid, "longitudes").reshape(ny, nx)[0, :]
                    tmpl = xr.DataArray(np.zeros((lat.size, lon.size), "f4"),
                                        coords={"latitude": lat, "longitude": lon},
                                        dims=("latitude", "longitude"))
                    crop = subset_to_india(tmpl, INDIA_BBOX)
                    iy = np.flatnonzero(np.isin(lat, crop["latitude"].values))
                    ix = np.flatnonzero(np.isin(lon, crop["longitude"].values))
                    grid = (lat.size, lon.size, iy, ix,
                            {"latitude": lat[iy], "longitude": lon[ix]})   # file order (N->S)
                ny, nx, iy, ix, _ = grid
                vals = eccodes.codes_get_values(gid).reshape(ny, nx)[np.ix_(iy, ix)].astype("f4")
                name = eccodes.codes_get(gid, "shortName")
            finally:
                eccodes.codes_release(gid)
            (t_rows if name in ("2t", "t2m") else p_rows)[f] = vals
            pos = k + n

    def build(rows):
        leads = sorted(rows)
        coords = dict(grid[4]) if grid else {}
        coords["lead_hours"] = ("step", np.array(leads, dtype=int))
        return xr.DataArray(np.stack([rows[f] for f in leads]) if leads else
                            np.zeros((0, 0, 0), "f4"),
                            dims=("step", "latitude", "longitude"), coords=coords)
    return build(t_rows), build(p_rows)


def fetch(date, member, step_hours, inspect=False, allow_partial=False):
    """Return (t_da, p_da) each dims (step, lat, lon) with coord lead_hours, cropped to
    India, from s3://noaa-gefs-pds via .idx byte-range requests on one pooled session.

    Lead coverage is VERIFIED: any lead that fails (throttling / reset / not yet on S3)
    is retried, and a forecast still short of MAX_LEAD_H is refused unless allow_partial,
    so a truncated "35-day" file (seen 2026-08-17 under Herbie: 15/31 members stopped at
    504 h) can never be written or cached by accident.
    """
    import time
    from concurrent.futures import ThreadPoolExecutor

    fxx = fxx_list(step_hours)
    sess = _session()
    if inspect:
        print(sess.get(_lead_url(date, member, fxx[0]) + ".idx", timeout=30).text[:4000])
        return None, None

    def one(f):
        try:
            return f, _fetch_lead(sess, date, member, f)
        except Exception:
            return f, None

    blobs, missing = {}, fxx
    for attempt in range(FXX_RETRIES + 1):
        if attempt:
            print(f"  {member}: {len(missing)}/{len(fxx)} lead(s) unresolved (from f{missing[0]:03d}); "
                  f"retrying, try {attempt}/{FXX_RETRIES}", flush=True)
            time.sleep(2 * attempt)
        with ThreadPoolExecutor(min(FETCH_THREADS, len(missing))) as ex:
            for f, blob in ex.map(one, missing):
                if blob:
                    blobs[f] = blob
        missing = [f for f in fxx if f not in blobs]
        if not missing:
            break
    if missing and not allow_partial:
        raise RuntimeError(
            f"GEFS {member} {date}: {len(missing)}/{len(fxx)} leads unavailable after "
            f"{FXX_RETRIES} retries (from f{missing[0]:03d}); refusing to build a partial "
            f"forecast (--allow-partial overrides)")

    t, p = _decode(blobs)
    # belt and braces: a lead's .idx may lack one of the two fields
    for name, da in (("TMP", t), ("APCP", p)):
        miss = _missing_leads(da, fxx)
        if miss and not allow_partial:
            raise RuntimeError(f"GEFS {member} {date}: {name} missing {len(miss)} lead(s) "
                               f"after download (from f{miss[0]:03d}); refusing partial forecast")
    return t, p


def _complete(path):
    """True if a saved weekly file covers every week to MAX_LEAD_H (else it is partial)."""
    try:
        with xr.open_dataset(path) as ds:
            return int(ds.sizes.get("week", 0)) >= N_WEEKS
    except Exception:
        return False


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
    ap.add_argument("--workers", type=int, default=4,
                    help="Concurrent members to fetch with --members (default 4; each also runs "
                         f"{FETCH_THREADS} lead requests). Measured for all 31 members: 1 worker "
                         "~190 s, 4 workers ~90 s, all 35-day complete.")
    ap.add_argument("--inspect", action="store_true", help="Print one GEFS inventory and stop.")
    ap.add_argument("--allow-partial", action="store_true",
                    help="Save a forecast even if some leads could not be fetched (default: "
                         "refuse, so a truncated 'N-week' file is never written or cached).")
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
        from concurrent.futures import ThreadPoolExecutor, as_completed
        members = expand_members(args.members)
        tag = d.strftime("%Y%m%d")

        def _get_member(m):
            """Fetch+save one member (cached members skip; one retry). Thread-safe:
            each member is a distinct GRIB and writes its own per-member file."""
            mf = GEFS_DIR / f"gefs_{tag}_member_{m}.nc"
            if mf.exists():
                if _complete(mf) or args.allow_partial:
                    return f"member {m}: cached"
                # a truncated member from an earlier run: re-fetch rather than keep it
                print(f"  member {m}: cached file is partial (< {N_WEEKS} weeks) -> re-fetching",
                      flush=True)
                mf.unlink()
            for attempt in (1, 2):
                try:
                    t, p = fetch(args.date, m, args.step_hours, allow_partial=args.allow_partial)
                    t2m, precip = to_weekly_fields(t, p, args.precip_accum)
                    save_netcdf(xr.Dataset({"t2m": t2m, "precip": precip},
                                           attrs={"model": "GEFS", "init_date": tag, "member": m}), mf)
                    return f"member {m}: saved (try {attempt})"
                except Exception as e:
                    if attempt == 2:
                        return f"member {m}: {type(e).__name__} - skipped ({str(e)[:120]})"
            return f"member {m}: skipped"

        # Members are fetched concurrently (the download is S3-latency bound, so this
        # is the dominant speed-up); fetch() still parallelises leads within a member.
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            futs = [ex.submit(_get_member, m) for m in members]
            for fut in as_completed(futs):
                print(f"  {fut.result()}", flush=True)

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
    t, p = fetch(args.date, args.member, args.step_hours, inspect=args.inspect,
                 allow_partial=args.allow_partial)
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
