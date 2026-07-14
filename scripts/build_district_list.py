#!/usr/bin/env python3
"""
Build the India district master list from an admin-boundary source.

Writes, for every district:
  data/district_metadata.csv     -> state,district                       (display names)
  data/district_coordinates.csv  -> state,district,latitude,longitude,region
  data/districts.geojson         -> simplified polygons {state,district}  (app map)

Two sources (--source, default 'lgd'):
  lgd  : ramSeraph LGD_Districts parquet -- current LGD roster, 785 districts, CC0,
         hybrid 2011-2023 geometry (Telangana 33, Ladakh split out, etc.).
  gadm : GADM v4.1 level-2 json.zip -- 2022 vintage, 666 districts (legacy).

Both are normalised to display names + a region/zone so the pilots' curated
forecast/ICAR data keeps resolving by (state, district).

Usage (from the advisor project root, heavy/global Python with geopandas):
    python scripts/build_district_list.py                 # LGD (785)
    python scripts/build_district_list.py --source gadm   # GADM (666)
"""

import re
import csv
import argparse
import urllib.request
from pathlib import Path

import geopandas as gpd

ADVISOR_ROOT = Path(__file__).resolve().parent.parent
DATA = ADVISOR_ROOT / "data"
GEO = ADVISOR_ROOT / "india_forecasts" / "data" / "geo"
GADM_LOCAL = GEO / "gadm41_IND_2.json.zip"
GADM_URL = "https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_IND_2.json.zip"
LGD_LOCAL = GEO / "LGD_Districts.parquet"
LGD_URL = ("https://github.com/ramSeraph/indian_admin_boundaries/"
           "releases/download/districts/LGD_Districts.parquet")

# GADM NAME_1 -> (display state, zone).
GADM_STATES = {
    "AndamanandNicobar": ("Andaman and Nicobar", "Islands"),
    "AndhraPradesh": ("Andhra Pradesh", "South India"),
    "ArunachalPradesh": ("Arunachal Pradesh", "Northeast India"),
    "Assam": ("Assam", "Northeast India"), "Bihar": ("Bihar", "East India"),
    "Chandigarh": ("Chandigarh", "North India"),
    "Chhattisgarh": ("Chhattisgarh", "Central India"),
    "DadraandNagarHaveli": ("Dadra and Nagar Haveli", "West India"),
    "DamanandDiu": ("Daman and Diu", "West India"), "Goa": ("Goa", "West India"),
    "Gujarat": ("Gujarat", "West India"), "Haryana": ("Haryana", "North India"),
    "HimachalPradesh": ("Himachal Pradesh", "North India"),
    "JammuandKashmir": ("Jammu and Kashmir", "North India"),
    "Jharkhand": ("Jharkhand", "East India"), "Karnataka": ("Karnataka", "South India"),
    "Kerala": ("Kerala", "South India"), "Lakshadweep": ("Lakshadweep", "Islands"),
    "MadhyaPradesh": ("Madhya Pradesh", "Central India"),
    "Maharashtra": ("Maharashtra", "Central India"),
    "Manipur": ("Manipur", "Northeast India"), "Meghalaya": ("Meghalaya", "Northeast India"),
    "Mizoram": ("Mizoram", "Northeast India"), "NCTofDelhi": ("Delhi", "North India"),
    "Nagaland": ("Nagaland", "Northeast India"), "Odisha": ("Odisha", "East India"),
    "Puducherry": ("Puducherry", "South India"), "Punjab": ("Punjab", "North India"),
    "Rajasthan": ("Rajasthan", "North-West India"), "Sikkim": ("Sikkim", "Northeast India"),
    "TamilNadu": ("Tamil Nadu", "South India"), "Telangana": ("Telangana", "South India"),
    "Tripura": ("Tripura", "Northeast India"), "UttarPradesh": ("Uttar Pradesh", "North India"),
    "Uttarakhand": ("Uttarakhand", "North India"), "WestBengal": ("West Bengal", "East India"),
}

# LGD stname (exact) -> (display state, zone). LGD merges D&NH+D&D, splits out Ladakh.
LGD_STATES = {
    "ANDAMAN & NICOBAR": ("Andaman and Nicobar", "Islands"),
    "ANDHRA PRADESH": ("Andhra Pradesh", "South India"),
    "ARUNACHAL PRADESH": ("Arunachal Pradesh", "Northeast India"),
    "ASSAM": ("Assam", "Northeast India"), "BIHAR": ("Bihar", "East India"),
    "CHANDIGARH": ("Chandigarh", "North India"),
    "CHHATTISGARH": ("Chhattisgarh", "Central India"),
    "DADRA,NAGAR HAVELI,DAMAN & DIU": ("Dadra and Nagar Haveli and Daman and Diu", "West India"),
    "DELHI": ("Delhi", "North India"), "GOA": ("Goa", "West India"),
    "GUJARAT": ("Gujarat", "West India"), "HARYANA": ("Haryana", "North India"),
    "HIMACHAL PRADESH": ("Himachal Pradesh", "North India"),
    "JAMMU & KASHMIR": ("Jammu and Kashmir", "North India"),
    "JHARKHAND": ("Jharkhand", "East India"), "KARNATAKA": ("Karnataka", "South India"),
    "KERALA": ("Kerala", "South India"), "LADAKH": ("Ladakh", "North India"),
    "LAKSHADWEEP": ("Lakshadweep", "Islands"),
    "MADHYA PRADESH": ("Madhya Pradesh", "Central India"),
    "MAHARASHTRA": ("Maharashtra", "Central India"),
    "MANIPUR": ("Manipur", "Northeast India"), "MEGHALAYA": ("Meghalaya", "Northeast India"),
    "MIZORAM": ("Mizoram", "Northeast India"), "NAGALAND": ("Nagaland", "Northeast India"),
    "ODISHA": ("Odisha", "East India"), "PUDUCHERRY": ("Puducherry", "South India"),
    "PUNJAB": ("Punjab", "North India"), "RAJASTHAN": ("Rajasthan", "North-West India"),
    "SIKKIM": ("Sikkim", "Northeast India"), "TAMIL NADU": ("Tamil Nadu", "South India"),
    "TELANGANA": ("Telangana", "South India"), "TRIPURA": ("Tripura", "Northeast India"),
    "UTTAR PRADESH": ("Uttar Pradesh", "North India"),
    "UTTARAKHAND": ("Uttarakhand", "North India"), "WEST BENGAL": ("West Bengal", "East India"),
}


