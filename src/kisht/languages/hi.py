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
                   r"(नोट|रिकॉर्ड|दर्ज) (कर (लिया|दिया)|हो (गया|गई|चुका))",
                   # "am recording it now": seen passing a retry and reaching the borrower
                   r"\b(record|note|darj|save) kar (rahi|raha) (hoon|hun|hu)\b"),
    link_sent=(r"link\b.{0,40}\bbhej (diya|di|rahi|raha|dunga|dungi|deti|deta)",
               r"\bbhej (diya|di|rahi|raha|deti|deta).{0,40}\blink\b"),
    waiver=(r"\b(waive kar|maaf kar (diya|denge|dete))\b",),
    stop_contact=((r"\b(contact|call|message|sampark|pareshan|disturb) nahi? "
                   r"(karenge|karungi|karunga|karegi|kiya jayega|kiye jayenge|aayega|aayegi)"),
                  r"\b(dobara|aage|ab) .{0,25}\b(call|contact|message|sampark) nahi\b",
                  r"\b(list se|number) hata (diya|di|rahi|denge)\b"),
    handed_over=((r"\bteam ko .{0,30}\b(forward|bhej|bata|inform|escalate|transfer|de) (kar )?"
                  r"(rahi|raha|chuki|chuka|diya|di|dungi|dunga|deti|deta)\b"),
                 r"\b(forward|escalate|transfer) kar (rahi|chuki|diya|di|dungi|deti)\b",
                 (r"\bteam (aapko|aap se|aapse|aap ko) .{0,30}\b(call|contact|sampark|baat) "
                  r"kar(egi|enge)\b"),
                 r"\bteam se (connect|baat) karw\w+ (rahi|deti|dungi)\b"),
    terms_cue=(r"\b(jurmana|byaj|shikayat|shikaayat|credit score|sibil)\b",),
    # Only a clear, lasting request ("dobara", "kabhi", "band"), not "abhi call mat karo".
    stop_request=((r"\b(dobara|phir se|phir kabhi|kabhi|aage se|aainda)\b.{0,25}"
                   r"\b(call|phone|message|sampark)\b.{0,12}\b(mat|na|nahi)\b"),
                  r"\b(call|phone|message) (karna|bhejna) band\b",
                  r"\b(mera|yeh|ye) number hata\b",
                  r"(दोबारा|फिर कभी|कभी|आगे से).{0,25}(कॉल|फोन|फ़ोन|मैसेज|संपर्क).{0,12}(मत|ना|नहीं)",
                  r"(कॉल|फोन|फ़ोन) करना बंद"),
    hardship_cue=((r"\b(naukri (chali|chhoot|chhut|chhod\w*|nahi)|job (chali|chhoot|chhut|chhod\w*|nahi)|"
                   r"kaam chhod\w*|"
                   r"business .{0,15}kharab|"
                   r"kaam (band|nahi)|business (band|thap)|aspatal|hospital|ilaj|ilaaj|operation|"
                   r"beemar|bimar|guzar ga(ya|yi|ye)|dehant|maut|accident)\b"),),
    negation=(r"\b(nahi|nahin)\b",),
    paid=(r"\bpayment mil gay(a|i)\b",
          # "aapka EMI ... pay ho gaya hai": the agent cannot know a payment went through.
          # Not "... saku ki aapka payment ho gaya hai" (so that I can confirm) or "ya nahi".
          (r"(?<!saku ki )(?<!sakein ki )(?<!sake ki )\baapk[ai] (payment|emi|bhugtan)\b"
           r"[^.?!]{0,50}(?<!late )(?<!overdue )(?<!due )(?<!pending )(?<!miss )(?<!baaki )"
           r"\bho gay[ai] hai\b(?! ya nahi)")),
    action_words=(r"darj|vaada|wada|bhej|team|forward|transfer|connect|sampark|pareshan|contact|hata d|maaf kar|chhoot|jama|mil gaya|ho gaya|kar diya|kar liya",
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
        "opted_out": ("Theek hai. Maine note kar liya hai, ab hum aapko dobara call ya message "
                      "nahi karenge. Dhanyavaad."),
        "link_sent": ("Maine Rs {amount} ka payment link aapke registered mobile number par "
                      "bhej diya hai."),
        "team_will_call": ("Maine aapki baat hamari team ko bhej di hai. Team se koi aapko call "
                           "karega. Dhanyavaad."),
        "stuck": "Maaf kijiye, main yeh nahi kar paayi. Kya main team se aapko call karwaun?",
        "recorded": "Yeh call record ki ja rahi hai.",
        "payment_pending": ("Dhanyavaad. Payment mujhe yahan se nahi dikhta; jaise hi woh hum tak "
                            "pahunchega, aapke account mein dikh jayega."),
        "promise_ask": "Abhi kuch save nahi hua hai. Aap kis tareekh ko aur kitna pay karenge?",
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
