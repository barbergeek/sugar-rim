from scrapers.match import rank


def pool(*items):
    return [{"id": i, "name": n, "on_shelf": s} for i, (n, s) in enumerate(items, 1)]


def names(res):
    return [r["name"] for r in res]


def test_partial_name_shelf_first():
    res = rank("Bourbon", pool(("Rye Whiskey", False), ("Bourbon Whiskey", True)))
    assert names(res) == ["Bourbon Whiskey"]
    assert res[0]["on_shelf"] and 0.8 <= res[0]["score"] < 1.0


def test_exact_case_space():
    res = rank("simple  syrup", pool(("Simple Syrup", False)))
    assert res[0]["score"] == 1.0


def test_plural_and_punctuation():
    p = pool(("Lime", False), ("Angostura Bitters", False))
    assert rank("Limes", p)[0]["name"] == "Lime"
    assert rank("Limes", p)[0]["score"] == 1.0
    assert rank("Angostura bitters", p)[0]["name"] == "Angostura Bitters"
    assert rank("Angostura, bitter", p)[0]["score"] == 1.0


def test_accents():
    assert rank("creme de cacao", pool(("Crème de Cacao", False)))[0]["score"] == 1.0


def test_no_match():
    assert rank("Unicorn tears", pool(("Bourbon Whiskey", True), ("Lime", False))) == []


def test_shelf_tiebreak():
    res = rank("Vermouth", pool(("Dry Vermouth", False), ("Sweet Vermouth", True)))
    assert names(res) == ["Sweet Vermouth", "Dry Vermouth"]


def test_limit_and_empty():
    p = pool(*[(f"Vermouth {c}", False) for c in "abcdefg"])
    assert len(rank("vermouth", p)) == 5
    assert len(rank("vermouth", p, limit=2)) == 2
    assert rank("", p) == []


def test_candidate_contained_in_query_not_confident():
    assert rank("Lime juice", pool(("Lime", False)))[0]["score"] < 0.8
    assert rank("Orange slices", pool(("Orange", False)))[0]["score"] < 0.8


def test_non_latin_and_non_decomposable_letters():
    assert rank("Øl", pool(("øl", False)))[0]["score"] == 1.0
    assert rank("Водка", pool(("водка", False)))[0]["score"] == 1.0
