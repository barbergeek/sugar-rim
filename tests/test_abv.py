import abv

BUILD = {"name": "Build", "dilution_percentage": 10}
SHAKE = {"name": "Shake", "dilution_percentage": 20}


def line(ing_id, amount, units):
    return {
        "amount": amount,
        "units": units,
        "ingredient": {"id": ing_id, "name": f"I{ing_id}"},
    }


def cocktail(method, *lines, abv_value=0):
    return {"method": method, "abv": abv_value, "ingredients": list(lines)}


BATCH_STRENGTHS = {1: 40, 2: 0, 3: 0, 4: 0}


def test_batch_in_cups():
    c = cocktail(
        BUILD,
        line(1, 4, "cup"),
        line(2, 1, "cup"),
        line(3, 2, "cup"),
        line(4, 3, "whole"),
    )
    assert abv.needs_estimate(c)
    assert abv.estimate(c, BATCH_STRENGTHS) == 20.78


def test_mixed_units_count_quart_and_oz_and_skip_whole():
    c = cocktail(BUILD, line(1, 1, "quart"), line(2, 2, "oz"), line(3, 1, "whole"))
    ml = 946.353 + 60
    expected = round((946.353 * 0.08 + 60 * 0.4) / (ml * 1.1) * 100, 2)
    assert abv.estimate(c, {1: 8, 2: 40, 3: 0}) == expected


def test_spoons_count_once_recomputing():
    c = cocktail(BUILD, line(1, 1, "cup"), line(2, 2, "TBSP"), line(3, 1, "sprig"))
    ml = 236.588 + 2 * 14.787
    expected = round((236.588 * 0.4 + 2 * 14.787 * 0.2) / (ml * 1.1) * 100, 2)
    assert abv.estimate(c, {1: 40, 2: 20, 3: 0}) == expected


def test_regular_drink_is_not_recomputed():
    c = cocktail(SHAKE, line(1, 2, "oz"), line(2, 2, "dashes"), abv_value=25.1)
    assert not abv.needs_estimate(c)
    assert abv.estimate(c, {1: 40, 2: 45}) is None


def test_ba_native_units_are_not_recomputed():
    # Irish Coffee style: all BA-native units, BA's value stands.
    c = cocktail(
        BUILD,
        line(1, 4, "cl"),
        line(2, 8, "cl"),
        line(3, 1, "barspoon"),
        line(4, 3, "cl"),
        abv_value=9.92,
    )
    assert not abv.needs_estimate(c)
    assert abv.estimate(c, {1: 40, 2: 0, 3: 0, 4: 0}) is None


def test_large_measure_on_a_non_alcoholic_line_is_recomputed():
    # Juice in cups, spirit in oz: BA skips the cups and overstates the ABV.
    c = cocktail(BUILD, line(1, 1, "cup"), line(2, 2, "oz"), abv_value=33.33)
    assert abv.needs_estimate(c)
    assert abv.estimate(c, {1: 0, 2: 40}) == 7.36


def test_batch_with_no_alcohol_is_zero():
    c = cocktail(BUILD, line(1, 2, "cup"), line(2, 1, "cup"))
    assert abv.estimate(c, {1: 0, 2: 0}) == 0.0


def test_abbreviations_and_spellings_count():
    c = cocktail(BUILD, line(1, 1, "qt"), line(2, 4, "ounces"))
    ml = 946.353 + 120
    expected = round((946.353 * 0.08 + 120 * 0.4) / (ml * 1.1) * 100, 2)
    assert abv.needs_estimate(c)
    assert abv.estimate(c, {1: 8, 2: 40}) == expected


def test_every_large_measure_spelling_triggers():
    for units in (
        "cup",
        "Cups",
        " c ",
        "pint",
        "pints",
        "PT",
        "quart",
        "quarts",
        "qt",
        "gallon",
        "gallons",
        "gal",
        "liter",
        "Liters",
        "litre",
        "litres",
    ):
        assert abv.needs_estimate(cocktail(BUILD, line(1, 1, units))), units


def test_spelling_variants_of_ba_units_count_once_recomputing():
    variants = {
        "ounce": 30,
        "ounces": 30,
        "fl oz": 30,
        "parts": 30,
        "shots": 30,
        "barspoons": 5,
        "dashes": 0.3125,
        "tsp": 4.929,
        "teaspoons": 4.929,
        "tablespoon": 14.787,
    }
    for units, ml in variants.items():
        c = cocktail(BUILD, line(1, 1, "cup"), line(2, 2, units))
        expected = round(2 * ml * 0.4 / ((236.588 + 2 * ml) * 1.1) * 100, 2)
        assert abv.estimate(c, {1: 0, 2: 40}) == expected, units


def test_unknown_units_are_not_triggers():
    c = cocktail(BUILD, line(1, 1, "bottle"), line(2, 2, "dashes"), line(3, 1, "tsp"))
    assert not abv.needs_estimate(c)
    assert abv.estimate(c, {1: 40, 2: 40, 3: 40}) is None


def test_no_method_keeps_ba_value():
    c = cocktail(None, line(1, 2, "cups"), abv_value=None)
    assert abv.estimate(c, {1: 40}) is None


def test_lines_without_amount_are_skipped():
    c = cocktail(BUILD, line(1, 1, "gallon"), line(2, None, "cup"))
    assert abv.estimate(c, {1: 40, 2: 40}) == round(40 / 1.1, 2)
