"""Apprentissage : cartes mémoire, quiz rapide et jeu de mémoire.

Les phrases validées par la communauté passent en premier (avec la voix d'un locuteur). Quand il
n'y en a pas assez, le vocabulaire de base (services/vocab.py) complète, avec sa source affichée.
"""
import random
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import CONGOLESE, LANGUAGES
from ..database import get_db
from ..models import TRADUCTION, TrainingEntry
from ..services import vocab
from ..services.translator import audio_url

router = APIRouter(prefix="/api/learn", tags=["learn"])
COMMUNITY = "Phrases de la communauté"


def _card(e: TrainingEntry, lang: str) -> dict:
    """Présente l'entrée avec la langue apprise d'abord."""
    if e.source_lang == lang:
        return {"id": e.id, "lang": lang, "text": e.source_text, "meaning_lang": e.target_lang,
                "meaning": e.target_text, "audio_url": audio_url(e.audio_path)}
    return {"id": e.id, "lang": lang, "text": e.target_text, "meaning_lang": e.source_lang,
            "meaning": e.source_text, "audio_url": None}


def _check(lang: str) -> None:
    if lang not in LANGUAGES:
        raise HTTPException(400, "Langue inconnue")


def _pool(db: Session, lang: str, n: int) -> list[TrainingEntry]:
    _check(lang)
    q = (select(TrainingEntry)
         .where(TrainingEntry.kind == TRADUCTION,
                or_(TrainingEntry.source_lang == lang, TrainingEntry.target_lang == lang))
         .order_by(func.random()).limit(n))
    return list(db.scalars(q))


def _tts(word: str, lang: str) -> Optional[str]:
    return f"/api/tts?lang={lang}&text={quote(word)}"


def _items(db: Session, lang: str, theme: Optional[str]) -> list[dict]:
    """Paires (français, mot) pour les jeux : communauté d'abord, puis vocabulaire de base."""
    if lang not in CONGOLESE:
        raise HTTPException(400, "Les jeux se font en lingala, swahili, kikongo ou tshiluba")
    community = []
    for e in _pool(db, lang, 200):
        c = _card(e, lang)
        if c["meaning_lang"] == "fr" and len(c["text"].split()) <= 6:
            community.append({"fr": c["meaning"], "word": c["text"], "theme": COMMUNITY,
                              "source": "Validé par la communauté", "audio_url": c["audio_url"]})
    items = community + vocab.base_items(lang)
    if theme:
        items = [it for it in items if it["theme"] == theme]
    return items


def _with_audio(it: dict, lang: str) -> dict:
    return {"fr": it["fr"], "word": it["word"], "theme": it["theme"], "source": it["source"],
            "audio_url": it.get("audio_url"), "tts_url": _tts(it["word"], lang)}


@router.get("/cards")
def cards(lang: str, limit: int = 10, theme: Optional[str] = None, db: Session = Depends(get_db)):
    limit = min(limit, 50)
    if theme:   # un thème : les mots de ce thème seulement
        return [{"id": None, "lang": lang, "text": it["word"], "meaning_lang": "fr", "meaning": it["fr"],
                 "audio_url": it.get("audio_url"), "tts_url": _tts(it["word"], lang), "source": it["source"]}
                for it in vocab.pick(_items(db, lang, theme), limit, random.Random())]
    out = [_card(e, lang) for e in _pool(db, lang, limit)]
    if len(out) < limit and lang in CONGOLESE:   # complété par le vocabulaire de base
        known = {c["text"].lower() for c in out}
        extra = [it for it in vocab.pick(vocab.base_items(lang), limit, random.Random()) if it["word"].lower() not in known]
        out += [{"id": None, "lang": lang, "text": it["word"], "meaning_lang": "fr", "meaning": it["fr"],
                 "audio_url": None, "tts_url": _tts(it["word"], lang), "source": it["source"]}
                for it in extra[:limit - len(out)]]
    return out


@router.get("/themes")
def themes(lang: str, db: Session = Depends(get_db)):
    items = _items(db, lang, None)
    counts: dict[str, int] = {}
    for it in items:
        counts[it["theme"]] = counts.get(it["theme"], 0) + 1
    return [{"theme": t, "count": n} for t, n in counts.items() if n >= 4]


@router.get("/quick-quiz")
def quick_quiz(lang: str, theme: Optional[str] = None, n: int = Query(10, ge=3, le=20),
               db: Session = Depends(get_db)):
    """Quiz rapide : n questions à choix multiples, de trois sortes :
    « traduire » (français → langue), « sens » (langue → français), « écoute » (on n'a que la voix)."""
    items = _items(db, lang, theme)
    rng = random.Random()
    chosen = vocab.pick(items, n, rng)
    if len(chosen) < min(n, 4):
        raise HTTPException(404, "Pas assez de mots dans ce thème pour un quiz")
    everyone = _items(db, lang, None)
    kinds = ["traduire", "sens", "ecoute"]
    questions = []
    for i, it in enumerate(chosen):
        kind = kinds[i % 3]
        # mauvaises réponses : du même thème si possible, jamais la bonne réponse
        same = [x for x in items if x is not it] or everyone
        field = "word" if kind == "traduire" else "fr"
        wrong, seen = [], {it[field].lower()}
        for x in rng.sample(same, len(same)) + rng.sample(everyone, len(everyone)):
            if x[field].lower() not in seen:
                seen.add(x[field].lower()); wrong.append(x[field])
            if len(wrong) == 3:
                break
        choices = wrong + [it[field]]
        rng.shuffle(choices)
        questions.append({**_with_audio(it, lang), "kind": kind,
                          "prompt": it["fr"] if kind == "traduire" else it["word"],
                          "choices": choices, "answer": it[field]})
    rng.shuffle(questions)
    return {"lang": lang, "theme": theme, "questions": questions}


@router.get("/memory")
def memory(lang: str, theme: Optional[str] = None, pairs: int = Query(6, ge=3, le=10),
           db: Session = Depends(get_db)):
    """Jeu de mémoire : retrouver les paires (mot français, mot dans la langue)."""
    chosen = vocab.pick(_items(db, lang, theme), pairs, random.Random())
    if len(chosen) < 3:
        raise HTTPException(404, "Pas assez de mots dans ce thème pour un jeu de mémoire")
    return {"lang": lang, "theme": theme, "pairs": [{"id": i, **_with_audio(it, lang)} for i, it in enumerate(chosen)]}


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
