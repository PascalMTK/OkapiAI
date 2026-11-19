"""Apprentissage à partir du dataset d'entraînement (données validées uniquement)."""
import random

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import LANGUAGES
from ..database import get_db
from ..models import TRADUCTION, TrainingEntry
from ..services.translator import audio_url

router = APIRouter(prefix="/api/learn", tags=["learn"])


def _card(e: TrainingEntry, lang: str) -> dict:
    """Présente l'entrée avec la langue apprise d'abord."""
    if e.source_lang == lang:
        return {"id": e.id, "lang": lang, "text": e.source_text, "meaning_lang": e.target_lang,
                "meaning": e.target_text, "audio_url": audio_url(e.audio_path)}
    return {"id": e.id, "lang": lang, "text": e.target_text, "meaning_lang": e.source_lang,
            "meaning": e.source_text, "audio_url": None}


def _pool(db: Session, lang: str, n: int) -> list[TrainingEntry]:
    if lang not in LANGUAGES:
        raise HTTPException(400, "Langue inconnue")
    q = (select(TrainingEntry)
         .where(TrainingEntry.kind == TRADUCTION,
                or_(TrainingEntry.source_lang == lang, TrainingEntry.target_lang == lang))
         .order_by(func.random()).limit(n))
    return list(db.scalars(q))


@router.get("/cards")
def cards(lang: str, limit: int = 10, db: Session = Depends(get_db)):
    return [_card(e, lang) for e in _pool(db, lang, min(limit, 50))]


@router.get("/quiz")
def quiz(lang: str, db: Session = Depends(get_db)):
    pool = [_card(e, lang) for e in _pool(db, lang, 12)]
    # éviter les doublons de réponses
    seen, uniq = set(), []
    for c in pool:
        if c["meaning"] not in seen:
            seen.add(c["meaning"])
            uniq.append(c)
    if len(uniq) < 2:
        raise HTTPException(404, "Pas assez de données validées pour un quiz dans cette langue")
    question = uniq[0]
    choices = [c["meaning"] for c in uniq[:4]]
    random.shuffle(choices)
    return {"question": question["text"], "audio_url": question["audio_url"],
            "lang": lang, "choices": choices, "answer": question["meaning"]}


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    out = {}
    for code in LANGUAGES:
        out[code] = db.scalar(select(func.count(TrainingEntry.id)).where(
            or_(TrainingEntry.source_lang == code, TrainingEntry.target_lang == code))) or 0
    return out
