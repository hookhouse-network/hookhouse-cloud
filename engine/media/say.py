"""Say it right: rewrite numbers, money, units and Roman numerals into the words a narrator would say, before any
voice reads them (every voice line in every channel goes through voice.synthesize, which calls this).

Why (measured 13 Nov 2026 with our own voices, Kokoro + misaki / espeak):
- English: "World War II" -> "World War I I", "$4.5B" -> "four point five B", "1/3" -> "one three", "50 kg" ->
  "fifty K G", "100*" -> "one hundred" (cricket "not out" lost), "Mt." unknown.
- Hindi: "₹15,000 की फिल्म" -> "pandrah, shoonya shoonya shoonya" (no "rupees"), "1983" -> "ek hazaar nau sau
  tiraasi" (people say "unnees sau tiraasi"), "1/3" -> "ek slash teen", "2.5 करोड़" -> "do . paanch".
Idea from Agents365-ai/video-podcast-maker (MIT): "~90% of TTS mispronunciations live in numbers, proper nouns and
English terms", fixed with a pronunciation file. Ours: config/pronunciations.yaml (word -> phonemes or words).

Captions keep the written form ($4.5B looks right on screen); only the spoken text changes."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DICT = ROOT / "config" / "pronunciations.yaml"

# ---------- English ----------
_SCALE = {"k": "thousand", "m": "million", "mn": "million", "b": "billion", "bn": "billion", "t": "trillion",
          "thousand": "thousand", "million": "million", "billion": "billion", "trillion": "trillion",
          "cr": "crore", "crore": "crore", "lakh": "lakh", "lakhs": "lakh"}
_CUR_EN = {"$": "dollars", "₹": "rupees", "£": "pounds", "€": "euros", "Rs": "rupees", "Rs.": "rupees"}
_UNITS = [(r"km/h|kmph|kph", "kilometers per hour"), (r"mph", "miles per hour"), (r"km", "kilometers"),
          (r"kg", "kilograms"), (r"cm", "centimeters"), (r"mm", "millimeters"), (r"ft", "feet"),
          (r"lbs?", "pounds"), (r"°C", "degrees Celsius"), (r"°F", "degrees Fahrenheit"), (r"m", "meters")]
_ORD_DEN = {2: ("half", "halves"), 3: ("third", "thirds"), 4: ("quarter", "quarters"), 5: ("fifth", "fifths"),
            6: ("sixth", "sixths"), 7: ("seventh", "sevenths"), 8: ("eighth", "eighths"), 9: ("ninth", "ninths"),
            10: ("tenth", "tenths")}
_CARD = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty"]
_ORD = ["", "First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth", "Ninth", "Tenth", "Eleventh",
        "Twelfth", "Thirteenth", "Fourteenth", "Fifteenth", "Sixteenth", "Seventeenth", "Eighteenth", "Nineteenth",
        "Twentieth"]
_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11,
          "XII": 12, "XIII": 13, "XIV": 14, "XV": 15, "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20}
_ROMAN_RX = r"(XX|XIX|XVIII|XVII|XVI|XV|XIV|XIII|XII|XI|X|IX|VIII|VII|VI|V|IV|III|II|I)"
_COUNTED = r"(War|Part|Chapter|Volume|Vol\.|Season|Phase|Act|Episode|Book|Round|Level|Apollo|Super Bowl|Rocky|Type)"
# Kings, queens and popes: "Henry VIII" = Henry the Eighth (II and up, so "Chapter I" style words are not touched)
_REGNAL = (r"\b(Henry|Louis|Charles|Elizabeth|George|Edward|William|James|Richard|John Paul|John|Paul|Pius|Leo|"
           r"Benedict|Gregory|Innocent|Philip|Frederick|Napoleon|Peter|Catherine|Mary|Ramesses|Ramses|Thutmose|"
           r"Amenhotep|Nicholas|Alexander|Ivan|Constantine|Justinian|Victor Emmanuel|Ferdinand|Isabella|Alfonso|"
           r"Wilhelm|Franz|Otto|Rudolf|Gustav|Christian|Olav|Haakon|Carl|Felipe|Juan Carlos|Umberto)\s+")


def _num(s: str) -> str:
    return s.replace(",", "")


def _en_money(m: re.Match) -> str:
    cur, n, scale = m.group(1), _num(m.group(2)), (m.group(3) or "").strip()
    word = _SCALE.get(scale.lower().rstrip("."), "") if scale else ""
    unit = _CUR_EN.get(cur.strip(), "dollars")
    if not word and n == "1":
        unit = unit[:-1]
    return f"{n} {word + ' ' if word else ''}{unit}"


def _en_fraction(m: re.Match) -> str:
    a, b = int(m.group(1)), int(m.group(2))
    if a < b and b in _ORD_DEN and a <= 20:
        if a == 1:
            return "one " + _ORD_DEN[b][0] if b != 4 else "a quarter"
        return f"{_CARD[a]} {_ORD_DEN[b][1]}"
    if (a, b) == (24, 7):
        return "twenty-four seven"
    if a >= 20 and b <= 10:                    # cricket score: 245/6 = "245 for 6"
        return f"{a} for {b}"
    return m.group(0)


def english(text: str) -> str:
    t = text
    t = re.sub(r"(\$|₹|£|€|\bRs\.?)\s?(\d[\d,]*(?:\.\d+)?)(?:\s?(thousand|million|billion|trillion|crore|lakhs?|"
               r"bn|mn|cr|[KMBT]))?\b(?=\W|$)", _en_money, t)
    for unit, word in _UNITS:
        t = re.sub(rf"(\d)\s?(?:{unit})(?=[\s.,;:!?)]|$)", rf"\1 {word}", t)
    t = re.sub(r"\b(\d{1,3})/(\d{1,2})\b(?!/)", _en_fraction, t)
    t = re.sub(r"(\d)\*", r"\1 not out", t)
    t = re.sub(r"\b(\d{1,2}):00\s?(am|pm|a\.m\.|p\.m\.)", r"\1 \2", t, flags=re.I)
    t = re.sub(r"\b(\d{1,2}):(0\d)\s?(am|pm|a\.m\.|p\.m\.)", lambda m: f"{m.group(1)} oh {int(m.group(2))} {m.group(3)}",
               t, flags=re.I)
    t = re.sub(r"\b(\d{1,2}):([1-5]\d)\s?(am|pm|a\.m\.|p\.m\.)", r"\1 \2 \3", t, flags=re.I)
    t = re.sub(rf"\b{_COUNTED}\s+{_ROMAN_RX[:-3]})\b",           # II and up (a bare "I" may be the word "I")
               lambda m: f"{m.group(1)} {_CARD[_ROMAN[m.group(2)]].capitalize()}", t)
    t = re.sub(rf"\b(World War|{_COUNTED[1:-1]})\s+I(?=\s*[.,;:!?)\]]|\s*$|\s+(?:ended|began|started|veterans?|"
               rf"soldiers?|broke out|was|is|had|and)\b)", lambda m: f"{m.group(1)} One", t)
    t = re.sub(_REGNAL + r"(XX|XIX|XVIII|XVII|XVI|XV|XIV|XIII|XII|XI|X|IX|VIII|VII|VI|V|IV|III|II)\b",
               lambda m: f"{m.group(1)} the {_ORD[_ROMAN[m.group(2)]]}", t)
    t = re.sub(r"\bMt\.\s", "Mount ", t)
    t = re.sub(r"\s&\s", " and ", t)
    return t


# ---------- Hindi (Devanagari narration, espeak reads the digits) ----------
_FRAC_HI = {(1, 2): "आधा", (1, 3): "एक तिहाई", (2, 3): "दो तिहाई", (1, 4): "एक चौथाई", (3, 4): "तीन चौथाई"}
_CUR_HI = {"₹": "रुपये", "Rs": "रुपये", "Rs.": "रुपये", "$": "डॉलर", "£": "पाउंड", "€": "यूरो"}
_SCALE_HI = {"करोड़": "करोड़", "करोड़": "करोड़", "लाख": "लाख", "हज़ार": "हज़ार", "हजार": "हज़ार", "cr": "करोड़",
             "crore": "करोड़", "lakh": "लाख", "k": "हज़ार", "m": "मिलियन", "mn": "मिलियन", "million": "मिलियन",
             "b": "बिलियन", "bn": "बिलियन", "billion": "बिलियन", "t": "ट्रिलियन", "trillion": "ट्रिलियन"}


def _hi_decimal(n: str) -> str:
    """1.5 = डेढ़, 2.5 = ढाई, 3.5 = साढ़े 3 (how people say it), else "2 दशमलव 75"."""
    whole, _, frac = n.partition(".")
    if frac == "5":
        return {"1": "डेढ़", "2": "ढाई"}.get(whole, f"साढ़े {whole}")
    return f"{whole} दशमलव {' '.join(frac)}" if frac else whole


def _hi_money(m: re.Match) -> str:
    cur, n, scale = m.group(1).strip(), _num(m.group(2)), (m.group(3) or "").strip()
    word = _SCALE_HI.get(scale.lower(), scale) if scale else ""
    return f"{_hi_decimal(n)} {word + ' ' if word else ''}{_CUR_HI.get(cur, 'रुपये')}"


def hindi(text: str) -> str:
    t = text
    t = re.sub(r"(₹|\$|£|€|\bRs\.?)\s?(\d[\d,]*(?:\.\d+)?)(?:\s?(करोड़|करोड़|लाख|हज़ार|हजार|crore|lakh|cr|million|"
               r"billion|trillion|bn|mn|[KMBTkmbt](?![a-zA-Z])))?", _hi_money, t)
    t = re.sub(r"(\d),(?=\d)", r"\1", t)                                  # 15,000 / 1,50,000 -> lakh / hazaar
    t = re.sub(r"\b(\d+\.\d+)(?=\s?(?:करोड़|करोड़|लाख|हज़ार|हजार|प्रतिशत|%|साल|घंटे|किलो|मीटर))",
               lambda m: _hi_decimal(m.group(1)), t)
    t = re.sub(r"(?<!\d)(?<!\d[.,])(1[1-9])(\d\d)(?!\d|[.,]\d|\s?(?:रुपये|रुपए|करोड़|लाख|लोग|किलो|मीटर|किमी|km|kg))",
               lambda m: f"{m.group(1)} सौ" + ("" if m.group(2) == "00" else f" {int(m.group(2))}"), t)
    t = re.sub(r"\b(\d)/(\d)\b", lambda m: _FRAC_HI.get((int(m.group(1)), int(m.group(2))),
                                                        f"{m.group(1)} बटा {m.group(2)}"), t)
    t = re.sub(r"(\d)\*", r"\1 नॉट आउट", t)
    t = re.sub(r"\s&\s", " और ", t)
    return t


# Hindi number words (0-99 are irregular in Hindi, so a table), then सौ / हज़ार / लाख / करोड़. Used for the Parler
# voice, which reads digits unreliably (Whisper heard "183" as nonsense; 13 Nov 2026 test).
_HI_0_99 = "शून्य एक दो तीन चार पाँच छह सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह उन्नीस बीस इक्कीस बाईस तेईस चौबीस पच्चीस छब्बीस सत्ताईस अट्ठाईस उनतीस तीस इकतीस बत्तीस तैंतीस चौंतीस पैंतीस छत्तीस सैंतीस अड़तीस उनतालीस चालीस इकतालीस बयालीस तैंतालीस चवालीस पैंतालीस छियालीस सैंतालीस अड़तालीस उनचास पचास इक्यावन बावन तिरपन चौवन पचपन छप्पन सत्तावन अट्ठावन उनसठ साठ इकसठ बासठ तिरसठ चौंसठ पैंसठ छियासठ सड़सठ अड़सठ उनहत्तर सत्तर इकहत्तर बहत्तर तिहत्तर चौहत्तर पचहत्तर छिहत्तर सतहत्तर अठहत्तर उन्यासी अस्सी इक्यासी बयासी तिरासी चौरासी पचासी छियासी सत्तासी अट्ठासी नवासी नब्बे इक्यानवे बानवे तिरानवे चौरानवे पंचानवे छियानवे सत्तानवे अट्ठानवे निन्यानवे".split()


def hi_words(n: int) -> str:
    if n < 100:
        return _HI_0_99[n]
    for size, name in ((10**7, "करोड़"), (10**5, "लाख"), (1000, "हज़ार"), (100, "सौ")):
        if n >= size:
            head, rest = divmod(n, size)
            return f"{hi_words(head)} {name}" + (f" {hi_words(rest)}" if rest else "")
    return ""


def _hi_digits(m: re.Match) -> str:
    s = m.group(0)
    if len(s) > 9 or (len(s) > 1 and s.startswith("0")):            # phone numbers, codes: digit by digit
        return " ".join(_HI_0_99[int(c)] for c in s)
    return hi_words(int(s))


# Common English words in Hindi narration, as a Hindi speaker says them (the Kokoro Hindi voice mangles Latin letters:
# Whisper heard "Kapil Dev" as "कापल देव", "Gavaskar" as "कावास का"). The writer now uses Devanagari; this catches
# what slips through. Names go in config/pronunciations.yaml (hi:).
_ROMAN_HI = {"tv": "टीवी", "world": "वर्ल्ड", "cup": "कप", "zero": "ज़ीरो", "test": "टेस्ट", "match": "मैच",
             "india": "इंडिया", "team": "टीम", "captain": "कैप्टन", "run": "रन", "runs": "रन", "over": "ओवर",
             "overs": "ओवर", "wicket": "विकेट", "film": "फिल्म", "movie": "मूवी", "box": "बॉक्स", "office": "ऑफिस",
             "hero": "हीरो", "superstar": "सुपरस्टार", "camera": "कैमरा", "shooting": "शूटिंग", "record": "रिकॉर्ड",
             "video": "वीडियो", "final": "फाइनल", "semi": "सेमी", "ok": "ओके", "sorry": "सॉरी", "thank": "थैंक",
             "you": "यू", "please": "प्लीज़", "news": "न्यूज़", "police": "पुलिस", "doctor": "डॉक्टर", "school": "स्कूल",
             "bat": "बैट", "ball": "बॉल", "six": "सिक्स", "four": "फोर", "century": "सेंचुरी", "stadium": "स्टेडियम"}


# ---------- pronunciation file ----------
@lru_cache(maxsize=1)
def _dictionary() -> dict:
    if not DICT.exists():
        return {}
    import yaml
    data = yaml.safe_load(DICT.read_text(encoding="utf-8")) or {}
    return {k: {str(w): str(p) for w, p in (v or {}).items()} for k, v in data.items() if isinstance(v, dict)}


def _apply_dictionary(text: str, lang: str) -> str:
    entries = _dictionary().get("hi" if lang == "hi" else "en", {})
    for word, say in sorted(entries.items(), key=lambda kv: -len(kv[0])):
        if lang != "hi" and say.startswith("/") and say.endswith("/"):        # phonemes: Kokoro's [word](/ipa/)
            repl = lambda m, s=say: f"[{m.group(0)}]({s})"
        else:
            repl = lambda m, s=say: s
        text = re.sub(rf"(?<![\w\[])({re.escape(word)})(?![\w\]])", repl, text)
    return text


def normalise(text: str, language: str = "en", engine: str = "kokoro") -> str:
    lang = "hi" if str(language).lower().startswith("hi") else "en"
    out = hindi(text) if lang == "hi" else english(text)
    if lang == "hi" and engine in ("kokoro", "parler"):   # mid-line '…' left an odd hole: a comma instead
        out = re.sub(r"\s*…\s*(?=\S)", ", ", out)
        out = re.sub(r"[A-Za-z][A-Za-z'.-]*", lambda m: _ROMAN_HI.get(m.group(0).lower(), m.group(0)), out)
    out = _apply_dictionary(out, lang)
    if lang == "hi" and engine == "parler":                # Parler reads words far better than digits
        out = re.sub(r"\d+", _hi_digits, out)
    return out
