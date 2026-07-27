#!/usr/bin/env python3
"""
Download ECMWF SEAS5 (or any C3S centre) seasonal forecast monthly means of
2 m temperature and total precipitation, cropped to India, as NetCDF.

Source : Copernicus Climate Data Store (CDS)
Dataset: seasonal-monthly-single-levels
Docs   : https://cds.climate.copernicus.eu/datasets/seasonal-monthly-single-levels

CDS does the spatial crop server-side (the `area` key), so the downloaded file
is already India-only.

SETUP (one time)
----------------
1. Make a free account at https://cds.climate.copernicus.eu and log in.
2. Copy your URL + personal access token from https://cds.climate.copernicus.eu/how-to-api
   into  ~/.cdsapirc  (Windows: C:\\Users\\<you>\\.cdsapirc):
       url: https://cds.climate.copernicus.eu/api
       key: <your-token>
3. On the dataset page, click "Download" and accept the licence once.
4. pip install "cdsapi>=0.7" xarray netcdf4

USAGE
-----
    python download_seas5.py                      # latest-ish defaults
    python download_seas5.py --year 2026 --month 6 --leadtime 1 2 3 4 5 6
    python download_seas5.py --centre ukmo --system 603   # a different C3S model
"""

import argparse
import cdsapi

from config import CDS_VARIABLES, SEAS5_DIR, cds_area, INDIA_BBOX

DATASET = "seasonal-monthly-single-levels"


def build_request(years, month, leadtimes, centre, system, variables, bbox):
    return {
        "originating_centre": centre,        # 'ecmwf' = SEAS5
        "system": str(system),               # SEAS5 = '51'
        "variable": variables,
        "product_type": ["monthly_mean"],    # also: monthly_maximum/minimum/standard_deviation
        "year": [str(y) for y in years],     # one year (forecast) or many (hindcast climatology)
        "month": [f"{int(month):02d}"],      # forecast initialization month
        "leadtime_month": [str(l) for l in leadtimes],
        "data_format": "netcdf",
        "area": cds_area(bbox),              # [N, W, S, E] -> server-side crop
    }


def main():
    p = argparse.ArgumentParser(description="Download SEAS5/C3S seasonal forecast for India.")
    p.add_argument("--year", type=int, required=False, default=None,
                   help="Forecast init year (default: current year).")
    p.add_argument("--month", type=int, required=False, default=None,
                   help="Forecast init month 1-12 (default: current month).")
    p.add_argument("--leadtime", type=int, nargs="+", default=[1, 2, 3, 4, 5, 6],
                   help="Lead months ahead of init (SEAS5 supports 1-7; default 1-6).")
    p.add_argument("--centre", default="ecmwf",
                   help="C3S originating centre: ecmwf, ukmo, meteo_france, dwd, cmcc, ncep, jma, eccc.")
    p.add_argument("--system", default="51",
                   help="System version for the centre (SEAS5 = 51).")
    p.add_argument("--variables", nargs="+", default=CDS_VARIABLES)
    p.add_argument("--hindcast", action="store_true",
                   help="Download the reforecast CLIMATOLOGY for --month over --ref-years "
                        "(used by plot_seas5.py to compute anomalies).")
    p.add_argument("--ref-years", type=int, nargs=2, metavar=("START", "END"), default=[1993, 2016],
                   help="Reference period for the hindcast climatology (default 1993 2016).")
    args = p.parse_args()

    if args.month is None:
        from datetime import date
        args.month = date.today().month

    if args.hindcast:
        start, end = args.ref_years
        years = list(range(start, end + 1))
        out = SEAS5_DIR / f"{args.centre}{args.system}_clim_{start}-{end}_init{int(args.month):02d}_india.nc"
        print(f"Requesting HINDCAST climatology {DATASET} ({args.centre} sys {args.system}) "
              f"init month {int(args.month):02d}, years {start}-{end}, leads {args.leadtime} ...")
    else:
        from datetime import date
        args.year = args.year or date.today().year
        years = [args.year]
        out = SEAS5_DIR / f"{args.centre}{args.system}_{args.year}{int(args.month):02d}_india.nc"
        print(f"Requesting {DATASET} ({args.centre} sys {args.system}) "
              f"init {args.year}-{int(args.month):02d}, leads {args.leadtime} ...")

    req = build_request(years, args.month, args.leadtime,
                        args.centre, args.system, args.variables, INDIA_BBOX)
    print("  (first request for a cycle can sit in the CDS queue for a few minutes)")

    cdsapi.Client().retrieve(DATASET, req, str(out))
    print(f"Done -> {out}")

    # quick sanity print
    try:
        import xarray as xr
        ds = xr.open_dataset(out)
        print("\nVariables:", list(ds.data_vars))
        print("Dims:", dict(ds.sizes))
        ds.close()
    except Exception as e:
        print(f"(open check skipped: {e})")


if __name__ == "__main__":
    main()
