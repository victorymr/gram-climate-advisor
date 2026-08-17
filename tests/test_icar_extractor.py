"""Regression tests for the ICAR contingency-plan table extractor.

The source PDFs are git-ignored, so real tables from each known template variant
are frozen verbatim into tests/fixtures/icar_tables.json. These tests pin the
behaviour that was established by hand while hardening scripts/extract_icar_pdf.py,
so a fix for one state's template cannot silently regress another's.

Template variants covered:
  compact_measures_gaya         6-column measures matrix (the classic layout)
  wide_padded_kurnool           15-column grid padded with empty spacer columns
  stage_matrix_westbengal       crop x growth-stage matrix (floods/waterlogging)
  header_condition_only_wb      condition text in a header row with no sub-headers
  mixed_header_row_goa          condition text and sub-headers sharing one row
  measures_continuation_andaman a continuation table with no header of its own
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from extract_icar_pdf import (  # noqa: E402
    SCENARIOS,
    _analyze_table,
    _classify,
    _clean,
    _is_ditto,
    _is_header_label,
    _is_placeholder,
    _nearest_role_map,
    _split_actions,
    _valid_action,
)

FIXTURES = json.load(open(ROOT / "tests" / "fixtures" / "icar_tables.json",
                          encoding="utf-8"))


def _table(label):
    return FIXTURES[label]["table"]


# --------------------------------------------------------------------------
# Template detection: roles, data_start and table scenario per variant
# --------------------------------------------------------------------------

@pytest.mark.parametrize("label", sorted(FIXTURES))
def test_analysis_matches_frozen_expectation(label):
    """Every fixture must analyze exactly as recorded when it was captured."""
    fx = FIXTURES[label]
    expect = fx["expect"]
    got = _analyze_table(_table(label))

    if expect["roles"] is None:
        assert got is None, f"{label}: expected standalone rejection, got {got}"
        return

    assert got is not None, f"{label}: table is no longer recognized"
    roles, data_start, scenario, _col_header = got
    assert sorted(roles) == expect["roles"], f"{label}: column roles drifted"
    assert data_start == expect["data_start"], f"{label}: header depth drifted"
    assert scenario == expect["scenario"], f"{label}: table scenario drifted"


def test_data_start_never_swallows_all_rows():
    """A recognized table must leave at least one data row behind the header."""
    for label, fx in FIXTURES.items():
        if fx["expect"]["roles"] is None:
            continue
        table = fx["table"]
        _roles, data_start, _scen, _ch = _analyze_table(table)
        assert data_start < len(table), (
            f"{label}: data_start={data_start} consumed the whole table")


@pytest.mark.parametrize("label", sorted(FIXTURES))
def test_column_header_profile_never_absorbs_advice(label):
    """Header profiles must contain only header text.

    If a data row is mistaken for a header row, its advice lands in the column
    header profile and `_split_actions` then deletes that advice as a "header
    fragment" -- silently losing real actions. Bullet glyphs occur only in advice
    cells, so their presence in a profile proves the header block over-ran.
    """
    fx = FIXTURES[label]
    if fx["expect"]["roles"] is None:
        return
    _roles, _ds, _scen, col_header = _analyze_table(fx["table"])
    bullets = "\uf0b7\uf0d8\uf076\uf0a7\uf0fc\uf0e0\u2022\u25cf"
    polluted = [(i, h) for i, h in enumerate(col_header)
                if any(b in h for b in bullets)]
    assert not polluted, f"{label}: advice leaked into header profile: {polluted}"


def test_stage_matrix_recovers_every_stage_column():
    """Regression: the vegetative-stage column was previously missed.

    Its header profile had been polluted by the data row below it, so the column
    was not recognized as a stage column and most of its advice was discarded.
    """
    roles, _ds, _scen, _ch = _analyze_table(_table("header_condition_only_wb"))
    stages = {k for k in roles if k.startswith("stage:")}
    assert stages == {
        "stage:seedling", "stage:vegetative stage",
        "stage:reproductive stage", "stage:at harvest",
    }, f"stage columns missing: {stages}"


def test_stage_matrix_harvest_is_not_decimated_by_header_filter():
    """The same table yielded only 2 actions before the header-pollution fix."""
    got = _harvest("header_condition_only_wb")
    assert len(got) >= 9, f"expected >=9 actions, got {len(got)}: {got}"


def test_advice_containing_a_stage_phrase_does_not_become_a_header():
    """A data row is not a header just because its text says "maturity stage".

    Six Uttar Pradesh districts lost their only terminal-drought advice this way.
    """
    table = [
        ["Condition", "Major Farming situation", "Normal Crop/cropping system",
         "Crop management", "Remarks on Implementation"],
        ["Terminal drought", "Irrigated upland", "Rice: PS 4",
         "1.Life saving irrigation 2.Picking/harvesting of pods "
         "3.Harvest at physiological maturity stage 4.Harvest for fodder", ""],
    ]
    roles, data_start, _scen, col_header = _analyze_table(table)
    assert data_start == 1, f"data row absorbed into header: data_start={data_start}"
    ci = roles["change"]
    assert "life saving irrigation" not in col_header[ci], (
        f"advice leaked into header profile: {col_header[ci]!r}")
    recs = _extract_synthetic(table)
    actions = [r["action"] for r in recs]
    assert "Life saving irrigation" in actions, actions
    assert "Harvest at physiological maturity stage" in actions, actions


def test_stage_matrix_keeps_condition_anchor():
    """Stage matrices must retain the leading column as an anchor.

    Without it the crop names in column 0 get attracted to the first stage
    column and are emitted as advice.
    """
    for label in ("stage_matrix_westbengal", "header_condition_only_wb"):
        roles, _ds, _scen, _ch = _analyze_table(_table(label))
        assert any(k.startswith("stage:") for k in roles), f"{label}: not a stage matrix"
        assert "condition" in roles, f"{label}: lost the condition anchor"


def test_measures_matrix_has_a_harvestable_column():
    """The measures variants must expose at least one column we harvest from."""
    for label in ("compact_measures_gaya", "wide_padded_kurnool",
                  "mixed_header_row_goa"):
        roles, _ds, _scen, _ch = _analyze_table(_table(label))
        assert {"change", "agro"} & set(roles), f"{label}: nothing to harvest"


def test_narrow_and_empty_tables_are_rejected():
    """pdfplumber emits 1-column fragments alongside real tables; ignore them."""
    assert _analyze_table([]) is None
    assert _analyze_table([["Condition"]]) is None
    assert _analyze_table([["Condition", "Crop management"]]) is None  # <3 cols
    assert _analyze_table([["a", "b", "c"]]) is None  # single row


# --------------------------------------------------------------------------
# Scenario classification
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Terminal drought (Early withdrawal of monsoon)", "terminal_drought"),
    ("Mid season drought (long dry spell)", "mid_season_break"),
    ("Mid-season drought", "mid_season_break"),
    ("Continuous high rainfall in a short span", "excess_rainfall_waterlogging"),
    ("Condition - Transient water logging", "excess_rainfall_waterlogging"),
    ("Floods", "excess_rainfall_waterlogging"),
    ("Delay by 2 weeks", "delayed_monsoon"),
    ("Delay by 4 weeks", "early_season_dry_spell"),
    ("Delay by 6 weeks", "early_season_dry_spell"),
    ("Early season drought (delayed onset)", "early_season_dry_spell"),
    ("Normal onset followed by 15-20 days dry spell", "early_season_dry_spell"),
    ("", None),
    ("Rice-Fallow Vr. Local", None),
    ("Major Farming situation", None),
])
def test_classify(text, expected):
    assert _classify(text) == expected


def test_every_classification_is_a_known_scenario():
    samples = ["Terminal drought", "Mid season drought", "Floods",
               "Delay by 2 weeks", "Delay by 8 weeks", "Normal onset"]
    for s in samples:
        assert _classify(s) in SCENARIOS


# --------------------------------------------------------------------------
# Action filtering: header fragments and junk must never surface as advice
# --------------------------------------------------------------------------

@pytest.mark.parametrize("label", [
    "condition", "Suggested Contingency measures", "Major Farming situation",
    "Normal Crop/cropping system", "Change in crop/cropping system",
    "Crop management", "Agronomic measures", "Remarks on Implementation",
    "Vegetative stage", "At harvest",
])
def test_header_labels_are_recognized(label):
    assert _is_header_label(label)


def test_header_label_tolerates_footnote_marker():
    """ICAR footnote markers append a stray letter, e.g. 'agronomic measuresi'."""
    assert _is_header_label("Agronomic measuresi")
    assert _is_header_label("Crop managementc")
    assert _is_header_label("Remarks on Implementatione")


def test_valid_action_rejects_non_advice():
    for junk in ("", "-", "1.", "2)", "a", "12", "  ", "***"):
        assert not _valid_action(junk), f"{junk!r} should be rejected"


def test_valid_action_rejects_continuation_fragments():
    """Page-break continuation fragments start with lowercase and are short."""
    for frag in ("earliest", "and whitefly", "be marketed.", "mildew",
                 "by rotating the chemicals", "measures to be initiated",
                 "aerated place", "form the field", "as early as possible",
                 "as soon as possible", "soon as possible", "as possible",
                 "marketed.", "once.", "times.",
                 "smother the weeds and to aerate the soil"):
        assert not _valid_action(frag), f"{frag!r} should be rejected as a continuation fragment"


def test_valid_action_accepts_long_lowercase_advice():
    """Long lowercase-first text is legitimate advice, not a continuation fragment."""
    for good in ("spray water soluble fertilizers like 19-19-19, 20-20-20, 21-21-21 at 1% to the crop",):
        assert _valid_action(good), f"{good!r} should be accepted"


def test_valid_action_rejects_stage_subheaders():
    """Growth-stage sub-headers must not be emitted as actions."""
    for label in ("Grand Growth stage", "Formative Phase", "Formative stage",
                  "Maturity stage", "Nursery stage", "Flowering stage",
                  "Seedling stage"):
        assert not _valid_action(label), f"{label!r} should be rejected as a stage sub-header"


def test_valid_action_accepts_real_advice():
    for good in ("Drain the excess water after recession of flood",
                 "Gap filling", "Mulching", "Apply 30 kg N per acre"):
        assert _valid_action(good), f"{good!r} should be accepted"


def test_split_actions_splits_on_bullet_glyphs():
    cell = "\uf0b7 Drain the excess water\n\uf0b7 Apply urea after drainage"
    got = _split_actions(cell)
    assert got == ["Drain the excess water", "Apply urea after drainage"]


def test_split_actions_never_splits_on_en_dash():
    """En-dash separates a crop from its variety and must stay intact."""
    cell = "Pigeonpea \u2013 Bahar, Pusa-9"
    assert _split_actions(cell) == ["Pigeonpea \u2013 Bahar, Pusa-9"]


def test_split_actions_drops_own_column_header_fragment():
    """A short candidate that is a substring of its own column header is header text."""
    hdr = "suggested contingency measures crop management"
    assert _split_actions("Crop management", hdr) == []
    # ...but genuine advice in the same column survives.
    assert _split_actions("Apply life saving irrigation", hdr) == [
        "Apply life saving irrigation"]


# --------------------------------------------------------------------------
# Inline enumerations ("1. ... 2. ...") are split into discrete actions
# --------------------------------------------------------------------------

def test_split_actions_splits_numbered_enumerations():
    cell = ("1. Excess water from the field to be drained out "
            "2. Intercultivate with gorru 3. Delay the sowing")
    assert _split_actions(cell) == [
        "Excess water from the field to be drained out",
        "Intercultivate with gorru",
        "Delay the sowing",
    ]


def test_split_actions_splits_roman_enumerations():
    cell = "i. If there is poor germination go for resowing ii. Apply urea"
    assert _split_actions(cell) == [
        "If there is poor germination go for resowing", "Apply urea"]


def test_split_actions_splits_enumerations_with_no_space_after_marker():
    """The common real-world form omits the space: "1.Drain ... 2.Apply ..."."""
    cell = ("1.Drain the excess water as early as possible in black soils "
            "2.Apply 20 kg N /ha after draining excess water "
            "3.Take up inter cultivation")
    assert _split_actions(cell) == [
        "Drain the excess water as early as possible in black soils",
        "Apply 20 kg N /ha after draining excess water",
        "Take up inter cultivation",
    ]


@pytest.mark.parametrize("cell", [
    # Fertiliser grades must not be mistaken for enumerators.
    "spray water soluble fertilizers like 19-19-19, 20-20-20, 21-21-21 at 1% to the crop",
    # Decimals must not split: the char after "1." is a digit, not a letter.
    "Apply 1.5 kg seed per hectare",
    "Use 2.5 litre per acre of the solution",
    # Dosage decimals mid-sentence, the no-space case's main hazard.
    "Spray Mancozeb 0.25% two to three times",
    "Use Copper oxy chloride 0.3 % solution",
    # "i.e." looks exactly like a roman enumerator with no trailing space; the
    # uppercase requirement is what keeps it intact.
    "Drain the field i.e. remove standing water",
    # A bare percentage has no "." or ")" after the number.
    "Spray KNO3 1 % or water soluble fertilizer",
    # En-dash separates crop from variety.
    "Pigeonpea \u2013 Bahar, Pusa-9",
])
def test_split_actions_does_not_split_false_positives(cell):
    assert _split_actions(cell) == [cell], f"{cell!r} was wrongly split"


def test_enumeration_split_output_stays_verbatim():
    """Splitting may only remove the enumerator, never alter the advice text."""
    cell = "1. Drain the excess water 2. Apply 4-5 kg N /acre"
    for piece in _split_actions(cell):
        assert piece in cell


# --------------------------------------------------------------------------
# Placeholders and ditto marks
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "NA", "N.A.", "Nil", "None", "Not Applicable", "Not applicable-",
    "No change", "No Change", "no change in cropping system",
    "No need of contingency",
])
def test_placeholders_are_detected(text):
    assert _is_placeholder(text)


@pytest.mark.parametrize("text", [
    "-do-", "do", "As above", "same as above", "Ditto",
])
def test_ditto_marks_are_detected(text):
    assert _is_ditto(text)


def test_real_advice_is_neither_placeholder_nor_ditto():
    for good in ("Drain the excess water", "Gap filling", "Mulching",
                 "Apply 30 kg N per acre"):
        assert not _is_placeholder(good)
        assert not _is_ditto(good)


# --------------------------------------------------------------------------
# Row context capture and context-aware dedup
# --------------------------------------------------------------------------

def _synthetic_measures_table():
    """A minimal measures matrix where one advice string repeats across crops.

    Row 2 leaves the farming-situation cell blank, which is how pdfplumber
    reports a cell merged/spanned down from the row above.
    """
    return [
        ["Condition", "Major Farming situation", "Normal Crop/cropping system",
         "Crop management", "Agronomic measures"],
        ["Mid season drought", "Rainfed upland", "Rice", "Drain the excess water", ""],
        ["", "", "Maize", "Drain the excess water", ""],
    ]


def test_row_context_is_captured_and_forward_filled():
    recs = _extract_synthetic(_synthetic_measures_table())
    crops = {r.get("crop") for r in recs}
    assert crops == {"Rice", "Maize"}, f"crop context missing: {recs}"
    # The blank farming-situation cell on row 2 must inherit from row 1.
    assert all(r.get("farming_situation") == "Rainfed upland" for r in recs), recs


def test_identical_advice_for_different_crops_is_not_collapsed():
    """The pre-fix dedup keyed on text alone and lost the second crop."""
    recs = _extract_synthetic(_synthetic_measures_table())
    same_text = [r for r in recs if r["action"] == "Drain the excess water"]
    assert len(same_text) == 2, (
        f"expected one record per crop, got {len(same_text)}: {same_text}")


def test_exact_duplicate_within_same_context_is_still_collapsed():
    table = _synthetic_measures_table()
    table.append(["", "", "Maize", "Drain the excess water", ""])  # true duplicate
    recs = _extract_synthetic(table)
    maize = [r for r in recs if r.get("crop") == "Maize"
             and r["action"] == "Drain the excess water"]
    assert len(maize) == 1, f"true duplicate not collapsed: {maize}"


def test_ditto_is_resolved_from_the_row_above_and_flagged():
    table = [
        ["Condition", "Major Farming situation", "Normal Crop/cropping system",
         "Crop management", "Agronomic measures"],
        ["Mid season drought", "Rainfed upland", "Rice", "Provide drainage", ""],
        ["", "", "Maize", "-do-", ""],
    ]
    recs = _extract_synthetic(table)
    maize = [r for r in recs if r.get("crop") == "Maize"]
    assert maize, f"maize row produced nothing: {recs}"
    assert maize[0]["action"] == "Provide drainage", maize
    assert maize[0].get("resolved_from_ditto") is True, maize


def test_ditto_with_nothing_above_is_dropped_not_emitted_literally():
    table = [
        ["Condition", "Major Farming situation", "Normal Crop/cropping system",
         "Crop management", "Agronomic measures"],
        ["Mid season drought", "Rainfed upland", "Rice", "-do-", ""],
    ]
    recs = _extract_synthetic(table)
    assert not any(_is_ditto(r["action"]) for r in recs), (
        f"an unresolvable ditto leaked as advice: {recs}")


def test_placeholder_is_flagged_not_silently_dropped():
    table = [
        ["Condition", "Major Farming situation", "Normal Crop/cropping system",
         "Crop management", "Agronomic measures"],
        ["Mid season drought", "Rainfed upland", "Rice", "No change", ""],
    ]
    recs = _extract_synthetic(table)
    assert len(recs) == 1, recs
    assert recs[0]["action"] == "No change"
    assert recs[0].get("placeholder") is True, recs


def test_ditto_resolving_to_placeholder_carries_both_flags():
    """Flags are independent: filtering on `placeholder` must not miss dittos."""
    table = [
        ["Condition", "Major Farming situation", "Normal Crop/cropping system",
         "Crop management", "Agronomic measures"],
        ["Mid season drought", "Rainfed upland", "Rice", "No change", ""],
        ["", "", "Maize", "-do-", ""],
    ]
    recs = _extract_synthetic(table)
    maize = [r for r in recs if r.get("crop") == "Maize"]
    assert maize, recs
    assert maize[0].get("resolved_from_ditto") is True, maize
    assert maize[0].get("placeholder") is True, maize


def test_real_advice_carries_neither_flag():
    recs = _extract_synthetic(_synthetic_measures_table())
    for r in recs:
        assert "placeholder" not in r, r
        assert "resolved_from_ditto" not in r, r


def _extract_synthetic(table):
    """Drive extract_pdf's row walk over an in-memory table via monkeypatching."""
    import extract_icar_pdf as m

    class _FakePage:
        def __init__(self, t): self._t = t
        def extract_tables(self): return [self._t]

    class _FakePDF:
        def __init__(self, t): self.pages = [_FakePage(t)]
        def __enter__(self): return self
        def __exit__(self, *a): return False

    orig = m.pdfplumber.open
    m.pdfplumber.open = lambda _p: _FakePDF(table)
    try:
        res = m.extract_pdf(Path("synthetic.pdf"))
    finally:
        m.pdfplumber.open = orig
    return [r for lst in res["scenarios"].values() for r in lst]


