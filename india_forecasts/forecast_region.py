#!/usr/bin/env python3
"""
Area-averaged seasonal forecast for a specific Indian STATE or DISTRICT.

For the chosen region this collapses the gridded SEAS5 and SFS Beta forecasts to
a single regional time series (cosine-latitude weighted over the grid cells inside
the region polygon) and reports, per lead month:

  * the ensemble-mean ANOMALY  (vs each model's hindcast climatology), and
  * TERCILE PROBABILITIES       P(below / near / above normal), the actual
    probabilistic forecast, with the most-likely category, and
  * the regional hindcast SKILL (anomaly correlation, if obs are present) as a
    confidence caveat.

Region polygons come from GADM v4.1 (level 2 = districts; NAME_1 = state).
June inits only, matching the rest of the project.

Outputs: a printed outlook, a CSV in plots/, and a tercile-probability figure.

Usage:
    python forecast_region.py --state Maharashtra
    python forecast_region.py --district Pune                 # state inferred if unique
    python forecast_region.py --state "Tamil Nadu" --district Chennai
    python forecast_region.py --list-districts "Tamil Nadu"
"""

import sys
import csv
import argparse
import urllib.request

import numpy as np
import pandas as pd
import xarray as xr
import matplotlib.pyplot as plt
import geopandas as gpd

from config import GEO_DIR, GADM_IND_L2_URL
from plot_seas5 import (
    PLOTS_DIR, M_S_TO_MMDAY, KG_M2_S_TO_MMDAY,
    latest_seas5, latest_sfs, find_seas5_clim, find_sfs_clim, find_obs,
    seas5_raw, sfs_raw, label_of, compute_skill,
)

# tercile category names per variable (index 0=below, 1=near, 2=above)
CATS = {"t": ("cooler", "near-normal", "warmer"),
        "p": ("drier", "near-normal", "wetter")}
PRECIP_FACTOR = {"SEAS5": M_S_TO_MMDAY, "SFS Beta": KG_M2_S_TO_MMDAY}


def _norm(s):
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def _slug(s):
    return "_".join("".join(ch for ch in w.lower() if ch.isalnum())
                    for w in str(s).replace(",", " ").split())


def gadm_districts():
    """Load GADM India level-2 (districts), caching the download locally."""
    local = GEO_DIR / "gadm41_IND_2.json.zip"
    if not local.exists():
        print(f"Downloading GADM India districts -> {local} (one-time) ...")
        urllib.request.urlretrieve(GADM_IND_L2_URL, local)
    return gpd.read_file(local)


def list_districts(state):
    g = gadm_districts()
    sel = g[g["NAME_1"].map(_norm) == _norm(state)]
    if sel.empty:
        sys.exit(f"No state matched '{state}'. States: {sorted(g['NAME_1'].unique())}")
    print(f"Districts in {sel['NAME_1'].iloc[0]}:")
    for d in sorted(sel["NAME_2"].unique()):
        print(f"  {d}")


def resolve_region(state, district):
    """Return (geometry, label, slug) for the requested state/district."""
    g = gadm_districts()
    if district:
        sel = g[g["NAME_2"].map(_norm) == _norm(district)]
        if state:
            sel = sel[sel["NAME_1"].map(_norm) == _norm(state)]
        if sel.empty:
            hint = g[g["NAME_2"].str.contains(district, case=False, na=False)]["NAME_2"].unique()
            sys.exit(f"No district matched '{district}'"
                     + (f" in {state}" if state else "")
                     + (f". Did you mean: {list(hint)}?" if len(hint) else ". Try --list-districts STATE."))
        states = sorted(sel["NAME_1"].unique())
        if len(states) > 1:
            sys.exit(f"District '{district}' exists in multiple states {states}; add --state.")
        label = f"{sel['NAME_2'].iloc[0]} district, {states[0]}"
    elif state:
        sel = g[g["NAME_1"].map(_norm) == _norm(state)]
        if sel.empty:
            sys.exit(f"No state matched '{state}'. Run with --list-districts or check the name.")
        label = sel["NAME_1"].iloc[0]
    else:
        sys.exit("Specify --state and/or --district.")
    geom = sel.geometry.union_all() if hasattr(sel.geometry, "union_all") else sel.geometry.unary_union
    return geom, label, _slug(label)


