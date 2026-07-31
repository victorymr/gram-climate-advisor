#!/usr/bin/env python3
"""Build data/icar_contingency_plans/manifest.csv by scraping the ICAR-CRIDA index.

The CRIDA contingency-plan URLs follow no guessable pattern (two different path
schemes, embedded dates, inconsistent spellings), so they must be *discovered*
rather than constructed. The single index page links every district plan, and
the district names come from the site's own anchor text -- nothing is inferred.

Existing manifest rows are preserved (matched on state+district) so previously
downloaded filenames and their sha256 checksums are never lost. New rows are
written with a blank sha256, which download_icar_pdfs.py treats as "unverified"
and fills in on first download.

Usage:
    python scripts/build_icar_manifest.py --dry-run   # report only, write nothing
    python scripts/build_icar_manifest.py             # merge + write manifest.csv
"""
from __future__ import annotations

import argparse
import csv
import html as H
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLANS_DIR = ROOT / "data" / "icar_contingency_plans"
MANIFEST = PLANS_DIR / "manifest.csv"
INDEX_URL = "https://www.icar-crida.res.in/Crop_Contingency_Plan.html"
USER_AGENT = "gram-climate-advisor/1.0 (ICAR contingency-plan manifest builder)"
FIELDS = ["state", "district", "filename", "source_url", "sha256"]

# The index uses varied spellings/casing for the same state in its URL paths.
# This is a spelling normalization of identical states -- not a geographic guess.
STATE_FROM_PATH = {
    "a&n": "Andaman & Nicobar",
    "andhra pradesh": "Andhra Pradesh",
    "arunachal pradesh": "Arunachal Pradesh",
    "assam": "Assam",
    "bihar": "Bihar",
    "chattisgarh": "Chhattisgarh",
    "goa": "Goa",
    "gujarat": "Gujarat",
    "haryana": "Haryana",
    "himachal pradesh": "Himachal Pradesh",
    "j&k": "Jammu & Kashmir",
    "jharkhand": "Jharkhand",
    "karnataka": "Karnataka",
    "kerala": "Kerala",
    "madhya pradesh": "Madhya Pradesh",
    "maharastra": "Maharashtra",
    "manipur": "Manipur",
    "meghalaya": "Meghalaya",
    "mizoram": "Mizoram",
    "nagaland": "Nagaland",
    "orissa": "Odisha",
    "punjab": "Punjab",
    "rajastan": "Rajasthan",
    "sikkim": "Sikkim",
    "tamilnadu": "Tamil Nadu",
    "tripura": "Tripura",
    "uttar pradesh": "Uttar Pradesh",
    "uttar_pradesh": "Uttar Pradesh",
    "uttarkhand": "Uttarakhand",
    "west bengal": "West Bengal",
}


class _PlanLinkParser(HTMLParser):
    """Collect (href, anchor text) for every PDF link.

    The page's markup is malformed (many <a> tags are never closed), so instead
    of relying on well-formed elements we take the first text node that follows
    each anchor start tag.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._href: str | None = None
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            self._href = href if href.lower().endswith(".pdf") else None
        elif self._href is not None and tag in ("br", "td", "tr", "table", "p"):
            self._href = None

    def handle_endtag(self, tag):
        if tag == "a":
            self._href = None

    def handle_data(self, data):
        if self._href:
            text = data.strip()
            if text:
                self.links.append((self._href, text))
                self._href = None


def _clean_district(text: str) -> str:
    """Anchor text often carries a trailing pipe separator, e.g. 'Chittoor |'."""
    t = H.unescape(text).replace("|", " ")
    t = re.sub(r"\s+", " ", t).strip(" -–")
    return t.strip()


def _state_from_href(href: str) -> str | None:
    m = re.search(r"(?:CP-2012/statewiseplans|CP)/([^/]+)/", href, re.I)
    if not m:
        return None
    seg = urllib.parse.unquote(m.group(1))
    seg = re.sub(r"\(pdf\)", "", seg, flags=re.I)  # strip "(Pdf)" suffix
    seg = re.sub(r"\s+", " ", seg).strip().lower()
    return STATE_FROM_PATH.get(seg)


def _slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", "ignore")


def _load_existing() -> dict[tuple[str, str], dict[str, str]]:
    if not MANIFEST.exists():
        return {}
    with open(MANIFEST, newline="", encoding="utf-8") as f:
        return {(r["state"].lower(), r["district"].lower()): r
                for r in csv.DictReader(f)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="report only; do not write")
    ap.add_argument("--url", default=INDEX_URL, help="index page to scrape")
    args = ap.parse_args()

    parser = _PlanLinkParser()
    parser.feed(_fetch(args.url))
    print(f"Discovered {len(parser.links)} PDF links on the index page.")

    existing = _load_existing()
    rows: dict[tuple[str, str], dict[str, str]] = {}
    unmapped: set[str] = set()
    skipped = 0

    for href, text in parser.links:
        district = _clean_district(text)
        state = _state_from_href(href)
        if not state:
            m = re.search(r"(?:CP-2012/statewiseplans|CP)/([^/]+)/", href, re.I)
            unmapped.add(urllib.parse.unquote(m.group(1)) if m else href[:50])
            skipped += 1
            continue
        if not district or len(district) < 2:
            skipped += 1
            continue
        key = (state.lower(), district.lower())
        if key in rows:  # duplicate link for the same district; keep the first
            continue
        prior = existing.get(key)
        rows[key] = {
            "state": state,
            "district": district,
            # Preserve the on-disk filename/checksum of anything already fetched.
            "filename": prior["filename"] if prior else f"{_slug(state)}_{_slug(district)}.pdf",
            "source_url": urllib.parse.urljoin(args.url, href),
            "sha256": prior.get("sha256", "") if prior else "",
        }

    if unmapped:
        print(f"\nWARNING: {len(unmapped)} unmapped state path segment(s) "
              f"({skipped} link(s) skipped). Add them to STATE_FROM_PATH:")
        for seg in sorted(unmapped):
            print(f"   - {seg}")

    ordered = [rows[k] for k in sorted(rows)]
    kept = sum(1 for k in rows if k in existing)
    print(f"\nDistricts: {len(ordered)} total | {kept} preserved from existing "
          f"manifest | {len(ordered) - kept} new")
    by_state: dict[str, int] = {}
    for r in ordered:
        by_state[r["state"]] = by_state.get(r["state"], 0) + 1
    for st, n in sorted(by_state.items()):
        print(f"   {n:3d}  {st}")

    missing = [k for k in existing if k not in rows]
    if missing:
        print(f"\nNOTE: {len(missing)} existing row(s) not found on the index "
              f"(kept as-is): {[f'{s}/{d}' for s, d in missing]}")
        for k in missing:
            ordered.append(existing[k])
        ordered.sort(key=lambda r: (r["state"].lower(), r["district"].lower()))

    if args.dry_run:
        print("\n--dry-run: manifest not written.")
        return 0

    with open(MANIFEST, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        w.writerows(ordered)
    print(f"\nWrote {len(ordered)} rows -> {MANIFEST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
