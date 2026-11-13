"""Telugu. Chat is often "Tenglish" (Telugu in Latin letters mixed with English); speech comes
back from Sarvam in Telugu script. Telugu first-person verbs are not gendered."""
from kisht.languages import LanguagePack

F = frozenset
PACK = LanguagePack(
    code="te", name="Telugu (Tenglish is fine)", sarvam="te-IN", script="ఀ-౿",
    markers=F({"enti", "emi", "ledu", "ledhu", "sare", "avunu", "nenu", "repu", "chestanu",
               "chesta", "kadtanu", "kadatanu", "meeru", "mee", "istanu", "ippudu", "entha",
               "cheppandi", "undi", "kaadu", "vaddu", "garu", "namaskaram", "konchem",
               "ellundi", "ivala", "jeetham", "dabbulu", "kattesta", "kadutanu", "salary"}),
    yes=F({"avunu", "aunu", "sare", "alage", "tappakunda",
           "అవును", "సరే", "అలాగే", "తప్పకుండా", "ఓకే"}),
    yes_phrases=("cheyyandi", "చేయండి"),
    no=F({"ledu", "ledhu", "kaadu", "kadu", "vaddu", "kaani", "maarchandi", "aagandi",
          "లేదు", "కాదు", "వద్దు", "కానీ", "ఆగండి", "మార్చండి"}),
    harmless=("parledu", "parvaledu", "parvaledhu", "పర్లేదు", "పర్వాలేదు"),
    time_words=F({"gantalaku", "podduna", "udayam", "madhyaahnam", "saayantram", "raatri",
                  "mundu", "tarvata", "taruvata", "ivala", "eeroju", "repu", "ellundi",
                  "గంటలకు", "ఉదయం", "మధ్యాహ్నం", "సాయంత్రం", "రాత్రి", "ముందు", "తర్వాత",
                  "ఈరోజు", "ఇవాళ", "రేపు", "ఎల్లుండి"}),
    day_parts=F({"podduna", "udayam", "madhyaahnam", "saayantram", "raatri", "ఉదయం", "మధ్యాహ్నం", "సాయంత్రం", "రాత్రి"}),
    today=F({"ivala", "eeroju", "ఈరోజు", "ఇవాళ"}),
    tomorrow=F({"repu", "రేపు"}),
    day_after=F({"ellundi", "ఎల్లుండి"}),
    weekdays=tuple(F(d) for d in [("somavaram", "సోమవారం"), ("mangalavaram", "మంగళవారం"),
                                  ("budhavaram", "బుధవారం"), ("guruvaram", "గురువారం"),
                                  ("sukravaram", "shukravaram", "శుక్రవారం"),
                                  ("sanivaram", "శనివారం"), ("aadivaram", "ఆదివారం")]),
    months=tuple(F({m}) for m in ["జనవరి", "ఫిబ్రవరి", "మార్చి", "ఏప్రిల్", "మే", "జూన్", "జూలై",
                                  "ఆగస్టు", "సెప్టెంబర్", "అక్టోబర్", "నవంబర్", "డిసెంబర్"]),
    weekday_names=("సోమవారం", "మంగళవారం", "బుధవారం", "గురువారం", "శుక్రవారం", "శనివారం",
                   "ఆదివారం"),
    month_names=("జనవరి", "ఫిబ్రవరి", "మార్చి", "ఏప్రిల్", "మే", "జూన్", "జూలై", "ఆగస్టు",
                 "సెప్టెంబర్", "అక్టోబర్", "నవంబర్", "డిసెంబర్"),
    promise_saved=(r"\b(note|record|save|namodu) (chesanu|chesaanu|chesesanu|chesam)",
                   r"(నమోదు|నోట్|రికార్డ్) (చేశాను|చేసాను|చేసేశాను|చేశాం)",
                   r"(నమోదు|నోట్|రికార్డ్) (చేయబడింది|అయింది|అయ్యింది)",
                   r"\b(note|record|namodu) (ayindi|ayyindi|cheyabadindi)"),
    link_sent=(r"\blink\b.{0,40}(pampanu|pampaanu|pampistunna|pamputunna|pampinchanu|pampesanu)",
               r"లింక్.{0,40}పంప"),
    waiver=(r"\b(maafi|tagginchamu|tagginchanu) (chesam|chesanu)?", r"మాఫీ|తగ్గించాం|తగ్గించాను"),
    negation=(r"\b(kudaradu|ledu|kaadu)\b", r"కుదరదు|లేదు|కాదు"),
    paid=(r"\bpayment (vachindi|andindi)", r"(డబ్బు|payment|పేమెంట్) (వచ్చింది|అందింది)"),
    action_words=(r"namodu|haami|pamp|dhruvikar|maafi|chesanu|chesaanu|ayindi|ayyindi",
                  r"నమోదు|హామీ|లింక్|పంప|ధృవీకర|షెడ్యూల్|మాఫీ|టీమ్|రికార్డ్|నోట్"),
    stall=(r"okka nimisham|check chestanu|\bchustanu\b", r"ఒక్క నిమిషం|చెక్ చేస్తాను", r"\brecord (chestanu|chesta)\b",
           r"(రికార్డ్|నమోదు) చేస్త"),
    possessive=F({"mee", "meeku", "mi", "మీ", "మీకు", "మీయొక్క"}),
    status=F({"baaki", "బాకీ", "ఆలస్యం", "పెండింగ్"}),
    greeting="నమస్కారం, నేను {lender} నుండి {agent} మాట్లాడుతున్నాను. {first_name} గారితో "
             "మాట్లాడుతున్నానా?",
    say={
        "promise_saved": "ధన్యవాదాలు, నమోదు చేశాను: {read_back}.",
        "read_back": "నిర్ధారించుకుంటాను: {read_back}. సరేనా?",
        "fallback": "క్షమించండి, ఇప్పుడు సాంకేతిక సమస్య ఉంది. మా టీమ్ మిమ్మల్ని సంప్రదిస్తుంది. "
                    "ధన్యవాదాలు.",
        "stuck": "క్షమించండి, ఇది నేను పరిష్కరించలేకపోయాను. మా టీమ్ మీకు కాల్ చేయమని చెప్పనా?",
        "moment": "ఒక్క నిమిషం.",
        "handover": "ఇకపై మా టీమ్ సభ్యులు మీతో మాట్లాడతారు. ధన్యవాదాలు.",
        "verify_first": "వివరాలు మాట్లాడే ముందు, మీ పుట్టిన తేదీ లేదా PIN code చెప్పగలరా?",
        "cannot_decide": "ఇది నేను స్వయంగా నిర్ణయించలేను, కానీ మీ వివరాలతో మా టీమ్‌కు "
                         "తెలియజేయగలను. అలా చేయనా?",
        "polite": "తప్పుగా అనిపించి ఉంటే క్షమించండి. మీకు సరిపోయే మార్గం కనుగొనడంలో సహాయం "
                  "చేయడానికే నేను ఉన్నాను.",
        "not_now": "క్షమించండి, ఇప్పుడు దీని గురించి మాట్లాడలేము. ధన్యవాదాలు.",
    },
    prompt_note="Telugu speakers often type Telugu in Latin letters mixed with English "
                "(Tenglish); reply the same way they write.",
    voice_note="On this phone call, if you reply in Telugu, write it in Telugu script so it is "
               "spoken correctly.",
    simulator_style="Tenglish (Telugu in Latin letters, mixed with English), as most people in "
                    "Andhra Pradesh and Telangana chat.",
)
