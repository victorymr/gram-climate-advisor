"""GEFS lead-coverage guard: Herbie silently drops leads whose S3 probe failed, which once
produced a 3-week '35-day' forecast. fetch() must re-probe the missing leads and refuse a
partial forecast; a partial cached member must be detected so it is re-fetched."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr



def _load_download_gefs():
    """Import india_forecasts/download_gefs.py without letting its sibling modules
    (utils, config, s2s_utils) shadow the advisor's src/utils.py for the other tests."""
    fc = str(Path(__file__).resolve().parent.parent / "india_forecasts")
    siblings = ("utils", "config", "s2s_utils", "download_gefs")
    saved = {k: sys.modules.pop(k) for k in siblings if k in sys.modules}
    sys.path.insert(0, fc)
    try:
        import download_gefs
        return download_gefs
    finally:
        sys.path.remove(fc)
        for k in siblings:
            sys.modules.pop(k, None)
        sys.modules.update(saved)


dg = _load_download_gefs()

FXX = dg.fxx_list(6)                     # 6 .. 840 h


def _patch(monkeypatch, resolve_on_retry):
    """Stub the network + GRIB decode: the first pass loses every lead > 504 h (throttling /
    resets); the retry recovers them iff resolve_on_retry. Returns the per-lead call log."""
    calls = []

    def fake_fetch_lead(sess, date, member, f):
        calls.append(f)
        first = calls.count(f) == 1
        if f <= 504 or (not first and resolve_on_retry):
            return b"GRIB"
        if f % 12 == 0:
            raise ConnectionError("reset")       # a failed request counts the same as a missing lead
        return None

    def fake_decode(blobs):
        steps = np.array(sorted(blobs))
        lat, lon = np.arange(30.0, 9.0, -5.0), np.arange(70.0, 91.0, 5.0)
        shape = (steps.size, lat.size, lon.size)
        coords = {"lead_hours": ("step", steps), "latitude": lat, "longitude": lon}
        dims = ("step", "latitude", "longitude")
        return (xr.DataArray(np.full(shape, 300.0), dims=dims, coords=coords),
                xr.DataArray(np.ones(shape), dims=dims, coords=coords))

    monkeypatch.setattr(dg, "_session", lambda *a, **k: None)
    monkeypatch.setattr(dg, "_fetch_lead", fake_fetch_lead)
    monkeypatch.setattr(dg, "_decode", fake_decode)
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)
    return calls


def test_retry_recovers_dropped_leads(monkeypatch):
    calls = _patch(monkeypatch, resolve_on_retry=True)
    t, p = dg.fetch("2026-08-17", "p17", 6)
    assert dg._missing_leads(t, FXX) == [] and dg._missing_leads(p, FXX) == []
    assert int(t["lead_hours"].max()) == dg.MAX_LEAD_H
    # the retry asked only for the dropped leads
    assert sorted(calls[len(FXX):]) == [f for f in FXX if f > 504]


def test_partial_forecast_is_refused_unless_allowed(monkeypatch):
    calls = _patch(monkeypatch, resolve_on_retry=False)
    with pytest.raises(RuntimeError, match="refusing"):
        dg.fetch("2026-08-17", "avg", 6)
    n_dropped = sum(f > 504 for f in FXX)
    assert len(calls) == len(FXX) + dg.FXX_RETRIES * n_dropped
    t, p = dg.fetch("2026-08-17", "avg", 6, allow_partial=True)
    assert int(t["lead_hours"].max()) == 504
    assert dg.to_weekly_fields(t, p, "bucket")[0].sizes["week"] == 3     # the old failure mode


def test_complete_detects_partial_member_files(tmp_path):
    def write(n_weeks, name):
        ds = xr.Dataset({"t2m": (("week", "latitude", "longitude"), np.zeros((n_weeks, 2, 2)))},
                        coords={"week": np.arange(1, n_weeks + 1)})
        path = tmp_path / name
        ds.to_netcdf(path)
        return path
    assert dg._complete(write(5, "full.nc"))
    assert not dg._complete(write(3, "short.nc"))
    assert not dg._complete(tmp_path / "missing.nc")
