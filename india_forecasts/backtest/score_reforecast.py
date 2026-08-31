#!/usr/bin/env python3
"""
Score the GEFSv12 reforecast backtest (2000-2019, 220 inits, 11 members).

Joins the collapsed reforecast (collapsed_refc/<init>.nc, RAW district weekly values
from collapse_reforecast.py) with the IMD truth (truth/<init>.nc via build_truth.py
--inits reforecast_inits.csv) and scores with the same metrics stack as the
operational backtest.

Model anomalies are vs a LEAVE-ONE-YEAR-OUT reforecast climatology: for each init
(year y, day-of-year d), the climatology is the mean of the ensemble-mean values over
every other year's init within +-10 days of d (the same biweekly slot, 19 samples) --
the reforecast analogue of the operational backtest's "own climatology" reference,
with the target year excluded so the skill estimate is not contaminated. Truth
anomalies are vs the IMD 1991-2020 day-of-year normal, as everywhere else.

Outputs (scores/): refc_deterministic.csv, refc_probabilistic.csv, refc_reliability.csv,
refc_rank_histogram.csv, refc_deterministic_by_zone.csv, refc_deterministic_by_enso.csv.
`load_pairs_refc()` is imported by build_skill.py to pool these samples with the
operational 2021-25 backtest when fitting the app's confidence tiers.

    python backtest/score_reforecast.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

HERE = Path(__file__).resolve().parent
FC = HERE.parent
sys.path.insert(0, str(FC)); sys.path.insert(0, str(HERE))
import metrics                                                  # noqa: E402
from metrics import EVENTS, crps_ensemble, _event_mask          # noqa: E402

COLL = HERE / "collapsed_refc"
TRUTH = HERE / "truth"
SCORES = HERE / "scores"
INITS_CSV = HERE / "reforecast_inits.csv"
DOY_WINDOW = 10          # +-days for the LOO climatology (catches the same biweekly slot)
VAR_MAP = {"precip": "refc_precip", "t2m": "refc_t2m"}


def _stack():
    """All collapsed inits as (init, district, member, week) arrays + init doy/year."""
    files = sorted(COLL.glob("*.nc"))
    dss = [xr.load_dataset(f) for f in files]
    inits = [d.attrs["init"] for d in dss]
    ix = pd.Index(inits, name="init")
    data = {v: xr.concat([d[nc] for d in dss], dim=ix) for v, nc in VAR_MAP.items()}
    doy = np.array([int(d.attrs["doy"]) for d in dss])
    year = np.array([int(i[:4]) for i in inits])
    meta = dss[0]
    return inits, data, doy, year, meta


def loo_anomalies(data, doy, year):
    """Member anomalies vs the leave-one-year-out same-slot climatology, per variable."""
    anoms = {}
    for v, da in data.items():
        M = da.mean("member")                                   # (init, district, week)
        clims = []
        for i in range(da.sizes["init"]):
            mask = (year != year[i]) & (np.abs(doy - doy[i]) <= DOY_WINDOW)
            if mask.sum() < 5:
                raise RuntimeError(f"init {i}: only {mask.sum()} climatology samples")
            clims.append(M.isel(init=np.where(mask)[0]).mean("init"))
        clim = xr.concat(clims, dim=da["init"])
        anoms[v] = da - clim                                    # broadcast over member
    return anoms


def load_pairs_refc():
    """Tidy per (init, district, week, variable) frame, schema-compatible with
    metrics.load_pairs (gefs = 11-member ensemble-mean anomaly; cfsv2/mme absent)."""
    inits, data, doy, year, meta = _stack()
    print(f"reforecast pairs: {len(inits)} inits x {data['precip'].sizes['district']} districts")
    anoms = loo_anomalies(data, doy, year)
    state = np.asarray(meta["state"].values)
    dist = np.asarray(meta["district_name"].values)
    frames = []
    for k, init in enumerate(inits):
        tpath = TRUTH / f"{init}.nc"
        if not tpath.exists():
            continue
        tr = xr.load_dataset(tpath)
        for var in ("precip", "t2m"):
            oname = f"obs_{var}_anom"
            if oname not in tr:
                continue
            A = anoms[var].isel(init=k)                          # (district, member, week)
            weeks = [w for w in A["week"].values if w in tr["week"].values]
            A = A.sel(week=weeks)
            O = tr[oname].sel(week=weeks)
            G = A.transpose("district", "member", "week").values
            Ov = O.transpose("district", "week").values
            D, M, W = G.shape
            n = D * W
            Gf = G.transpose(0, 2, 1).reshape(n, M)
            Of = Ov.reshape(n)
            ok = np.isfinite(Of) & np.isfinite(Gf).all(axis=1)
            if not ok.any():
                continue
            Gf, Of = Gf[ok], Of[ok]
            d_idx = np.repeat(np.arange(D), W)[ok]
            w_idx = np.tile(np.asarray(weeks), D)[ok]
            df = pd.DataFrame({
                "init": init, "variable": var,
                "state": state[d_idx], "district": dist[d_idx], "week": w_idx.astype(int),
                "gefs": np.nanmean(Gf, axis=1), "cfsv2": np.nan, "obs": Of,
            })
            df["mme"] = np.nan
            df["crps"] = crps_ensemble(Gf, Of)
            df["crps_clim"] = np.abs(Of)
            df["rank"] = (Gf < Of[:, None]).sum(axis=1)
            df["n_members"] = M
            for name, evar, cmp, lvl in EVENTS:
                if evar != var:
                    continue
                df[f"p_{name}"] = _event_mask(Gf, cmp, lvl).mean(axis=1)
                df[f"y_{name}"] = _event_mask(Of, cmp, lvl).astype(float)
            frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df["year"] = df["init"].str[:4].astype(int)
    tags = pd.read_csv(INITS_CSV)
    tags["init"] = tags["init_date"].str.replace("-", "", regex=False)
    df = df.merge(tags[["init", "phase", "enso", "monsoon_season_note"]], on="init", how="left")
    coords = pd.read_csv(FC.parent / "data" / "district_coordinates.csv")
    if "region" in coords.columns:
        df = df.merge(coords[["state", "district", "region"]].rename(columns={"region": "zone"}),
                      on=["state", "district"], how="left")
    return df


def main():
    df = load_pairs_refc()
    print(f"scoring {len(df):,} samples from {df['init'].nunique()} inits, "
          f"enso mix: {df.groupby('enso')['init'].nunique().to_dict()}")
    det = metrics.det_scores(df, ["week", "variable"])
    prob = metrics.prob_scores(df, ["week", "variable"])
    det.to_csv(SCORES / "refc_deterministic.csv", index=False)
    prob.to_csv(SCORES / "refc_probabilistic.csv", index=False)
    metrics.reliability(df).to_csv(SCORES / "refc_reliability.csv", index=False)
    metrics.rank_histogram(df).to_csv(SCORES / "refc_rank_histogram.csv", index=False)
    metrics.det_scores(df, ["week", "variable", "zone"]).to_csv(
        SCORES / "refc_deterministic_by_zone.csv", index=False)
    metrics.det_scores(df, ["week", "variable", "enso"]).to_csv(
        SCORES / "refc_deterministic_by_enso.csv", index=False)

    with pd.option_context("display.width", 200, "display.max_columns", 40):
        print("\n=== Reforecast deterministic skill (11-member ens mean, LOO own-clim) ===")
        print(det[det.model == "gefs"].round(3).to_string(index=False))
        op = pd.read_csv(SCORES / "deterministic.csv")
        cmpdf = det[det.model == "gefs"][["week", "variable", "acc"]].rename(columns={"acc": "acc_refc_2000_19"}) \
            .merge(op[op.model == "gefs"][["week", "variable", "acc"]].rename(columns={"acc": "acc_op_2021_25"}),
                   on=["week", "variable"])
        print("\n=== ACC: reforecast vs operational backtest ===")
        print(cmpdf.round(3).to_string(index=False))
        print("\n=== ACC by ENSO (precip) ===")
        be = pd.read_csv(SCORES / "refc_deterministic_by_enso.csv")
        print(be[(be.model == "gefs") & (be.variable == "precip")]
              .pivot_table(index="week", columns="enso", values="acc").round(3).to_string())
    print(f"\nwrote -> {SCORES}/refc_*.csv")


if __name__ == "__main__":
    main()
