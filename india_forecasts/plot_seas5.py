#!/usr/bin/env python3
"""
Plot ECMWF SEAS5 and NOAA SFS Beta ensemble-mean forecasts SIDE BY SIDE over
India -- one row per valid month (the overlap of the two models' leads), two
columns (SEAS5 | SFS). Produces two PNGs in plots/: 2 m temperature and
precipitation.

DEFAULT = ANOMALY (forecast ensemble mean minus the model's own hindcast
climatology), so the two models are compared like-for-like on a shared diverging
scale. Pass --absolute for raw ensemble means instead.

  SEAS5 anomaly = forecast - hindcast climatology
        forecast : download_seas5.py            (t2m [K], tprate [m s-1])
        clim     : download_seas5.py --hindcast (mean over number + forecast_reference_time)
  SFS   anomaly = forecast - reforecast climatology
        forecast : download_sfs.py              (tmp2m [K], pratesfc [kg m-2 s-1], India crop)
        clim     : download_sfs.py --reforecast (GLOBAL file; cropped to India and
                   averaged over init + member on the fly here)

Lead alignment: SEAS5 forecastMonth=1 and SFS lead=0 are both the init month;
each is converted to a valid month and rows are the overlap.

Usage:
    python plot_seas5.py                    # anomaly maps, newest files auto-found
    python plot_seas5.py --absolute         # raw ensemble-mean maps
    python plot_seas5.py --percent          # precip as % of normal (temp stays anomaly)
    python plot_seas5.py --season           # collapse to the upcoming season (JAS for a June init)
    python plot_seas5.py --combine          # merge SEAS5 + SFS into one multi-model graphic
    python plot_seas5.py --mode tercile --season --combine
    python plot_seas5.py --seas5 F --sfs F --seas5-clim F --sfs-clim F
"""

import os
import sys
import re
import glob
import argparse
import textwrap
import warnings
import numpy as np
import pandas as pd
import xarray as xr
import matplotlib.pyplot as plt
from matplotlib import ticker
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize
import cartopy.crs as ccrs
import cartopy.feature as cfeature

from config import SEAS5_DIR, SFS_DIR, OBS_DIR, INDIA_BBOX, ROOT
from utils import subset_to_india

PLOTS_DIR = ROOT / "plots"
PLOTS_DIR.mkdir(exist_ok=True)

SHOW = True   # display figures interactively as well as saving (toggle with --no-show)

M_S_TO_MMDAY = 86400.0 * 1000.0   # m s-1        -> mm/day  (SEAS5 tprate)
KG_M2_S_TO_MMDAY = 86400.0        # kg m-2 s-1   -> mm/day  (SFS pratesfc, == mm/s)

plt.rcParams["hatch.linewidth"] = 0.5   # thin hatching for the low-skill overlay

PANEL_W, PANEL_H = 4.7, 4.8   # per-map size (in); India maps are ~square (slightly tall)


def fig_size(ncol, nrow, ncbars=1):
    """Figure size that keeps each map ~PANEL_W x PANEL_H and reserves just enough
    horizontal room for the (thin) colourbar(s) plus their labels -- so narrow
    (few-column) figures don't shrink the maps, but a single panel isn't left with
    a wide empty gap beside one colourbar either."""
    return (PANEL_W * ncol + 0.8 * ncbars + 0.2, PANEL_H * nrow)


def wrapped_suptitle(fig, axes, text, fontsize=13, fontweight="bold"):
    """Figure title centred over the map axes (not the whole figure, which is
    offset by the colourbar) and wrapped to their width, so a long title doesn't
    stretch the saved image (bbox_inches='tight') wider than the plots."""
    fig.canvas.draw()   # let constrained_layout settle the axes positions first
    boxes = [ax.get_position() for ax in axes.ravel()]
    x0, x1 = min(b.x0 for b in boxes), max(b.x1 for b in boxes)
    width_in = (x1 - x0) * fig.get_size_inches()[0]
    char_in = 0.62 * fontsize / 72.0            # avg glyph advance for the bold title (inches)
    maxchars = max(16, int(width_in / char_in))
    wrapped = "\n".join(textwrap.fill(line, maxchars) for line in text.split("\n"))
    fig.suptitle(wrapped, x=0.5 * (x0 + x1), ha="center", fontsize=fontsize, fontweight=fontweight)


def latest_seas5():
    files = [f for f in sorted(glob.glob(str(SEAS5_DIR / "*.nc"))) if "clim" not in os.path.basename(f).lower()]
    if not files:
        sys.exit(f"No SEAS5 forecast NetCDF in {SEAS5_DIR}. Run download_seas5.py first.")
    return files[-1]


def latest_sfs():
    files = sorted(glob.glob(str(SFS_DIR / "sfs_beta1_*_atm_monthly_india.nc")))
    if not files:
        sys.exit(f"No SFS NetCDF in {SFS_DIR}. Run download_sfs.py first.")
    return files[-1]


def find_seas5_clim(mm):
    c = sorted(glob.glob(str(SEAS5_DIR / f"*clim*init{mm}*.nc"))) or \
        sorted(glob.glob(str(SEAS5_DIR / "*clim*.nc")))
    return c[-1] if c else None


def find_sfs_clim(mm):
    c = sorted(glob.glob(str(SFS_DIR / f"sfs_beta1_reforecast_init{mm}_*global.nc"))) or \
        sorted(glob.glob(str(SFS_DIR / "sfs_beta1_reforecast_*global.nc")))
    return c[-1] if c else None


def find_obs(var):
    """Locate the observation file for var in {'t','p'}."""
    pat = "ghcncams_t2m_india.nc" if var == "t" else "chirps_precip_india.nc"
    hits = sorted(glob.glob(str(OBS_DIR / pat)))
    return hits[-1] if hits else None


def label_of(ts):
    return pd.Timestamp(ts).strftime("%b %Y")


# --------------------------------------------------------------------------
# State focus: zoom/outline one or more Indian states (Natural Earth admin-1).
# --------------------------------------------------------------------------
def _india_state_records():
    import cartopy.io.shapereader as shpreader
    shp = shpreader.natural_earth(resolution="10m", category="cultural",
                                  name="admin_1_states_provinces")
    return [r for r in shpreader.Reader(shp).records()
            if str(r.attributes.get("admin", "") or "").lower() == "india"]


def list_states():
    names = sorted(str(r.attributes.get("name", "")) for r in _india_state_records())
    print("India states/UTs (Natural Earth admin-1):")
    for n in names:
        print(f"  {n}")


