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
from ..security import get_current_user, get_optional_user
from ..services import dataset
from ..services.audio import save_audio
from ..services.translator import audio_url

router = APIRouter(prefix="/api/contributions", tags=["contributions"])

_AUDIO_NAME = re.compile(r"^[0-9a-f]{32}\.(webm|ogg|wav|mp3|m4a)$")


_MESSAGES = {
    "collecte": "Merci ! {n}/{req} personnes soutiennent cette proposition.",
    "en_attente_admin": "Merci ! {n} personnes l'ont confirmée : elle attend maintenant la validation d'un administrateur.",
    "approuve": "Merci ! Cette entrée est déjà validée : votre soutien (et votre voix) y sont ajoutés.",
    "rejete": "Cette proposition a été rejetée par un administrateur.",
}


def _result(db: Session, c: Contribution) -> dict:
    prop = c.proposition
    n = dataset.support_count(db, prop.id)
    return {
        "contribution_id": c.id, "proposition_id": prop.id, "kind": prop.kind, "status": prop.status,
        "support": n, "required": MIN_SIMILAR,
        "message": _MESSAGES.get(prop.status, "Merci pour votre contribution !").format(n=n, req=MIN_SIMILAR),
    }


def _add(db: Session, user: User, body: ContributionIn, audio: Optional[str]) -> dict:
    check_langs(body.source_lang, body.target_lang, kind=body.kind)
    try:
        c = dataset.add_contribution(db, user, audio_path=audio, **body.model_dump())
    except dataset.AlreadyVoted as exc:
        raise HTTPException(409, str(exc))
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
    uploaded = audio is not None and bool(audio.filename)
    if uploaded:
        name = await save_audio(audio)
    elif audio_file and _AUDIO_NAME.match(audio_file) and (AUDIO_DIR / audio_file).exists():
        name = audio_file
    else:
        raise HTTPException(400, "Enregistrement vocal manquant")
    if kind not in ("traduction", "dialogue"):
        raise HTTPException(400, "Type de contribution inconnu")
    body = ContributionIn(kind=kind, source_lang=source_lang, source_text=source_text,
                          target_lang=target_lang, target_text=target_text)
    try:
        return _add(db, user, body, name)
    except HTTPException:
        if uploaded:  # vote refusé : ne pas garder l'enregistrement orphelin
            (AUDIO_DIR / name).unlink(missing_ok=True)
        raise


@router.get("/proposals")
def open_proposals(lang: Optional[str] = None, limit: int = 30,
                   user: Optional[User] = Depends(get_optional_user), db: Session = Depends(get_db)):
    """Propositions en cours de collecte que les autres peuvent confirmer.
    `voted` indique si la personne connectée a déjà proposé ou confirmé."""
    q = select(Proposition).where(Proposition.status == COLLECTE)
    if lang:
        q = q.where((Proposition.source_lang == lang) | (Proposition.target_lang == lang))
    props = list(db.scalars(q.order_by(Proposition.id.desc()).limit(min(limit, 100))))
    voted = dataset.voted_ids(db, user.id, [p.id for p in props]) if user else set()
    out = []
    for p in props:
        src, tgt = dataset.canonical_variant(p)
        out.append({"id": p.id, "kind": p.kind, "source_lang": p.source_lang, "source_text": src,
                    "target_lang": p.target_lang, "target_text": tgt,
                    "support": dataset.support_count(db, p.id), "required": MIN_SIMILAR,
                    "voted": p.id in voted})
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
    existing = dataset.user_vote(db, user.id, p.id)
    has_audio = audio is not None and bool(audio.filename)
    if existing is not None and (existing.audio_path or not has_audio):
        raise HTTPException(409, str(dataset.AlreadyVoted()))  # avant d'enregistrer l'audio
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
