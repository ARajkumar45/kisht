from kisht.languages import LanguagePack

F = frozenset
PACK = LanguagePack(
    code="hi", name="Hindi (Hinglish is fine)", sarvam="hi-IN", script="ऀ-ॿ",
    markers=F({"hai", "hain", "kya", "kal", "parso", "aaj", "mujhe", "nahi", "nahin", "haan", "ji",
               "kitna", "mera", "meri", "aap", "theek", "paisa", "paise", "karunga", "karungi",
               "kar", "dunga", "dungi", "abhi", "salary", "tankhwah"}),
    yes=F({"haan", "han", "haa", "ha", "hanji", "ji", "theek", "thik", "bilkul", "sahi",
           "हाँ", "हां", "हा", "जी", "ठीक", "बिल्कुल", "सही", "हो", "करो", "कर", "दो", "दीजिए"}),
    yes_phrases=("kar do", "kar dijiye", "kar dena"),
    no=F({"nahi", "nahin", "na", "mat", "ruko", "ruk", "ruka", "lekin", "magar", "badlo", "badal",
          "dusra", "doosra", "nako",
          "नहीं", "नही", "ना", "मत", "रुको", "रुकिए", "लेकिन", "मगर", "बदल", "बदलो", "दूसरा", "बाद"}),
    harmless=("koi baat nahi", "koi baat nahin"),
    time_words=F({"baje", "subah", "shaam", "sham", "dopahar", "raat", "aaj", "kal", "parso",
                  "pehle", "baad", "jaldi", "somvar", "mangalvar", "budhvar", "guruvar",
                  "shukravar", "shanivar", "ravivar",
                  "बजे", "सुबह", "शाम", "दोपहर", "रात", "कल", "परसों", "आज", "सोमवार", "मंगलवार",
                  "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार", "रविवार", "पहले"}),
    day_parts=F({"subah", "shaam", "sham", "dopahar", "raat", "सुबह", "शाम", "दोपहर", "रात"}),
    today=F({"aaj", "आज"}), tomorrow=F({"kal", "कल"}), day_after=F({"parso", "परसों"}),
    weekdays=tuple(F(d) for d in [("somvar", "सोमवार"), ("mangalvar", "मंगलवार"),
                                  ("budhvar", "बुधवार"), ("guruvar", "गुरुवार"),
                                  ("shukravar", "शुक्रवार"), ("shanivar", "शनिवार"),
                                  ("ravivar", "रविवार")]),
    promise_saved=((r"\b(note kar (liya|li)|record kar (liya|diya|di)|darj kar (liya|diya)|"
                   r"confirmation mil gaya|confirm ho gaya|"
                    r"(note|record|darj|save) ho (gaya|gayi|chuka|chuki))\b"),
                   r"(नोट|रिकॉर्ड|दर्ज) (कर (लिया|दिया)|हो (गया|गई|चुका))"),
    link_sent=(r"link\b.{0,40}\bbhej (diya|di|rahi|raha|dunga|dungi|deti|deta)",
               r"\bbhej (diya|di|rahi|raha|deti|deta).{0,40}\blink\b"),
    waiver=(r"\b(waive kar|maaf kar (diya|denge|dete))\b",),
    negation=(r"\b(nahi|nahin)\b",),
    paid=(r"\bpayment mil gay(a|i)\b",),
    action_words=(r"darj|vaada|wada|bhej|maaf kar|chhoot|jama|mil gaya|ho gaya|kar diya|kar liya",
                  r"रिकॉर्ड|नोट|दर्ज|वादा|लिंक|भेज|कन्फर्म|वेरिफ|माफ|छूट|जमा|टीम"),
    stall=((r"check kar(te|ti|ta) (hain|hoon|hun)|check kar rah(a|i|e)|"
           r"dekh rah(a|i|e) (hoon|hun|hain)|ek (minute|second)"),
           r"\brecord kar (rahi|raha|deti|deta|dungi|dunga) (hoon|hun|hu)\b"),
    possessive=F({"aapka", "aapki", "aapke", "aapko", "tumhara", "tumhari"}),
    status=F({"bakaya", "baaki", "peeche"}),
    greeting="Namaste, main {agent} bol rahi hoon {lender} se. Kya meri baat {first_name} ji se "
             "ho rahi hai?",
    say={
        "promise_saved": "Dhanyavaad, note kar liya: {read_back}.",
        "read_back": "Confirm kar doon: {read_back}. Sahi hai?",
        "fallback": "Maaf kijiye, abhi technical dikkat hai. Hamari team aapse sampark karegi. "
                    "Dhanyavaad.",
        "stuck": "Maaf kijiye, main yeh nahi kar paayi. Kya main team se aapko call karwaun?",
        "recorded": "Yeh call record ki ja rahi hai.",
        "moment": "Ji, ek second.",
        "handover": "Main aapko hamari team ke ek saathi se jod rahi hoon, aage ki baat wahi "
                    "karenge. Dhanyavaad.",
        "verify_first": "Kuch bhi details batane se pehle, kya aap apni date of birth ya PIN code "
                        "bata sakte hain?",
        "cannot_decide": "Yeh main khud decide nahi kar sakti, lekin aapki baat team tak pahuncha "
                         "sakti hoon. Kar doon?",
        "polite": "Maaf kijiye agar baat galat lagi. Main aapki madad ke liye hoon, aap jaisa "
                  "aasaan ho.",
        "not_now": "Maaf kijiye, abhi baat nahi ho sakti. Dhanyavaad.",
    },
    prompt_note="Hindi speakers often mix Hindi and English (Hinglish); reply the same way.",
    simulator_style="Hinglish (Hindi in Latin letters, mixed with English), as most people in "
                    "north India chat.",
)
