"""Validation par l'admin : seul passage du dataset de collecte vers le dataset d'entraînement."""
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import MIN_SIMILAR
from ..database import get_db
from ..models import (APPROUVE, COLLECTE, EN_ATTENTE, REJETE, Contribution,
                      Proposition, TrainingEntry, User)
from ..schemas import ReviewIn
from ..security import get_admin
from ..services import dataset
from ..services.translator import audio_url

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _detail(db: Session, p: Proposition) -> dict:
    src, tgt = dataset.canonical_variant(p)
    variants: dict[tuple, int] = {}
    for c in p.contributions:
        variants[(c.source_text, c.target_text)] = variants.get((c.source_text, c.target_text), 0) + 1
    return {
        "id": p.id, "status": p.status, "source_lang": p.source_lang, "target_lang": p.target_lang,
        "source_text": src, "target_text": tgt,
        "support": dataset.support_count(db, p.id), "required": MIN_SIMILAR,
        "variants": [{"source_text": s, "target_text": t, "count": n}
                     for (s, t), n in sorted(variants.items(), key=lambda x: -x[1])],
        "audios": [{"url": audio_url(c.audio_path), "user": c.user.username}
                   for c in p.contributions if c.audio_path],
    }


@router.get("/stats")
def stats(_: User = Depends(get_admin), db: Session = Depends(get_db)):
    by_status = dict(db.execute(select(Proposition.status, func.count()).group_by(Proposition.status)).all())
    return {
        "users": db.scalar(select(func.count(User.id))),
        "dataset_collecte": db.scalar(select(func.count(Contribution.id))),
        "contributions_voix": db.scalar(select(func.count(Contribution.id)).where(Contribution.audio_path.is_not(None))),
        "dataset_entrainement": db.scalar(select(func.count(TrainingEntry.id))),
        "propositions": {s: by_status.get(s, 0) for s in (COLLECTE, EN_ATTENTE, APPROUVE, REJETE)},
        "min_similar": MIN_SIMILAR,
    }


@router.get("/propositions")
def list_propositions(status: str = EN_ATTENTE, limit: int = 50,
                      _: User = Depends(get_admin), db: Session = Depends(get_db)):
    q = (select(Proposition).where(Proposition.status == status)
         .order_by(Proposition.id).limit(min(limit, 200)))
    return [_detail(db, p) for p in db.scalars(q)]


def _get(db: Session, pid: int) -> Proposition:
    p = db.get(Proposition, pid)
    if p is None:
        raise HTTPException(404, "Proposition introuvable")
    return p


@router.post("/propositions/{pid}/approve")
def approve(pid: int, body: Optional[ReviewIn] = None,
            admin: User = Depends(get_admin), db: Session = Depends(get_db)):
    body = body or ReviewIn()
    try:
        entry = dataset.approve(db, _get(db, pid), admin, source_text=body.source_text,
                                target_text=body.target_text, note=body.note)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "training_entry_id": entry.id}


@router.post("/propositions/{pid}/reject")
def reject(pid: int, body: Optional[ReviewIn] = None,
           admin: User = Depends(get_admin), db: Session = Depends(get_db)):
    try:
        dataset.reject(db, _get(db, pid), admin, note=(body.note if body else None))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@router.get("/export/entrainement.jsonl")
def export_training(_: User = Depends(get_admin), db: Session = Depends(get_db)):
    """Exporte le dataset d'entraînement (une paire de traduction par ligne)."""
    lines = []
    for e in db.scalars(select(TrainingEntry).order_by(TrainingEntry.id)):
        lines.append(json.dumps({
            "id": e.id, "source_lang": e.source_lang, "source_text": e.source_text,
            "target_lang": e.target_lang, "target_text": e.target_text,
            "audio": e.audio_path, "support": e.support_count,
        }, ensure_ascii=False))
    return Response("\n".join(lines) + "\n", media_type="application/x-ndjson",
                    headers={"Content-Disposition": "attachment; filename=okapi_entrainement.jsonl"})
