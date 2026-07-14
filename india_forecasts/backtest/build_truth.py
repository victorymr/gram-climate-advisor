#!/usr/bin/env python3
"""
Build the verification truth for the backtest: per district, per init, per forecast
week, the OBSERVED weekly-mean anomaly of rainfall and 2 m temperature, from IMD
gridded data via imdlib. Anomalies are vs a fixed day-of-year normal so they line up
with the model anomalies produced by run_backtest.py.

Truth variables (kept in truth/<init>.nc, dims district x week):
  obs_precip_anom  mm/day   IMD 0.25 deg rainfall, weekly mean minus DOY normal
  obs_t2m_anom     degC     IMD 1 deg (tmax+tmin)/2, weekly mean minus DOY normal

Reuses observed_departures.build_climatology (rain) + the same resolve_geom/region_weights
district collapse. Temperature adds a (tmax+tmin)/2 DOY normal built the same way.

Cost note: the one-time DOY-normal build downloads IMD data over --clim-years (default
1991-2020). The rain normal is shared with observed_departures (often already cached);
the temperature normal is an additional ~30-year IMD pull the first time.

Usage:
    python backtest/build_truth.py                       # all inits x 5 weeks
    python backtest/build_truth.py --clim-years 1991 2020
    python backtest/build_truth.py --weeks 4
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
sys.path.insert(0, str(FC))

# Pin to the GADM 666 geometry + frozen coords snapshot (matches run_backtest.py) so the
# verification truth is built on the same districts as the collapsed forecasts.
os.environ.setdefault("GRAM_GEO", "gadm")

from config import DATA_DIR                                    # noqa: E402
from forecast_region import gadm_districts, region_weights     # noqa: E402
from forecast_region_s2s import resolve_geom, _lonlat          # noqa: E402
from observed_departures import build_climatology, IMD_DIR     # noqa: E402  (rain DOY normal)

TRUTH = HERE / "truth"
TRUTH.mkdir(exist_ok=True)
INITS_CSV = HERE / "inits.csv"
DISTRICTS_CSV = HERE / "districts_gadm666.csv"


def _temp(ds, name):
    """IMD temperature DataArray with physically-implausible fills masked out."""
    da = ds[name]
    return da.where((da > -60) & (da < 65))


def build_temp_clim(years):
    """IMD (tmax+tmin)/2 day-of-year normal (degC) over `years`, cached."""
    import imdlib as imd
    cache = IMD_DIR / f"imd_tmean_doy_clim_{years[0]}_{years[1]}.nc"
    if cache.exists():
        return xr.open_dataset(cache)["clim"]
    IMD_DIR.mkdir(parents=True, exist_ok=True)
    means = []
    for y in range(years[0], years[1] + 1):
        print(f"  IMD historical temp {y} ...")
        tx = _temp(imd.get_data("tmax", y, y, fn_format="yearwise", file_dir=str(IMD_DIR)).get_xarray(), "tmax")
        tn = _temp(imd.get_data("tmin", y, y, fn_format="yearwise", file_dir=str(IMD_DIR)).get_xarray(), "tmin")
        means.append(((tx + tn) / 2.0))
    allt = xr.concat(means, dim="time")
    clim = allt.groupby("time.dayofyear").mean("time").rename("clim")
    clim.to_dataset().to_netcdf(cache)
    print(f"  cached temp normal -> {cache}")
    return clim


def year_current(year, var):
    """This year's IMD daily field (rain, or (tmax+tmin)/2), on its native grid."""
    import imdlib as imd
    if var == "rain":
        r = imd.get_data("rain", year, year, fn_format="yearwise", file_dir=str(IMD_DIR)).get_xarray()["rain"]
        return r.where(r >= 0)
    tx = _temp(imd.get_data("tmax", year, year, fn_format="yearwise", file_dir=str(IMD_DIR)).get_xarray(), "tmax")
    tn = _temp(imd.get_data("tmin", year, year, fn_format="yearwise", file_dir=str(IMD_DIR)).get_xarray(), "tmin")
    return (tx + tn) / 2.0


