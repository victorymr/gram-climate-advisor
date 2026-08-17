#!/usr/bin/env python3
"""Download ICAR-CRIDA district contingency-plan PDFs listed in the manifest.

The PDFs are *source material* used offline to build
``data/icar_contingency_actions.json`` (the only file the app reads at runtime).
They are intentionally git-ignored to keep the repository small, so this script
lets anyone reproduce the local ``data/icar_contingency_plans/`` folder.

Usage:
    python scripts/download_icar_pdfs.py                 # download all missing
    python scripts/download_icar_pdfs.py --force         # re-download everything
    python scripts/download_icar_pdfs.py --district Gaya # download one district
    python scripts/download_icar_pdfs.py --verify        # only verify checksums

Manifest format (data/icar_contingency_plans/manifest.csv):
    state,district,filename,source_url,sha256
The ``sha256`` column may be left blank; if present it is verified after download.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import sys
import urllib.request
from pathlib import Path

PLANS_DIR = Path(__file__).resolve().parent.parent / "data" / "icar_contingency_plans"
MANIFEST = PLANS_DIR / "manifest.csv"
USER_AGENT = "gram-climate-advisor/1.0 (ICAR contingency-plan fetcher)"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_manifest() -> list[dict[str, str]]:
    if not MANIFEST.exists():
        sys.exit(f"Manifest not found: {MANIFEST}")
    with open(MANIFEST, newline="", encoding="utf-8") as f:
        rows = [row for row in csv.DictReader(f)]
    for i, row in enumerate(rows, start=2):
        missing = [c for c in ("filename", "source_url") if not row.get(c)]
        if missing:
            sys.exit(f"Manifest row {i} missing required column(s): {', '.join(missing)}")
    return rows


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as out:
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            out.write(chunk)
    tmp.replace(dest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true",
                        help="re-download even if the file already exists")
    parser.add_argument("--district", help="only fetch the given district (case-insensitive)")
    parser.add_argument("--verify", action="store_true",
                        help="do not download; only verify checksums of existing files")
    args = parser.parse_args()

    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    rows = _load_manifest()
    if args.district:
        rows = [r for r in rows if r["district"].lower() == args.district.lower()]
        if not rows:
            sys.exit(f"No manifest entry for district: {args.district}")

    ok = downloaded = skipped = failed = 0
    for row in rows:
        dest = PLANS_DIR / row["filename"]
        label = f"{row.get('district', '?')} ({row['filename']})"
        expected = (row.get("sha256") or "").strip().lower()

        if args.verify:
            if not dest.exists():
                print(f"MISSING  {label}")
                failed += 1
            elif expected and _sha256(dest) != expected:
                print(f"MISMATCH {label}")
                failed += 1
            else:
                print(f"OK       {label}")
                ok += 1
            continue

        if dest.exists() and not args.force:
            if expected and _sha256(dest) != expected:
                print(f"MISMATCH {label} — re-downloading")
            else:
                print(f"SKIP     {label} (already present)")
                skipped += 1
                continue

        try:
            print(f"GET      {label}")
            _download(row["source_url"], dest)
        except Exception as exc:  # network/HTTP errors vary; report and continue
            print(f"FAILED   {label}: {exc}")
            failed += 1
            continue

        if expected:
            actual = _sha256(dest)
            if actual != expected:
                print(f"WARNING  {label}: checksum mismatch "
                      f"(expected {expected[:12]}…, got {actual[:12]}…)")
                failed += 1
                continue
        downloaded += 1

    print("\nSummary:", ", ".join(
        f"{name}={val}" for name, val in
        [("ok", ok), ("downloaded", downloaded), ("skipped", skipped), ("failed", failed)]
        if val
    ) or "nothing to do")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