def region_weights(latvals, lonvals, latn, lonn, geom):
    """cos(lat) weights over grid cells whose centre lies in geom; if none (region
    smaller than a grid cell), fall back to the single nearest cell. Returns
    (weights DataArray, n_cells, used_fallback)."""
    from shapely.geometry import Point
    from shapely.prepared import prep
    pg = prep(geom)
    inside = np.array([[pg.contains(Point(float(x), float(y))) for x in lonvals]
                       for y in latvals])
    fallback = False
    if not inside.any():
        c = geom.centroid
        i = int(np.argmin(np.abs(latvals - c.y)))
        j = int(np.argmin(np.abs(lonvals - c.x)))
        inside[i, j] = True
        fallback = True
    w = np.cos(np.deg2rad(latvals))[:, None] * inside
    weights = xr.DataArray(w, coords={latn: latvals, lonn: lonvals}, dims=(latn, lonn))
    return weights, int(inside.sum()), fallback


def regional_forecast(m, var, weights):
    """Collapse model m's var to a regional series and return per-lead dict with
    anomaly, tercile probabilities, category index, and valid-month labels."""
    latn, lonn = m["lat"], m["lon"]
    fc = m["fc"][var]
    clim = m["clim"][var].reindex({latn: fc[latn], lonn: fc[lonn]}, method="nearest")
    w = weights.fillna(0.0)

    fc_s = fc.weighted(w).mean((latn, lonn))      # (member, lead)
    clim_s = clim.weighted(w).mean((latn, lonn))  # (pool..., lead)

    q33 = clim_s.quantile(1 / 3, dim=m["pool"]).drop_vars("quantile")
    q67 = clim_s.quantile(2 / 3, dim=m["pool"]).drop_vars("quantile")
    below = (fc_s < q33).mean(m["member_dim"])
    above = (fc_s > q67).mean(m["member_dim"])
    near = 1.0 - below - above
    anom = fc_s.mean(m["member_dim"]) - clim_s.mean(m["pool"])
    if var == "p":
        anom = anom * PRECIP_FACTOR[m["name"]]

    probs = np.stack([below.values, near.values, above.values], axis=0)  # (3, lead)
    return {
        "labels": m["labels"],
        "anom": anom.values,
        "probs": probs,
        "cat": probs.argmax(axis=0),
    }


def regional_skill(kind, clim_path, init_month, var, obs_path, weights):
    """Area-averaged anomaly correlation per lead (or None if it can't be computed)."""
    try:
        acc = compute_skill(kind, clim_path, init_month, var, obs_path)  # (lead, lat, lon)
        latn, lonn = acc.dims[-2], acc.dims[-1]
        w = weights.rename({weights.dims[0]: latn, weights.dims[1]: lonn})
        w = w.reindex({latn: acc[latn], lonn: acc[lonn]}, method="nearest").fillna(0.0)
        return acc.weighted(w).mean((latn, lonn)).values
    except Exception as e:
        print(f"  (skill unavailable for {kind}/{var}: {e})")
        return None


def print_outlook(label, results):
    """results: {var: {model_name: {fc dict, 'skill': arr|None, 'nmem': int}}}"""
    vname = {"t": "TEMPERATURE (2 m)", "p": "PRECIPITATION"}
    unit = {"t": "degC", "p": "mm/day"}
    for var in ("t", "p"):
        print(f"\n{vname[var]} outlook  -  {label}")
        lo, mid, hi = CATS[var]
        for model, r in results[var].items():
            fc = r["fc"]
            print(f"  {model} ({r['nmem']} members):")
            for k, lab in enumerate(fc["labels"]):
                b, n, a = (fc["probs"][:, k] * 100)
                cat = (lo, mid, hi)[fc["cat"][k]]
                sk = "" if r["skill"] is None else f" | skill ACC {r['skill'][k]:+.2f}"
                print(f"    {lab} (+{k}): anom {fc['anom'][k]:+5.2f} {unit[var]}"
                      f" | {lo} {b:2.0f}% / {mid} {n:2.0f}% / {hi} {a:2.0f}%"
                      f"  -> {cat.upper()}{sk}")


