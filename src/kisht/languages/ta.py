"""Tamil. Chat is often "Tanglish" (Tamil in Latin letters mixed with English); speech comes
back from Sarvam in Tamil script. Tamil first-person verbs are not gendered."""
from kisht.languages import LanguagePack

F = frozenset
PACK = LanguagePack(
    code="ta", name="Tamil (Tanglish is fine)", sarvam="ta-IN", script="஀-௿",
    markers=F({"enna", "illa", "illai", "seri", "sari", "aamaa", "aama", "naan", "naalaikku",
               "naalai", "panren", "pannren", "pannunga", "unga", "ungal", "vendam", "vendaam",
               "kodukkaren", "kattaren", "kattiduren", "eppo", "evlo", "sollunga", "irukku",
               "theriyum", "theriyadhu", "mudiyadhu", "vanakkam", "romba", "konjam", "innaiku",
               "panna", "panniduren", "kudukaren", "panam", "salary"}),
    yes=F({"aamaa", "aama", "aamam", "aamaam", "seri", "sari", "kandippa",
           "ஆமா", "ஆமாம்", "சரி", "ஓகே", "கண்டிப்பா", "கண்டிப்பாக"}),
    yes_phrases=("pannunga", "pannidunga", "பண்ணுங்க"),
    no=F({"illa", "illai", "vendam", "vendaam", "venaam", "aana", "aanaa", "maathu",
          "maathunga", "nillunga",
          "இல்ல", "இல்லை", "வேண்டாம்", "வேணாம்", "ஆனா", "ஆனால்", "மாத்து", "மாத்துங்க"}),
    harmless=("paravaillai", "paravala", "பரவாயில்லை"),
    time_words=F({"mani", "kaalai", "madhiyam", "saayankaalam", "maalai", "raathiri", "munnadi",
                  "apram", "aprom", "indru", "innaiku", "inniki", "naalai", "naalaikku",
                  "naalaiku", "naliku", "naalanniki",
                  "மணி", "காலை", "மதியம்", "மாலை", "இரவு", "முன்னாடி", "அப்புறம்", "இன்று",
                  "இன்னைக்கு", "நாளை", "நாளைக்கு", "நாளன்னைக்கு"}),
    day_parts=F({"kaalai", "madhiyam", "saayankaalam", "maalai", "raathiri", "காலை", "மதியம்", "மாலை", "இரவு"}),
    today=F({"indru", "innaiku", "inniki", "இன்று", "இன்னைக்கு"}),
    tomorrow=F({"naalai", "naalaikku", "naalaiku", "naliku", "நாளை", "நாளைக்கு"}),
    day_after=F({"naalanniki", "நாளன்னைக்கு"}),
    weekdays=tuple(F(d) for d in [("thingal", "திங்கள்"), ("sevvai", "செவ்வாய்"),
                                  ("budhan", "புதன்"), ("viyazhan", "vyazhan", "வியாழன்"),
                                  ("velli", "வெள்ளி"), ("sani", "சனி"),
                                  ("gnayiru", "nyayiru", "ஞாயிறு")]),
    months=tuple(F({m}) for m in ["ஜனவரி", "பிப்ரவரி", "மார்ச்", "ஏப்ரல்", "மே", "ஜூன்", "ஜூலை",
                                  "ஆகஸ்ட்", "செப்டம்பர்", "அக்டோபர்", "நவம்பர்", "டிசம்பர்"]),
    weekday_names=("திங்கள்கிழமை", "செவ்வாய்க்கிழமை", "புதன்கிழமை", "வியாழக்கிழமை", "வெள்ளிக்கிழமை",
                   "சனிக்கிழமை", "ஞாயிற்றுக்கிழமை"),
    month_names=("ஜனவரி", "பிப்ரவரி", "மார்ச்", "ஏப்ரல்", "மே", "ஜூன்", "ஜூலை", "ஆகஸ்ட்",
                 "செப்டம்பர்", "அக்டோபர்", "நவம்பர்", "டிசம்பர்"),
    promise_saved=(r"\b(note|record|save) (panniten|pannitten|pannittaen|senjitten)",
                   r"\bpathivu (senjitten|seithen|panniten)",
                   r"பதிவு செய்(தேன்|துவிட்டேன்|துட்டேன்)", r"நோட் பண்ணி(ட்டேன்|னேன்)",
                   (r"பதிவு (செய்யப்பட்டது|செய்யப்பட்டுள்ளது|செய்யப்பட்டுவிட்டது|செய்யப்படுகிறது|"
                   r"ஆகிவிட்டது|ஆயிடுச்சு)"),
                   r"\bpathivu (aagiduchu|aayiduchu|seyyapattathu)",
                   r"பதிவு (செய்கிறேன்|பண்றேன்|செய்து கொண்டிருக்கிறேன்)"),
    link_sent=(r"\blink\b.{0,40}(anupiten|anuppiten|anuppitten|anupuren|anuppuren|anuppi)",
               r"லிங்க்.{0,40}அனுப்பி"),
    waiver=(r"thallupadi (panniten|senjom|pannitom)", r"தள்ளுபடி (செய்|பண்ணி)"),
    negation=(r"\b(mudiyadhu|mudiyaathu)\b", r"முடியாது"),
    paid=(r"\bpayment (vandhuduchu|vanduduchu|kidaichiduchu)", r"(பணம்|payment) (வந்துவிட்டது|வந்துடுச்சு|கிடைச்சுடுச்சு)"),
    action_words=(r"pathivu|vaakkuruthi|vakkuruthi|anupp|anupi|uruthi|thallupadi|senjitt|pannitt",
                  r"பதிவு|வாக்குறுதி|லிங்க்|அனுப்|உறுதி|சரிபார்|திட்டமிட|தள்ளுபடி|குழு|ரெக்கார்ட|நோட்"),
    stall=(r"konjam wait|check (panren|pannuren)|\bpaakuren\b|oru nimisham",
           r"ஒரு நிமிஷம்|செக் பண்றேன்", r"\brecord (panren|pannuren)\b",
           r"பதிவு (செய்கிறேன்|பண்றேன்)|ரெக்கார்டு பண்றேன்"),
    possessive=F({"unga", "ungal", "ungaloda", "உங்க", "உங்கள்", "உங்களோட", "உங்களுடைய"}),
    status=F({"baaki", "nilluvai", "நிலுவை", "பாக்கி", "தாமதம்"}),
    greeting="வணக்கம், நான் {lender} நிறுவனத்திலிருந்து {agent} பேசுகிறேன். {first_name} அவர்களிடம் "
             "பேசுகிறேனா?",
    say={
        "promise_saved": "நன்றி, பதிவு செய்தேன்: {read_back}.",
        "read_back": "உறுதி செய்கிறேன்: {read_back}. சரியா?",
        "fallback": "மன்னிக்கவும், இப்போது ஒரு தொழில்நுட்ப பிரச்சனை. எங்கள் குழு உங்களைத் தொடர்பு "
                    "கொள்வார்கள். நன்றி.",
        "stuck": "மன்னிக்கவும், இதை என்னால் சரி செய்ய முடியவில்லை. எங்கள் குழுவிடம் உங்களை அழைக்கச் "
                 "சொல்லட்டுமா?",
        "recorded": "இந்த அழைப்பு பதிவு செய்யப்படுகிறது.",
        "moment": "ஒரு நிமிஷம்.",
        "handover": "இனி எங்கள் குழுவில் ஒருவர் உங்களுடன் பேசுவார். நன்றி.",
        "verify_first": "விவரங்களைப் பேசுவதற்கு முன், உங்கள் பிறந்த தேதி அல்லது PIN code சொல்ல "
                        "முடியுமா?",
        "cannot_decide": "இதை நான் தானாக முடிவு செய்ய முடியாது, ஆனால் உங்கள் விவரங்களுடன் எங்கள் "
                         "குழுவிடம் தெரிவிக்க முடியும். அப்படிச் செய்யட்டுமா?",
        "polite": "தவறாகப் பேசியிருந்தால் மன்னிக்கவும். உங்களுக்கு ஏற்ற வழியைக் கண்டுபிடிக்க "
                  "உதவத்தான் நான் இருக்கிறேன்.",
        "not_now": "மன்னிக்கவும், இப்போது இதைப் பற்றிப் பேச முடியாது. நன்றி.",
    },
    prompt_note="Tamil speakers often type Tamil in Latin letters mixed with English (Tanglish); "
                "reply the same way they write.",
    voice_note="On this phone call, if you reply in Tamil, write it in Tamil script so it is "
               "spoken correctly.",
    simulator_style="Tanglish (Tamil in Latin letters, mixed with English), as most people in "
                    "Tamil Nadu chat.",
)
