#!/usr/bin/env python3
"""
Download NOAA SFS Beta (Seasonal Forecast System v1.0 prototype) monthly
forecasts, crop to India, save NetCDF.

Source : NOAA Open Data Dissemination (NODD) on AWS S3 -- no account needed.
Bucket : s3://noaa-oar-sfsdev-pds   (anonymous / UNSIGNED access)
  experiments/beta1/forecast/<YYYYMM>/<group>.zarr/  -> NRT (31-member, 12-month lead)
  experiments/beta1/reforecast/                      -> on-the-fly reforecasts
  experiments/phase_1/                               -> earlier hindcasts (1994-2023)
Announcement: https://epic.noaa.gov/seasonal-forecast-system-sfs-beta-near-real-time-capability-launched/

FILE FORMAT: ZARR (not GRIB2/NetCDF)
------------------------------------
The beta1 NRT forecasts are published as consolidated Zarr v2 stores
(`atm_monthly.zarr`, `ocn_monthly.zarr`, `atm_daily.zarr`, ...), one per
monthly init cycle. Each store holds dims (member, lead, lat, lon) on a global
0.5 deg grid, with vars like tmp2m [K] and pratesfc [kg m-2 s-1].

We read the remote store directly over S3 (anon) and crop to India lazily, so
only the India-region chunks are pulled -- no full global download. The older
file-based path (GRIB2/NetCDF -> download -> crop) is kept for any prefix that
still serves discrete files (e.g. phase_1 hindcasts).

WHY THIS SCRIPT DISCOVERS BEFORE IT READS
-----------------------------------------
SFS Beta is brand-new and its layout still evolves, so this script DISCOVERS
the live tree at runtime instead of hardcoding a fragile path. Run `--explore`
first to see the real structure.

SETUP
-----
    pip install boto3 s3fs zarr xarray netcdf4
    # cfgrib/eccodes only needed for the legacy GRIB2 file path (phase_1).

USAGE
-----
    python download_sfs.py                                 # latest cycle, atm_monthly.zarr -> India NetCDF
    python download_sfs.py --cycle 202606 --store atm_monthly --vars tmp2m,pratesfc
    python download_sfs.py --explore --prefix experiments/beta1/forecast/
    python download_sfs.py --prefix experiments/beta1/forecast/202606/atm_monthly.zarr
    python download_sfs.py --prefix experiments/phase_1/.../ --pattern atm   # legacy file path
"""

import argparse
import os
import sys

import boto3
from botocore import UNSIGNED
from botocore.config import Config

from config import SFS_DIR, SFS_GRIB_SHORTNAMES, INDIA_BBOX

BUCKET = "noaa-oar-sfsdev-pds"


def client():
    return boto3.client("s3", config=Config(signature_version=UNSIGNED))


def list_level(s3, prefix):
    """One level of the tree: (subdirs, [(key, size_bytes), ...])."""
    paginator = s3.get_paginator("list_objects_v2")
    subdirs, files = [], []
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix, Delimiter="/"):
        subdirs += [cp["Prefix"] for cp in page.get("CommonPrefixes", [])]
        files += [(o["Key"], o["Size"]) for o in page.get("Contents", [])
                  if o["Key"] != prefix]
    return subdirs, files


def explore(prefix, depth=1):
    s3 = client()
    def _walk(pfx, d, indent=""):
        subdirs, files = list_level(s3, pfx)
        for sd in subdirs:
            print(f"{indent}{sd.rstrip('/').split('/')[-1]}/")
            if d > 1:
                _walk(sd, d - 1, indent + "  ")
        for k, sz in files[:25]:
            print(f"{indent}{k.split('/')[-1]}   ({sz/1e6:.1f} MB)")
        if len(files) > 25:
            print(f"{indent}... (+{len(files)-25} more files)")
    print(f"s3://{BUCKET}/{prefix}")
    _walk(prefix, depth)


