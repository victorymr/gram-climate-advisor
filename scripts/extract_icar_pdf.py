#!/usr/bin/env python3
"""Table-aware, verbatim extractor for ICAR-CRIDA district contingency plans.

Why this exists
---------------
ICAR-CRIDA plans are landscape, multi-column table PDFs. Naive text extraction
reads *across* columns and shreds each cell into fragments ("column bleed"),
which is why the earlier ``icar_pdf_extracted_actions.json`` is unusable.

This script instead uses ``pdfplumber.extract_tables()`` so each table cell
stays intact, locates the "Suggested Contingency measures" matrix, maps its
columns by their header text, classifies each row into a scenario, and keeps
**verbatim** cell text with page/column provenance. Nothing is invented.

It deliberately does NOT rephrase or generate advice (an earlier generated
layer hallucinated variety names not present in the source PDFs). A separate,
auditable normalization step can be added later.

Usage:
    python scripts/extract_icar_pdf.py                     # all districts in manifest
    python scripts/extract_icar_pdf.py --district Gaya      # one district
    python scripts/extract_icar_pdf.py -o data/out.json     # custom output path

Output (default data/icar_extracted_v2.json):
    [ {state, district, source_pdf, pages,
       scenarios: {scen: [ {action, page, column,
                            crop?, farming_situation?,
                            resolved_from_ditto?, placeholder?} ]}} ]

Each action carries the row context it came from, because the same advice
legitimately recurs for different crops and farming situations and collapsing
those would hide which crops are covered. Two optional flags keep the output
honest rather than quietly dropping cells:
    resolved_from_ditto  the cell said "-do-"/"As above"; text was carried down
                         from the row above (the source's own notation)
    placeholder          the cell says nothing applies ("NA", "No change")
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    sys.exit("pdfplumber is required: pip install pdfplumber")

ROOT = Path(__file__).resolve().parent.parent
PLANS_DIR = ROOT / "data" / "icar_contingency_plans"
MANIFEST = PLANS_DIR / "manifest.csv"
DEFAULT_OUT = ROOT / "data" / "icar_extracted_v2.json"

SCENARIOS = [
    "delayed_monsoon",
    "early_season_dry_spell",
    "mid_season_break",
    "terminal_drought",
    "excess_rainfall_waterlogging",
]

# Private-use / symbol-font bullet glyphs and common bullets used in these PDFs.
_BULLETS = "\uf0b7\uf0d8\uf076\uf0a7\uf0fc\uf0e0\uf02d\u2022\u2023\u25cf\u25aa\u00b7\u2043"
_BULLET_SPLIT = re.compile(f"[{_BULLETS}]")

# Many plans enumerate steps inside a single cell instead of using bullets
# ("1. Drain the excess water 2. Apply urea ..."). Split on those markers too.
#
# Guards against false positives:
#   * requires a "." or ")" after the number, so "19-19-19" and "1 %" are safe;
#   * requires a letter next, so decimals like "1.5 kg" are safe;
#   * only fires at the start of the cell or after whitespace.
#   * many cells omit the space after the marker ("1.Drain the excess water"),
#     so when no space follows we additionally require an uppercase letter --
#     that keeps "i.e." and "1.5 kg" intact while still splitting "2.Apply".
_ENUM_SPLIT = re.compile(
    r"(?:(?<=^)|(?<=\s))(?:\d{1,2}|i{1,3}|iv|vi{0,3}|v)[.)]"
    r"(?:\s+(?=[A-Za-z])|(?=[A-Z]))"
)

# Cells that carry no advice on their own. Kept (flagged) rather than dropped so
# the output still reflects what the source table said.
_PLACEHOLDERS = {
    "na", "n.a", "n.a.", "nil", "none", "not applicable", "notapplicable",
    "no change", "nochange", "no change in cropping system", "not required",
    "no need of contingency", "not applicable-", "-", "--",
}

# "-do-" / "As above" are ditto marks: the source means "same as the row above".
_DITTO = {"do", "-do-", "do-", "-do", "as above", "same as above", "ditto",
          "as above-", "same as previous"}

# Header labels (normalized) that must never be emitted as actions.
_HEADER_LABELS = {
    "condition", "suggested contingency measures", "major farming situation",
    "normal crop / cropping system", "normal crop/cropping system",
    "normal crop / cropping systems", "change in crop / cropping system",
    "change in crop/cropping system", "change in crop / cropping system including variety",
    "change in crop/cropping system including variety", "crop management",
    "agronomic measures", "soil nutrient & moisture conservation measures",
    "soil nutrient & moisture conservation measues", "remarks on implementation",
    "remarks on implementati on", "crop maturity stage", "post harvest",
    "reproductive stage", "at harvest", "vegetative stage",
    "grand growth stage", "formative phase", "formative stage",
    "maturity stage", "nursery stage", "flowering stage",
    "seedling stage",
}


def _clean(s: str | None) -> str:
    """Collapse whitespace; keep original characters otherwise."""
    return re.sub(r"\s+", " ", (s or "").replace("\n", " ")).strip()


def _norm(s: str) -> str:
    """Normalize for comparison: collapse whitespace and lowercase."""
    return _clean(s).lower()


def _is_header_label(text: str) -> bool:
    """True if the cell is a column header (optionally with a trailing footnote letter).

    ICAR footnote markers append a stray single letter, e.g. "agronomic measuresi"
    or "change in crop/cropping systemc". We test both the raw label and the label
    with its final character removed.
    """
    n = _norm(text)
    if n in _HEADER_LABELS:
        return True
    if len(n) > 1 and n[:-1] in _HEADER_LABELS:
        return True
    return False


def _is_placeholder(text: str) -> bool:
    """True if the cell states that nothing applies ("NA", "No change", "Nil")."""
    return _norm(text).strip(" .*") in _PLACEHOLDERS


def _is_ditto(text: str) -> bool:
    """True if the cell is a back-reference to the row above ("-do-", "As above")."""
    return _norm(text).strip(" .*") in _DITTO


def _classify(text: str) -> str | None:
    """Map a Condition-column string to a scenario key. Returns None if unknown."""
    t = _clean(text).lower()
    if not t:
        return None
    if "terminal" in t:
        return "terminal_drought"
    if "mid season" in t or "mid-season" in t:
        return "mid_season_break"
    if any(k in t for k in ("flood", "water logging", "waterlogging",
                            "high rainfall", "heavy rain", "excess rain")):
        return "excess_rainfall_waterlogging"
    if "delay by 2" in t or ("delayed onset" in t and "2 week" in t):
        return "delayed_monsoon"
    if any(k in t for k in ("delay by 4", "delay by 6", "delay by 8",
                            "early season", "delayed onset", "dry spell",
                            "normal onset")):
        return "early_season_dry_spell"
    return None


# Header rows may be split vertically across several physical rows, so we build a
# per-column "header profile" by joining the first few rows of each column.
_HEADER_DEPTH = 5
_HEADER_HINTS = ("condition", "contingency measures", "contingency measure",
                 "farming situation", "change in", "crop management", "agronomic",
                 "soil management", "soil nutrient", "moisture conservation",
                 "remarks on")

# The floods / waterlogging sections use a different matrix: rows are crops and
# columns are crop growth stages, each cell holding the advice for that stage.
_STAGE_KEYS = ("seedling", "nursery stage", "vegetative stage", "flowering stage",
               "crop maturity", "maturity stage", "post harvest",
               "reproductive stage", "at harvest")

# Longest a cell may be while still counting as a column header label. The real
# labels top out around 50 chars ("Change in crop / cropping system including
# variety"); advice blobs run far longer.
_HEADER_CELL_MAX_LEN = 60


def _header_cell_text(row: list) -> str:
    """Join only the cells of ``row`` that could plausibly be header labels.

    Header detection matches keywords such as "seedling" or "crop management",
    but those words also occur inside ordinary advice ("Gap filling with
    seedlings ..."). Matching against the whole row therefore mistakes data rows
    for header rows; the row then lands in the column header profile and
    ``_split_actions`` deletes that advice as a header fragment.

    A genuine header cell is a short label and never carries a bullet glyph,
    whereas advice cells are bulleted, long, or both.
    """
    keep = []
    for cell in row:
        text = _clean(cell)
        if not text or len(text) >= _HEADER_CELL_MAX_LEN:
            continue
        if any(b in text for b in _BULLETS):
            continue
        keep.append(text)
    return _norm(" ".join(keep))


def _analyze_table(
    table: list[list],
) -> tuple[dict[str, int], int, str | None, list[str]] | None:
    """Identify column roles, where data rows begin, and the table-level scenario.

    Templates vary a lot between districts: some plans use a compact 6-column
    matrix, others a 15-16 column grid padded with empty spacer columns and a
    header split across 3-4 physical rows. Rather than assume fixed indices we
    join the leading rows per column and match role keywords against that.

    Returns ``(roles, data_start, table_scenario, col_header)`` or None if the
    table is not a recognizable contingency matrix.
    """
    if not table or len(table) < 2:
        return None
    ncols = max(len(r) for r in table)
    if ncols < 3:  # 1-column fragments pdfplumber emits alongside the real table
        return None

    limit = min(_HEADER_DEPTH, len(table))

    # 1) Locate the end of the header block *before* profiling columns, so the
    #    profile never absorbs real data rows.
    #
    #    Three template patterns:
    #    (a) Header rows, then data rows with condition text (classic template).
    #    (b) A mixed row carries condition text *and* column sub-headers
    #        (Sikkim): treat it as both header (for profiling) and data.
    #    (c) A pure header row carries condition text but no sub-headers
    #        (West Bengal flood tables): keep scanning for sub-header rows
    #        before data starts.
    data_start = 0
    header_end = 0
    # Hints that indicate sub-headers alongside condition text (Sikkim mixed
    # row).  "condition" is excluded because it appears in the condition column
    # header itself and would falsely trigger the mixed-row path.
    _SUBHEADER_HINTS = tuple(k for k in _HEADER_HINTS if k != "condition")
    for ri, row in enumerate(table[:limit]):
        has_condition = any(_classify(_clean(c)) for c in row)
        # Only header-shaped cells may vote for this row being a header; see
        # _header_cell_text. Matching the whole row would let a keyword buried in
        # advice ("Gap filling with seedlings") promote a data row to a header.
        labels = _header_cell_text(row)
        has_subheader = any(k in labels for k in _SUBHEADER_HINTS + _STAGE_KEYS)
        has_header_hint = any(k in labels for k in _HEADER_HINTS + _STAGE_KEYS)
        if has_condition and has_subheader:
            # Mixed header/data row (Sikkim pattern): condition text in one
            # cell, column sub-headers in other cells of the same row.
            header_end = ri + 1
            data_start = ri
            break
        if has_condition:
            if data_start > 0:
                # data_start already set by a prior header row → this is a
                # data row with condition text (classic template).  Break.
                break
            # Pure header row with condition text but no sub-headers
            # (West Bengal flood tables).  Keep scanning for sub-header rows.
            header_end = ri + 1
            continue
        if has_header_hint:
            data_start = ri + 1
            header_end = ri + 1
    if header_end == 0:
        return None
    # Headers frequently wrap onto further rows ("change in" / "crop/cropping" /
    # "system"). Keep consuming short fragment rows that state no condition.
    while data_start < limit:
        cells = [_clean(c) for c in table[data_start]]
        nonempty = [c for c in cells if c]
        if not nonempty or any(_classify(c) for c in cells):
            break
        if not all(len(c) < 25 for c in nonempty):
            break
        data_start += 1
        header_end = max(header_end, data_start)

    # 2) Build a per-column header profile from the header rows only.
    col_header: list[str] = []
    for ci in range(ncols):
        parts = [_clean(r[ci]) for r in table[:header_end] if ci < len(r)]
        col_header.append(_norm(" ".join(p for p in parts if p)))

    roles: dict[str, int] = {}
    stages: dict[int, str] = {}
    for ci, h in enumerate(col_header):
        if not h:
            continue
        if ("change in" in h and "crop" in h) or "crop management" in h:
            roles.setdefault("change", ci)
        elif any(k in h for k in ("agronomic", "soil nutrient", "soil management",
                                  "moisture conservation")):
            roles.setdefault("agro", ci)
        elif "remarks" in h:
            roles.setdefault("remarks", ci)
        # "normal" and "farming" are never harvested, but they are needed as
        # anchors so neighbouring columns are not misattributed to an action.
        elif "crop" in h and "system" in h:
            roles.setdefault("normal", ci)
        elif "farming situation" in h:
            roles.setdefault("farming", ci)
        elif "condition" in h:
            roles.setdefault("condition", ci)
        for sk in _STAGE_KEYS:
            if sk in h:
                # Label by the matched stage keyword; the raw profile often also
                # contains the spanning "suggested contingency measure" header.
                stages[ci] = sk
                break

    # Prefer the measures matrix; fall back to the crop x growth-stage matrix.
    if "change" not in roles and "agro" not in roles:
        if len(stages) < 2:
            return None
        # Keep the leading condition/crop column as an anchor, otherwise the crop
        # names in column 0 get attracted to the first stage column and emitted.
        cond_anchor = roles.get("condition", 0)
        roles = {f"stage:{label}": ci for ci, label in stages.items()}
        if cond_anchor not in stages:
            roles["condition"] = cond_anchor

    # Table-level scenario from the whole header block (e.g. "Mid season drought
    # (long dry spell)"), used when an individual row does not restate it.
    header_blob = " ".join(col_header)
    table_scen = _classify(header_blob)

    return roles, data_start, table_scen, col_header


def _nearest_role_map(roles: dict[str, int], ncols: int) -> dict[int, str]:
    """Assign every column to its nearest header anchor.

    Wide ICAR grids pad the matrix with empty spacer columns, and a header label
    often lands one column away from the data beneath it. Matching on exact
    indices therefore drops content, so each cell is attributed to the closest
    header anchor instead (ties resolve to the left-most anchor).
    """
    anchors = sorted((ci, role) for role, ci in roles.items())
    mapping: dict[int, str] = {}
    for ci in range(ncols):
        best_role, best_dist = None, None
        for aci, role in anchors:
            dist = abs(aci - ci)
            if best_dist is None or dist < best_dist:
                best_role, best_dist = role, dist
        if best_role is not None:
            mapping[ci] = best_role
    return mapping


def _valid_action(piece: str) -> bool:
    if not piece:
        return False
    if _is_header_label(piece):
        return False
    # Continuation fragments from page-break-split rows start with a lowercase
    # letter (they are the tail of a sentence whose beginning was on the previous
    # page).  Legitimate ICAR actions always start with an uppercase imperative
    # verb or a number marker.  Only filter short fragments — long lowercase
    # text (e.g. "spray water soluble fertilizers like 19-19-19...") is real
    # advice that merely lost its capitalisation during bullet splitting.
    first_alpha = re.search(r"[A-Za-z]", piece)
    if first_alpha and first_alpha.group().islower() and len(piece.split()) < 9:
        return False
    words = [w for w in re.findall(r"[A-Za-z]{3,}", piece)]
    if not words:  # numbers/symbols only
        return False
    if len(piece) < 4:
        return False
    return True


def _split_actions(cell: str, col_header: str = "") -> list[str]:
    """Split a cell into candidate actions, dropping this column's header fragments.

    Headers are frequently split across several physical rows, so stray pieces
    like "crop/cropping" or "system" can survive into the data rows. Any short
    candidate that is merely a substring of its own column's header profile is
    header text, not advice.
    """
    cell = _clean(cell)
    if not cell:
        return []
    out = []
    for chunk in _BULLET_SPLIT.split(cell):
        # Cells often enumerate steps inline ("1. ... 2. ...") instead of using
        # bullets, so split those out too rather than emitting one long blob.
        for p in (_clean(x) for x in _ENUM_SPLIT.split(chunk)):
            if not _valid_action(p):
                continue
            n = _norm(p)
            if col_header and len(n) < 60 and n in col_header:
                continue
            out.append(p)
    return out


def extract_pdf(pdf_path: Path) -> dict:
    """Extract verbatim contingency actions with provenance from one plan PDF."""
    scenarios: dict[str, list[dict]] = {s: [] for s in SCENARIOS}
    seen: dict[str, set] = {s: set() for s in SCENARIOS}

    with pdfplumber.open(pdf_path) as pdf:
        npages = len(pdf.pages)
        # Stage-matrix and measures-matrix tables often span multiple pages
        # without repeating the header.  We carry the last header table's
        # analysis so continuation tables can be processed.
        last_stage: tuple[dict[str, int], str | None, list[str], int] | None = None
        last_measures: tuple[dict[str, int], str | None, list[str], int] | None = None
        for pi, page in enumerate(pdf.pages):
            for table in page.extract_tables():
                if not table or len(table) < 2:
                    continue
                ncols = max(len(r) for r in table)
                if ncols < 3:
                    continue
                analyzed = _analyze_table(table)
                if analyzed:
                    roles, data_start, table_scen, col_header = analyzed
                    stage_cols = {r for r in roles if r.startswith("stage:")}
                    if stage_cols:
                        last_stage = (roles, table_scen, col_header, ncols)
                        last_measures = None
                    else:
                        last_stage = None  # reset on non-stage table
                        last_measures = (roles, table_scen, col_header, ncols)
                elif last_stage:
                    # Continuation of a stage matrix from a previous page.
                    s_roles, s_scen, s_col_header, s_ncols = last_stage
                    if ncols != s_ncols:
                        continue
                    # Require at least 2 non-empty cells in stage columns to
                    # avoid matching unrelated tables with the same width.
                    s_wanted = {r for r in s_roles if r.startswith("stage:")}
                    s_col_to_role = _nearest_role_map(s_roles, ncols)
                    nonempty = sum(
                        1 for row in table for ci, cell in enumerate(row)
                        if ci < ncols and s_col_to_role.get(ci) in s_wanted
                        and _clean(cell)
                    )
                    if nonempty < 2:
                        continue
                    roles, data_start = s_roles, 0
                    table_scen, col_header = s_scen, s_col_header
                    stage_cols = s_wanted
                elif last_measures:
                    # Continuation of a measures matrix from a previous page.
                    m_roles, m_scen, m_col_header, m_ncols = last_measures
                    if ncols != m_ncols:
                        continue
                    # Require at least one classifiable condition cell to
                    # confirm this is a continuation, not an unrelated table.
                    has_cond = any(_classify(_clean(c)) for row in table for c in row)
                    if not has_cond:
                        continue
                    roles, data_start = m_roles, 0
                    table_scen, col_header = m_scen, m_col_header
                    stage_cols = set()
                else:
                    continue
                wanted = stage_cols or {"change", "agro"}
                col_to_role = _nearest_role_map(roles, ncols)
                last_scen = table_scen
                cond_idx = roles.get("condition", 0)
                # Row context. In these tables a farming situation (and often a
                # crop) spans several rows via a merged cell, which pdfplumber
                # reports as blanks on the continuation rows, so carry the last
                # seen value forward. In a stage matrix the leading column holds
                # the crop instead.
                crop_idx = roles.get("normal", roles.get("condition") if stage_cols else None)
                farm_idx = roles.get("farming")
                cur_crop = cur_farm = ""
                # Previous cell text per column, used to resolve "-do-" ditto marks.
                prev_cell: dict[int, str] = {}
                for row in table[data_start:]:
                    # The condition may sit in a shifted/merged cell, so scan the
                    # leading columns up to and including the nominal condition
                    # column and take the first one that classifies.
                    scen = None
                    for ci in range(0, min(len(row), max(cond_idx, 0) + 1)):
                        scen = _classify(_clean(row[ci]))
                        if scen:
                            break
                    if scen:
                        last_scen = scen
                    if not last_scen:
                        continue

                    if farm_idx is not None and farm_idx < len(row):
                        v = _clean(row[farm_idx])
                        if v and not _is_header_label(v):
                            cur_farm = v
                    if crop_idx is not None and crop_idx < len(row):
                        v = _clean(row[crop_idx])
                        # A condition restated in the crop column is not a crop.
                        if v and not _is_header_label(v) and not _classify(v):
                            cur_crop = v

                    for ci, cell in enumerate(row):
                        role = col_to_role.get(ci)
                        if role not in wanted:
                            continue
                        anchor = roles.get(role, ci)
                        hdr = " ".join(col_header[i] for i in {ci, anchor}
                                       if i < len(col_header))
                        text = _clean(cell)
                        if not text:
                            continue
                        # Flags are independent: a ditto can resolve to a
                        # placeholder, and downstream filters must see both.
                        from_ditto = False
                        if _is_ditto(text):
                            # "-do-" means "same as the row above" in the source.
                            # Substitute that text and record that we did so.
                            carried = prev_cell.get(ci, "")
                            if not carried:
                                continue
                            text, from_ditto = carried, True
                        else:
                            prev_cell[ci] = text
                        placeholder = _is_placeholder(text)

                        for action in _split_actions(text, hdr):
                            # Dedup on the full row context, not the text alone:
                            # the same advice legitimately recurs for different
                            # crops and farming situations, and collapsing those
                            # silently loses crop coverage.
                            key = (action.lower(), cur_crop.lower(),
                                   cur_farm.lower(), role)
                            if key in seen[last_scen]:
                                continue
                            seen[last_scen].add(key)
                            rec = {"action": action, "page": pi, "column": role}
                            if cur_crop:
                                rec["crop"] = cur_crop
                            if cur_farm:
                                rec["farming_situation"] = cur_farm
                            if from_ditto:
                                # Text was carried from the row above ("-do-").
                                rec["resolved_from_ditto"] = True
                            if placeholder:
                                # Source says nothing applies ("NA", "No change").
                                rec["placeholder"] = True
                            scenarios[last_scen].append(rec)
    return {"pages": npages, "scenarios": scenarios}


def _load_manifest() -> list[dict[str, str]]:
    if not MANIFEST.exists():
        sys.exit(f"Manifest not found: {MANIFEST}")
    with open(MANIFEST, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--district", help="only extract the given district (case-insensitive)")
    ap.add_argument("-o", "--output", type=Path, default=DEFAULT_OUT,
                    help=f"output JSON path (default {DEFAULT_OUT.relative_to(ROOT)})")
    args = ap.parse_args()

    rows = _load_manifest()
    if args.district:
        rows = [r for r in rows if r["district"].lower() == args.district.lower()]
        if not rows:
            sys.exit(f"No manifest entry for district: {args.district}")

    out = []
    for row in rows:
        pdf_path = PLANS_DIR / row["filename"]
        if not pdf_path.exists():
            print(f"MISSING  {row['district']} ({row['filename']}) — run download_icar_pdfs.py")
            continue
        try:
            res = extract_pdf(pdf_path)
        except Exception as exc:
            print(f"ERROR    {row['district']} ({row['filename']}): {exc}")
            continue
        counts = {s: len(v) for s, v in res["scenarios"].items()}
        print(f"{row['district']:<12} pages={res['pages']:<3} "
              + " ".join(f"{s.split('_')[0]}={counts[s]}" for s in SCENARIOS))
        out.append({
            "state": row["state"], "district": row["district"],
            "source_pdf": row["filename"], "pages": res["pages"],
            "extractor": "table-aware-verbatim-v2",
            "scenarios": res["scenarios"],
        })

    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        display = args.output.relative_to(ROOT)
    except ValueError:
        display = args.output
    print(f"\nWrote {len(out)} district(s) -> {display}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
