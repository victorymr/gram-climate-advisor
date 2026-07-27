"""
Subseasonal helpers shared by the EC46 / GEFS pipeline.

A "forecast" DataArray here has a lead dimension whose coordinate `lead_hours`
gives hours from initialization (>0). to_weekly() collapses that into fixed
7-day windows (week 1 = days 1-7 = lead 0-168 h, ..., week 5 = days 29-35).

Temperature (instantaneous) is aggregated with method="mean".
Precip given as 6-hourly ACCUMULATIONS (mm/bucket) is aggregated with
method="sum_per_day" -> weekly mean rate in mm/day. Precip given as a RATE
(mm/day already) uses method="mean".
"""

import numpy as np
import pandas as pd
import xarray as xr

HOURS_PER_WEEK = 168


def to_weekly(da, weeks=(1, 2, 3, 4, 5), method="mean", lead_name="lead_hours"):
    """Collapse a lead-resolved DataArray into weekly windows.

    Returns a DataArray with the lead dim replaced by an integer `week` dim.
    Windows are (lo, hi] in hours: week w -> ((w-1)*168, w*168].
    """
    if lead_name not in da.coords and lead_name not in da.dims:
        raise KeyError(f"'{lead_name}' not found on DataArray (dims={da.dims})")
    lh = da[lead_name]
    # the dim to reduce over is the one `lead_hours` indexes (often 'step')
    rdim = lead_name if lead_name in da.dims else lh.dims[0]
    out = []
    for w in weeks:
        lo, hi = (w - 1) * HOURS_PER_WEEK, w * HOURS_PER_WEEK
        sel = da.where((lh > lo) & (lh <= hi), drop=True)
        if sel[lead_name].size == 0:
            continue  # this model doesn't reach week w
        if method == "mean":
            wk = sel.mean(rdim)
        elif method == "sum_per_day":
            wk = sel.sum(rdim) / 7.0
        else:
            raise ValueError(f"unknown method {method!r}")
        out.append(wk.assign_coords(week=w))
    if not out:
        raise ValueError("no weeks produced (check lead coverage)")
    return xr.concat(out, dim="week")


def weekly_anomaly(fc_weekly, clim_weekly):
    """fc - clim, auto-aligned on the shared (week, lat, lon). Both must be on
    the same grid (same model). Returns the anomaly DataArray."""
    fc, cl = xr.align(fc_weekly, clim_weekly, join="inner")
    return fc - cl


def overlap_weeks(*weekly_objs):
    """Sorted list of week indices present in all given (week,...)-dim objects."""
    sets = [set(int(w) for w in o["week"].values) for o in weekly_objs]
    return sorted(set.intersection(*sets))


def weekly_clim_for_init(doy_clim, init_date, weeks):
    """Turn a day-of-year climatology (dim 'dayofyear' 1..365/366, + lat/lon) into
    a per-init weekly climatology (dim 'week'), matching the forecast week windows:
    week w covers forecast days (w-1)*7+1 .. w*7 (valid date = init + day).
    Works on a Dataset (e.g. vars t2m, precip) or a DataArray."""
    init = pd.Timestamp(init_date)
    avail = set(int(x) for x in np.asarray(doy_clim["dayofyear"]))
    out = []
    for w in weeks:
        doys = []
        for d in range((w - 1) * 7 + 1, w * 7 + 1):
            doy = (init + pd.Timedelta(days=int(d))).dayofyear
            doys.append(doy if doy in avail else (365 if doy == 366 else doy))
        wk = doy_clim.sel(dayofyear=doys).mean("dayofyear").assign_coords(week=w)
        out.append(wk)
    return xr.concat(out, dim="week")