def write_csv(label, slug, results):
    out = PLOTS_DIR / f"forecast_{slug}.csv"
    with open(out, "w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["region", "variable", "model", "lead", "valid_month", "units",
                     "anomaly", "p_below", "p_near", "p_above", "category", "acc"])
        for var in ("t", "p"):
            unit = "degC" if var == "t" else "mm/day"
            for model, r in results[var].items():
                fc = r["fc"]
                for k, lab in enumerate(fc["labels"]):
                    b, n, a = fc["probs"][:, k]
                    wr.writerow([label, var, model, k, lab, unit,
                                 f"{fc['anom'][k]:.3f}", f"{b:.3f}", f"{n:.3f}", f"{a:.3f}",
                                 CATS[var][fc["cat"][k]],
                                 "" if r["skill"] is None else f"{r['skill'][k]:.3f}"])
    print(f"\n  saved -> {out}")


def make_figure(label, slug, results):
    models = list(results["t"].keys())
    nrow, ncol = 2, len(models)
    fig, axes = plt.subplots(nrow, ncol, figsize=(5.2 * ncol, 6.4), squeeze=False,
                             constrained_layout=True)
    colors = {"t": ("#2c7bb6", "#cccccc", "#d7191c"),    # cool / near / warm
              "p": ("#a6611a", "#cccccc", "#1a9641")}     # dry / near / wet
    for ci, model in enumerate(models):
        for ri, var in enumerate(("t", "p")):
            ax = axes[ri][ci]
            fc = results[var][model]["fc"]
            labs = [l.replace(" ", "\n") for l in fc["labels"]]
            x = np.arange(len(labs))
            b, n, a = fc["probs"] * 100
            lo, mid, hi = CATS[var]
            cl, cn, ch = colors[var]
            ax.bar(x, b, color=cl, label=lo)
            ax.bar(x, n, bottom=b, color=cn, label=mid)
            ax.bar(x, a, bottom=b + n, color=ch, label=hi)
            ax.axhline(33.3, color="k", lw=0.6, ls="--", alpha=0.6)
            ax.set_ylim(0, 100)
            ax.set_xticks(x)
            ax.set_xticklabels(labs, fontsize=8)
            ax.set_ylabel("probability (%)")
            ax.set_title(f"{model} — {'temperature' if var=='t' else 'precipitation'}", fontsize=10)
            ax.legend(fontsize=7, ncol=3, loc="upper center", framealpha=0.8)
    fig.suptitle(f"Tercile probability outlook  —  {label}", fontsize=13, fontweight="bold")
    out = PLOTS_DIR / f"forecast_{slug}.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved -> {out}")


def _geom_for(gadm, state, district):
    """District polygon by normalized (state, district) name, or None."""
    sel = gadm[gadm["NAME_2"].map(_norm) == _norm(district)]
    s2 = sel[sel["NAME_1"].map(_norm) == _norm(state)]
    sel = s2 if not s2.empty else sel
    if sel.empty:
        return None
    return sel.geometry.union_all() if hasattr(sel.geometry, "union_all") else sel.geometry.unary_union


def _weight_skill(acc, weights):
    """Region-weight a precomputed ACC map (avoids recomputing the map per district)."""
    if acc is None:
        return None
    latn, lonn = acc.dims[-2], acc.dims[-1]
    w = weights.rename({weights.dims[0]: latn, weights.dims[1]: lonn})
    w = w.reindex({latn: acc[latn], lonn: acc[lonn]}, method="nearest").fillna(0.0)
    return acc.weighted(w).mean((latn, lonn)).values


