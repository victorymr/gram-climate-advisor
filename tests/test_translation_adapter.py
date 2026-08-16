from pathlib import Path

from i18n import action_text, display_action, make_action, t
from translation_adapter import IndicTrans2Adapter, JsonTranslationAdapter

ROOT = Path(__file__).resolve().parent.parent


def test_json_adapter_translates_catalog_action():
    adapter = JsonTranslationAdapter(str(ROOT / "data" / "translations.json"))
    assert adapter.translate("Retransplanting through Dapog nursery if needed", "hi") == (
        "आवश्यकता होने पर डैपोग नर्सरी के माध्यम से दोबारा रोपाई करें"
    )


def test_action_record_uses_catalog_translation():
    action = make_action("Protect important documents and valuables", source="icar")
    assert display_action(action, "hi") == "महत्वपूर्ण दस्तावेज़ों और कीमती वस्तुओं को सुरक्षित रखें"
    assert str(action) == "Protect important documents and valuables"


def test_indictrans2_adapter_maps_hindi_language_code():
    class FakeModel:
        def batch_translate(self, texts, source, target):
            assert texts == ["Store water"]
            assert source == "eng_Latn"
            assert target == "hin_Deva"
            return ["पानी जमा करें"]

    adapter = IndicTrans2Adapter("unused", model=FakeModel())
    assert adapter.translate("Store water", "hi") == "पानी जमा करें"


def test_missing_language_falls_back_to_source_text():
    text = "A new action without a catalog entry"
    assert action_text(text, "bn") == text
    assert t("recommended_actions", "bn") == "📋 Recommended Actions"
