#!/usr/bin/env python3
"""
Build the full India district master list from GADM v4.1 level-2 (676 districts).

Writes, for every district:
  data/district_metadata.csv     -> state,district                       (display names)
  data/district_coordinates.csv  -> state,district,latitude,longitude,region

GADM stores single-token names ("AndhraPradesh", "EastGodavari"); we prettify states via a
curated map (correct for the "and"/"of" cases) and camelCase-split district names. The five
pilot states prettify to exactly their existing names ("Uttar Pradesh", "Andhra Pradesh", …),
so the 10 pilots' curated forecast/ICAR data keeps resolving by (state, district).

Usage (from the advisor project root, heavy/global Python with geopandas):
    python scripts/build_district_list.py
    python scripts/build_district_list.py --gadm <path_or_url>
"""

import re
import csv
import argparse
import urllib.request
from pathlib import Path

import geopandas as gpd

ADVISOR_ROOT = Path(__file__).resolve().parent.parent
DATA = ADVISOR_ROOT / "data"
GADM_LOCAL = ADVISOR_ROOT / "india_forecasts" / "data" / "geo" / "gadm41_IND_2.json.zip"
GADM_URL = "https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_IND_2.json.zip"

# GADM NAME_1 -> (display state, region/zone). Zones match the pilots' existing region labels.
STATES = {
    "AndamanandNicobar": ("Andaman and Nicobar", "Islands"),
    "AndhraPradesh": ("Andhra Pradesh", "South India"),
    "ArunachalPradesh": ("Arunachal Pradesh", "Northeast India"),
    "Assam": ("Assam", "Northeast India"),
    "Bihar": ("Bihar", "East India"),
    "Chandigarh": ("Chandigarh", "North India"),
    "Chhattisgarh": ("Chhattisgarh", "Central India"),
    "DadraandNagarHaveli": ("Dadra and Nagar Haveli", "West India"),
    "DamanandDiu": ("Daman and Diu", "West India"),
    "Goa": ("Goa", "West India"),
    "Gujarat": ("Gujarat", "West India"),
    "Haryana": ("Haryana", "North India"),
    "HimachalPradesh": ("Himachal Pradesh", "North India"),
    "JammuandKashmir": ("Jammu and Kashmir", "North India"),
    "Jharkhand": ("Jharkhand", "East India"),
    "Karnataka": ("Karnataka", "South India"),
    "Kerala": ("Kerala", "South India"),
    "Lakshadweep": ("Lakshadweep", "Islands"),
    "MadhyaPradesh": ("Madhya Pradesh", "Central India"),
    "Maharashtra": ("Maharashtra", "Central India"),
    "Manipur": ("Manipur", "Northeast India"),
    "Meghalaya": ("Meghalaya", "Northeast India"),
    "Mizoram": ("Mizoram", "Northeast India"),
    "NCTofDelhi": ("Delhi", "North India"),
    "Nagaland": ("Nagaland", "Northeast India"),
    "Odisha": ("Odisha", "East India"),
    "Puducherry": ("Puducherry", "South India"),
    "Punjab": ("Punjab", "North India"),
    "Rajasthan": ("Rajasthan", "North-West India"),
    "Sikkim": ("Sikkim", "Northeast India"),
    "TamilNadu": ("Tamil Nadu", "South India"),
    "Telangana": ("Telangana", "South India"),
    "Tripura": ("Tripura", "Northeast India"),
    "UttarPradesh": ("Uttar Pradesh", "North India"),
    "Uttarakhand": ("Uttarakhand", "North India"),
    "WestBengal": ("West Bengal", "East India"),
}


def prettify_district(name):
    """camelCase -> spaced ('EastGodavari' -> 'East Godavari'); tidy joined 'and'/'&'."""
    s = str(name).replace("&", " and ")
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)
    s = re.sub(r"\b([A-Z][a-z]+)and\b", r"\1 and", s)   # 'Dadraand' -> 'Dadra and'
    return re.sub(r"\s+", " ", s).strip()


def load_gadm(src):
    if src:
        return gpd.read_file(src)
    if not GADM_LOCAL.exists():
        GADM_LOCAL.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading GADM -> {GADM_LOCAL} (one-time) ...")
        urllib.request.urlretrieve(GADM_URL, GADM_LOCAL)
    return gpd.read_file(GADM_LOCAL)


def main():
    ap = argparse.ArgumentParser(description="Build the India district master list from GADM.")
    ap.add_argument("--gadm", default=None, help="GADM level-2 file/URL (default: vendored zip).")
    args = ap.parse_args()

    g = load_gadm(args.gadm)
    # GADM splits some Himalayan/border districts into several features with the same
    # (NAME_1, NAME_2) — dissolve so each district is one polygon / one row.
    g = g.dissolve(by=["NAME_1", "NAME_2"], as_index=False)
    rows = []
    unknown = set()
    for _, r in g.iterrows():
        s1 = r["NAME_1"]
        state, region = STATES.get(s1, (prettify_district(s1), "India"))
        if s1 not in STATES:
            unknown.add(s1)
        district = prettify_district(r["NAME_2"])
        pt = r.geometry.representative_point()   # guaranteed inside the polygon
        rows.append({"state": state, "district": district,
                     "latitude": round(float(pt.y), 4), "longitude": round(float(pt.x), 4),
                     "region": region})

    rows.sort(key=lambda x: (x["state"], x["district"]))

    with open(DATA / "district_metadata.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["state", "district"])
        for r in rows:
            w.writerow([r["state"], r["district"]])

    with open(DATA / "district_coordinates.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["state", "district", "latitude", "longitude", "region"])
        w.writeheader(); w.writerows(rows)

    # simplified district polygons for the app's clickable map (kept small so the app
    # renders them fast and needs no geo dependency — just reads this GeoJSON).
    g2 = g.copy()
    g2["state"] = g2["NAME_1"].map(lambda s: STATES.get(s, (prettify_district(s), "India"))[0])
    g2["district"] = g2["NAME_2"].map(prettify_district)
    g2["geometry"] = g2.geometry.simplify(0.02, preserve_topology=True)
    geojson = DATA / "districts.geojson"
    if geojson.exists():
        geojson.unlink()
    g2[["state", "district", "geometry"]].to_file(geojson, driver="GeoJSON")

    print(f"[OK] {len(rows)} districts across {len({r['state'] for r in rows})} states/UTs")
    print(f"     -> {DATA/'district_metadata.csv'}")
    print(f"     -> {DATA/'district_coordinates.csv'}")
    print(f"     -> {geojson}  ({geojson.stat().st_size // 1024} KB)")
    if unknown:
        print(f"[warn] GADM states not in the display map (used fallback): {sorted(unknown)}")
    # sanity: pilots still present with matching keys
    pilots = {("Bihar", "Gaya"), ("Uttar Pradesh", "Varanasi"), ("Andhra Pradesh", "Anantapur"),
              ("Maharashtra", "Nagpur"), ("Rajasthan", "Jaipur")}
    have = {(r["state"], r["district"]) for r in rows}
    missing = pilots - have
    print("     pilot keys preserved" if not missing else f"[warn] pilots missing: {missing}")


if __name__ == "__main__":
    main()
