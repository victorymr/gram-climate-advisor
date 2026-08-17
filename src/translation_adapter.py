"""Provider-neutral translation catalog adapter.

The application reads cached translations from JSON. A future IndicTrans2 or
cloud provider can implement the same interface to populate missing entries
without changing the Streamlit or advisory code.
"""

import json
import os
import re
from typing import Any, Dict, Optional


class TranslationAdapter:
    """Interface for translating text by locale."""

    def translate(self, text: str, target_language: str, source_language: str = "en") -> Optional[str]:
        raise NotImplementedError


class JsonTranslationAdapter(TranslationAdapter):
    """Read reviewed or machine-generated translations from a JSON catalog."""

    def __init__(self, catalog_path: str):
        self.catalog_path = catalog_path
        self.catalog = self._load_catalog()

    def _load_catalog(self) -> Dict[str, Any]:
        if not os.path.exists(self.catalog_path):
            return {"actions": {}}
        with open(self.catalog_path, encoding="utf-8") as fh:
            return json.load(fh)

    @staticmethod
    def _normalize(text: str) -> str:
        text = str(text).replace("’", "'").replace("", " ")
        return re.sub(r"\s+", " ", text).strip().strip(" .,;:").lower()

    def translate(self, text: str, target_language: str, source_language: str = "en") -> Optional[str]:
        if target_language == source_language:
            return text
        normalized = self._normalize(text)
        for record in self.catalog.get("actions", {}).values():
            if self._normalize(record.get("source_text", "")) != normalized:
                continue
            translation = record.get("translations", {}).get(target_language)
            if translation:
                return translation
        return None


class IndicTrans2Adapter(TranslationAdapter):
    """Optional offline IndicTrans2 provider.

    IndicTrans2 is intentionally imported lazily because the main Streamlit app
    should run from the normal lightweight environment. Install/run IndicTrans2
    separately and pass its checkpoint directory when generating translations.
    """

    LANGUAGE_CODES = {
        "hi": "hin_Deva",
        "bn": "ben_Beng",
        "te": "tel_Telu",
        "ta": "tam_Taml",
        "mr": "mar_Deva",
        "gu": "guj_Gujr",
        "kn": "kan_Knda",
        "ml": "mal_Mlym",
        "or": "ory_Orya",
        "pa": "pan_Guru",
    }

    def __init__(self, checkpoint_dir: str, model_type: str = "fairseq", model=None):
        self.checkpoint_dir = checkpoint_dir
        self.model_type = model_type
        self._model = model

    @property
    def model(self):
        if self._model is None:
            try:
                from inference.engine import Model
            except ImportError as exc:
                raise RuntimeError(
                    "IndicTrans2 is not installed in this environment. "
                    "Use its separate inference environment or install the "
                    "official IndicTrans2 dependencies."
                ) from exc
            self._model = Model(self.checkpoint_dir, model_type=self.model_type)
        return self._model

    def translate(self, text: str, target_language: str, source_language: str = "en") -> Optional[str]:
        if source_language != "en":
            raise ValueError("IndicTrans2Adapter currently expects English source text")
        try:
            target_code = self.LANGUAGE_CODES[target_language]
        except KeyError as exc:
            raise ValueError(f"Unsupported IndicTrans2 target language: {target_language}") from exc
        result = self.model.batch_translate([text], "eng_Latn", target_code)
        return result[0] if result else None


class FallbackTranslationAdapter(TranslationAdapter):
    """Try a catalog/provider first, then a compatibility callback."""

    def __init__(self, primary: TranslationAdapter, fallback):
        self.primary = primary
        self.fallback = fallback

    def translate(self, text: str, target_language: str, source_language: str = "en") -> Optional[str]:
        return self.primary.translate(text, target_language, source_language) or self.fallback(
            text, target_language
        )