def run_batch(districts_csv, out_path):
    """Seasonal tercile forecast for EVERY district in districts_csv -> one combined CSV.
    Models and the (district-independent) skill maps are computed once; only the
    region-weighting varies per district, so 600+ districts stay fast."""
    s5_path, sfs_path = latest_seas5(), latest_sfs()
    ref = pd.Timestamp(np.atleast_1d(xr.open_dataset(s5_path)["forecast_reference_time"].values)[0])
    mm = ref.strftime("%m")
    s5_clim, sfs_clim = find_seas5_clim(mm), find_sfs_clim(mm)
    if not s5_clim or not sfs_clim:
        sys.exit("Need both hindcast climatologies (June init):\n"
                 "  python download_seas5.py --hindcast --month 6\n"
                 "  python download_sfs.py --reforecast --init-month 6")
    obs = {"t": find_obs("t"), "p": find_obs("p")}
    models = [seas5_raw(s5_path, s5_clim), sfs_raw(sfs_path, sfs_clim)]
    clim_of = {"SEAS5": s5_clim, "SFS Beta": sfs_clim}
    kind_of = {"SEAS5": "seas5", "SFS Beta": "sfs"}

    skill_maps = {}                                    # (model, var) -> ACC map (computed once)
    for m in models:
        for var in ("t", "p"):
            try:
                skill_maps[(m["name"], var)] = (compute_skill(kind_of[m["name"]], clim_of[m["name"]],
                                                              int(mm), var, obs[var]) if obs[var] else None)
            except Exception as e:
                print(f"  (skill unavailable {m['name']}/{var}: {e})")
                skill_maps[(m["name"], var)] = None

    gadm = gadm_districts()
    districts = pd.read_csv(districts_csv)
    print(f"Seasonal batch (vectorized): {len(districts)} districts, init {label_of(ref)}")

    rows, skipped_names = [], set()
    for m in models:
        latn, lonn, pool, memb = m["lat"], m["lon"], m["pool"], m["member_dim"]
        latvals = m["fc"]["t"][latn].values
        lonvals = m["fc"]["t"][lonn].values

        # district x (lat,lon) NORMALISED weight tensor, built once per model.
        # Collapsing every district then becomes a single xr.dot instead of a 600x loop.
        Wnp = np.zeros((len(districts), latvals.size, lonvals.size))
        valid = []
        for i, (_, d) in enumerate(districts.iterrows()):
            geom = _geom_for(gadm, d["state"], d["district"])
            if geom is None:
                skipped_names.add((d["state"], d["district"]))
                continue
            w, _, _ = region_weights(latvals, lonvals, latn, lonn, geom)
            wv = np.nan_to_num(w.values, nan=0.0)
            tot = wv.sum()
            if tot > 0:
                Wnp[i] = wv / tot            # normalised -> xr.dot gives the weighted mean
                valid.append(i)
        W = xr.DataArray(Wnp, dims=("d", latn, lonn), coords={latn: latvals, lonn: lonvals})

        for var in ("t", "p"):
            fc = m["fc"][var]
            clim = m["clim"][var].reindex({latn: latvals, lonn: lonvals}, method="nearest")
            lead_dim = next(dd for dd in fc.dims if dd not in (memb, latn, lonn))

            fc_c = xr.dot(W, fc, dims=[latn, lonn])        # (d, member, lead)
            clim_c = xr.dot(W, clim, dims=[latn, lonn])    # (d, pool..., lead)
            q33 = clim_c.quantile(1 / 3, dim=pool).drop_vars("quantile")
            q67 = clim_c.quantile(2 / 3, dim=pool).drop_vars("quantile")
            below = (fc_c < q33).mean(memb).transpose("d", lead_dim)
            above = (fc_c > q67).mean(memb).transpose("d", lead_dim)
            near = (1.0 - below - above)
            anom = (fc_c.mean(memb) - clim_c.mean(pool)).transpose("d", lead_dim)
            if var == "p":
                anom = anom * PRECIP_FACTOR[m["name"]]

            acc_v = None
            acc = skill_maps[(m["name"], var)]
            if acc is not None:
                la, lo = acc.dims[-2], acc.dims[-1]
                Wa = W.rename({latn: la, lonn: lo}).reindex({la: acc[la], lo: acc[lo]}, method="nearest").fillna(0.0)
                Wa = Wa / Wa.sum([la, lo])                 # renormalise on the obs grid
                acc_v = xr.dot(Wa, acc, dims=[la, lo]).transpose("d", acc.dims[0]).values

            bv, nv, av, anv = below.values, near.values, above.values, anom.values
            unit = "degC" if var == "t" else "mm/day"
            for i in valid:
                d = districts.iloc[i]
                for k, lab in enumerate(m["labels"]):
                    b, n, a = bv[i, k], nv[i, k], av[i, k]
                    cat = CATS[var][int(np.argmax([b, n, a]))]
                    rows.append({"state": d["state"], "district": d["district"], "variable": var,
                                 "model": m["name"], "lead": k, "valid_month": lab, "units": unit,
                                 "anomaly": round(float(anv[i, k]), 3),
                                 "p_below": round(float(b), 3), "p_near": round(float(n), 3),
                                 "p_above": round(float(a), 3), "category": cat,
                                 "acc": "" if acc_v is None else round(float(acc_v[i, k]), 3)})
    skipped = len(skipped_names)
    fields = ["state", "district", "variable", "model", "lead", "valid_month", "units",
              "anomaly", "p_below", "p_near", "p_above", "category", "acc"]
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=fields)
        wr.writeheader()
        wr.writerows(rows)
    print(f"saved -> {out_path}  ({len(rows)} rows, {len(districts) - skipped} districts, {skipped} skipped)")


