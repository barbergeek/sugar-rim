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


def test_cut_and_prep_words_ignored():
    assert rank("Orange slices", pool(("Orange", False)))[0]["score"] == 0.95
    p = pool(("Rosemary", False), ("Apple Juice", False), ("Apple", False))
    assert rank("Stalks fresh rosemary", p)[0]["name"] == "Rosemary"
    assert rank("Apple slices", p)[0]["name"] == "Apple"


def test_candidate_in_longer_query_sharing_head_word():
    p = pool(("Maple syrup", False), ("Syrups", False), ("Simple Syrup", False))
    res = rank("Grade A dark amber maple syrup", p)
    assert res[0]["name"] == "Maple syrup" and res[0]["score"] >= 0.8
    # a one-word parent category is suggested but not confident
    assert next(r for r in res if r["name"] == "Syrups")["score"] < 0.8


def test_non_latin_and_non_decomposable_letters():
    assert rank("Øl", pool(("øl", False)))[0]["score"] == 1.0
    assert rank("Водка", pool(("водка", False)))[0]["score"] == 1.0


def test_synonym_and_filler_are_soft_confident():
    p = pool(("Agave Syrup", False), ("Lime Juice", True), ("Lime", False))
    agave = rank("Agave nectar", p)[0]
    assert agave["name"] == "Agave Syrup" and agave["score"] == 0.95
    lime = rank("Fresh lime juice", p)[0]
    assert lime["name"] == "Lime Juice" and lime["score"] == 0.95


def test_filler_only_name_still_matches_itself():
    assert rank("Fresh", pool(("Fresh", False)))[0]["score"] == 1.0


def test_one_word_generic_not_confident_for_a_more_specific_kind():
    # "Gin" is the head noun of "Sloe Gin", which is a different product
    assert rank("Gin", pool(("Sloe Gin", False)))[0]["score"] < 0.8
    # ...but a qualifier of the candidate's head is still confident
    assert rank("Bourbon", pool(("Bourbon Whiskey", False)))[0]["score"] >= 0.8
