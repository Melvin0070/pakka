"""Canonical Hindi number words. Spelling variants for recognition live in normalise.py;
this file is the single source for rendering a value as speech."""

HI_0_99: tuple[str, ...] = (
    "शून्य", "एक", "दो", "तीन", "चार", "पाँच", "छह", "सात", "आठ", "नौ",
    "दस", "ग्यारह", "बारह", "तेरह", "चौदह", "पंद्रह", "सोलह", "सत्रह", "अठारह", "उन्नीस",
    "बीस", "इक्कीस", "बाईस", "तेईस", "चौबीस", "पच्चीस", "छब्बीस", "सत्ताईस", "अट्ठाईस", "उनतीस",
    "तीस", "इकतीस", "बत्तीस", "तैंतीस", "चौंतीस", "पैंतीस", "छत्तीस", "सैंतीस", "अड़तीस", "उनतालीस",
    "चालीस", "इकतालीस", "बयालीस", "तैंतालीस", "चौवालीस", "पैंतालीस", "छियालीस", "सैंतालीस", "अड़तालीस", "उनचास",
    "पचास", "इक्यावन", "बावन", "तिरपन", "चौवन", "पचपन", "छप्पन", "सत्तावन", "अट्ठावन", "उनसठ",
    "साठ", "इकसठ", "बासठ", "तिरसठ", "चौंसठ", "पैंसठ", "छियासठ", "सड़सठ", "अड़सठ", "उनहत्तर",
    "सत्तर", "इकहत्तर", "बहत्तर", "तिहत्तर", "चौहत्तर", "पचहत्तर", "छिहत्तर", "सतहत्तर", "अठहत्तर", "उनासी",
    "अस्सी", "इक्यासी", "बयासी", "तिरासी", "चौरासी", "पचासी", "छियासी", "सत्तासी", "अट्ठासी", "नवासी",
    "नब्बे", "इक्यानवे", "बानवे", "तिरानवे", "चौरानवे", "पंचानवे", "छियानवे", "सत्तानवे", "अट्ठानवे", "निन्यानवे",
)  # fmt: skip
assert len(HI_0_99) == 100

HI_SCALES = {100: "सौ", 1000: "हज़ार", 100000: "लाख", 10000000: "करोड़"}
HI_FRACTIONS = {"sava": "सवा", "saadhe": "साढ़े", "paune": "पौने", "dedh": "डेढ़", "dhai": "ढाई"}

# English digits as Hindi ASR models spell them, for phone numbers read in English.
EN_DIGITS_DEV = ("ज़ीरो", "वन", "टू", "थ्री", "फ़ोर", "फ़ाइव", "सिक्स", "सेवन", "एट", "नाइन")
EN_DIGITS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
HI_WEEKDAYS = {
    "monday": ("सोमवार",),
    "tuesday": ("मंगलवार", "मंगल"),
    "wednesday": ("बुधवार", "बुध"),
    "thursday": ("गुरुवार", "बृहस्पतिवार", "वीरवार"),
    "friday": ("शुक्रवार", "शुक्र"),
    "saturday": ("शनिवार", "शनि"),
    "sunday": ("रविवार", "इतवार"),
}
EN_WEEKDAYS_DEV = {
    "monday": ("मंडे",),
    "tuesday": ("ट्यूज़डे",),
    "wednesday": ("वेडनेसडे", "वेंसडे"),
    "thursday": ("थर्सडे",),
    "friday": ("फ्राइडे",),
    "saturday": ("सैटरडे",),
    "sunday": ("संडे",),
}

# ---------------------------------------------------------------- Telugu

_TE_ONES = ("సున్నా", "ఒకటి", "రెండు", "మూడు", "నాలుగు", "ఐదు", "ఆరు", "ఏడు", "ఎనిమిది", "తొమ్మిది")
_TE_TEENS = ("పది", "పదకొండు", "పన్నెండు", "పదమూడు", "పద్నాలుగు", "పదిహేను", "పదహారు", "పదిహేడు",
             "పద్దెనిమిది", "పంతొమ్మిది")  # fmt: skip
TE_TENS = {20: "ఇరవై", 30: "ముప్పై", 40: "నలభై", 50: "యాభై", 60: "అరవై", 70: "డెబ్బై", 80: "ఎనభై", 90: "తొంభై"}
# Above twenty Telugu says the ten and the unit as two words, so only 0-19 and the tens are lexical.
TE_0_99: tuple[str, ...] = (
    *_TE_ONES,
    *_TE_TEENS,
    *(TE_TENS[n - n % 10] + (f" {_TE_ONES[n % 10]}" if n % 10 else "") for n in range(20, 100)),
)
assert len(TE_0_99) == 100

# A scale has three shapes: alone it already means one of it (వంద = 100, never "ఒకటి వంద"); after a
# multiplier it is plural when it ends the number (ఐదు వందలు) and oblique when more follows or a noun
# does (ఐదు వందల యాభై, ఐదు వందల రూపాయలు). One hundred with a remainder is నూట (నూట యాభై = 150).
TE_SCALE_ONE = {100: "వంద", 1000: "వెయ్యి", 100000: "లక్ష", 10000000: "కోటి"}
TE_SCALE_PLURAL = {100: "వందలు", 1000: "వేలు", 100000: "లక్షలు", 10000000: "కోట్లు"}
TE_SCALE_OBLIQUE = {100: "వందల", 1000: "వేల", 100000: "లక్షల", 10000000: "కోట్ల"}
TE_HUNDRED_AND = "నూట"
# Halves are a suffix on the multiplier (రెండున్నర వేలు = 2,500); quarters stand before the scale.
TE_HALF_SUFFIX = "న్నర"
TE_FRACTIONS = {"quarter": "పావు", "half": "అర", "three_quarters": "ముప్పావు"}

# English digits as Telugu recognisers spell them; most callers read a phone number this way.
EN_DIGITS_TE = ("జీరో", "వన్", "టూ", "త్రీ", "ఫోర్", "ఫైవ్", "సిక్స్", "సెవెన్", "ఎయిట్", "నైన్")
TE_WEEKDAYS = {
    "monday": ("సోమవారం",),
    "tuesday": ("మంగళవారం",),
    "wednesday": ("బుధవారం",),
    "thursday": ("గురువారం", "లక్ష్మివారం", "బేస్తవారం"),
    "friday": ("శుక్రవారం",),
    "saturday": ("శనివారం",),
    "sunday": ("ఆదివారం",),
}
EN_WEEKDAYS_TE = {
    "monday": ("మండే",),
    "tuesday": ("ట్యూస్డే",),
    "wednesday": ("వెడ్నెస్డే",),
    "thursday": ("థర్స్డే",),
    "friday": ("ఫ్రైడే",),
    "saturday": ("సాటర్డే",),
    "sunday": ("సండే",),
}
