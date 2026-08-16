"""Small, dependency-free localization layer for the Streamlit app."""

import os
import re

from translation_adapter import JsonTranslationAdapter


_CATALOG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "translations.json")
_CATALOG_TRANSLATOR = JsonTranslationAdapter(_CATALOG_PATH)


class ActionRecord(str):
    """String-compatible bilingual action with stable identity and provenance."""

    def __new__(cls, text_en, text_hi=None, action_id=None, source="unknown"):
        obj = super().__new__(cls, text_en)
        obj.text_en = text_en
        obj.text_hi = text_hi
        obj.action_id = action_id or action_id_for(text_en)
        obj.source = source
        return obj

    def display(self, language="en"):
        return self.text_hi if language == "hi" and self.text_hi else self.text_en


def action_id_for(text):
    """Create a stable fallback ID for legacy/source actions."""
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:120]


LANGUAGES = {"English": "en", "हिन्दी": "hi"}

_TRANSLATIONS = {
    "en": {
        "language": "Language",
        "header": "🌾 Rural Weather & Climate Risk Advisory",
        "header_subtitle": "Forecast-informed guidance for heat, monsoon delay, dry spells, and excess rainfall.",
        "location": "📍 Location",
        "context": "👤 Your Context",
        "select_by": "Select by",
        "dropdowns": "Dropdowns",
        "map": "Map",
        "select_state": "Select State",
        "select_district": "Select District",
        "user_type": "User Type",
        "crop_type": "Crop Type (Optional)",
        "irrigation": "Irrigation Status",
        "crop_stage": "Crop Stage (Optional)",
        "not_specified": "Not specified",
        "show_actions": "Show adaptation actions",
        "get_advisory": "🌱 Get Advisory",
        "do_now": "Do Now",
        "prepare": "Prepare",
        "avoid": "Avoid",
        "recommended_actions": "📋 Recommended Actions",
        "general_guidance": "ℹ️ General Guidance",
        "outlook": "📅 4-Week Outlook",
        "scenarios": "🎯 Risk Scenarios",
        "source_data": "📡 Source Data",
        "sources": "📚 Sources & Disclaimer",
        "overall_risk": "Overall Risk",
        "confidence": "Confidence",
        "active_concerns": "Active Concerns",
        "risk": "Risk",
        "no_immediate": "No immediate actions flagged.",
        "no_preparatory": "No preparatory actions flagged.",
        "no_cautions": "No specific cautions flagged.",
        "no_outlook": "No extended outlook available for this district.",
        "no_scenarios": "✅ No risk scenarios triggered. Baseline planning guidance applies.",
        "forecast_source": "Forecast source",
        "variable": "Variable",
        "week": "Week",
        "data_source": "Data source",
        "rainfall": "Rainfall",
        "temperature": "Temperature",
        "season_rainfall": "Season rainfall departure",
        "wetter": "Wetter than normal",
        "near": "Near normal",
        "drier": "Drier than normal",
        "very_unlikely": "Very unlikely",
        "unlikely": "Unlikely",
        "possible": "Possible",
        "likely": "Likely",
        "very_likely": "Very likely",
        "almost_certain": "Almost certain",
        "show_more": "Show {count} more",
    },
    "hi": {
        "language": "भाषा",
        "header": "🌾 ग्रामीण मौसम और जलवायु जोखिम सलाह",
        "header_subtitle": "गर्मी, मानसून में देरी, सूखे दौर और अधिक वर्षा के लिए पूर्वानुमान आधारित मार्गदर्शन।",
        "location": "📍 स्थान",
        "context": "👤 आपका संदर्भ",
        "select_by": "चुनने का तरीका",
        "dropdowns": "ड्रॉपडाउन",
        "map": "मानचित्र",
        "select_state": "राज्य चुनें",
        "select_district": "जिला चुनें",
        "user_type": "उपयोगकर्ता का प्रकार",
        "crop_type": "फसल का प्रकार (वैकल्पिक)",
        "irrigation": "सिंचाई की स्थिति",
        "crop_stage": "फसल की अवस्था (वैकल्पिक)",
        "not_specified": "उल्लेख नहीं किया गया",
        "show_actions": "अनुकूलन उपाय दिखाएँ",
        "get_advisory": "🌱 सलाह प्राप्त करें",
        "do_now": "अभी करें",
        "prepare": "तैयारी करें",
        "avoid": "बचें",
        "recommended_actions": "📋 सुझाए गए उपाय",
        "general_guidance": "ℹ️ सामान्य मार्गदर्शन",
        "outlook": "📅 4 सप्ताह का पूर्वानुमान",
        "scenarios": "🎯 जोखिम की स्थितियाँ",
        "source_data": "📡 स्रोत डेटा",
        "sources": "📚 स्रोत और अस्वीकरण",
        "overall_risk": "कुल जोखिम",
        "confidence": "विश्वसनीयता",
        "active_concerns": "सक्रिय चिंताएँ",
        "risk": "जोखिम",
        "no_immediate": "तुरंत करने योग्य कोई उपाय चिन्हित नहीं है।",
        "no_preparatory": "तैयारी के लिए कोई उपाय चिन्हित नहीं है।",
        "no_cautions": "कोई विशेष सावधानी चिन्हित नहीं है।",
        "no_outlook": "इस जिले के लिए विस्तृत पूर्वानुमान उपलब्ध नहीं है।",
        "no_scenarios": "✅ जोखिम की कोई स्थिति नहीं मिली। सामान्य योजना के अनुसार तैयारी करें।",
        "forecast_source": "पूर्वानुमान स्रोत",
        "variable": "चर",
        "week": "सप्ताह",
        "data_source": "डेटा स्रोत",
        "rainfall": "वर्षा",
        "temperature": "तापमान",
        "season_rainfall": "मौसम की वर्षा में बदलाव",
        "wetter": "सामान्य से अधिक वर्षा",
        "near": "सामान्य के आसपास",
        "drier": "सामान्य से कम वर्षा",
        "very_unlikely": "बहुत कम संभावना",
        "unlikely": "कम संभावना",
        "possible": "संभावना है",
        "likely": "संभावित",
        "very_likely": "बहुत संभावित",
        "almost_certain": "लगभग निश्चित",
        "show_more": "{count} और दिखाएँ",
    },
}