def find_files(prefix, pattern=None, exts=(".grib2", ".grb2", ".nc", ".nc4")):
    """Recursively collect data files under prefix, optionally filtered by a
    substring `pattern` (e.g. 'atm', 'sfc', a date, an ensemble id)."""
    s3 = client()
    paginator = s3.get_paginator("list_objects_v2")
    hits = []
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for o in page.get("Contents", []):
            k = o["Key"]
            if k.endswith("/"):
                continue
            if exts and not k.lower().endswith(exts):
                continue
            if pattern and pattern.lower() not in k.lower():
                continue
            hits.append((k, o["Size"]))
    return hits


def latest_cycle(prefix):
    """Newest YYYYMM init-cycle directory directly under `prefix` (or None)."""
    s3 = client()
    subdirs, _ = list_level(s3, prefix)
    cycles = sorted(d.rstrip("/").split("/")[-1] for d in subdirs)
    cycles = [c for c in cycles if c.isdigit() and len(c) == 6]
    return cycles[-1] if cycles else None


def list_zarr_stores(prefix):
    """`.zarr` stores (CommonPrefixes ending in .zarr/) directly under prefix."""
    s3 = client()
    subdirs, _ = list_level(s3, prefix)
    return [d for d in subdirs if d.rstrip("/").endswith(".zarr")]


def resolve_zarr_store(prefix, store="atm_monthly", cycle=None):
    """Resolve `prefix` (+optional cycle/store) to a single .zarr store key.

    Accepts a direct `*.zarr` prefix, a cycle dir containing stores, or a
    parent (e.g. .../forecast/) under which we descend into a YYYYMM cycle.
    Returns the store key (str) or None if no zarr store is found.
    """
    prefix = prefix if prefix.endswith("/") else prefix + "/"
    if prefix.rstrip("/").endswith(".zarr"):
        return prefix

    stores = list_zarr_stores(prefix)
    if not stores:  # maybe `prefix` holds YYYYMM cycle dirs; descend into one
        cyc = cycle or latest_cycle(prefix)
        if cyc:
            stores = list_zarr_stores(prefix + cyc + "/")
    if not stores:
        return None

    for s in stores:  # match requested store group by name substring
        if store in s.rstrip("/").split("/")[-1]:
            return s
    print(f"  '{store}' not found; using {stores[0].rstrip('/').split('/')[-1]}. "
          f"Available: {[s.rstrip('/').split('/')[-1] for s in stores]}")
    return stores[0]


def subset_zarr_to_india(store_key, varnames=None):
    """Open a remote Zarr store (anon S3), keep `varnames`, crop to India, save NetCDF."""
    import s3fs
    import xarray as xr
    from utils import subset_to_india, save_netcdf

    fs = s3fs.S3FileSystem(anon=True)
    mapper = s3fs.S3Map(f"{BUCKET}/{store_key.rstrip('/')}", s3=fs)
    ds = xr.open_zarr(mapper, consolidated=True)

    if varnames:
        keep = [v for v in varnames if v in ds.data_vars]
        missing = [v for v in varnames if v not in ds.data_vars]
        if missing:
            print(f"  warning: not in store, skipped: {missing}")
        if not keep:
            sys.exit(f"None of {varnames} in store. Available: {sorted(ds.data_vars)}")
        ds = ds[keep]

    sub = subset_to_india(ds, INDIA_BBOX).load()  # pull only the India-region chunks
    parts = store_key.rstrip("/").split("/")
    cyc = next((p for p in parts if p.isdigit() and len(p) == 6), "cycle")
    group = parts[-1].replace(".zarr", "")
    sub.attrs["init_cycle"] = cyc  # YYYYMM init month (lead=0); used by plot script
    out = SFS_DIR / f"sfs_beta1_{cyc}_{group}_india.nc"
    save_netcdf(sub, out)
    ds.close()
    return out