def weight_tensor(cur, districts, gadm):
    """district x (lat,lon) normalised weights for this grid (one xr.dot to collapse)."""
    lonn, latn = _lonlat(cur)
    latv, lonv = cur[latn].values, cur[lonn].values
    Wnp = np.zeros((len(districts), latv.size, lonv.size))
    for i, d in enumerate(districts.itertuples(index=False)):
        geom, _ = resolve_geom(gadm, d.state, d.district, d.latitude, d.longitude)
        w, _, _ = region_weights(latv, lonv, latn, lonn, geom)
        wv = np.asarray(w.fillna(0.0).values)
        tot = wv.sum()
        if tot > 0:
            Wnp[i] = wv / tot
    return xr.DataArray(Wnp, dims=("district", latn, lonn), coords={latn: latv, lonn: lonv}), latn, lonn


def weekly_anom(cur, clim, init_ts, weeks):
    """(week, lat, lon) observed weekly-mean anomaly vs the DOY normal for one init."""
    times = pd.to_datetime(cur["time"].values)
    out = []
    for wk in range(1, weeks + 1):
        start = init_ts + pd.Timedelta(days=7 * (wk - 1) + 1)
        end = init_ts + pd.Timedelta(days=7 * wk)
        m = (times >= start) & (times <= end)
        if not m.any():
            out.append(None)
            continue
        sub = cur.isel(time=m)
        doy = pd.to_datetime(sub["time"].values).dayofyear
        cl = clim.sel(dayofyear=xr.DataArray(doy, dims="time"))
        out.append((sub.mean("time") - cl.mean("time")))
    valid = [(i + 1, a) for i, a in enumerate(out) if a is not None]
    if not valid:
        return None
    wks = [w for w, _ in valid]
    da = xr.concat([a for _, a in valid], dim=pd.Index(wks, name="week"))
    return da


def main():
    ap = argparse.ArgumentParser(description="Observed IMD truth (weekly district anomalies) for the backtest.")
    ap.add_argument("--inits", default=str(INITS_CSV))
    ap.add_argument("--clim-years", type=int, nargs=2, metavar=("START", "END"), default=[1991, 2020])
    ap.add_argument("--weeks", type=int, default=5)
    args = ap.parse_args()

    inits = pd.read_csv(args.inits)
    districts = pd.read_csv(DISTRICTS_CSV)
    gadm = gadm_districts()

    print("building IMD day-of-year normals ...")
    rain_clim = build_climatology(tuple(args.clim_years))       # 0.25 deg
    temp_clim = build_temp_clim(tuple(args.clim_years))         # 1 deg

    wcache = {}
    for year, grp in inits.groupby(inits["init_date"].str[:4].astype(int)):
        print(f"[{year}] loading IMD rain + temp ...", flush=True)
        fields = {"precip": (year_current(year, "rain"), rain_clim),
                  "t2m":    (year_current(year, "temp"), temp_clim)}
        for _, row in grp.iterrows():
            init_ts = pd.Timestamp(row["init_date"])
            init = row["init_date"].replace("-", "")
            out_path = TRUTH / f"{init}.nc"
            if out_path.exists():
                print(f"  {row['init_date']}: truth exists -> skip")
                continue
            dvars = {}
            for var, (cur, clim) in fields.items():
                anom = weekly_anom(cur, clim, init_ts, args.weeks)
                if anom is None:
                    continue
                gkey = _lonlat(cur)
                if gkey not in wcache:
                    wcache[gkey] = weight_tensor(cur, districts, gadm)
                W, latn, lonn = wcache[gkey]
                dvars[f"obs_{var}_anom"] = xr.dot(W, anom, dims=[latn, lonn])   # (district, week)
            if not dvars:
                print(f"  {row['init_date']}: no valid weeks -> skip")
                continue
            ds = xr.Dataset(dvars).assign_coords(
                state=("district", districts["state"].to_numpy()),
                district_name=("district", districts["district"].to_numpy()))
            ds.attrs["init"] = init
            ds.to_netcdf(out_path)
            print(f"  {row['init_date']}: wrote {out_path.name} (vars {list(dvars)})")


if __name__ == "__main__":
    main()
