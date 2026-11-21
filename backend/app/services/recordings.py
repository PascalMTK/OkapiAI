"""Enregistrements du dataset liés à un message : de vraies phrases, dites par de vrais locuteurs.

Affichés sous les réponses du chat (« Dans le dataset »), pour toutes les langues :
  1. les contributions validées par la communauté qui ont une voix (toutes les langues) ;
  2. les corpus enregistrés : LRSC pour le lingala (CC BY 4.0), Common Voice pour le
     tshiluba (CC0, tools/import_tshiluba.py --audio).
Le swahili et le kikongo n'ont pour l'instant que les contributions validées.
"""
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import LANGUAGES
from ..models import TrainingEntry
from .corpus import corpus, corpus_lua_voice
from .lexicon import key
from .translator import audio_url

CORPORA = {"ln": corpus, "lua": corpus_lua_voice}


def _overlap(query: set[str], text: str) -> float:
    words = set(key(text).split())
    return len(query & words) / (1 + 0.15 * len(words)) if words else 0.0


def for_message(db: Session, lang: str, text: str, k: int = 3,
                exclude: Optional[set[str]] = None) -> list[dict]:
    """Jusqu'à `k` phrases enregistrées proches de `text`, dans la langue `lang`.
    [{text, translation, translation_lang, audio_url, source}]"""
    if lang not in LANGUAGES or not (text or "").strip():
        return []
    query = {w for w in key(text).split() if len(w) > 1}
    if not query:
        return []
    seen = {key(t) for t in (exclude or set())}
    out: list[dict] = []

    def add(item: dict) -> None:
        kk = key(item["text"])
        if kk and kk not in seen and len(out) < k:
            seen.add(kk)
            out.append(item)

    # 1. contributions validées avec une voix
    scored = []
    rows = db.scalars(select(TrainingEntry).where(
        TrainingEntry.audio_path.is_not(None),
        or_(TrainingEntry.source_lang == lang, TrainingEntry.target_lang == lang)))
    for e in rows:
        mine, other, other_lang = ((e.source_text, e.target_text, e.target_lang) if e.source_lang == lang
                                   else (e.target_text, e.source_text, e.source_lang))
        score = _overlap(query, mine)
        if score > 0:
            scored.append((score, mine, other if other_lang != lang else None, other_lang, e.audio_path))
    for score, mine, other, other_lang, path in sorted(scored, key=lambda x: -x[0]):
        add({"text": mine, "translation": other, "translation_lang": other_lang if other else None,
             "audio_url": audio_url(path), "source": "Contribution validée"})

    # 2. corpus enregistrés (seulement les phrases dont on a l'audio)
    c = CORPORA.get(lang)
    if c is not None and len(out) < k:
        for r in c.search(text, k=k * 3):
            if r.get("audio_url"):
                add({"text": r["text"], "translation": None, "translation_lang": None,
                     "audio_url": r["audio_url"], "source": r["source"]})
    return out
