"""
Reliability calibration for the weekly threshold odds.

The raw odds shown in Source Data are the fraction of ensemble members crossing a
threshold -- the ensemble's *confidence*. The backtest showed that ensemble is
under-dispersed, so those odds are over-confident. data/calibration.json (built by
india_forecasts/backtest/build_calibration.py) holds, per threshold event x lead-week, a
monotonic map from raw probability to the frequency that probability has actually verified
historically. calibrate() applies it; where a curve is missing it returns the raw value
unchanged (identity fallback), so nothing breaks without the file.
"""

import json
import os

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "data", "calibration.json")


def load_calibration():
    """Parsed calibration.json, or None if absent/unreadable (odds stay raw)."""
    try:
        with open(_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError, OSError):
        return None


def _interp(x, xs, ys):
    """Linear interpolation without numpy (xs ascending)."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
            t = 0 if x1 == x0 else (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return ys[-1]


def calibrate(cal, event, week, p):
    """Map a raw ensemble probability (0..1) to its historically-observed frequency.

    event in {wetter, drier, heavy, dryspell, hot}. Returns p unchanged if p is None, the
    calibration is missing, or this (event, week) has no fitted curve."""
    if p is None or cal is None:
        return p
    try:
        ev = cal.get("events", {}).get(event, {}).get(str(int(week)))
    except (TypeError, ValueError):
        return p
    if not ev or "x" not in ev or "y" not in ev:
        return p
    return round(_interp(float(p), ev["x"], ev["y"]), 3)
