"""Contributions au dataset de collecte (texte et voix)."""
import re
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import AUDIO_DIR, MIN_SIMILAR
from ..database import get_db
from ..models import COLLECTE, Contribution, Proposition, User
from ..schemas import ContributionIn, check_langs
from ..security import get_current_user
from ..services import dataset
from ..services.audio import save_audio
from ..services.translator import audio_url

router = APIRouter(prefix="/api/contributions", tags=["contributions"])

_AUDIO_NAME = re.compile(r"^[0-9a-f]{32}\.(webm|ogg|wav|mp3|m4a)$")


def _result(db: Session, c: Contribution) -> dict:
    prop = c.proposition
    n = dataset.support_count(db, prop.id)
    return {
        "contribution_id": c.id, "proposition_id": prop.id, "kind": prop.kind, "status": prop.status,
        "support": n, "required": MIN_SIMILAR,
        "message": (f"Merci ! {n}/{MIN_SIMILAR} personnes ont proposé une traduction similaire."
                    if prop.status == COLLECTE else f"Statut de la proposition : {prop.status}"),
    }


def _add(db: Session, user: User, body: ContributionIn, audio: Optional[str]) -> dict:
    check_langs(body.source_lang, body.target_lang, kind=body.kind)
    try:
        c = dataset.add_contribution(db, user, audio_path=audio, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return _result(db, c)


@router.post("/text")
def add_text(body: ContributionIn, user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    return _add(db, user, body, None)


@router.post("/voice")
async def add_voice(
    source_lang: str = Form(...), source_text: str = Form(...),
    target_lang: str = Form(...), target_text: str = Form(...),
    kind: str = Form("traduction"),
    audio: Optional[UploadFile] = File(None),
    audio_file: Optional[str] = Form(None),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Voix qui prononce `source_text` (traduction) ou la réponse `target_text` (dialogue). Envoyer soit `audio` (fichier), soit `audio_file`
    (nom renvoyé par /api/voice/chat)."""
    if audio is not None and audio.filename:
        name = await save_audio(audio)
    elif audio_file and _AUDIO_NAME.match(audio_file) and (AUDIO_DIR / audio_file).exists():
        name = audio_file
    else:
        raise HTTPException(400, "Enregistrement vocal manquant")
    if kind not in ("traduction", "dialogue"):
        raise HTTPException(400, "Type de contribution inconnu")
    body = ContributionIn(kind=kind, source_lang=source_lang, source_text=source_text,
                          target_lang=target_lang, target_text=target_text)
    return _add(db, user, body, name)


@router.get("/proposals")
def open_proposals(lang: Optional[str] = None, limit: int = 30, db: Session = Depends(get_db)):
    """Propositions en cours de collecte que les autres peuvent confirmer."""
    q = select(Proposition).where(Proposition.status == COLLECTE)
    if lang:
        q = q.where((Proposition.source_lang == lang) | (Proposition.target_lang == lang))
    out = []
    for p in db.scalars(q.order_by(Proposition.id.desc()).limit(min(limit, 100))):
        src, tgt = dataset.canonical_variant(p)
        out.append({"id": p.id, "kind": p.kind, "source_lang": p.source_lang, "source_text": src,
                    "target_lang": p.target_lang, "target_text": tgt,
                    "support": dataset.support_count(db, p.id), "required": MIN_SIMILAR})
    return out


@router.post("/proposals/{proposition_id}/confirm")
async def confirm_proposal(
    proposition_id: int, audio: Optional[UploadFile] = File(None),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """« Je confirme cette traduction » (+ voix optionnelle)."""
    p = db.get(Proposition, proposition_id)
    if p is None or p.status != COLLECTE:
        raise HTTPException(404, "Proposition introuvable ou déjà clôturée")
    src, tgt = dataset.canonical_variant(p)
    name = await save_audio(audio) if audio is not None and audio.filename else None
    body = ContributionIn(kind=p.kind, source_lang=p.source_lang, source_text=src,
                          target_lang=p.target_lang, target_text=tgt)
    return _add(db, user, body, name)


@router.get("/mine")
def mine(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Contribution).where(Contribution.user_id == user.id)
                      .order_by(Contribution.id.desc()).limit(100))
    return [{"id": c.id, "kind": c.kind, "type": c.proposition.kind, "source_lang": c.source_lang, "source_text": c.source_text,
             "target_lang": c.target_lang, "target_text": c.target_text,
             "audio_url": audio_url(c.audio_path), "status": c.proposition.status,
             "support": dataset.support_count(db, c.proposition_id), "required": MIN_SIMILAR,
             "created_at": c.created_at.isoformat()} for c in rows]
