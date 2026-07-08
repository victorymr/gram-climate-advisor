#!/usr/bin/env python3
"""
Run the whole forecast pipeline and refresh the advisor's district_forecasts.json.

Orchestrates, in order (skipping a stage whose output already exists unless --force):

  [download]  download_gefs/cfsv2/ec46 --date <init>       subseasonal model pulls (--download)
   clim        build_era5_clim.py --date <init>            common ERA5 weekly climatology
   s2s         forecast_region_s2s.py                      weekly multi-model anomaly CSV
   seasonal    forecast_region.py per advisor district     seasonal tercile CSVs
   import      import_model_forecasts.py                   merge -> data/district_forecasts.json

The india_forecasts scripts run in their own directory; the bridge runs here. The
init date is auto-detected from the newest data/*/*_india_weekly.nc unless --init is given.

Usage (from anywhere):
    python scripts/run_forecast_pipeline.py                    # use existing model files
    python scripts/run_forecast_pipeline.py --init 2026-06-29
    python scripts/run_forecast_pipeline.py --download         # pull GEFS/CFSv2/EC46 first
    python scripts/run_forecast_pipeline.py --force            # rebuild clim + seasonal too
    python scripts/run_forecast_pipeline.py --skip-seasonal --no-backup

Notes:
  * Seasonal MODEL files (SEAS5/SFS) and the one-time hindcast climatologies are assumed
    present in india_forecasts/data/; --download only pulls the subseasonal models.
  * --python points at the interpreter for the india_forecasts (heavy) env if it differs
    from this one; the bridge always runs with this interpreter.
"""

import os
import re
import csv
import sys
import time
import glob
import argparse
import subprocess
from pathlib import Path

ADVISOR_ROOT = Path(__file__).resolve().parent.parent
FORECASTS_DIR = ADVISOR_ROOT / "india_forecasts"   # vendored forecast pipeline
PLOTS_DIR = FORECASTS_DIR / "plots"
CLIM_DIR = FORECASTS_DIR / "data" / "clim"
DISTRICTS_CSV = ADVISOR_ROOT / "data" / "district_coordinates.csv"
BRIDGE = ADVISOR_ROOT / "scripts" / "import_model_forecasts.py"

S2S_MODELS = {"gefs": "download_gefs.py", "cfsv2": "download_cfsv2.py", "ec46": "download_ec46.py"}


def _norm(s):
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def child_env():
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"   # sub-scripts print unicode; force utf-8 on Windows
    return env


def run(cmd, cwd, check=True):
    printable = " ".join(str(c) for c in cmd)
    print(f"\n$ {printable}\n  (cwd={cwd})", flush=True)
    r = subprocess.run([str(c) for c in cmd], cwd=str(cwd), env=child_env())
    if check and r.returncode != 0:
        raise SystemExit(f"[FATAL] stage failed (exit {r.returncode}): {printable}")
    return r.returncode


def detect_init():
    """Newest YYYYMMDD across the weekly model files, or None."""
    inits = []
    for sub in S2S_MODELS:
        for f in glob.glob(str(FORECASTS_DIR / "data" / sub / "*_india_weekly.nc")):
            m = re.search(r"_(\d{8})_india_weekly", os.path.basename(f))
            if m:
                inits.append(m.group(1))
    return max(inits) if inits else None


def load_districts():
    with open(DISTRICTS_CSV, newline="", encoding="utf-8") as fh:
        return [(r["state"], r["district"]) for r in csv.DictReader(fh)]


def seasonal_have():
    """(norm_state, norm_district) already covered by an existing seasonal CSV."""
    have = set()
    for p in PLOTS_DIR.glob("forecast_*.csv"):
        if p.name == "s2s_region_weekly.csv":
            continue
        try:
            with open(p, newline="", encoding="utf-8") as fh:
                row = next(csv.DictReader(fh), None)
        except OSError:
            continue
        region = (row or {}).get("region", "")
        if " district," in region:
            d, _, s = region.partition(" district,")
            have.add((_norm(s), _norm(d)))
    return have


