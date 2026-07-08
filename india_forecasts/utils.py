"""
Shared helpers: crop any gridded dataset to the India bounding box and save NetCDF.
Works for both CDS NetCDF output and SFS GRIB2 (opened via cfgrib).
"""

import xarray as xr
from config import INDIA_BBOX


def _find_coord(ds, candidates):
    for name in candidates:
        if name in ds.coords or name in ds.dims:
            return name
    raise KeyError(f"None of {candidates} found in dataset coords {list(ds.coords)}")


def subset_to_india(ds, bbox=INDIA_BBOX, lat_name=None, lon_name=None):
    """Return ds cropped to bbox. Handles ascending/descending latitude and
    0-360 vs -180-180 longitude. (India does not cross the 0/360 seam, so the
    longitude slice is straightforward either way.)"""
    lat_name = lat_name or _find_coord(ds, ["latitude", "lat", "y"])
    lon_name = lon_name or _find_coord(ds, ["longitude", "lon", "x"])

    lon = ds[lon_name]
    if float(lon.max()) > 180.0:  # 0-360 convention
        west, east = bbox["west"] % 360, bbox["east"] % 360
    else:
        west, east = bbox["west"], bbox["east"]

    lat = ds[lat_name]
    if float(lat[0]) > float(lat[-1]):  # descending (90 -> -90)
        lat_slice = slice(bbox["north"], bbox["south"])
    else:                                # ascending (-90 -> 90)
        lat_slice = slice(bbox["south"], bbox["north"])

    return ds.sel({lat_name: lat_slice, lon_name: slice(west, east)})


def save_netcdf(ds, path, complevel=4):
    """Write a compressed NetCDF4 file."""
    enc = {v: {"zlib": True, "complevel": complevel} for v in ds.data_vars}
    ds.to_netcdf(path, engine="netcdf4", encoding=enc)
    print(f"  saved -> {path}  ({path.stat().st_size/1e6:.1f} MB)")
    return path