def save_zarr_global(store_key, varnames=None, init_month=None):
    """Open a remote Zarr store (anon S3), keep `varnames`, and save the GLOBAL
    field as NetCDF -- no spatial crop, no averaging. Streams to disk chunk by
    chunk (dask-backed) so memory stays bounded even for multi-GB downloads.
    Crop/average locally later from this file.
    """
    import s3fs
    import xarray as xr
    from utils import save_netcdf

    fs = s3fs.S3FileSystem(anon=True)
    mapper = s3fs.S3Map(f"{BUCKET}/{store_key.rstrip('/')}", s3=fs)
    ds = xr.open_zarr(mapper, consolidated=True)  # lazy / dask-backed

    if varnames:
        keep = [v for v in varnames if v in ds.data_vars]
        missing = [v for v in varnames if v not in ds.data_vars]
        if missing:
            print(f"  warning: not in store, skipped: {missing}")
        if not keep:
            sys.exit(f"None of {varnames} in store. Available: {sorted(ds.data_vars)}")
        ds = ds[keep]

    parts = store_key.rstrip("/").split("/")
    group = parts[-1].replace(".zarr", "")
    mm = init_month or next((p for p in parts if p.isdigit() and len(p) == 2), "xx")
    ds.attrs["reforecast_init_month"] = mm
    ds.attrs["source"] = f"s3://{BUCKET}/{store_key.rstrip('/')}"

    out = SFS_DIR / f"sfs_beta1_reforecast_init{mm}_{group}_global.nc"
    nbytes = sum(ds[v].nbytes for v in ds.data_vars)
    print(f"  dims {dict(ds.sizes)}; vars {list(ds.data_vars)}")
    print(f"  streaming ~{nbytes/1e9:.1f} GB (uncompressed) GLOBAL field to NetCDF; "
          f"this can take several minutes...")
    save_netcdf(ds, out)
    ds.close()
    return out


def download(key, dest_dir=SFS_DIR):
    s3 = client()
    dest = dest_dir / os.path.basename(key)
    print(f"Downloading {key} ...")
    s3.download_file(BUCKET, key, str(dest))
    print(f"  -> {dest}  ({dest.stat().st_size/1e6:.1f} MB)")
    return dest


def subset_file_to_india(path):
    """Open a downloaded global file (GRIB2 or NetCDF), crop to India, save NetCDF."""
    import xarray as xr
    from utils import subset_to_india, save_netcdf

    name = str(path).lower()
    if name.endswith((".grib2", ".grb2")):
        # Keep it simple/robust: let cfgrib split by variable, crop each, merge.
        try:
            dss = xr.open_dataset(
                path, engine="cfgrib",
                backend_kwargs={"filter_by_keys": {"typeOfLevel": "heightAboveGround"}},
            )
        except Exception:
            dss = xr.open_dataset(path, engine="cfgrib")
    else:
        dss = xr.open_dataset(path)

    sub = subset_to_india(dss, INDIA_BBOX)
    out = SFS_DIR / (os.path.splitext(os.path.basename(path))[0] + "_india.nc")
    save_netcdf(sub, out)
    dss.close()
    return out