# --------------------------------------------------------------------------
# Column drift: data cells map to the nearest header anchor
# --------------------------------------------------------------------------

def test_nearest_role_map_assigns_every_column():
    roles = {"condition": 0, "change": 4, "agro": 8}
    mapping = _nearest_role_map(roles, 10)
    assert set(mapping) == set(range(10))


def test_nearest_role_map_picks_closest_anchor():
    roles = {"condition": 0, "change": 4, "agro": 8}
    mapping = _nearest_role_map(roles, 10)
    assert mapping[0] == "condition"
    assert mapping[3] == "change"   # distance 1 vs 3
    assert mapping[4] == "change"
    assert mapping[7] == "agro"
    assert mapping[9] == "agro"


def test_nearest_role_map_ties_resolve_left():
    roles = {"change": 0, "agro": 2}
    mapping = _nearest_role_map(roles, 3)
    assert mapping[1] == "change", "ties must resolve to the left-most anchor"


# --------------------------------------------------------------------------
# End-to-end on a fixture: harvested advice is verbatim and header-free
# --------------------------------------------------------------------------

def _harvest(label):
    """Run the same row/column walk extract_pdf does, for one fixture table."""
    table = _table(label)
    roles, data_start, table_scen, col_header = _analyze_table(table)
    ncols = max(len(r) for r in table)
    stage_cols = {r for r in roles if r.startswith("stage:")}
    wanted = stage_cols or {"change", "agro"}
    col_to_role = _nearest_role_map(roles, ncols)
    cond_idx = roles.get("condition", 0)

    out, last_scen = [], table_scen
    for row in table[data_start:]:
        scen = None
        for ci in range(0, min(len(row), max(cond_idx, 0) + 1)):
            scen = _classify(_clean(row[ci]))
            if scen:
                break
        if scen:
            last_scen = scen
        if not last_scen:
            continue
        for ci, cell in enumerate(row):
            role = col_to_role.get(ci)
            if role not in wanted:
                continue
            anchor = roles.get(role, ci)
            hdr = " ".join(col_header[i] for i in {ci, anchor} if i < len(col_header))
            for action in _split_actions(cell, hdr):
                out.append((last_scen, action))
    return out


@pytest.mark.parametrize("label", [
    "compact_measures_gaya", "wide_padded_kurnool",
    "stage_matrix_westbengal", "header_condition_only_wb",
])
def test_fixture_yields_actions(label):
    got = _harvest(label)
    assert got, f"{label}: harvested nothing"
    for scen, _action in got:
        assert scen in SCENARIOS


@pytest.mark.parametrize("label", [
    "compact_measures_gaya", "wide_padded_kurnool",
    "stage_matrix_westbengal", "header_condition_only_wb",
    "mixed_header_row_goa",
])
def test_no_header_label_is_emitted_as_advice(label):
    leaked = [a for _s, a in _harvest(label) if _is_header_label(a)]
    assert not leaked, f"{label}: header labels emitted as advice: {leaked}"


@pytest.mark.parametrize("label", [
    "compact_measures_gaya", "wide_padded_kurnool",
    "stage_matrix_westbengal", "header_condition_only_wb",
])
def test_actions_are_verbatim_substrings_of_source_cells(label):
    """Nothing may be paraphrased: every action must appear in some source cell."""
    cells = [_clean(c) for row in _table(label) for c in row if c]
    for _scen, action in _harvest(label):
        assert any(action in c for c in cells), f"{label}: {action!r} is not verbatim"
