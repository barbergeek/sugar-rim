"""ABV estimate for batch cocktails measured in cups, pints, quarts or gallons.

Bar Assistant only counts lines in its own units (ml, cl, oz, ...) and skips
the rest, so a batch written in cups comes back with ABV 0. This recomputes
ABV with BA's formula (Utils::calculateAbv) for those cocktails only,
converting to ml for the math; amounts and units shown are never changed.
"""

# BA's own units and factors (karlomikus/recipe-utils), in ml.
_NATIVE = {
    "ml": 1,
    "cl": 10,
    "oz": 30,
    "dash": 0.3125,
    "shot": 30,
    "part": 30,
    "l": 1000,
    "barspoon": 5,
}

# Larger US measures: any line in one of these triggers the estimate.
_LARGE = {
    "cup": 236.588,
    "cups": 236.588,
    "c": 236.588,
    "pint": 473.176,
    "pints": 473.176,
    "pt": 473.176,
    "quart": 946.353,
    "quarts": 946.353,
    "qt": 946.353,
    "gallon": 3785.41,
    "gallons": 3785.41,
    "gal": 3785.41,
    "liter": 1000,
    "liters": 1000,
    "litre": 1000,
    "litres": 1000,
}

# Counted once a cocktail is being recomputed: batches measure syrups in
# spoons, and spell BA's own units in ways BA doesn't match.
_EXTRA = {
    "tbsp": 14.787,
    "tablespoon": 14.787,
    "tablespoons": 14.787,
    "tsp": 4.929,
    "teaspoon": 4.929,
    "teaspoons": 4.929,
    "dashes": 0.3125,
    "ounce": 30,
    "ounces": 30,
    "fl oz": 30,
    "parts": 30,
    "shots": 30,
    "barspoons": 5,
}

_ML = {**_NATIVE, **_LARGE, **_EXTRA}


def _unit(line):
    return str(line.get("units") or "").strip().lower()


def _ingredient_id(line):
    return (line.get("ingredient") or {}).get("id")


def _amount(line):
    try:
        return float(line.get("amount"))
    except (TypeError, ValueError):
        return None


def needs_estimate(cocktail):
    """True if any line uses a large measure."""
    return any(_unit(i) in _LARGE for i in cocktail.get("ingredients") or [])


def ingredient_ids(cocktail):
    return {_ingredient_id(i) for i in cocktail.get("ingredients") or []} - {None}


def estimate(cocktail, strengths):
    """BA's ABV formula with large measures counted, or None to keep BA's value
    (no method, or no large-measure line).
    strengths maps ingredient id -> strength (% ABV)."""
    method = cocktail.get("method")
    if not method or not needs_estimate(cocktail):
        return None
    lines = cocktail.get("ingredients") or []
    alcohol = diluted = 0.0
    dilution = float(method.get("dilution_percentage") or 0)
    for line in lines:
        factor = _ML.get(_unit(line))
        amount = _amount(line)
        if factor is None or amount is None:
            continue
        ml = amount * factor
        alcohol += ml * float(strengths.get(_ingredient_id(line)) or 0) / 100
        diluted += ml * (1 + dilution / 100)
    if diluted <= 0:
        return 0.0
    return round(alcohol / diluted * 100, 2)
