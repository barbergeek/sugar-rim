"""Convert between our flat draft and Bar Assistant's "draft2" import schema.

BA v5 (``/import/cocktail`` and ``/import/scrape``) speaks draft2: the recipe
sits under ``recipe``, and each recipe ingredient references an entry in a
top-level ``ingredients`` list by ``_id``.
"""

from .base import make_draft

_RECIPE_FIELDS = ("description", "source", "garnish", "glass", "method")


def to_draft2(draft):
    """Flat draft -> draft2 document for ``/import/cocktail``."""
    recipe_ings, ings = [], []
    for i, ing in enumerate(draft.get("ingredients") or [], 1):
        _id = f"ingredient-{i}"
        ings.append({"_id": _id, "name": ing.get("name") or ""})
        recipe_ings.append(
            {
                "_id": _id,
                "amount": ing.get("amount") or 0,
                "amount_max": ing.get("amount_max"),
                "units": ing.get("units"),  # key is required by BA, even if null
                "note": ing.get("note"),
                "optional": bool(ing.get("optional")),
                "sort": ing.get("sort") or i,
            }
        )
    recipe = {
        "name": draft.get("name") or "",
        "instructions": draft.get("instructions") or "",
        **{k: draft.get(k) for k in _RECIPE_FIELDS},
        "tags": draft.get("tags") or [],
        "images": draft.get("images") or [],
        "ingredients": recipe_ings,
    }
    return {"recipe": recipe, "ingredients": ings}


def from_draft2(schema):
    """draft2 document from ``/import/scrape`` -> flat draft."""
    recipe = schema.get("recipe") or {}
    names = {i.get("_id"): i.get("name") for i in schema.get("ingredients") or []}
    ingredients = [
        {
            "name": ing.get("name") or names.get(ing.get("_id")) or "",
            "amount": ing.get("amount"),
            "amount_max": ing.get("amount_max"),
            "units": ing.get("units"),
            "note": ing.get("note"),
            "optional": bool(ing.get("optional")),
            "sort": ing.get("sort") or i,
        }
        for i, ing in enumerate(recipe.get("ingredients") or [], 1)
    ]
    return make_draft(
        name=recipe.get("name") or "",
        instructions=recipe.get("instructions") or "",
        **{k: recipe.get(k) for k in _RECIPE_FIELDS},
        tags=recipe.get("tags") or [],
        images=[
            {"uri": im.get("uri"), "copyright": im.get("copyright")}
            for im in recipe.get("images") or []
            if im.get("uri")
        ],
        ingredients=ingredients,
    )
