"""Fuzzy-match recipe ingredient names against a bar's existing ingredients.

Pure and stdlib-only. Not a scraper; do not register it.
"""

import re
import unicodedata
from difflib import SequenceMatcher

MIN_SCORE = 0.5
SHELF_BONUS = 0.03  # breaks near-ties only


def _singular(tok):
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
        return tok[:-1]
    return tok


def normalize(name):
    """Lowercase, strip accents/punctuation, singularize each token."""
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return [_singular(t) for t in re.findall(r"[^\W_]+", text)]


def _score(q, c):
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    qs, cs = set(q), set(c)
    if qs <= cs:  # "bourbon" in "bourbon whiskey"
        return max(0.6, 0.95 - 0.05 * (len(c) - len(q)))
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