_SCENARIOS = {
    "heat_stress": "लू और गर्मी का तनाव",
    "delayed_monsoon": "मानसून में देरी / बुवाई में देरी",
    "early_season_dry_spell": "मौसम की शुरुआत में सूखा दौर",
    "mid_season_break": "मानसून में मध्य-मौसम विराम",
    "terminal_drought": "अंतिम सूखा / मानसून की जल्दी वापसी का जोखिम",
    "excess_rainfall_waterlogging": "अधिक वर्षा / जलभराव",
}

_RISKS = {"Severe": "गंभीर", "Alert": "सतर्कता", "Watch": "निगरानी", "Low": "कम"}

_OPTIONS = {
    "user_type": {
        "Farmer": "किसान",
        "Livestock owner": "पशुपालक",
        "Outdoor worker": "बाहरी कामगार",
        "Village official": "ग्राम अधिकारी",
        "NGO / extension worker": "एनजीओ / कृषि विस्तार कार्यकर्ता",
        "Health worker": "स्वास्थ्य कार्यकर्ता",
    },
    "irrigation": {
        "Rainfed": "वर्षा आधारित",
        "Partial irrigation": "आंशिक सिंचाई",
        "Assured irrigation": "सुनिश्चित सिंचाई",
        "Unknown": "ज्ञात नहीं",
    },
    "crop_stage": {
        "Not sown": "बुवाई नहीं हुई",
        "Recently sown": "हाल ही में बोई गई",
        "Vegetative": "वानस्पतिक अवस्था",
        "Flowering / reproductive": "फूल आने / प्रजनन की अवस्था",
        "Harvesting": "कटाई",
        "Unknown": "ज्ञात नहीं",
    },
}