def build_focus(names, margin=0.6):
    """Return {geoms, extent, names} for the requested states (case-insensitive,
    substring-tolerant), or exit with guidance if none match."""
    from shapely.ops import unary_union
    wanted = [n.strip().lower() for n in names]
    geoms, matched = [], []
    for r in _india_state_records():
        nm = str(r.attributes.get("name", "") or "")
        low = nm.lower()
        if any(w == low or w in low for w in wanted):
            geoms.append(r.geometry)
            matched.append(nm)
    if not geoms:
        sys.exit(f"No India states matched {names}. Run --list-states to see valid names.")
    unmatched = [n for n in names if not any(n.strip().lower() in m.lower() for m in matched)]
    if unmatched:
        print(f"  warning: no match for: {unmatched}")
    minx, miny, maxx, maxy = unary_union(geoms).bounds
    extent = [minx - margin, maxx + margin, miny - margin, maxy + margin]
    return dict(geoms=geoms, extent=extent, names=matched)


def panel_extent(focus):
    if focus is not None:
        return focus["extent"]
    return [INDIA_BBOX["west"], INDIA_BBOX["east"], INDIA_BBOX["south"], INDIA_BBOX["north"]]


def draw_focus(ax, focus, proj):
    if focus is not None:
        ax.add_geometries(focus["geoms"], crs=proj, facecolor="none",
                          edgecolor="black", linewidth=1.1, zorder=5)


def focus_suffix(focus):
    return f"   |   {', '.join(focus['names'])}" if focus else ""


def focus_slug(focus):
    """Filename fragment from the focused state names, e.g. '_tamil_nadu' or
    '_karnataka-kerala'. Empty string when not focusing."""
    if not focus:
        return ""
    slugs = ["".join(c if c.isalnum() else "_" for c in n.lower()).strip("_")
             for n in focus["names"]]
    return "_" + "-".join(slugs)


def scale_vals(da2d, lonn, latn, focus):
    """Flat values for colour-scaling; restricted to the focus bbox when focusing."""
    if focus is None:
        return da2d.values.ravel()
    w, e, s, n = focus["extent"]
    sub = da2d.where((da2d[lonn] >= w) & (da2d[lonn] <= e) &
                     (da2d[latn] >= s) & (da2d[latn] <= n))
    return sub.values.ravel()


# --------------------------------------------------------------------------
# Skill mask: anomaly (temporal) correlation of each model's hindcast
# ensemble mean against observations, per lead and grid cell, across the
# model's own hindcast years. Pearson over years == anomaly correlation.
# --------------------------------------------------------------------------
def compute_skill(kind, clim_path, init_month, var, obs_path):
    """Return ACC as a DataArray (lead_dim, lat, lon) on the model grid.
    lead_dim is 'forecastMonth' (SEAS5) or 'lead' (SFS) to match the forecast."""
    ovar = "t2m" if var == "t" else "precip"
    obs = xr.open_dataset(obs_path)[ovar]   # (time, lat, lon)

    if kind == "sfs":
        dc = subset_to_india(xr.open_dataset(clim_path), INDIA_BBOX)
        cvar = "tmp2m" if var == "t" else "pratesfc"
        hc = dc[cvar].mean("member")        # (init, lead, lat, lon)
        yrdim, leaddim, latn, lonn = "init", "lead", "lat", "lon"
        lead_offsets = [int(l) for l in dc["lead"].values]
    else:  # seas5
        dc = xr.open_dataset(clim_path)
        cvar = "t2m" if var == "t" else "tprate"
        hc = dc[cvar].mean("number")        # (forecast_reference_time, forecastMonth, lat, lon)
        yrdim, leaddim, latn, lonn = "forecast_reference_time", "forecastMonth", "latitude", "longitude"
        lead_offsets = [int(m) - 1 for m in dc["forecastMonth"].values]

    years = pd.to_datetime(dc[yrdim].values).year
    # obs (land, monthly) regridded onto the model grid (nearest; grids are ~equal res)
    oi = obs.reindex(lat=dc[latn].values, lon=dc[lonn].values, method="nearest")
    oi = oi.rename({"lat": latn, "lon": lonn})

    layers = []
    for off in lead_offsets:  # match obs to each (year, lead) valid month
        valid = [pd.Timestamp(year=int(y), month=int(init_month), day=1) + pd.DateOffset(months=off)
                 for y in years]
        sel = oi.reindex(time=pd.to_datetime(valid), method="nearest", tolerance=pd.Timedelta("20D"))
        layers.append(sel.rename({"time": yrdim}).assign_coords({yrdim: hc[yrdim].values}))
    obs_match = xr.concat(layers, dim=leaddim).assign_coords({leaddim: hc[leaddim].values})
    obs_match = obs_match.transpose(*hc.dims)

    with warnings.catch_warnings():  # all-NaN (ocean) cells -> NaN ACC; expected
        warnings.simplefilter("ignore", RuntimeWarning)
        return xr.corr(hc, obs_match, dim=yrdim)  # (leaddim, lat, lon)


def hatch_lowskill(ax, acc2d, m, thresh, proj):
    """Overlay grey hatching on cells that are NOT demonstrably skillful, i.e.
    ACC < thresh OR ACC undefined (NaN, e.g. ocean with no land obs). The
    forecast colours stay visible underneath."""
    if acc2d is None:
        return
    low = xr.where(acc2d >= thresh, 0.0, 1.0)  # 1 = low / unknown skill
    cs = ax.contourf(acc2d[m["lon"]], acc2d[m["lat"]], low.values,
                     levels=[0.5, 1.5], colors="none", hatches=["////"],
                     transform=proj, zorder=4)
    cs.set_edgecolor((0.2, 0.2, 0.2, 0.9))  # dark-grey hatch lines


def pct_of_normal(fc, clim):
    """Forecast rate as a percent of the climatological normal (100% == normal).
    Units cancel in the ratio, so raw rates are fine. Cells whose normal is
    non-positive (dry deserts, ocean) are masked -- percent-of-normal blows up."""
    return fc / clim.where(clim > 0) * 100.0


