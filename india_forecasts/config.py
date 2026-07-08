"""
Shared configuration for India seasonal/subseasonal forecast downloads.

Edit values here; both download scripts import from this module.
"""

from pathlib import Path

# --------------------------------------------------------------------------
# India bounding box (degrees). Generous box covering mainland + Andaman &
# Nicobar + Lakshadweep. Order-agnostic; scripts read the named keys.
#   - Kashmir reaches ~37 N, Kanyakumari ~8 N, Andaman/Nicobar down to ~6 N
#   - westernmost (Gujarat) ~68 E, Andaman/Nicobar east to ~94 E
# Use the tighter MAINLAND box if you don't need the island territories.
# --------------------------------------------------------------------------
INDIA_BBOX = {"north": 38.0, "south": 6.0, "west": 66.0, "east": 98.0}
INDIA_BBOX_MAINLAND = {"north": 37.5, "south": 7.5, "west": 68.0, "east": 92.0}

# CDS expects area as [North, West, South, East]
def cds_area(bbox=INDIA_BBOX):
    return [bbox["north"], bbox["west"], bbox["south"], bbox["east"]]

# --------------------------------------------------------------------------
# Variables of interest. Each model names them differently; mappings below.
# --------------------------------------------------------------------------
# Copernicus CDS (SEAS5 / C3S) variable IDs
CDS_VARIABLES = ["2m_temperature", "total_precipitation"]
# Note: in 'seasonal-monthly-single-levels', monthly_mean of total_precipitation
# is a MEAN RATE in m s^-1 (multiply by seconds-in-month for a monthly total).
# 2m_temperature is in Kelvin.

# NOAA SFS (UFS/FV3 GRIB2) GRIB shortNames for the same fields.
# Confirm against `python download_sfs.py --explore` output for your build.
SFS_GRIB_SHORTNAMES = {
    "t2m": "2t",      # 2 m temperature (K)
    "precip": "prate" # precipitation rate (kg m^-2 s^-1 == mm s^-1)
}

# --------------------------------------------------------------------------
# Output locations (relative to this folder by default)
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SEAS5_DIR = DATA_DIR / "seas5"
SFS_DIR = DATA_DIR / "sfs"
OBS_DIR = DATA_DIR / "obs"     # gridded observations for skill verification
GEO_DIR = DATA_DIR / "geo"     # administrative boundaries (states/districts)
for _d in (DATA_DIR, SEAS5_DIR, SFS_DIR, OBS_DIR, GEO_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# GADM v4.1 India admin boundaries (level 2 = districts, carries NAME_1 state too).
# Free for academic/non-commercial use. Cached locally on first use.
GADM_IND_L2_URL = "https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_IND_2.json.zip"

# --------------------------------------------------------------------------
# Observation sources for the hindcast skill mask (land, monthly).
#   - Temperature: GHCN-CAMS 2 m air temperature (NOAA PSL, 0.5 deg)
#   - Precip     : CHIRPS v2.0 (UCSB), subset+regridded via the IRI Data Library
# --------------------------------------------------------------------------
GHCNCAMS_URL = "https://psl.noaa.gov/thredds/dodsC/Datasets/ghcncams/air.mon.mean.nc"
CHIRPS_IRIDL = "http://iridl.ldeo.columbia.edu/SOURCES/.UCSB/.CHIRPS/.v2p0/.monthly/.global/.precipitation/"
OBS_YEARS = (1991, 2025)       # inclusive; covers both SFS (1991-2025) and SEAS5 (1993-2016) hindcasts