def option_labels(kind, values, language="en"):
    if language != "hi":
        return values
    return [_OPTIONS.get(kind, {}).get(value, value) for value in values]


def option_value(kind, label, language="en"):
    if language != "hi":
        return label
    return next((value for value, translated in _OPTIONS.get(kind, {}).items() if translated == label), label)


def action_text(text, language="en"):
    if language == "en":
        return text
    catalog_translation = _CATALOG_TRANSLATOR.translate(text, language)
    if catalog_translation:
        return catalog_translation
    if language != "hi":
        return text
    exact = {
        "Drink water frequently; use ORS where appropriate": "बार-बार पानी पिएँ; आवश्यकता होने पर ओआरएस का उपयोग करें",
        "Rest in shade or cooler spaces": "छायादार या ठंडी जगहों पर आराम करें",
        "Store drinking water": "पीने का पानी जमा रखें",
        "Conserve water and use it judiciously": "पानी बचाएँ और समझदारी से उपयोग करें",
        "Stay updated with official weather forecasts": "आधिकारिक मौसम पूर्वानुमान से अपडेट रहें",
        "Use water efficiently for essential needs only": "पानी का उपयोग केवल आवश्यक कार्यों के लिए सावधानी से करें",
        "Monitor weather forecasts regularly": "मौसम पूर्वानुमान नियमित रूप से देखें",
        "Non-essential water use": "गैर-जरूरी कार्यों में पानी का उपयोग",
        "Nonessential irrigation for low-priority fields": "कम प्राथमिकता वाले खेतों में गैर-जरूरी सिंचाई",
        "Protect important documents and valuables": "महत्वपूर्ण दस्तावेज़ों और कीमती वस्तुओं को सुरक्षित रखें",
        "Monitor IMD forecasts and local KVK advisories for updates": "अपडेट के लिए IMD पूर्वानुमान और स्थानीय KVK सलाह देखते रहें",
        "Good moisture conditions expected this week — favorable for sowing or field operations": "इस सप्ताह मिट्टी में नमी की अच्छी स्थिति रहेगी — बुवाई या खेत के काम के लिए अनुकूल",
        "Conditions are near normal — continue routine crop management and monitoring": "स्थितियाँ सामान्य के आसपास हैं — नियमित फसल प्रबंधन और निगरानी जारी रखें",
        "Rainfed field: prioritize soil moisture conservation — mulching, weeding, and dust mulch": "वर्षा आधारित खेत: मिट्टी की नमी बचाने को प्राथमिकता दें — मल्चिंग, निराई और धूल मल्च करें",
        "Without irrigation backup, plan for shorter-duration or drought-tolerant varieties if re-sowing is needed": "सिंचाई की सुविधा न होने पर दोबारा बुवाई की स्थिति में कम अवधि या सूखा-सहने वाली किस्मों की योजना बनाएँ",
        "Use irrigation strategically at critical crop stages — you have more flexibility than rainfed farmers": "फसल की महत्वपूर्ण अवस्थाओं में सिंचाई का रणनीतिक उपयोग करें — वर्षा आधारित किसानों की तुलना में आपके पास अधिक सुविधा है",
        "Watch for heat exhaustion and heat stroke symptoms": "गर्मी से थकावट और लू लगने के लक्षणों पर ध्यान दें",
        "Refer severe cases urgently to health facilities": "गंभीर मामलों को तुरंत स्वास्थ्य केंद्र भेजें",
        "Monitor vulnerable households during alerts": "चेतावनी के दौरान कमजोर परिवारों की निगरानी करें",
        "Prepare contingency plans for water scarcity": "पानी की कमी के लिए आकस्मिक योजनाएँ तैयार करें",
        "Review water conservation measures": "जल संरक्षण के उपायों की समीक्षा करें",
        "Check irrigation sources and repair water-harvesting structures": "सिंचाई स्रोतों की जाँच करें और जल-संचयन संरचनाओं की मरम्मत करें",
        "Above-normal rainfall expected in coming weeks — ensure field drainage is clear": "आने वाले सप्ताहों में सामान्य से अधिक वर्षा की संभावना है — खेत की जल निकासी साफ रखें",
        "Plan pesticide/fungicide applications around expected wet spells": "संभावित बारिश के दौर को ध्यान में रखकर कीटनाशक/फफूंदनाशक के उपयोग की योजना बनाएँ",
        "Check on elderly people, children, pregnant women, and people with health conditions": "बुजुर्गों, बच्चों, गर्भवती महिलाओं और स्वास्थ्य समस्याओं वाले लोगों का हाल जानें",
        "Identify shaded or cooler community spaces": "छायादार या ठंडी सामुदायिक जगहों की पहचान करें",
        "Coordinate work shifts for early morning or evening": "काम की पाली सुबह जल्दी या शाम के समय रखें",
        "Keep basic heat illness response information available": "गर्मी से होने वाली बीमारी की प्राथमिक सहायता की जानकारी उपलब्ध रखें",
        "Heavy outdoor work during the hottest part of the day": "दिन के सबसे गर्म समय में भारी बाहरी काम",
        "Long outdoor work without rest breaks": "बिना आराम के लंबे समय तक बाहरी काम",
        "Leaving children, elderly people, or animals in enclosed hot spaces": "बच्चों, बुजुर्गों या पशुओं को बंद गर्म जगहों में छोड़ना",
        "Unnecessary livestock transport during peak heat": "अत्यधिक गर्मी में अनावश्यक पशु परिवहन",
        "Provide shade and continuous drinking water for livestock": "पशुओं के लिए छाया और लगातार पीने का पानी उपलब्ध कराएँ",
        "Shift heavy work to early morning or evening": "भारी काम सुबह जल्दी या शाम के समय करें",
        "Use work-rest cycles during heat alerts": "गर्मी की चेतावनी के दौरान काम और आराम का क्रम रखें",
        "Ensure drinking water and ORS availability at worksite": "कार्यस्थल पर पीने का पानी और ओआरएस उपलब्ध रखें",
        "Prepare for potential changes in planting schedules": "बुवाई के समय में संभावित बदलाव के लिए तैयार रहें",
        "Review water storage and conservation options": "जल भंडारण और संरक्षण के विकल्पों की समीक्षा करें",
        "Panic or make drastic agricultural decisions without official guidance": "आधिकारिक मार्गदर्शन के बिना घबराकर बड़े कृषि निर्णय लेना",
        "Waste water on non-essential activities": "गैर-जरूरी कार्यों में पानी बर्बाद करना",
        "Do not rush sowing without adequate soil moisture": "पर्याप्त मिट्टी की नमी के बिना जल्दबाजी में बुवाई न करें",
        "Preserve seed for the right sowing window": "सही बुवाई समय के लिए बीज सुरक्षित रखें",
        "Check local KVK or agriculture officer guidance": "स्थानीय KVK या कृषि अधिकारी के मार्गदर्शन की जाँच करें",
        "Assess germination and plant stand": "अंकुरण और पौधों की स्थिति का आकलन करें",
        "Use protective irrigation if available": "उपलब्ध होने पर जीवन रक्षक सिंचाई करें",
        "Prioritize water for most critical needs": "सबसे जरूरी जरूरतों के लिए पानी को प्राथमिकता दें",
        "Monitor crop and livestock conditions closely": "फसल और पशुओं की स्थिति पर ध्यान से निगरानी रखें",
        "Plan for potential water rationing": "संभावित जल राशनिंग की योजना बनाएँ",
        "Review alternative water sources": "वैकल्पिक जल स्रोतों की समीक्षा करें",
        "Prioritize protective irrigation during critical crop stages": "फसल की महत्वपूर्ण अवस्थाओं में जीवन रक्षक सिंचाई को प्राथमिकता दें",
        "Remove weeds to reduce moisture competition": "नमी के लिए प्रतिस्पर्धा कम करने हेतु खरपतवार निकालें",
        "Use soil moisture conservation practices": "मिट्टी की नमी बचाने के उपाय अपनाएँ",
        "Prioritize drinking water for all": "सभी के लिए पीने के पानी को प्राथमिकता दें",
        "Conserve water for essential uses only": "पानी को केवल जरूरी उपयोग के लिए बचाएँ",
        "Prepare for extended water scarcity": "लंबे समय तक पानी की कमी के लिए तैयार रहें",
        "Review emergency water sources": "आपातकालीन जल स्रोतों की समीक्षा करें",
        "Protect important documents and valuables": "महत्वपूर्ण दस्तावेज़ों और कीमती वस्तुओं को सुरक्षित रखें",
        "Identify higher ground for emergency shelter": "आपातकालीन आश्रय के लिए ऊँची जगह की पहचान करें",
        "Prepare emergency supplies": "आपातकालीन सामग्री तैयार रखें",
        "Unnecessary travel in flooded areas": "बाढ़ वाले क्षेत्रों में अनावश्यक यात्रा",
        "Entering flooded areas unnecessarily": "बाढ़ वाले क्षेत्रों में बिना आवश्यकता प्रवेश करना",
        "Contaminated water consumption": "दूषित पानी पीना",
        "Clear drainage channels": "जल निकासी नालियाँ साफ करें",
        "Move livestock away from flood-prone areas": "पशुओं को बाढ़ संभावित क्षेत्रों से दूर ले जाएँ",
        "Field operations during heavy rain": "भारी वर्षा के दौरान खेत का काम",
        "Entering flooded fields unnecessarily": "बिना आवश्यकता जलमग्न खेतों में प्रवेश करना",
        "Applying fertilizer before heavy rainfall": "भारी वर्षा से पहले उर्वरक डालना",
        "Allowing livestock to drink contaminated stagnant water": "पशुओं को दूषित रुका हुआ पानी पीने देना",
        "Not a problem due to sandy soils": "रेतीली मिट्टी के कारण समस्या नहीं है",
        "Storing of house hold feeds like broken rice, pulse etc.": "टूटे हुए चावल, दाल आदि जैसे घरेलू पशु-चारे का भंडारण करें",
        "Use stored feed as supplement": "भंडारित चारे का पूरक के रूप में उपयोग करें",
        "Don’t allow for scavenging": "पशुओं को खुले में चरने न दें",
        "Routine practices are followed Deworming and vaccination against RD": "नियमित उपाय अपनाएँ: कृमिनाशक दवा दें और RD के विरुद्ध टीकाकरण करें",
        "Adopt various water conservation methods at village level to improve the ground water level for adequate water supply.": "पर्याप्त जल आपूर्ति के लिए भूजल स्तर सुधारने हेतु गाँव स्तर पर विभिन्न जल संरक्षण उपाय अपनाएँ।",
        "Use water sanitizers or offer cool hygienic drinking water": "जल शुद्धिकरण पदार्थों का उपयोग करें या ठंडा और स्वच्छ पेयजल उपलब्ध कराएँ",
        "Add antibiotic powder in drinking water to prevent any disease outbreak": "बीमारी फैलने से रोकने के लिए पीने के पानी में एंटीबायोटिक पाउडर मिलाएँ",
        "Prevent water logging surrounding the sheds through proper drainage facility": "उचित जल निकासी की व्यवस्था से पशु-शेड के आसपास जलभराव रोकें",
        "Re transplanting through Dapog nursery if needed": "आवश्यकता होने पर डैपोग नर्सरी के माध्यम से दोबारा रोपाई करें",
        "Retransplanting through Dapog nursery if needed": "आवश्यकता होने पर डैपोग नर्सरी के माध्यम से दोबारा रोपाई करें",
        "Gap filling, if required": "आवश्यकता होने पर खाली जगहों में पौधे लगाएँ",
        "Gap filling, if needed": "आवश्यकता होने पर खाली जगहों में पौधे लगाएँ",
        "Gap filling if needed": "आवश्यकता होने पर खाली जगहों में पौधे लगाएँ",
        "Gap filling, if damage less than 20%": "क्षति 20% से कम होने पर खाली जगहों में पौधे लगाएँ",
        "Resowing through drum seeder": "ड्रम सीडर के माध्यम से दोबारा बुवाई करें",
        "Subsequent crop like Toria may be taken if present crop is substantially damaged/affected": "यदि वर्तमान फसल को काफी नुकसान हुआ है तो टोरिया जैसी अगली फसल ली जा सकती है",
        "Harvest at physiological maturity": "फसल को शारीरिक परिपक्वता पर काटें",
        "Harvest at proper time": "फसल की उचित समय पर कटाई करें",
        "Storage and transportati on at safer place": "भंडारण और परिवहन सुरक्षित स्थान पर करें",
        "Storage and transportation at safer place": "भंडारण और परिवहन सुरक्षित स्थान पर करें",
        "Safer storage and Transportation": "फसल को सुरक्षित स्थान पर भंडारित और परिवहन करें",
        "Resowing or Replanting, if substantially damaged as the case may be": "काफी नुकसान होने पर परिस्थिति के अनुसार दोबारा बुवाई या रोपाई करें",
        "Resowing, if sequentially affected": "लगातार प्रभावित होने पर दोबारा बुवाई करें",
        "Identify higher ground for livestock and equipment": "पशुओं और उपकरणों के लिए ऊँची जगह की पहचान करें",
        "Watch for pest and disease outbreaks after rainfall": "वर्षा के बाद कीट और रोग फैलने पर ध्यान दें",
        "Repair bunds after water recedes": "पानी उतरने के बाद खेत की मेड़ों की मरम्मत करें",
    }
    if text in exact:
        return exact[text]

    # ICAR extraction can add bullets, trailing commas, repeated spaces, or
    # minor OCR spacing differences. Match those variants without changing the
    # source text stored in the action record.
    def _normalized(value):
        value = str(value).replace("’", "'").replace("", " ")
        value = re.sub(r"\s+", " ", value).strip()
        return value.strip(" .,;:")

    normalized_text = _normalized(text)
    for source, target in exact.items():
        if normalized_text == _normalized(source):
            return target

    variants = {
        "Storing of house hold feeds like broken rice, pulse etc,": exact["Storing of house hold feeds like broken rice, pulse etc."],
        "Routinepractices are followed Deworming and vaccination against RD": exact["Routine practices are followed Deworming and vaccination against RD"],
        "Don't allow for scavenging": exact["Don’t allow for scavenging"],
    }
    if normalized_text in variants:
        return variants[normalized_text]

    replacements = {
        "Additional contingency measures": "अतिरिक्त आकस्मिक उपाय",
        "Additional preparatory measures": "अतिरिक्त तैयारी के उपाय",
        "are available — consult your local KVK extension officer.": "उपलब्ध हैं — अपने स्थानीय KVK विस्तार अधिकारी से सलाह लें।",
        "Season-to-date rainfall is": "अब तक की मौसमी वर्षा",
        "below normal — prioritize moisture conservation": "सामान्य से कम है — नमी संरक्षण को प्राथमिकता दें",
        "Rainfall outlook dries out over weeks 2-4 —": "सप्ताह 2-4 में वर्षा कम होने की संभावना है —",
        "conserve soil moisture and plan water use carefully": "मिट्टी की नमी बचाएँ और पानी के उपयोग की सावधानीपूर्वक योजना बनाएँ",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


_ACTION_TEMPLATES = {
    "additional_contingency": {
        "en": "Additional contingency measures ({count} items) are available — consult your local KVK extension officer.",
        "hi": "अतिरिक्त आकस्मिक उपाय ({count} वस्तुएँ) उपलब्ध हैं — अपने स्थानीय KVK विस्तार अधिकारी से सलाह लें।",
    },
    "additional_preparatory": {
        "en": "Additional preparatory measures ({count} items) are available — consult your local KVK extension officer.",
        "hi": "अतिरिक्त तैयारी के उपाय ({count} वस्तुएँ) उपलब्ध हैं — अपने स्थानीय KVK विस्तार अधिकारी से सलाह लें।",
    },
}


def make_template_action(template_id, variables=None, source="generated"):
    variables = variables or {}
    template = _ACTION_TEMPLATES[template_id]
    return ActionRecord(
        template["en"].format(**variables),
        template["hi"].format(**variables),
        action_id=template_id,
        source=source,
    )


def display_action(text, language="en"):
    return text.display(language) if isinstance(text, ActionRecord) else action_text(text, language)


def make_action(text, source="unknown", action_id=None, text_hi=None):
    """Build a bilingual record while accepting legacy plain-string actions."""
    if isinstance(text, ActionRecord):
        return text
    return ActionRecord(
        text,
        text_hi if text_hi is not None else action_text(text, "hi"),
        action_id=action_id,
        source=source,
    )


def t(key, language="en"):
    """Return a translated UI label, falling back safely to English/key."""
    return _TRANSLATIONS.get(language, _TRANSLATIONS["en"]).get(
        key, _TRANSLATIONS["en"].get(key, key)
    )


def scenario_name(key, english_name, language="en"):
    return _SCENARIOS.get(key, english_name) if language == "hi" else english_name


def risk_name(value, language="en"):
    return _RISKS.get(value, value) if language == "hi" else value


def category(value, language="en"):
    if language != "hi":
        return value
    translations = {
        "Much wetter than normal": "सामान्य से बहुत अधिक वर्षा",
        "Wetter than normal": "सामान्य से अधिक वर्षा",
        "Slightly wetter": "थोड़ी अधिक वर्षा",
        "Near normal": "सामान्य के आसपास",
        "Slightly drier": "थोड़ी कम वर्षा",
        "Drier than normal": "सामान्य से कम वर्षा",
        "Much drier than normal": "सामान्य से बहुत कम वर्षा",
        "Very warm": "बहुत गर्म",
        "Warm": "गर्म",
        "Slightly warm": "थोड़ा गर्म",
        "Slightly cool": "थोड़ा ठंडा",
        "Cool": "ठंडा",
        "Very cool": "बहुत ठंडा",
    }
    return translations.get(value, value)


def reason(text, language="en"):
    """Translate the stable prefixes used by scenario reason generators."""
    if language != "hi":
        return text
    replacements = {
        "Heat wave warning is in effect": "लू की चेतावनी लागू है",
        "Maximum temperatures are above normal": "अधिकतम तापमान सामान्य से अधिक है",
        "Minimum temperatures are above normal": "न्यूनतम तापमान सामान्य से अधिक है",
        "Humidity heat index is high": "नमी वाला हीट इंडेक्स अधिक है",
        "Rainfall since June 1 is": "1 जून से वर्षा",
        "below normal": "सामान्य से कम",
        "above normal": "सामान्य से अधिक",
        "Monsoon onset is delayed": "मानसून का आगमन देर से है",
        "The first forecast week is below normal": "पहले पूर्वानुमान सप्ताह में वर्षा सामान्य से कम है",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text
