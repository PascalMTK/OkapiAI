"""Normalisation et similarité de textes."""
import re
import unicodedata
from difflib import SequenceMatcher

_PUNCT = re.compile(r"[^\w\s']", re.UNICODE)


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFC", text or "").lower().strip()
    t = _PUNCT.sub(" ", t)
    return " ".join(t.split())


def similarity(a: str, b: str) -> float:
    """Score entre 0 et 1 sur des textes déjà normalisés."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def pair_similarity(src_a: str, tgt_a: str, src_b: str, tgt_b: str) -> float:
    """Deux paires (phrase, traduction) sont similaires si les DEUX côtés le sont."""
    return min(similarity(src_a, src_b), similarity(tgt_a, tgt_b))
