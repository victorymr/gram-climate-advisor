#!/usr/bin/env python3
"""
Download the GEFSv12 REFORECAST (2000-2019) over India and KEEP the cropped grids.

Extends the district backtest beyond the operational GEFSv12 archive (which starts
2020-09) with the same model's 20-year reforecast: every OTHER Wednesday, May-Sep,
2000-2019 (~220 inits) -- Wednesdays because only they run 11 members (c00+p01-p10)
to 35 days; other days stop at 16 days with 5 members.

Unlike the operational backtest (collapse -> delete raw), the cropped India grids are
KEPT (~120 MB/init, ~25 GB total) so future work -- other thresholds, sub-weekly
metrics, gridded verification -- needs no re-download. District collapse and scoring
run later, locally, from these files.

Source: s3://noaa-gefs-retrospective (AWS Open Data, anonymous, free egress).
Layout: GEFSv12/reforecast/YYYY/YYYYMMDD00/<member>/<chunk>/<var>_YYYYMMDD00_<member>.grib2
  chunk "Days:1-10" : 0.25 deg, 3-hourly buckets/instants, leads 3..240 h  (80 steps)
  chunk "Days:10-35": 0.50 deg, 6-hourly,                leads 246..840 h (100 steps)
Variables fetched: tmp_2m (instant, K), apcp_sfc (per-bucket accumulation, mm).

Output per init (data/gefs_reforecast/):
  refc_<init>_days01-10_india.nc   (member, step, lat, lon) x {t2m, apcp}, 0.25 deg
  refc_<init>_days10-35_india.nc   same at 0.5 deg
APCP is stored as the RAW bucket accumulations (sum a window then /days for mm/day).

Robustness (lessons from the operational-GEFS truncation bug): every download is
size-checked against S3's Content-Length, every assembled dataset is validated for
the full step count x 11 members x 2 vars BEFORE saving, files are written to a tmp
name and renamed, and an init is skipped as done only if BOTH outputs re-validate.
So a partial init can never be cached. Idempotent and resumable: just rerun.

    python backtest/download_reforecast.py --limit 1      # smoke: first pending init
    python backtest/download_reforecast.py                # full run (~220 inits)
    python backtest/download_reforecast.py --workers 4    # decode processes (default 3)
"""

import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import xarray as xr

HERE = Path(__file__).resolve().parent
FC = HERE.parent
OUT = FC / "data" / "gefs_reforecast"
TMP = OUT / "_tmp"
BUCKET = "https://noaa-gefs-retrospective.s3.amazonaws.com"
MEMBERS = ["c00"] + [f"p{i:02d}" for i in range(1, 11)]
VARS = {"tmp_2m": "t2m", "apcp_sfc": "apcp"}
# chunk -> (file tag, expected steps, first/last lead hour)
CHUNKS = {"Days:1-10": ("days01-10", 80, 3, 240), "Days:10-35": ("days10-35", 100, 246, 840)}
BBOX = dict(latitude=slice(38, 6), longitude=slice(66, 98))     # India (config.INDIA_BBOX)
YEARS = (2000, 2019)
MONTHS = (5, 9)                       # May-Sep
DL_RETRIES = 3


def init_list():
    """Every other Wednesday, May-Sep, 2000-2019 (alternation restarts each season)."""
    wed = pd.date_range(f"{YEARS[0]}-01-01", f"{YEARS[1]}-12-31", freq="W-WED")
    wed = wed[(wed.month >= MONTHS[0]) & (wed.month <= MONTHS[1])]
    out = []
    for _, season in pd.Series(wed, index=wed).groupby(wed.year):
        out.extend(season.iloc[::2])
    return [d.strftime("%Y%m%d") for d in out]


def _download(url, dest):
    """GET with retries; verifies the byte count against S3's Content-Length."""
    for attempt in range(1, DL_RETRIES + 1):
        try:
            r = requests.get(url, timeout=600)
            r.raise_for_status()
            want = int(r.headers.get("Content-Length", -1))
            if want > 0 and len(r.content) != want:
                raise IOError(f"short read {len(r.content)}/{want}")
            dest.write_bytes(r.content)
            return len(r.content)
        except Exception as e:
            if attempt == DL_RETRIES:
                raise RuntimeError(f"download failed {url}: {type(e).__name__} {e}") from e
            time.sleep(3 * attempt)


def _open_grib(path):
    """Open a reforecast GRIB2, tolerating the archive's mixed-dataType wart: in some
    perturbed-member APCP files the first bucket (f003) is mistagged 'cf' while the rest
    are 'pf', which makes a plain cfgrib open fail with 'multiple values for unique key'.
    Fall back to opening each dataType separately and stitching the steps back together."""
    kw = dict(engine="cfgrib", backend_kwargs={"indexpath": ""})
    try:
        return xr.open_dataset(path, **kw)
    except Exception:
        parts = []
        for dt in ("cf", "pf"):
            try:
                p = xr.open_dataset(path, engine="cfgrib",
                                    backend_kwargs={"indexpath": "",
                                                    "filter_by_keys": {"dataType": dt}})
            except Exception:
                continue
            da = p[list(p.data_vars)[0]].drop_vars("number", errors="ignore")
            if "step" not in da.dims:                      # singleton step gets squeezed
                da = da.expand_dims("step")
            parts.append(da)
        if not parts:
            raise
        da = xr.concat(parts, dim="step").sortby("step")
        _, keep = np.unique(da["step"].values, return_index=True)
        return da.isel(step=np.sort(keep)).to_dataset()