def main():
    ap = argparse.ArgumentParser(description="Run the full forecast pipeline into the advisor.")
    ap.add_argument("--init", default=None, help="Init date YYYY-MM-DD or YYYYMMDD (default: newest weekly file).")
    ap.add_argument("--download", action="store_true", help="Pull GEFS/CFSv2/EC46 for the init first.")
    ap.add_argument("--no-members", action="store_true",
                    help="Skip the GEFS ensemble-member pull (weekly probability odds) during --download.")
    ap.add_argument("--force", action="store_true", help="Rebuild clim + seasonal even if outputs exist.")
    ap.add_argument("--skip-seasonal", action="store_true", help="Skip the seasonal per-district stage.")
    ap.add_argument("--no-backup", action="store_true", help="Pass through to the bridge (no .bak).")
    ap.add_argument("--python", default=sys.executable, help="Interpreter for india_forecasts scripts.")
    args = ap.parse_args()

    if not FORECASTS_DIR.exists():
        raise SystemExit(f"[FATAL] india_forecasts not found at {FORECASTS_DIR}")

    py_fc = args.python           # heavy env (india_forecasts)
    py_here = sys.executable      # light env (advisor / bridge)
    t0 = time.time()
    summary = []

    # ---- resolve init (YYYYMMDD + YYYY-MM-DD) --------------------------------
    raw = (args.init or "").replace("-", "")
    if args.download and not raw:
        raise SystemExit("[FATAL] --download needs an explicit --init (no files to infer from).")
    ymd = raw or detect_init()
    if not ymd:
        raise SystemExit("[FATAL] no weekly model files found and no --init given. "
                         "Run with --download --init YYYY-MM-DD, or place *_india_weekly.nc files.")
    dash = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
    print(f"=== Forecast pipeline - init {dash} ===")
    print(f"    india_forecasts: {FORECASTS_DIR}")
    print(f"    advisor JSON   : {ADVISOR_ROOT / 'data' / 'district_forecasts.json'}")

    # ---- [download] subseasonal models --------------------------------------
    if args.download:
        ok = []
        for sub, script in S2S_MODELS.items():
            rc = run([py_fc, script, "--date", dash], cwd=FORECASTS_DIR, check=False)
            (ok.append(sub) if rc == 0 else None)
            summary.append((f"download {sub}", "ok" if rc == 0 else "FAILED (continuing)"))
        # GEFS ensemble members -> weekly threshold probabilities
        if not args.no_members:
            rc = run([py_fc, "download_gefs.py", "--date", dash, "--members", "all"],
                     cwd=FORECASTS_DIR, check=False)
            summary.append(("download gefs members", "ok" if rc == 0 else "FAILED (odds unavailable)"))
        if not ok:
            print("[warn] all mean downloads failed; will use whatever weekly files exist.")
    else:
        summary.append(("download", "skipped (--download off)"))

    # ---- clim: ERA5 weekly climatology for this init ------------------------
    clim_out = CLIM_DIR / f"era5_weekly_init{ymd[4:8]}_india_weekly.nc"
    if clim_out.exists() and not args.force:
        print(f"\n[skip] clim exists: {clim_out.name}")
        summary.append(("clim", "skipped (exists)"))
    else:
        run([py_fc, "build_era5_clim.py", "--date", dash], cwd=FORECASTS_DIR)
        summary.append(("clim", "built"))

    # ---- s2s: weekly multi-model regional CSV (always) ----------------------
    run([py_fc, "forecast_region_s2s.py", "--init", ymd, "--districts", DISTRICTS_CSV],
        cwd=FORECASTS_DIR)
    summary.append(("s2s", "ok"))

    # ---- seasonal: tercile CSV per advisor district -------------------------
    if args.skip_seasonal:
        summary.append(("seasonal", "skipped (--skip-seasonal)"))
    else:
        have = set() if args.force else seasonal_have()
        districts = load_districts()
        done = 0
        for state, district in districts:
            if (_norm(state), _norm(district)) in have:
                print(f"[skip] seasonal exists: {district}, {state}")
                continue
            run([py_fc, "forecast_region.py", "--state", state, "--district", district, "--no-fig"],
                cwd=FORECASTS_DIR, check=False)
            done += 1
        summary.append(("seasonal", f"generated {done}, reused {len(districts) - done}"))

    # ---- import: merge into district_forecasts.json -------------------------
    bridge_cmd = [py_here, str(BRIDGE)]
    if args.no_backup:
        bridge_cmd.append("--no-backup")
    run(bridge_cmd, cwd=ADVISOR_ROOT)
    summary.append(("import", "ok"))

    # ---- summary ------------------------------------------------------------
    print("\n" + "=" * 56)
    print(f"Pipeline complete for init {dash} in {time.time() - t0:.0f}s")
    for stage, status in summary:
        print(f"  {stage:<16} {status}")
    print("=" * 56)
    print("Next: streamlit run app.py")


if __name__ == "__main__":
    main()
