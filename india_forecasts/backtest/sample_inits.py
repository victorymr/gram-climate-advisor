#!/usr/bin/env python3
"""
Choose the backtest initialization dates and write backtest/inits.csv.

Return-on-investment logic (see backtest/README.md): one download = one init =
every district x every lead-week x every ensemble member. So the scarce axis a
download can't buy is the *climate state* (year-to-year monsoon/ENSO condition)
and the season. We therefore spend the ~50-init budget spanning conditions, not
near-duplicate dates.

Window: GEFSv12's 31-member, 35-day operational archive on s3://noaa-gefs-pds
starts 2020-09-23, so the clean full-season window is 2021-2025 (five monsoons):
  2021  La Nina         monsoon ~99% LPA  (normal)
  2022  La Nina         monsoon ~106% LPA (above normal / surplus)
  2023  El Nino         monsoon ~94% LPA  (below normal / DEFICIT)   <- the dry contrast
  2024  La Nina (dev.)  monsoon ~108% LPA (above normal / surplus)   <- the wet contrast
  2025  neutral/weak    monsoon (near normal)
(ENSO/monsoon tags are documented context for stratifying the skill analysis, not truth.)

Per year we sample ~10 00Z inits: 2 pre-monsoon (heat + onset), 7 monsoon (JJAS,
~biweekly), 1 withdrawal. GEFS extended runs are daily, so exact days are free to
choose; we use the 1st and 15th (snapped) for a clean, reproducible cadence.
"""

import csv
import datetime as dt
from pathlib import Path

OUT = Path(__file__).resolve().parent / "inits.csv"

# ENSO / monsoon context per season (approximate, for stratified analysis only).
YEARS = {
    2021: ("la_nina", "normal"),
    2022: ("la_nina", "surplus"),
    2023: ("el_nino", "deficit"),
    2024: ("la_nina", "surplus"),
    2025: ("neutral", "normal"),
}

# (month, day, phase) sampled each year -- 5 slots (~25 inits total) at ~43 min/init.
# One pre-monsoon (heat/onset) + monthly monsoon coverage (early -> tail), so each of
# the 5 ENSO-diverse years contributes the full monsoon evolution without near-duplicates.
SLOTS = [
    (5, 15, "pre_monsoon"),   # heat / pre-onset
    (6, 15, "monsoon"),       # early monsoon
    (7, 15, "monsoon"),       # mid monsoon
    (8, 15, "monsoon"),       # late monsoon
    (9, 15, "monsoon"),       # monsoon tail / withdrawal onset
]


def rows():
    for year, (enso, monsoon) in YEARS.items():
        for mo, day, phase in SLOTS:
            d = dt.date(year, mo, day)
            yield {
                "init_date": d.isoformat(),
                "year": year,
                "month": mo,
                "phase": phase,
                "enso": enso,
                "monsoon_season_note": monsoon,
            }


def main():
    rs = list(rows())
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rs[0].keys()))
        w.writeheader()
        w.writerows(rs)
    # quick strata summary
    from collections import Counter
    print(f"wrote {len(rs)} inits -> {OUT}")
    print("by phase :", dict(Counter(r["phase"] for r in rs)))
    print("by enso  :", dict(Counter(r["enso"] for r in rs)))
    print("by year  :", dict(Counter(r["year"] for r in rs)))


if __name__ == "__main__":
    main()