def load_seas5(fc_path, clim_path=None, metric="anomaly"):
    ds = xr.open_dataset(fc_path)
    ref = pd.Timestamp(np.atleast_1d(ds["forecast_reference_time"].values)[0])
    fc_t = ds["t2m"].mean("number").squeeze(drop=True)       # K
    fc_p = ds["tprate"].mean("number").squeeze(drop=True)    # m s-1

    if clim_path:
        dc = xr.open_dataset(clim_path)
        clim_t = dc["t2m"].mean(["number", "forecast_reference_time"])
        clim_p = dc["tprate"].mean(["number", "forecast_reference_time"])
        t = fc_t - clim_t                          # degC anomaly (K diff)
        if metric == "percent":
            p = pct_of_normal(fc_p, clim_p)        # % of normal
        else:
            p = (fc_p - clim_p) * M_S_TO_MMDAY     # mm/day anomaly
    else:
        t = fc_t - 273.15                          # degC
        p = fc_p * M_S_TO_MMDAY                     # mm/day

    fm = ds["forecastMonth"].values                # 1 == init month
    valid = [ref + pd.DateOffset(months=int(m) - 1) for m in fm]
    return dict(name="SEAS5", ref=ref, nmem=int(ds.sizes["number"]),
                fields={"t": t, "p": p}, lead_dim="forecastMonth",
                labels=[label_of(v) for v in valid], lat="latitude", lon="longitude")


def load_sfs(fc_path, clim_path=None, metric="anomaly"):
    ds = xr.open_dataset(fc_path)
    cyc = ds.attrs.get("init_cycle") or (re.search(r"_(\d{6})_", str(fc_path)) or [None, None])[1]
    if not cyc:
        sys.exit(f"Cannot determine SFS init cycle (YYYYMM) from {fc_path}.")
    ref = pd.Timestamp(f"{cyc}01")
    fc_t = ds["tmp2m"].mean("member").squeeze(drop=True)        # K
    fc_p = ds["pratesfc"].mean("member").squeeze(drop=True)     # kg m-2 s-1

    if clim_path:
        # global reforecast -> crop to India first (tiny slab) -> climatology over init + member
        dcg = subset_to_india(xr.open_dataset(clim_path), INDIA_BBOX)
        clim = dcg[["tmp2m", "pratesfc"]].mean(["init", "member"]).load()
        clim = clim.reindex(lat=ds["lat"], lon=ds["lon"], method="nearest")
        t = fc_t - clim["tmp2m"]                     # degC anomaly
        if metric == "percent":
            p = pct_of_normal(fc_p, clim["pratesfc"])      # % of normal
        else:
            p = (fc_p - clim["pratesfc"]) * KG_M2_S_TO_MMDAY   # mm/day anomaly
    else:
        t = fc_t - 273.15                            # degC
        p = fc_p * KG_M2_S_TO_MMDAY                   # mm/day

    lead = ds["lead"].values                         # 0 == init month
    valid = [ref + pd.DateOffset(months=int(l)) for l in lead]
    return dict(name="SFS Beta", ref=ref, nmem=int(ds.sizes["member"]),
                fields={"t": t, "p": p}, lead_dim="lead",
                labels=[label_of(v) for v in valid], lat="lat", lon="lon")


def get2d(m, var, label):
    """2-D (lat, lon) slice of model m's var at the given valid-month label."""
    i = m["labels"].index(label)
    return m["fields"][var].isel({m["lead_dim"]: i})


# --------------------------------------------------------------------------
# Upcoming-season collapse: instead of one column per valid month, average the
# `nmonths` months *after* the init month into a single seasonal-mean column
# (JAS for a June init). Works on loaded dicts (fields), raw dicts (fc/clim),
# and skill arrays -- all share lead position 0 == init month, so the upcoming
# months are always positions 1..nmonths.
# --------------------------------------------------------------------------
MONTH_LETTERS = "JFMAMJJASOND"


def season_positions(nmonths=3, skip_init=True):
    start = 1 if skip_init else 0
    return list(range(start, start + nmonths))


def season_label(months, year):
    """e.g. months [7, 8, 9], year 2026 -> 'JAS 2026'."""
    return "".join(MONTH_LETTERS[m - 1] for m in months) + f" {year}"


def _collapse_field(da, lead_dim, pos):
    """Mean over the season's lead positions, keeping a length-1 lead dim so the
    downstream isel-by-index machinery is unchanged."""
    return da.isel({lead_dim: pos}).mean(lead_dim).expand_dims({lead_dim: [0]})


