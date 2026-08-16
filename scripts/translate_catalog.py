#!/usr/bin/env python3
"""Populate the translation catalog with offline IndicTrans2 translations.

Example (from the advisor project root, using the IndicTrans2 inference environment):
    python scripts/translate_catalog.py --language hi --checkpoint-dir /models/indictrans2

The script only adds missing translations and marks them ``machine_translated``.
Review entries before changing their status to ``approved``.
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable, Set

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from advisory import AdvisoryGenerator
from translation_adapter import IndicTrans2Adapter


def _action_strings(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        action = value.get("action")
        if isinstance(action, str) and action.strip():
            yield action.strip()
        for child in value.values():
            yield from _action_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _action_strings(child)


def collect_action_texts(data_path: Path) -> Set[str]:
    """Collect built-in and ICAR action strings without changing source data."""
    texts = set()
    advisor = AdvisoryGenerator()
    for scenario in advisor.action_library.values():
        for key, values in scenario.items():
            if key.startswith(("do_now", "prepare", "avoid")):
                texts.update(value for value in values if isinstance(value, str))

    if data_path.exists():
        with data_path.open(encoding="utf-8") as fh:
            source_data = json.load(fh)
        texts.update(_action_strings(source_data))

    return {text for text in texts if len(text) > 2}


def _normalize(text: str) -> str:
    return " ".join(text.replace("’", "'").split()).strip(" .,;:").lower()


def update_catalog(catalog_path: Path, source_path: Path, language: str, translator, limit: int = 0) -> int:
    with catalog_path.open(encoding="utf-8") as fh:
        catalog = json.load(fh)
    actions = catalog.setdefault("actions", {})
    existing = {_normalize(record.get("source_text", "")) for record in actions.values()}
    texts = sorted(collect_action_texts(source_path), key=str.casefold)
    missing = [text for text in texts if _normalize(text) not in existing]
    if limit:
        missing = missing[:limit]

    translated = 0
    for text in missing:
        result = translator.translate(text, language)
        if not result:
            continue
        action_id = "icar_" + hashlib.sha1(_normalize(text).encode("utf-8")).hexdigest()[:16]
        actions[action_id] = {
            "source_text": text,
            "translations": {language: result},
            "status": {language: "machine_translated"},
        }
        translated += 1

    with catalog_path.open("w", encoding="utf-8") as fh:
        json.dump(catalog, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return translated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", default="hi", choices=sorted(IndicTrans2Adapter.LANGUAGE_CODES))
    parser.add_argument("--checkpoint-dir", required=True)
    parser.add_argument("--model-type", default="fairseq", choices=("fairseq", "ctranslate2"))
    parser.add_argument("--catalog", type=Path, default=ROOT / "data" / "translations.json")
    parser.add_argument("--icar-data", type=Path, default=ROOT / "data" / "icar_contingency_actions.json")
    parser.add_argument("--limit", type=int, default=0, help="Translate at most N missing entries")
    args = parser.parse_args()

    adapter = IndicTrans2Adapter(args.checkpoint_dir, model_type=args.model_type)
    count = update_catalog(args.catalog, args.icar_data, args.language, adapter, args.limit)
    print(f"Added {count} {args.language} machine translations to {args.catalog}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
