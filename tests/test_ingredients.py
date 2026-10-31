import pytest

from scrapers.ingredients import parse_line


def p(text):
    r = parse_line(text)
    return r["amount"], r["amount_max"], r["units"], r["name"], r["note"]


@pytest.mark.parametrize(
    "line,expected",
    [
        (
            "One 750-milliliter bottle bourbon, such as Four Roses",
            (750, None, "ml", "Bourbon", "such as Four Roses"),
        ),
        (
            "Half of a 750-milliliter bottle allspice dram, such as St. Elizabeth's",
            (375, None, "ml", "Allspice dram", "such as St. Elizabeth's"),
        ),
        ("1/4 cup agave nectar ", (0.25, None, "cup", "Agave nectar", None)),
        ("1 1/2 oz gin", (1.5, None, "oz", "Gin", None)),
        ("½ oz lime juice", (0.5, None, "oz", "Lime juice", None)),
        ("2-3 dashes bitters", (2, 3, "dash", "Bitters", None)),
        ("2 navel oranges, sliced", (2, None, None, "Navel oranges", "sliced")),
        (
            "One 750-milliliter bottle sweet vermouth",
            (750, None, "ml", "Sweet vermouth", None),
        ),
        ("2 12-ounce cans soda water", (24, None, "oz", "Soda water", None)),
        ("2oz gin", (2, None, "oz", "Gin", None)),
        ("1.5oz rye", (1.5, None, "oz", "Rye", None)),
        ("Ice", (None, None, None, "Ice", None)),
        ("Half of lime", (0.5, None, None, "Lime", None)),
        ("2 oz of gin", (2, None, "oz", "Gin", None)),
    ],
)
def test_parse_line(line, expected):
    assert p(line) == expected


def test_optional_flag_stripped():
    r = parse_line("1 dash absinthe (optional)")
    assert (r["optional"], r["name"], r["units"]) == (True, "Absinthe", "dash")
