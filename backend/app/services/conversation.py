"""Converser avec le système en langue nationale.

Ordre :
  1. Dialogue validé par la communauté (dataset_entrainement, type "dialogue").
  2. IA (Claude), ancrée sur les exemples validés les plus proches.
  3. Sinon : le bot demande à l'utilisateur de lui apprendre une réponse.
Chaque réponse peut être corrigée par l'utilisateur -> nouvelle contribution "dialogue"
qui suivra la règle des 10 personnes + validation admin.
"""
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import LOOKUP_THRESHOLD
from ..models import DIALOGUE, TRADUCTION, TrainingEntry
from ..similarity import normalize, similarity
from . import translator
from .llm import claude_chat

MAX_EXAMPLES = 25


def _relevance(query: str, words: set[str], text_norm: str) -> float:
    tw = set(text_norm.split())
    overlap = len(words & tw) / max(1, len(words | tw))
    return max(overlap, similarity(query, text_norm) * 0.8)


def grounding_examples(db: Session, lang: str, query: str) -> list[dict]:
    """Exemples validés (dialogues + traductions) les plus proches du message."""
    words = set(query.split())
    scored = []
    rows = db.scalars(select(TrainingEntry).where(
        or_(TrainingEntry.source_lang == lang, TrainingEntry.target_lang == lang)))
    for e in rows:
        if e.kind == DIALOGUE:
            score = _relevance(query, words, e.source_norm)
            item = {"texte": f"« {e.source_text} » → réponse : « {e.target_text} »", "sens": "(dialogue)"}
        elif e.kind == TRADUCTION:
            in_lang, other = ((e.source_text, e.source_norm), e.target_text) if e.source_lang == lang \
                else ((e.target_text, e.target_norm), e.source_text)
            score = _relevance(query, words, in_lang[1])
            item = {"texte": in_lang[0], "sens": other}
        else:
            continue
        scored.append((score, e.id, item))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [it for _, _, it in scored[:MAX_EXAMPLES]]


def converse(db: Session, lang: str, message: str, history: list[dict]) -> dict:
    out = {"lang": lang, "message": message, "reply": None, "reply_fr": None,
           "method": None, "audio_url": None, "ai_available": claude_chat.enabled()}
    query = normalize(message)
    if not query:
        return out

    # 1. Dialogue validé
    best, best_score = None, 0.0
    for e in db.scalars(select(TrainingEntry).where(
            TrainingEntry.kind == DIALOGUE, TrainingEntry.source_lang == lang)):
        s = similarity(query, e.source_norm)
        if s > best_score:
            best, best_score = e, s
    if best is not None and best_score >= LOOKUP_THRESHOLD:
        fr = translator.translate(db, best.target_text, lang, "fr")
        out.update(reply=best.target_text, reply_fr=fr["translation"], method="dataset",
                   audio_url=translator.audio_url(best.audio_path))
        return out

    # 2. IA ancrée sur le dataset
    ai = claude_chat.reply(lang, message, history, grounding_examples(db, lang, query))
    if ai:
        out.update(reply=ai["reply"], reply_fr=ai["reply_fr"], method="ia")
    return out
