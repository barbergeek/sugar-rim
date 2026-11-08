"""Fuzzy-match recipe ingredient names against a bar's existing ingredients.

Pure and stdlib-only. Not a scraper; do not register it.
"""

import re
import unicodedata
from difflib import SequenceMatcher

MIN_SCORE = 0.5
SHELF_BONUS = 0.03  # breaks near-ties only
SYNONYMS = {"nectar": "syrup"}
# Prep, cut and quality words that don't change which ingredient it is.
FILLER = {
    "fresh", "freshly", "squeezed", "whole", "slice", "wedge", "wheel", "sprig",
    "stalk", "stem", "leaf", "leave", "chunk", "large", "small", "medium",
    "grade", "quality", "good", "ripe", "chilled", "cold", "organic",
    "a", "an", "of", "the", "inch",
}  # fmt: skip


def _singular(tok):
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
        return tok[:-1]
    return tok


def normalize(name):
    """Lowercase, strip accents/punctuation, singularize each token."""
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return [_singular(t) for t in re.findall(r"[^\W_]+", text)]


def _canonical(tokens):
    """Map synonyms and drop filler words ("fresh", "whole")."""
    out = [SYNONYMS.get(t, t) for t in tokens if t not in FILLER and not t.isdigit()]
    return out or tokens


def _score(q, c):
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    q, c = _canonical(q), _canonical(c)
    if q == c:  # "agave nectar" ~ "agave syrup": confident, but not exact
        return 0.95
    qs, cs = set(q), set(c)
    if qs <= cs:  # "bourbon" in "bourbon whiskey"
        # "gin" in "sloe gin": a specific kind, not the thing itself
        if len(q) == 1 and q[0] == c[-1]:
            return 0.7
        return max(0.6, 0.95 - 0.05 * (len(c) - len(q)))
    if cs <= qs and q[-1] == c[-1]:  # "maple syrup" in "dark amber maple syrup"
        return {1: 0.7, 2: 0.85}.get(len(cs), 0.9)
    ratio = SequenceMatcher(None, " ".join(q), " ".join(c)).ratio()
    overlap = len(qs & cs) / len(qs | cs)
    return 0.6 * ratio + 0.4 * overlap


def rank(name, candidates, limit=5):
    """Best matches for ``name`` among ``[{id, name, on_shelf}]``.

    Returns at most ``limit`` ``{id, name, on_shelf, score}`` dicts with
    score >= 0.5, best first (shelf ingredients win near-ties).
    """
    q = normalize(name)
    scored = []
    for cand in candidates:
        s = _score(q, normalize(cand.get("name")))
        if s < MIN_SCORE:
            continue
        on_shelf = bool(cand.get("on_shelf"))
        key = s + (SHELF_BONUS if on_shelf else 0)
        scored.append(
            (
                -key,
                cand.get("name") or "",
                {
                    "id": cand.get("id"),
                    "name": cand.get("name"),
                    "on_shelf": on_shelf,
                    "score": round(s, 3),
                },
            )
        )
    scored.sort(key=lambda t: t[:2])
    return [t[2] for t in scored[:limit]]