def prettify_gadm(name):
    """camelCase -> spaced ('EastGodavari' -> 'East Godavari'); tidy joined 'and'/'&'."""
    s = str(name).replace("&", " and ")
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)
    s = re.sub(r"\b([A-Z][a-z]+)and\b", r"\1 and", s)
    return re.sub(r"\s+", " ", s).strip()


def clean_lgd(name):
    """LGD district name cleanup: title-case all-caps, normalise '&' -> 'and'."""
    s = str(name).strip()
    if s.isupper():
        s = s.title()
    s = s.replace(" & ", " and ").replace("&", " and ")
    return re.sub(r"\s+", " ", s).strip()


def load_source(source, override):
    """Return (GeoDataFrame with NAME_1/NAME_2, state_map, district_fn)."""
    if source == "gadm":
        if override:
            g = gpd.read_file(override)
        else:
            if not GADM_LOCAL.exists():
                GADM_LOCAL.parent.mkdir(parents=True, exist_ok=True)
                print(f"Downloading GADM -> {GADM_LOCAL} (one-time) ...")
                urllib.request.urlretrieve(GADM_URL, GADM_LOCAL)
            g = gpd.read_file(GADM_LOCAL)
        return g, GADM_STATES, prettify_gadm
    # lgd
    src = override or LGD_LOCAL
    if not Path(src).exists():
        LGD_LOCAL.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading LGD_Districts -> {LGD_LOCAL} (one-time) ...")
        urllib.request.urlretrieve(LGD_URL, LGD_LOCAL)
        src = LGD_LOCAL
    g = gpd.read_parquet(src).rename(columns={"stname": "NAME_1", "dtname": "NAME_2"})
    bad = ~g.geometry.is_valid
    if bad.any():
        g.loc[bad, "geometry"] = g.loc[bad, "geometry"].buffer(0)
    return g[["NAME_1", "NAME_2", "geometry"]], LGD_STATES, clean_lgd


def main():
    ap = argparse.ArgumentParser(description="Build the India district master list.")
    ap.add_argument("--source", choices=["lgd", "gadm"], default="lgd",
                    help="Boundary source (default lgd = 785 current districts).")
    ap.add_argument("--geo", default=None, help="Override boundary file/URL.")
    args = ap.parse_args()

    g, state_map, district_fn = load_source(args.source, args.geo)
    # one polygon per (state, district) -- dissolves any split features.
    g = g.dissolve(by=["NAME_1", "NAME_2"], as_index=False)

    rows, unknown = [], set()
    for _, r in g.iterrows():
        s1 = r["NAME_1"]
        if s1 in state_map:
            state, region = state_map[s1]
        else:
            state, region = district_fn(s1), "India"
            unknown.add(s1)
        district = district_fn(r["NAME_2"])
        pt = r.geometry.representative_point()
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

    g2 = g.copy()
    g2["state"] = g2["NAME_1"].map(lambda s: state_map.get(s, (district_fn(s), "India"))[0])
    g2["district"] = g2["NAME_2"].map(district_fn)
    g2["geometry"] = g2.geometry.simplify(0.02, preserve_topology=True)
    geojson = DATA / "districts.geojson"
    if geojson.exists():
        geojson.unlink()
    g2[["state", "district", "geometry"]].to_file(geojson, driver="GeoJSON")

    print(f"[OK] source={args.source}: {len(rows)} districts across "
          f"{len({r['state'] for r in rows})} states/UTs")
    print(f"     -> {DATA/'district_metadata.csv'}")
    print(f"     -> {DATA/'district_coordinates.csv'}")
    print(f"     -> {geojson}  ({geojson.stat().st_size // 1024} KB)")
    if unknown:
        print(f"[warn] states not in the display map (used fallback): {sorted(unknown)}")
    pilots = {("Bihar", "Gaya"), ("Uttar Pradesh", "Varanasi"), ("Andhra Pradesh", "Anantapur"),
              ("Maharashtra", "Nagpur"), ("Rajasthan", "Jaipur")}
    have = {(r["state"], r["district"]) for r in rows}
    missing = pilots - have
    print("     pilot keys preserved" if not missing else f"[warn] pilots not matched: {missing}")


if __name__ == "__main__":
    main()