def collapse_to_season(m, nmonths=3, skip_init=True):
    """Collapse a model dict to a single upcoming-season column. Handles loaded
    dicts ('fields'), raw dicts ('fc'/'clim'), and returns the new season label."""
    pos = season_positions(nmonths, skip_init)
    if len(m["labels"]) < pos[-1] + 1:
        sys.exit(f"{m['name']}: only {len(m['labels'])} lead months available; "
                 f"need {pos[-1] + 1} for the {nmonths}-month upcoming season.")
    valid = [m["ref"] + pd.DateOffset(months=o) for o in pos]
    lab = season_label([v.month for v in valid], valid[len(valid) // 2].year)
    ld = m["lead_dim"]
    out = dict(m)
    out["labels"] = [lab]
    for key in ("fields", "fc", "clim"):
        if key in m:
            out[key] = {v: _collapse_field(da, ld, pos) for v, da in m[key].items()}
    return out


def collapse_skill(skill, lead_dims, nmonths=3, skip_init=True):
    """Season-collapse ACC arrays by averaging over the same lead positions (a
    coarse but adequate summary for the low-skill hatch mask)."""
    pos = season_positions(nmonths, skip_init)
    return {name: {var: _collapse_field(acc, lead_dims[name], pos)
                   for var, acc in d.items()}
            for name, d in skill.items()}


def season_slug(models):
    """Filename fragment from the collapsed season label, e.g. '_jas2026'."""
    return "_" + models[0]["labels"][0].replace(" ", "").lower()


# --------------------------------------------------------------------------
# Multi-model ensemble (MME): merge SEAS5 + SFS into one forecast graphic. The
# two models sit on different grids, so the second is regridded onto the first's
# grid and combined per valid month. Deterministic fields are averaged; tercile
# probabilities are averaged (see combine_tercile). Equal weight per model.
# --------------------------------------------------------------------------
def regrid_like(da, src, tgt_lat, tgt_lon, ref):
    """Regrid `da` (on model `src`'s grid) onto `ref`'s grid, renaming the spatial
    dims to (tgt_lat, tgt_lon) and interpolating to ref's coordinates."""
    return (da.rename({src["lat"]: tgt_lat, src["lon"]: tgt_lon})
              .interp({tgt_lat: ref[tgt_lat], tgt_lon: ref[tgt_lon]}, method="linear"))


def combine_loaded(models):
    """Merge loaded model dicts (ensemble-mean 'fields') into one 'Multi-model'
    column on the first model's grid, averaged per overlapping valid month."""
    a, b = models
    latn, lonn, ld = a["lat"], a["lon"], a["lead_dim"]
    common = [l for l in a["labels"] if l in set(b["labels"])]
    if not common:
        sys.exit("No overlapping valid months between SEAS5 and SFS leads.")
    fields = {}
    for var in a["fields"]:
        layers = []
        for lab in common:
            fa = get2d(a, var, lab)
            fb = regrid_like(get2d(b, var, lab), b, latn, lonn, fa)
            layers.append((fa + fb) / 2.0)
        fields[var] = xr.concat(layers, dim=ld).assign_coords({ld: list(range(len(common)))})
    out = dict(a)
    out["name"], out["fields"], out["labels"] = "Multi-model", fields, common
    return [out]


def combine_skill(skill, models):
    """Multi-model ACC keyed 'Multi-model': average each model's hindcast skill
    onto the first model's grid, aligned by valid month. Coarse but adequate for
    the low-skill hatch mask."""
    a, b = models
    latn, lonn, ld = a["lat"], a["lon"], a["lead_dim"]
    common = [l for l in a["labels"] if l in set(b["labels"])]
    out = {}
    for var in skill[a["name"]]:
        aacc, bacc = skill[a["name"]][var], skill[b["name"]][var]
        layers = []
        for lab in common:
            sa = aacc.isel({a["lead_dim"]: a["labels"].index(lab)})
            sb = regrid_like(bacc.isel({b["lead_dim"]: b["labels"].index(lab)}), b, latn, lonn, sa)
            layers.append((sa + sb) / 2.0)
        out[var] = xr.concat(layers, dim=ld).assign_coords({ld: list(range(len(common)))})
    return {"Multi-model": out}


# --------------------------------------------------------------------------
# Tercile / confidence support: keep the raw ensembles, not just the means.
# --------------------------------------------------------------------------
def seas5_raw(fc_path, clim_path):
    ds = xr.open_dataset(fc_path)
    ref = pd.Timestamp(np.atleast_1d(ds["forecast_reference_time"].values)[0])
    fc = {"t": ds["t2m"].squeeze(drop=True), "p": ds["tprate"].squeeze(drop=True)}  # (number, fM, lat, lon)
    dc = xr.open_dataset(clim_path)
    clim = {"t": dc["t2m"], "p": dc["tprate"]}  # (number, forecast_reference_time, fM, lat, lon)
    fm = ds["forecastMonth"].values
    valid = [ref + pd.DateOffset(months=int(m) - 1) for m in fm]
    return dict(name="SEAS5", ref=ref, nmem=int(ds.sizes["number"]),
                fc=fc, clim=clim, member_dim="number",
                pool=["number", "forecast_reference_time"], lead_dim="forecastMonth",
                labels=[label_of(v) for v in valid], lat="latitude", lon="longitude")


def sfs_raw(fc_path, clim_path):
    ds = xr.open_dataset(fc_path)
    cyc = ds.attrs.get("init_cycle") or (re.search(r"_(\d{6})_", str(fc_path)) or [None, None])[1]
    if not cyc:
        sys.exit(f"Cannot determine SFS init cycle (YYYYMM) from {fc_path}.")
    ref = pd.Timestamp(f"{cyc}01")
    fc = {"t": ds["tmp2m"].squeeze(drop=True), "p": ds["pratesfc"].squeeze(drop=True)}  # (member, lead, lat, lon)
    dcg = subset_to_india(xr.open_dataset(clim_path), INDIA_BBOX)
    clim = {"t": dcg["tmp2m"], "p": dcg["pratesfc"]}  # (init, member, lead, lat, lon)
    lead = ds["lead"].values
    valid = [ref + pd.DateOffset(months=int(l)) for l in lead]
    return dict(name="SFS Beta", ref=ref, nmem=int(ds.sizes["member"]),
                fc=fc, clim=clim, member_dim="member",
                pool=["init", "member"], lead_dim="lead",
                labels=[label_of(v) for v in valid], lat="lat", lon="lon")


def tercile_probs_full(m, var):
    """Below/near/above tercile probabilities as a DataArray with a 'cat' dim
    (0=below, 1=near, 2=above) x (lead_dim, lat, lon). Thresholds from the pooled
    hindcast distribution; probabilities from the forecast member fractions."""
    fc = m["fc"][var]
    clim = m["clim"][var].reindex({m["lat"]: fc[m["lat"]], m["lon"]: fc[m["lon"]]},
                                  method="nearest")
    q33 = clim.quantile(1 / 3, dim=m["pool"]).drop_vars("quantile")
    q67 = clim.quantile(2 / 3, dim=m["pool"]).drop_vars("quantile")
    below = (fc < q33).mean(m["member_dim"])
    above = (fc > q67).mean(m["member_dim"])
    normal = 1.0 - below - above
    return xr.concat([below, normal, above], dim="cat")


def tercile_prob(m, var):
    """Most-likely tercile category and its probability, as DataArrays (lead_dim, lat, lon)."""
    probs = tercile_probs_full(m, var)
    return probs.argmax("cat"), probs.max("cat")


def combine_tercile(models, var):
    """Multi-model tercile: average the two models' category probabilities onto the
    first model's grid (aligned by valid month), then take the most-likely category.
    Returns a pseudo-model dict plus (cat, pmax) for the plotting loop."""
    a, b = models
    latn, lonn, ld = a["lat"], a["lon"], a["lead_dim"]
    common = [l for l in a["labels"] if l in set(b["labels"])]
    if not common:
        sys.exit("No overlapping valid months between SEAS5 and SFS leads.")
    pa, pb = tercile_probs_full(a, var), tercile_probs_full(b, var)
    layers = []
    for lab in common:
        sa = pa.isel({a["lead_dim"]: a["labels"].index(lab)})
        sb = regrid_like(pb.isel({b["lead_dim"]: b["labels"].index(lab)}), b, latn, lonn, sa)
        layers.append((sa + sb) / 2.0)
    probs = xr.concat(layers, dim=ld).assign_coords({ld: list(range(len(common)))})
    pseudo = dict(name="Multi-model", labels=common, lat=latn, lon=lonn, lead_dim=ld)
    return pseudo, probs.argmax("cat"), probs.max("cat")


# --------------------------------------------------------------------------
# Hindcast events: for a chosen (June-init) year, build the model hindcast
# anomaly and the observed anomaly so forecast and verification sit together.
# --------------------------------------------------------------------------
def seas5_hindcast_year(clim_path, year):
    dc = xr.open_dataset(clim_path)
    yrs = pd.to_datetime(dc["forecast_reference_time"].values).year
    if year not in set(yrs):
        return None
    i = int(np.where(yrs == year)[0][0])
    t = dc["t2m"].isel(forecast_reference_time=i).mean("number") - dc["t2m"].mean(["number", "forecast_reference_time"])
    p = (dc["tprate"].isel(forecast_reference_time=i).mean("number") - dc["tprate"].mean(["number", "forecast_reference_time"])) * M_S_TO_MMDAY
    valid = [pd.Timestamp(year, 6, 1) + pd.DateOffset(months=int(m) - 1) for m in dc["forecastMonth"].values]
    return dict(name="SEAS5", fields={"t": t, "p": p}, lead_dim="forecastMonth",
                labels=[label_of(v) for v in valid], lat="latitude", lon="longitude")


def sfs_hindcast_year(clim_path, year):
    dc = subset_to_india(xr.open_dataset(clim_path), INDIA_BBOX)
    yrs = pd.to_datetime(dc["init"].values).year
    if year not in set(yrs):
        return None
    i = int(np.where(yrs == year)[0][0])
    t = dc["tmp2m"].isel(init=i).mean("member") - dc["tmp2m"].mean(["init", "member"])
    p = (dc["pratesfc"].isel(init=i).mean("member") - dc["pratesfc"].mean(["init", "member"])) * KG_M2_S_TO_MMDAY
    valid = [pd.Timestamp(year, 6, 1) + pd.DateOffset(months=int(l)) for l in dc["lead"].values]
    return dict(name="SFS Beta", fields={"t": t, "p": p}, lead_dim="lead",
                labels=[label_of(v) for v in valid], lat="lat", lon="lon")


def obs_year(obs_t_path, obs_p_path, year, nlead=12):
    """Observed anomaly for the year's June-init valid months (offset 0..nlead-1).
    Anomaly = month value minus that calendar month's climatology over all obs years.
    Precip converted mm/month -> mm/day to match the model fields."""
    ot = xr.open_dataset(obs_t_path)["t2m"]      # degC
    op = xr.open_dataset(obs_p_path)["precip"]   # mm/month
    ot_clim = ot.groupby("time.month").mean("time")
    op_clim = op.groupby("time.month").mean("time")
    t_layers, p_layers, labels = [], [], []
    for off in range(nlead):
        v = pd.Timestamp(year, 6, 1) + pd.DateOffset(months=off)
        labels.append(label_of(v))
        tv = ot.sel(time=v, method="nearest") - ot_clim.sel(month=v.month)
        pv = (op.sel(time=v, method="nearest") - op_clim.sel(month=v.month)) / v.days_in_month
        t_layers.append(tv.drop_vars("month", errors="ignore"))
        p_layers.append(pv.drop_vars("month", errors="ignore"))
    t = xr.concat(t_layers, dim="lead")
    p = xr.concat(p_layers, dim="lead")
    return dict(name="Observed", fields={"t": t, "p": p}, lead_dim="lead",
                labels=labels, lat="lat", lon="lon")


def event_figure(cols, var, *, title, units, cmap, out, robust=(2, 98), focus=None):
    """Forecast-vs-verification: N columns (model hindcasts + obs), one row per
    valid month common to all columns. Shared symmetric (diverging) anomaly scale."""
    common = [l for l in cols[0]["labels"] if all(l in set(c["labels"]) for c in cols[1:])]
    if not common:
        sys.exit("No overlapping valid months across the requested columns.")

    vals = np.concatenate([scale_vals(get2d(c, var, l), c["lon"], c["lat"], focus)
                           for c in cols for l in common])
    a = np.nanpercentile(np.abs(vals), robust[1])
    vmin, vmax = -a, a

    nrow, ncol = len(cols), len(common)   # rows = columns/models, cols = months (landscape)
    proj = ccrs.PlateCarree()
    fig, axes = plt.subplots(nrow, ncol, figsize=fig_size(ncol, nrow),
                             constrained_layout=True, squeeze=False,
                             subplot_kw={"projection": proj})
    extent = panel_extent(focus)

    im = None
    for ri, col in enumerate(cols):
        for ci, lab in enumerate(common):
            ax = axes[ri][ci]
            f = get2d(col, var, lab)
            im = ax.pcolormesh(f[col["lon"]], f[col["lat"]], f.values,
                               cmap=cmap, vmin=vmin, vmax=vmax, shading="auto", transform=proj)
            ax.add_feature(cfeature.COASTLINE, linewidth=0.6)
            ax.add_feature(cfeature.BORDERS, linewidth=0.4)
            draw_focus(ax, focus, proj)
            ax.set_extent(extent, crs=proj)
            if ri == 0:
                ax.set_title(f"{lab}  (lead +{ci})", fontsize=10)
            if ci == 0:
                ax.text(-0.30, 0.5, col["name"], transform=ax.transAxes, rotation=90,
                        va="center", ha="center", fontsize=11, fontweight="bold")
            gl = ax.gridlines(draw_labels=True, lw=0.3, alpha=0.4)
            gl.top_labels = gl.right_labels = False
            gl.left_labels = (ci == 0)
            gl.bottom_labels = (ri == nrow - 1)
            gl.xlocator = ticker.MultipleLocator(10)
            gl.ylocator = ticker.MultipleLocator(10)

    cbar = fig.colorbar(im, ax=axes.ravel().tolist(), shrink=0.55, pad=0.015, aspect=32)
    cbar.set_label(units)
    wrapped_suptitle(fig, axes, title + focus_suffix(focus))
    fig.savefig(out, dpi=150, bbox_inches="tight")
    if not SHOW:
        plt.close(fig)   # when showing, keep the figure open for a single plt.show() at the end
    print(f"  saved -> {out}")


def comparison_figure(models, var, *, title, units, cmap, out, robust=(2, 98), symmetric=False,
                      center=None, skill=None, skill_thresh=0.3, focus=None, lead_suffix=True):
    """models: list of model dicts (column order). One row per overlapping valid month.
    center: if given, use a diverging scale centred on that value (e.g. 100 for
    percent-of-normal); symmetric centres on 0."""
    common = [l for l in models[0]["labels"] if all(l in set(m["labels"]) for m in models[1:])]
    if not common:
        sys.exit("No overlapping valid months between SEAS5 and SFS leads.")

    vals = np.concatenate([scale_vals(get2d(m, var, l), m["lon"], m["lat"], focus)
                           for m in models for l in common])
    if center is not None:  # diverging scale centred on `center` (percent-of-normal)
        a = np.nanpercentile(np.abs(vals - center), robust[1])
        vmin, vmax = center - a, center + a
    elif symmetric:  # diverging scale centred on 0 (anomalies)
        a = np.nanpercentile(np.abs(vals), robust[1])
        vmin, vmax = -a, a
    else:
        vmin, vmax = np.nanpercentile(vals, robust)

    nrow, ncol = len(models), len(common)   # rows = models, cols = months (landscape)
    proj = ccrs.PlateCarree()
    fig, axes = plt.subplots(nrow, ncol, figsize=fig_size(ncol, nrow),
                             constrained_layout=True, squeeze=False,
                             subplot_kw={"projection": proj})
    extent = panel_extent(focus)

    im = None
    for ri, m in enumerate(models):
        for ci, lab in enumerate(common):
            ax = axes[ri][ci]
            f = get2d(m, var, lab)
            im = ax.pcolormesh(f[m["lon"]], f[m["lat"]], f.values,
                               cmap=cmap, vmin=vmin, vmax=vmax, shading="auto",
                               transform=proj)
            if skill is not None:
                acc = skill[m["name"]][var]
                hatch_lowskill(ax, acc.isel({m["lead_dim"]: m["labels"].index(lab)}),
                               m, skill_thresh, proj)
            ax.add_feature(cfeature.COASTLINE, linewidth=0.6)
            ax.add_feature(cfeature.BORDERS, linewidth=0.4)
            draw_focus(ax, focus, proj)
            ax.set_extent(extent, crs=proj)
            if ri == 0:
                ax.set_title(f"{lab}  (lead +{ci})" if lead_suffix else lab, fontsize=10)
            if ci == 0 and m["name"] != "Multi-model":  # single MME row needs no model label
                ax.text(-0.30, 0.5, m["name"], transform=ax.transAxes, rotation=90,
                        va="center", ha="center", fontsize=11, fontweight="bold")
            gl = ax.gridlines(draw_labels=True, lw=0.3, alpha=0.4)
            gl.top_labels = gl.right_labels = False
            gl.left_labels = (ci == 0)
            gl.bottom_labels = (ri == nrow - 1)
            gl.xlocator = ticker.MultipleLocator(10)
            gl.ylocator = ticker.MultipleLocator(10)

    cbar = fig.colorbar(im, ax=axes.ravel().tolist(), shrink=0.55, pad=0.015, aspect=32)
    cbar.set_label(units)
    if skill is not None:
        fig.text(0.5, -0.02, f"hatched = low hindcast skill (anomaly correlation < {skill_thresh})",
                 ha="center", fontsize=9, style="italic")
    wrapped_suptitle(fig, axes, title + focus_suffix(focus))
    fig.savefig(out, dpi=150, bbox_inches="tight")
    if not SHOW:
        plt.close(fig)   # when showing, keep the figure open for a single plt.show() at the end
    print(f"  saved -> {out}")


def tercile_figure(models, var, *, title, cmaps, cat_labels, out, pnorm=(1 / 3, 0.8),
                   skill=None, skill_thresh=0.3, focus=None, lead_suffix=True, combine=False):
    """Most-likely-tercile maps, SEAS5 | SFS, one row per overlapping valid month.
    cmaps/cat_labels: 3-tuples for (below, near, above). Cell colour = category,
    intensity = probability of that category (the forecast 'confidence').
    combine=True merges the two models into a single Multi-model row."""
    if combine:
        pseudo, cat, pmax = combine_tercile(models, var)
        models, data = [pseudo], {pseudo["name"]: (cat, pmax)}
    else:
        data = {m["name"]: tercile_prob(m, var) for m in models}  # (cat, pmax) per model
    common = [l for l in models[0]["labels"] if all(l in set(m["labels"]) for m in models[1:])]
    if not common:
        sys.exit("No overlapping valid months between SEAS5 and SFS leads.")

    nrow, ncol = len(models), len(common)   # rows = models, cols = months (landscape)
    proj = ccrs.PlateCarree()
    norm = Normalize(*pnorm)
    fig, axes = plt.subplots(nrow, ncol, figsize=fig_size(ncol, nrow, ncbars=len(cmaps)),
                             constrained_layout=True, squeeze=False,
                             subplot_kw={"projection": proj})
    extent = panel_extent(focus)

    for ri, m in enumerate(models):
        for ci, lab in enumerate(common):
            ax = axes[ri][ci]
            cat, pmax = data[m["name"]]
            i = m["labels"].index(lab)
            catL = cat.isel({m["lead_dim"]: i})
            pL = pmax.isel({m["lead_dim"]: i})
            lon, lat = pL[m["lon"]], pL[m["lat"]]
            for k, cmap in enumerate(cmaps):  # one masked layer per category
                ax.pcolormesh(lon, lat, pL.where(catL == k).values,
                              cmap=cmap, norm=norm, shading="auto", transform=proj)
            if skill is not None:
                acc = skill[m["name"]][var]
                hatch_lowskill(ax, acc.isel({m["lead_dim"]: i}), m, skill_thresh, proj)
            ax.add_feature(cfeature.COASTLINE, linewidth=0.6)
            ax.add_feature(cfeature.BORDERS, linewidth=0.4)
            draw_focus(ax, focus, proj)
            ax.set_extent(extent, crs=proj)
            if ri == 0:
                ax.set_title(f"{lab}  (lead +{ci})" if lead_suffix else lab, fontsize=10)
            if ci == 0 and m["name"] != "Multi-model":  # single MME row needs no model label
                ax.text(-0.30, 0.5, m["name"], transform=ax.transAxes, rotation=90,
                        va="center", ha="center", fontsize=11, fontweight="bold")
            gl = ax.gridlines(draw_labels=True, lw=0.3, alpha=0.4)
            gl.top_labels = gl.right_labels = False
            gl.left_labels = (ci == 0)
            gl.bottom_labels = (ri == nrow - 1)
            gl.xlocator = ticker.MultipleLocator(10)
            gl.ylocator = ticker.MultipleLocator(10)

    for cmap, clab in zip(cmaps, cat_labels):  # one colourbar per category
        cb = fig.colorbar(ScalarMappable(norm=norm, cmap=cmap), ax=axes.ravel().tolist(),
                          shrink=0.55, pad=0.015, aspect=32)
        cb.set_label(f"P({clab})")
        cb.set_ticks([1 / 3, 0.5, 0.7])
        cb.set_ticklabels(["33%", "50%", "70%"])
    if skill is not None:
        fig.text(0.5, -0.02, f"hatched = low hindcast skill (anomaly correlation < {skill_thresh})",
                 ha="center", fontsize=9, style="italic")
    wrapped_suptitle(fig, axes, title + focus_suffix(focus))
    fig.savefig(out, dpi=150, bbox_inches="tight")
    if not SHOW:
        plt.close(fig)   # when showing, keep the figure open for a single plt.show() at the end
    print(f"  saved -> {out}")


def run_hindcast(args, focus=None):
    """--mode hindcast: forecast (model hindcast anomaly) vs verification (observed
    anomaly) for one past June-init year, columns SEAS5 | SFS | Observed."""
    if not args.year:
        sys.exit("--mode hindcast needs --year YYYY (June init), e.g. --year 2002.")
    year = args.year
    s5_clim = args.seas5_clim or find_seas5_clim("06")
    sfs_clim = args.sfs_clim or find_sfs_clim("06")
    obs_t, obs_p = find_obs("t"), find_obs("p")
    if not s5_clim or not sfs_clim:
        sys.exit("Hindcast mode needs both hindcast climatologies (June init) in data/.\n"
                 "  python download_seas5.py --hindcast --month 6\n"
                 "  python download_sfs.py --reforecast --init-month 6")
    if not obs_t or not obs_p:
        sys.exit("Hindcast mode needs observation files in data/obs/.\n  python download_obs.py")

    cols = []
    for builder, clim, tag in [(seas5_hindcast_year, s5_clim, "SEAS5"),
                               (sfs_hindcast_year, sfs_clim, "SFS Beta")]:
        c = builder(clim, year)
        if c is None:
            print(f"  note: {year} not in {tag} hindcast range; skipping that column.")
        else:
            cols.append(c)
    if not cols:
        sys.exit(f"{year} is not in either model's June hindcast (SEAS5 1993-2016, SFS 1991-2025).")
    cols.append(obs_year(obs_t, obs_p, year))

    print(f"Hindcast {year} (June init): columns = {[c['name'] for c in cols]}")
    names = " vs ".join(c["name"] for c in cols)
    event_figure(
        cols, "t",
        title=f"2 m temperature anomaly  -  hindcast {year} (June init):  {names}",
        units="degC anomaly", cmap="RdBu_r",
        out=PLOTS_DIR / f"hindcast_{year}06_t2m_anom{focus_slug(focus)}.png", focus=focus,
    )
    event_figure(
        cols, "p",
        title=f"Precipitation anomaly  -  hindcast {year} (June init):  {names}",
        units="mm/day anomaly", cmap="BrBG",
        out=PLOTS_DIR / f"hindcast_{year}06_precip_anom{focus_slug(focus)}.png", focus=focus,
    )
    print("Done.")
    if SHOW:
        plt.show()


def main():
    ap = argparse.ArgumentParser(description="Plot SEAS5 vs SFS forecasts side by side: anomaly (default), absolute, tercile probability, or a past hindcast year.")
    ap.add_argument("--seas5", default=None, help="SEAS5 forecast NetCDF (default: newest in data/seas5/).")
    ap.add_argument("--sfs", default=None, help="SFS forecast NetCDF (default: newest in data/sfs/).")
    ap.add_argument("--seas5-clim", default=None, help="SEAS5 hindcast climatology NetCDF (anomaly/tercile modes).")
    ap.add_argument("--sfs-clim", default=None, help="SFS global reforecast NetCDF (anomaly/tercile modes).")
    ap.add_argument("--mode", choices=["anomaly", "absolute", "percent", "tercile", "hindcast"], default="anomaly",
                   help="anomaly (default), absolute, percent (precip as %% of normal, temp as anomaly), "
                        "tercile, or hindcast (a past June-init year: forecast vs verification).")
    ap.add_argument("--year", type=int, default=None,
                   help="Hindcast year for --mode hindcast (June init). e.g. 2002.")
    ap.add_argument("--absolute", action="store_true", help="Alias for --mode absolute.")
    ap.add_argument("--percent", action="store_true",
                   help="Alias for --mode percent: precipitation as %% of the hindcast normal (100%% = normal).")
    ap.add_argument("--season", action="store_true",
                   help="Collapse to a single seasonal-mean column: the three months AFTER "
                        "the init month (e.g. JAS for a June init). Applies to anomaly/absolute/tercile.")
    ap.add_argument("--season-months", type=int, default=3, metavar="N",
                   help="Number of upcoming months to average for --season (default 3).")
    ap.add_argument("--combine", action="store_true",
                   help="Merge SEAS5 + SFS into a single multi-model (MME) forecast graphic "
                        "(equal weight; SFS regridded onto the SEAS5 grid). Works for "
                        "anomaly/absolute/percent/tercile.")
    ap.add_argument("--skill-mask", action="store_true",
                   help="Fade grid cells where hindcast-vs-obs anomaly correlation is below --skill-thresh.")
    ap.add_argument("--skill-thresh", type=float, default=0.3,
                   help="ACC threshold below which cells are faded as low-skill (default 0.3).")
    ap.add_argument("--state", nargs="+", default=None, metavar="NAME",
                   help="Zoom/outline one or more Indian states, e.g. --state Maharashtra 'Tamil Nadu'.")
    ap.add_argument("--list-states", action="store_true", help="List valid India state names and exit.")
    ap.add_argument("--no-show", action="store_true",
                   help="Only save the PNGs; do not open interactive figure windows (they are shown by default).")
    args = ap.parse_args()
    mode = "absolute" if args.absolute else ("percent" if args.percent else args.mode)

    global SHOW
    SHOW = not args.no_show

    if args.list_states:
        list_states()
        return

    focus = build_focus(args.state) if args.state else None
    if focus:
        print(f"Focusing on: {', '.join(focus['names'])}")

    if mode == "hindcast":
        if args.season:
            print("  note: --season is ignored in hindcast mode (it plots all lead months).")
        run_hindcast(args, focus)
        return

    s5_path = args.seas5 or latest_seas5()
    sfs_path = args.sfs or latest_sfs()

    s5_clim = sfs_clim = None
    need_clim = mode in ("anomaly", "percent", "tercile") or args.skill_mask
    if need_clim:  # anomaly/tercile and the skill mask all need each model's hindcast
        ref = pd.Timestamp(np.atleast_1d(xr.open_dataset(s5_path)["forecast_reference_time"].values)[0])
        mm = ref.strftime("%m")
        s5_clim = args.seas5_clim or find_seas5_clim(mm)
        sfs_clim = args.sfs_clim or find_sfs_clim(mm)
        if not s5_clim:
            sys.exit("Need a SEAS5 hindcast climatology (none found in data/seas5/).\n"
                     f"  python download_seas5.py --hindcast --month {int(mm)}")
        if not sfs_clim:
            sys.exit("Need an SFS reforecast climatology (none found in data/sfs/).\n"
                     f"  python download_sfs.py --reforecast --init-month {int(mm)}")

    print(f"SEAS5: {s5_path}")
    print(f"SFS  : {sfs_path}")
    if need_clim:
        print(f"  SEAS5 clim: {s5_clim}")
        print(f"  SFS   clim: {sfs_clim}")

    skill = None
    if args.skill_mask:
        obs_t, obs_p = find_obs("t"), find_obs("p")
        if not obs_t or not obs_p:
            sys.exit("Skill mask needs observation files in data/obs/.\n"
                     "  python download_obs.py")
        print(f"  obs: {obs_t}\n       {obs_p}")
        print(f"  computing hindcast skill (ACC), hatching cells < {args.skill_thresh} ...")
        skill = {
            "SEAS5": {"t": compute_skill("seas5", s5_clim, int(mm), "t", obs_t),
                      "p": compute_skill("seas5", s5_clim, int(mm), "p", obs_p)},
            "SFS Beta": {"t": compute_skill("sfs", sfs_clim, int(mm), "t", obs_t),
                         "p": compute_skill("sfs", sfs_clim, int(mm), "p", obs_p)},
        }

    if mode == "tercile":
        models = [seas5_raw(s5_path, s5_clim), sfs_raw(sfs_path, sfs_clim)]
        tag = models[0]["ref"].strftime("%Y%m")
        init = label_of(models[0]["ref"])
        n5, nsf = models[0]["nmem"], models[1]["nmem"]
        mtag = (f"Multi-model MME  -  SEAS5 ({n5}) + SFS Beta ({nsf})" if args.combine
                else f"SEAS5 ({n5}) vs SFS Beta ({nsf})")
        if args.combine and skill is not None:  # combine ACC on the full-lead models
            skill = combine_skill(skill, models)
        sslug = "_mme" if args.combine else ""
        if args.season:
            models = [collapse_to_season(m, args.season_months) for m in models]
            if skill is not None:
                lead_dims = ({"Multi-model": models[0]["lead_dim"]} if args.combine
                             else {m["name"]: m["lead_dim"] for m in models})
                skill = collapse_skill(skill, lead_dims, args.season_months)
            sslug += season_slug(models)
            print(f"  season: {models[0]['labels'][0]} (mean of {args.season_months} months after init)")
        tercile_figure(
            models, "t",
            title=f"2 m temperature: most-likely tercile  -  {mtag}  init {init}",
            cmaps=("Blues", "Greys", "Reds"), cat_labels=("below", "near", "above"),
            out=PLOTS_DIR / f"compare_{tag}_t2m_tercile{sslug}{focus_slug(focus)}.png",
            skill=skill, skill_thresh=args.skill_thresh, focus=focus,
            lead_suffix=not args.season, combine=args.combine,
        )
        tercile_figure(
            models, "p",
            title=f"Precipitation: most-likely tercile  -  {mtag}  init {init}",
            cmaps=("YlOrBr", "Greys", "Greens"), cat_labels=("dry", "near", "wet"),
            out=PLOTS_DIR / f"compare_{tag}_precip_tercile{sslug}{focus_slug(focus)}.png",
            skill=skill, skill_thresh=args.skill_thresh, focus=focus,
            lead_suffix=not args.season, combine=args.combine,
        )
        print("Done.")
        if SHOW:
            plt.show()
        return

    metric = "percent" if mode == "percent" else "anomaly"
    s5 = load_seas5(s5_path, s5_clim, metric)
    sfs = load_sfs(sfs_path, sfs_clim, metric)
    models = [s5, sfs]
    tag = s5["ref"].strftime("%Y%m")
    init = label_of(s5["ref"])
    n5, nsf = s5["nmem"], sfs["nmem"]
    mtag = (f"Multi-model MME  -  SEAS5 ({n5}) + SFS Beta ({nsf})" if args.combine
            else f"SEAS5 ({n5}) vs SFS Beta ({nsf})")

    if args.combine:
        if skill is not None:  # combine ACC before merging the model fields
            skill = combine_skill(skill, models)
        models = combine_loaded(models)

    sslug = "_mme" if args.combine else ""
    if args.season:
        models = [collapse_to_season(m, args.season_months) for m in models]
        if skill is not None:
            lead_dims = ({"Multi-model": models[0]["lead_dim"]} if args.combine
                         else {m["name"]: m["lead_dim"] for m in models})
            skill = collapse_skill(skill, lead_dims, args.season_months)
        sslug += season_slug(models)
        print(f"  season: {models[0]['labels'][0]} (mean of {args.season_months} months after init)")
    lead_suffix = not args.season

    if mode in ("anomaly", "percent"):
        comparison_figure(   # temperature is always an anomaly (percent-of-normal is not meaningful for T)
            models, "t",
            title=f"2 m temperature anomaly  -  {mtag}  init {init}  (vs hindcast clim)",
            units="degC anomaly", cmap="RdBu_r", symmetric=True,
            out=PLOTS_DIR / f"compare_{tag}_t2m_anom{sslug}{focus_slug(focus)}.png",
            skill=skill, skill_thresh=args.skill_thresh, focus=focus, lead_suffix=lead_suffix,
        )
        if mode == "percent":
            comparison_figure(
                models, "p",
                title=f"Precipitation, % of normal  -  {mtag}  init {init}  (vs hindcast clim)",
                units="% of normal", cmap="BrBG", center=100.0,
                out=PLOTS_DIR / f"compare_{tag}_precip_pctnormal{sslug}{focus_slug(focus)}.png",
                skill=skill, skill_thresh=args.skill_thresh, focus=focus, lead_suffix=lead_suffix,
            )
        else:
            comparison_figure(
                models, "p",
                title=f"Precipitation anomaly  -  {mtag}  init {init}  (vs hindcast clim)",
                units="mm/day anomaly", cmap="BrBG", symmetric=True,
                out=PLOTS_DIR / f"compare_{tag}_precip_anom{sslug}{focus_slug(focus)}.png",
                skill=skill, skill_thresh=args.skill_thresh, focus=focus, lead_suffix=lead_suffix,
            )
    else:  # absolute
        comparison_figure(
            models, "t",
            title=f"Ensemble-mean 2 m temperature  -  {mtag}  init {init}",
            units="degC", cmap="RdYlBu_r",
            out=PLOTS_DIR / f"compare_{tag}_t2m_ensmean{sslug}{focus_slug(focus)}.png",
            skill=skill, skill_thresh=args.skill_thresh, focus=focus, lead_suffix=lead_suffix,
        )
        comparison_figure(
            models, "p",
            title=f"Ensemble-mean precipitation  -  {mtag}  init {init}",
            units="mm/day", cmap="YlGnBu",
            out=PLOTS_DIR / f"compare_{tag}_precip_ensmean{sslug}{focus_slug(focus)}.png",
            skill=skill, skill_thresh=args.skill_thresh, focus=focus, lead_suffix=lead_suffix,
        )
    print("Done.")
    if SHOW:
        plt.show()


if __name__ == "__main__":
    main()