def main():
    ap = argparse.ArgumentParser(description="Area-averaged tercile forecast for an Indian state/district.")
    ap.add_argument("--state", default=None, help="State name, e.g. Maharashtra or 'Tamil Nadu'.")
    ap.add_argument("--district", default=None, help="District name, e.g. Pune.")
    ap.add_argument("--districts", default=None,
                    help="CSV of state,district — batch every district into one combined seasonal CSV.")
    ap.add_argument("--out", default=str(PLOTS_DIR / "seasonal_region.csv"), help="Batch output CSV path.")
    ap.add_argument("--list-districts", metavar="STATE", default=None, help="List districts in a state and exit.")
    ap.add_argument("--no-fig", action="store_true", help="Skip the figure (text + CSV only).")
    args = ap.parse_args()

    if args.list_districts:
        list_districts(args.list_districts)
        return

    if args.districts:
        run_batch(args.districts, args.out)
        return

    geom, label, slug = resolve_region(args.state, args.district)

    s5_path, sfs_path = latest_seas5(), latest_sfs()
    ref = pd.Timestamp(np.atleast_1d(xr.open_dataset(s5_path)["forecast_reference_time"].values)[0])
    mm = ref.strftime("%m")
    s5_clim, sfs_clim = find_seas5_clim(mm), find_sfs_clim(mm)
    if not s5_clim or not sfs_clim:
        sys.exit("Need both hindcast climatologies (June init).\n"
                 "  python download_seas5.py --hindcast --month 6\n"
                 "  python download_sfs.py --reforecast --init-month 6")
    obs_t, obs_p = find_obs("t"), find_obs("p")  # optional (skill caveat)

    models = [seas5_raw(s5_path, s5_clim), sfs_raw(sfs_path, sfs_clim)]
    print(f"Region: {label}   init {label_of(ref)}")

    results = {"t": {}, "p": {}}
    for m in models:
        fcgrid = m["fc"]["t"]
        weights, ncell, fb = region_weights(fcgrid[m["lat"]].values, fcgrid[m["lon"]].values,
                                            m["lat"], m["lon"], geom)
        note = "  [nearest-cell fallback: region smaller than grid]" if fb else ""
        print(f"  {m['name']}: {ncell} grid cell(s) in region{note}")
        kind = "seas5" if m["name"] == "SEAS5" else "sfs"
        clim_path = s5_clim if kind == "seas5" else sfs_clim
        for var in ("t", "p"):
            obs = obs_t if var == "t" else obs_p
            results[var][m["name"]] = {
                "fc": regional_forecast(m, var, weights),
                "skill": regional_skill(kind, clim_path, int(mm), var, obs, weights) if obs else None,
                "nmem": m["nmem"],
            }

    print_outlook(label, results)
    write_csv(label, slug, results)
    if not args.no_fig:
        make_figure(label, slug, results)
    print("Done.")


if __name__ == "__main__":
    main()
