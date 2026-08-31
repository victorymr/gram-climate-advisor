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


class _H:
    def __init__(self, fxx, grib=True):
        self.fxx, self.grib = fxx, (object() if grib else None)


def _make_stub(resolve_on_retry):
    """A FastHerbie stand-in: the first (50-thread) probe loses every lead > 504 h; the
    gentle re-probe recovers them iff resolve_on_retry."""
    calls = []

    class FakeFastHerbie:
        def __init__(self, DATES, fxx, max_threads=50, **kw):
            calls.append((tuple(fxx), max_threads))
            first = len(fxx) == len(FXX)          # the full probe (vs a re-probe of the missing leads)
            ok = [f for f in fxx if f <= 504] if first else (list(fxx) if resolve_on_retry else [])
            self.objects = [_H(f) for f in ok] + [_H(f, grib=False) for f in fxx if f not in ok]
            self.file_exists = [H for H in self.objects if H.grib is not None]
            self.file_not_exists = [H for H in self.objects if H.grib is None]
            self.tasks = len(self.objects)

        def xarray(self, search):
            steps = np.array([H.fxx for H in self.file_exists])
            lat, lon = np.arange(10.0, 31.0, 5.0), np.arange(70.0, 91.0, 5.0)
            shape = (steps.size, lat.size, lon.size)
            coords = {"step": ("step", pd.to_timedelta(steps, unit="h")), "latitude": lat, "longitude": lon}
            return xr.Dataset({"t2m": (("step", "latitude", "longitude"), np.full(shape, 300.0)),
                               "tp": (("step", "latitude", "longitude"), np.ones(shape))}, coords=coords)

    return FakeFastHerbie, calls


def _patch(monkeypatch, stub):
    import types
    fake_mod = types.SimpleNamespace(FastHerbie=stub)
    monkeypatch.setitem(sys.modules, "herbie", fake_mod)
    monkeypatch.setattr(dg.time, "sleep", lambda s: None, raising=False) if hasattr(dg, "time") else None
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)


def test_reprobe_recovers_dropped_leads(monkeypatch):
    stub, calls = _make_stub(resolve_on_retry=True)
    _patch(monkeypatch, stub)
    t, p = dg.fetch("2026-08-17", "p17", 6)
    assert dg._missing_leads(t, FXX) == [] and dg._missing_leads(p, FXX) == []
    assert int(t["lead_hours"].max()) == dg.MAX_LEAD_H
    # the re-probe asked only for the dropped leads, with the gentle thread count
    assert calls[1][0] == tuple(f for f in FXX if f > 504) and calls[1][1] == dg.FXX_RETRY_THREADS


def test_partial_forecast_is_refused_unless_allowed(monkeypatch):
    stub, calls = _make_stub(resolve_on_retry=False)
    _patch(monkeypatch, stub)
    with pytest.raises(RuntimeError, match="refusing"):
        dg.fetch("2026-08-17", "avg", 6)
    assert len(calls) == 1 + dg.FXX_RETRIES
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
