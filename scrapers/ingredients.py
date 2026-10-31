"""Parse free-text ingredient lines into Bar Assistant ingredient dicts."""

import re

_FRACTIONS = {
    "½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4",
    "⅕": "1/5", "⅖": "2/5", "⅗": "3/5", "⅘": "4/5", "⅙": "1/6",
    "⅚": "5/6", "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8",
}  # fmt: skip

_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}  # fmt: skip

_UNITS = {
    "oz": "oz", "ounce": "oz", "fl oz": "oz", "fl. oz": "oz", "floz": "oz", "fluid ounce": "oz",
    "ml": "ml", "milliliter": "ml", "millilitre": "ml",
    "cl": "cl", "centiliter": "cl", "centilitre": "cl",
    "cup": "cup",
    "tbsp": "tbsp", "tablespoon": "tbsp", "tbs": "tbsp", "tbl": "tbsp",
    "tsp": "tsp", "teaspoon": "tsp",
    "dash": "dash", "drop": "drop",
    "barspoon": "barspoon", "bar spoon": "barspoon", "bsp": "barspoon",
    "part": "part", "splash": "splash",
}  # fmt: skip

_CONTAINERS = ("bottle", "can", "jar", "carton", "box")

_NUM = r"\d+(?:\.\d+)?"
_QTY = rf"(?:{_NUM}(?:\s+\d+/\d+)?|\d+/\d+)"
_QTY_RE = re.compile(rf"^({_QTY})(?:\s*(?:-|–|—|to)\s*({_QTY})(?![\d/]))?(?![\d/.])")
_WORD_RE = re.compile(
    r"^(half\s+of\s+an?|half\s+an?|half|" + "|".join(_WORDS) + r")\s+", re.IGNORECASE
)
_UNIT_RE = re.compile(
    r"^(fl\.?\s*oz|fluid\s+ounces?|bar\s+spoons?|[A-Za-z]+)\b\.?\s*", re.IGNORECASE
)
_SIZE_RE = re.compile(rf"^({_NUM})\s*-?\s*([a-zA-Z]+(?:\s?oz)?)\b\.?\s*")


def _to_num(s):
    s = s.strip()
    total = 0.0
    for part in s.split():
        if "/" in part:
            n, d = part.split("/")
            total += int(n) / int(d)
        else:
            total += float(part)
    return int(total) if total == int(total) else round(total, 4)


def _unit(word):
    w = word.lower().strip(".")
    if w in _UNITS:
        return _UNITS[w]
    if w.endswith("es") and w[:-2] in _UNITS:
        return _UNITS[w[:-2]]
    if w.endswith("s") and w[:-1] in _UNITS:
        return _UNITS[w[:-1]]
    return None


def _num(v):
    return int(v) if float(v) == int(v) else round(v, 4)


def parse_line(text):
    s = " ".join(text.split())
    for ch, rep in _FRACTIONS.items():
        s = re.sub(rf"(\d){ch}", rf"\1 {rep}", s).replace(ch, rep)
    optional = bool(re.search(r"\(?\boptional\b\)?", s, re.IGNORECASE))
    if optional:
        s = re.sub(r"[,(]?\s*\(?\boptional\b\)?", "", s, flags=re.IGNORECASE).strip(
            " ,"
        )

    amount = amount_max = None
    unit = None
    rest = s

    m = _WORD_RE.match(s)
    if m:
        w = m.group(1).lower()
        amount = 0.5 if w.startswith("half") else _WORDS[w]
        rest = s[m.end() :]
        if w == "half" and rest.lower().startswith("of "):
            rest = rest[3:]
        # "a"/"an" followed by nothing useful, e.g. "A twist": keep as 1
    else:
        m = _QTY_RE.match(s)
        if m:
            amount = _to_num(m.group(1))
            if m.group(2):
                amount_max = _to_num(m.group(2))
            rest = s[m.end() :].lstrip()

    if amount is not None:
        # "<n> <size>-<unit> bottle": multiply count by size
        sm = _SIZE_RE.match(rest)
        if sm and amount_max is None and _unit(sm.group(2)):
            unit = _unit(sm.group(2))
            amount = _num(amount * float(sm.group(1)))
            rest = rest[sm.end() :]
            cm = re.match(rf"({'|'.join(_CONTAINERS)})s?\b\s*", rest, re.IGNORECASE)
            if cm:
                rest = rest[cm.end() :]
        else:
            um = _UNIT_RE.match(rest)
            if um and _unit(re.sub(r"\s+", " ", um.group(1))):
                unit = _unit(re.sub(r"\s+", " ", um.group(1)))
                rest = rest[um.end() :]
        if unit and rest.lower().startswith("of "):
            rest = rest[3:]
    if amount is None:
        rest = s

    name, _, note = rest.partition(",")
    name = name.strip()
    note = note.strip() or None
    if name:
        name = name[0].upper() + name[1:]
    return {
        "name": name,
        "amount": amount,
        "amount_max": amount_max,
        "units": unit,
        "note": note,
        "optional": optional,
    }