def main():
    p = argparse.ArgumentParser(description="Download NOAA SFS Beta forecast for India.")
    p.add_argument("--prefix", default="experiments/beta1/forecast/",
                   help="S3 prefix to browse/pull (default experiments/beta1/forecast/).")
    p.add_argument("--explore", action="store_true",
                   help="Print the bucket tree under --prefix and exit.")
    p.add_argument("--depth", type=int, default=1, help="Tree depth for --explore.")
    p.add_argument("--cycle", default=None,
                   help="Init cycle YYYYMM for the zarr path (default: newest under --prefix).")
    p.add_argument("--store", default="atm_monthly",
                   help="Zarr store group to read (atm_monthly, ocn_monthly, atm_daily, ...).")
    p.add_argument("--vars", default="tmp2m,pratesfc",
                   help="Comma-separated vars to keep from the zarr store ('all' for everything).")
    p.add_argument("--reforecast", action="store_true",
                   help="Download a reforecast/hindcast store (by init month), kept GLOBAL for later subsetting.")
    p.add_argument("--init-month", type=int, default=6,
                   help="Reforecast init month for --reforecast (available: 3,4,5,6,11). Default 6 (June).")
    p.add_argument("--no-zarr", action="store_true",
                   help="Skip the zarr path; force legacy file discovery/download.")
    p.add_argument("--pattern", default=None,
                   help="Substring filter on keys, e.g. 'atm', 'sfc', a date, member id.")
    p.add_argument("--max-files", type=int, default=4,
                   help="Safety cap on number of files to download in one run.")
    p.add_argument("--download-only", action="store_true",
                   help="Download but skip the India crop (e.g. inspect with wgrib2 first).")
    p.add_argument("--list-vars", default=None, metavar="FILE",
                   help="Print GRIB shortNames/variables in an already-downloaded FILE and exit.")
    args = p.parse_args()

    if args.list_vars:
        import xarray as xr
        try:
            ds = xr.open_dataset(args.list_vars, engine="cfgrib")
        except Exception:
            ds = xr.open_dataset(args.list_vars)
        print("Variables:", list(ds.data_vars))
        for v in ds.data_vars:
            print(f"  {v}: {ds[v].attrs.get('long_name','')} [{ds[v].attrs.get('units','')}]")
        return

    if args.explore:
        explore(args.prefix, depth=args.depth)
        print("\nTip: re-run with --prefix <one of the dirs above> to drill in,")
        print("then drop --explore and add --pattern atm (or sfc) to fetch monthly files.")
        return

    # --- reforecast (hindcast) path: global download, no crop/average ---
    if args.reforecast:
        mm = f"{args.init_month:02d}"
        store_key = f"experiments/beta1/reforecast/{mm}/{args.store}.zarr/"
        varnames = None if args.vars.lower() == "all" else \
            [v.strip() for v in args.vars.split(",") if v.strip()]
        print(f"Reading reforecast store  s3://{BUCKET}/{store_key.rstrip('/')}/"
              + (f"  vars={varnames}" if varnames else "  (all vars)"))
        save_zarr_global(store_key, varnames, init_month=mm)
        return

    # --- zarr path (default for beta1 NRT forecasts) ---
    if not args.no_zarr:
        store_key = resolve_zarr_store(args.prefix, store=args.store, cycle=args.cycle)
        if store_key:
            varnames = None if args.vars.lower() == "all" else \
                [v.strip() for v in args.vars.split(",") if v.strip()]
            print(f"Reading zarr store  s3://{BUCKET}/{store_key.rstrip('/')}/"
                  + (f"  vars={varnames}" if varnames else "  (all vars)"))
            subset_zarr_to_india(store_key, varnames)
            return
        print("No .zarr store under prefix; falling back to file discovery.")

    # --- legacy file path (download discrete GRIB2/NetCDF, then crop) ---
    hits = find_files(args.prefix, pattern=args.pattern)
    if not hits:
        print(f"No data files found under '{args.prefix}'"
              + (f" matching '{args.pattern}'" if args.pattern else "")
              + ". Run with --explore to inspect the layout.")
        sys.exit(1)

    print(f"Found {len(hits)} matching file(s); downloading up to {args.max_files}:")
    for k, sz in hits[:args.max_files]:
        print(f"  {k}  ({sz/1e6:.1f} MB)")
    if len(hits) > args.max_files:
        print(f"  ... ({len(hits)-args.max_files} more; raise --max-files to get them)")

    for k, _ in hits[:args.max_files]:
        f = download(k)
        if not args.download_only:
            try:
                subset_file_to_india(f)
            except Exception as e:
                print(f"  crop failed ({e}); file kept at {f}. "
                      f"Inspect vars with:  python download_sfs.py --list-vars {f}")


if __name__ == "__main__":
    main()