def fetch_member(task):
    """Worker: one (init, member, chunk) -> cropped {var: DataArray} dict (as a dataset).

    Returns (member, chunk, path-to-tmp-netcdf) -- the cropped result is written to a
    small intermediate file rather than pickled back, keeping IPC light.
    """
    init, member, chunk = task
    tag = CHUNKS[chunk][0]
    tmpdir = TMP / f"{init}_{member}_{tag}"
    tmpdir.mkdir(parents=True, exist_ok=True)
    das, nbytes = {}, 0
    try:
        for fvar, name in VARS.items():
            url = f"{BUCKET}/GEFSv12/reforecast/{init[:4]}/{init}00/{member}/{chunk}/{fvar}_{init}00_{member}.grib2"
            gp = tmpdir / f"{fvar}.grib2"
            nbytes += _download(url, gp)
            ds = _open_grib(gp)
            da = ds[list(ds.data_vars)[0]].sel(**BBOX)
            lead = (da["step"] / np.timedelta64(1, "h")).astype("int32")
            da = da.assign_coords(lead_hours=("step", np.asarray(lead))).load()
            das[name] = da.astype("float32")
            ds.close()
        out = xr.Dataset(das)
        keep = {"lead_hours", "latitude", "longitude", "step"}
        out = out.drop_vars([c for c in out.coords if c not in keep and c not in out.dims])
        res = tmpdir / "cropped.nc"
        out.to_netcdf(res)
        return member, chunk, str(res), nbytes
    finally:
        for fvar in VARS:
            (tmpdir / f"{fvar}.grib2").unlink(missing_ok=True)


def _validate(path, chunk):
    """Full coverage or nothing: every member, both vars, every step, sane lead range."""
    tag, nsteps, lead0, lead1 = CHUNKS[chunk]
    try:
        with xr.open_dataset(path) as ds:
            ok = (ds.sizes.get("member") == len(MEMBERS)
                  and ds.sizes.get("step") == nsteps
                  and all(v in ds for v in VARS.values())
                  and int(ds["lead_hours"].min()) == lead0
                  and int(ds["lead_hours"].max()) == lead1
                  and all(np.isfinite(ds[v].values).all() for v in VARS.values()))
        return bool(ok)
    except Exception:
        return False


def out_paths(init):
    return {c: OUT / f"refc_{init}_{CHUNKS[c][0]}_india.nc" for c in CHUNKS}


def init_done(init):
    return all(p.exists() and _validate(p, c) for c, p in out_paths(init).items())


def run_init(init, workers):
    t0 = time.time()
    tasks = [(init, m, c) for m in MEMBERS for c in CHUNKS]
    results = {c: {} for c in CHUNKS}
    total_bytes = 0
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for member, chunk, res, nbytes in ex.map(fetch_member, tasks):
            results[chunk][member] = res
            total_bytes += nbytes
    for chunk, paths in results.items():
        das = [xr.load_dataset(paths[m]).expand_dims(member=[m]) for m in MEMBERS]
        ds = xr.concat(das, dim="member")
        ds.attrs.update(model="GEFSv12 reforecast", init=init,
                        source="s3://noaa-gefs-retrospective", chunk=chunk,
                        apcp_units="mm per bucket (accumulation)", t2m_units="K")
        final = out_paths(init)[chunk]
        tmpf = final.with_suffix(".nc.part")
        enc = {v: {"zlib": True, "complevel": 4} for v in VARS.values()}
        ds.to_netcdf(tmpf, engine="netcdf4", encoding=enc)   # explicit: auto-pick falls back to scipy (no zlib)
        if not _validate(tmpf, chunk):
            tmpf.unlink(missing_ok=True)
            raise RuntimeError(f"{init} {chunk}: assembled file failed validation")
        os.replace(tmpf, final)
        for p in paths.values():
            Path(p).unlink(missing_ok=True)
            Path(p).parent.rmdir()
    kept = sum(p.stat().st_size for p in out_paths(init).values())
    print(f"  {init}: ok  dl {total_bytes/1e9:.2f} GB -> kept {kept/1e6:.0f} MB "
          f"in {time.time()-t0:.0f}s", flush=True)


def main():
    ap = argparse.ArgumentParser(description="GEFSv12 reforecast India download (grids kept).")
    ap.add_argument("--limit", type=int, default=0, help="Stop after N pending inits (0 = all).")
    ap.add_argument("--workers", type=int, default=3, help="Decode processes (default 3).")
    ap.add_argument("--list", action="store_true", help="Print the init list and exit.")
    args = ap.parse_args()

    inits = init_list()
    if args.list:
        print("\n".join(inits))
        print(f"{len(inits)} inits")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    pending = [i for i in inits if not init_done(i)]
    print(f"{len(inits)} inits total, {len(pending)} pending "
          f"({len(inits)-len(pending)} already complete)", flush=True)
    if args.limit:
        pending = pending[:args.limit]
    t0, done, failed = time.time(), 0, []
    for k, init in enumerate(pending, 1):
        print(f"[{k}/{len(pending)}] {init}", flush=True)
        try:
            run_init(init, args.workers)
            done += 1
        except Exception as e:
            failed.append(init)
            print(f"  {init}: FAILED - {type(e).__name__}: {str(e)[:200]} (continuing)", flush=True)
    dt = time.time() - t0
    print(f"\n{done} init(s) completed in {dt/3600:.2f} h"
          + (f"; {len(failed)} FAILED: {failed} -- rerun to retry" if failed else ""))


if __name__ == "__main__":
    main()
