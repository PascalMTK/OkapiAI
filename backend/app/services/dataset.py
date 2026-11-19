"""Logique des deux datasets.

Flux d'une contribution :
  1. L'utilisateur envoie (phrase, traduction, [voix]) -> enregistrée dans `dataset_collecte`.
  2. Elle est rattachée à une `Proposition` existante si elle est similaire
     (similarité >= SIMILARITY_THRESHOLD), sinon une nouvelle proposition est créée.
  3. Quand une proposition réunit MIN_SIMILAR contributeurs DIFFÉRENTS,
     elle passe au statut `en_attente_admin`.
  4. L'admin approuve -> une ligne est créée dans `dataset_entrainement`.
     (ou rejette -> la proposition est bloquée).
"""
from collections import Counter
from typing import Optional

from sqlalchemy import distinct, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import MIN_SIMILAR, SIMILARITY_THRESHOLD
from ..models import (APPROUVE, COLLECTE, DIALOGUE, EN_ATTENTE, REJETE, TRADUCTION,
                      Contribution, Proposition, TrainingEntry, User, utcnow)
from ..similarity import normalize, pair_similarity


def find_proposition(db: Session, kind: str, source_lang: str, target_lang: str,
                     src_norm: str, tgt_norm: str) -> Optional[Proposition]:
    same_pair = ((Proposition.kind == kind) & (Proposition.source_lang == source_lang)
                 & (Proposition.target_lang == target_lang))
    exact = db.scalar(select(Proposition).where(
        same_pair, Proposition.source_norm == src_norm, Proposition.target_norm == tgt_norm))
    if exact:
        return exact

    best, best_score = None, 0.0
    for p in db.scalars(select(Proposition).where(same_pair)):
        score = pair_similarity(src_norm, tgt_norm, p.source_norm, p.target_norm)
        if score >= SIMILARITY_THRESHOLD and score > best_score:
            best, best_score = p, score
    return best


class AlreadyVoted(ValueError):
    """La personne a déjà proposé ou confirmé cette proposition."""

    def __init__(self):
        super().__init__("Vous avez déjà proposé ou confirmé cette traduction : un seul vote par personne.")


def user_vote(db: Session, user_id: int, proposition_id: int) -> Optional[Contribution]:
    return db.scalar(select(Contribution).where(
        Contribution.user_id == user_id, Contribution.proposition_id == proposition_id))


def voted_ids(db: Session, user_id: int, proposition_ids: list[int]) -> set[int]:
    if not proposition_ids:
        return set()
    return set(db.scalars(select(Contribution.proposition_id).where(
        Contribution.user_id == user_id, Contribution.proposition_id.in_(proposition_ids))))


def support_count(db: Session, proposition_id: int) -> int:
    """Nombre de personnes différentes ayant envoyé une contribution similaire."""
    return db.scalar(
        select(func.count(distinct(Contribution.user_id)))
        .where(Contribution.proposition_id == proposition_id)
    ) or 0


def add_contribution(db: Session, user: User, *, source_lang: str, source_text: str,
                     target_lang: str, target_text: str,
                     audio_path: Optional[str] = None, kind: str = TRADUCTION) -> Contribution:
    src_norm, tgt_norm = normalize(source_text), normalize(target_text)
    if not src_norm or not tgt_norm:
        raise ValueError("La phrase et sa traduction sont obligatoires")
    if kind not in (TRADUCTION, DIALOGUE):
        raise ValueError("Type de contribution inconnu")
    if kind == TRADUCTION and source_lang == target_lang:
        raise ValueError("Les deux langues doivent être différentes")
    if kind == DIALOGUE and source_lang != target_lang:
        raise ValueError("Un dialogue (message -> réponse) se fait dans une seule langue")

    prop = find_proposition(db, kind, source_lang, target_lang, src_norm, tgt_norm)
    if prop is None:
        prop = Proposition(kind=kind, source_lang=source_lang, target_lang=target_lang,
                           source_norm=src_norm, target_norm=tgt_norm)
        db.add(prop)
        db.flush()
    else:
        existing = user_vote(db, user.id, prop.id)
        if existing is not None:
            # Seule exception : ajouter sa voix à un vote texte, sans compter un 2e vote
            if audio_path and not existing.audio_path:
                existing.audio_path, existing.kind = audio_path, "voix"
                refresh_status(db, prop, new_audio=audio_path)
                db.commit()
                return existing
            db.rollback()
            raise AlreadyVoted()

    contrib = Contribution(
        user_id=user.id, proposition_id=prop.id,
        kind="voix" if audio_path else "texte",
        source_lang=source_lang, source_text=source_text.strip(),
        target_lang=target_lang, target_text=target_text.strip(),
        audio_path=audio_path,
    )
    db.add(contrib)
    try:
        db.flush()
    except IntegrityError:  # deux requêtes simultanées de la même personne
        db.rollback()
        raise AlreadyVoted()
    refresh_status(db, prop, new_audio=audio_path)
    db.commit()
    return contrib


def refresh_status(db: Session, prop: Proposition, new_audio: Optional[str] = None) -> None:
    n = support_count(db, prop.id)
    if prop.status == COLLECTE and n >= MIN_SIMILAR:
        prop.status = EN_ATTENTE
    elif prop.status == APPROUVE and prop.training_entry is not None:
        entry = prop.training_entry
        entry.support_count = n
        if new_audio and not entry.audio_path:
            entry.audio_path = new_audio


def canonical_variant(prop: Proposition) -> tuple[str, str]:
    """La variante (phrase, traduction) la plus fréquente dans la proposition."""
    counts = Counter((c.source_text, c.target_text) for c in prop.contributions)
    return counts.most_common(1)[0][0]


def approve(db: Session, prop: Proposition, admin: User, *,
            source_text: Optional[str] = None, target_text: Optional[str] = None,
            note: Optional[str] = None) -> TrainingEntry:
    if prop.status != EN_ATTENTE:
        raise ValueError(f"Seules les propositions '{EN_ATTENTE}' peuvent être approuvées "
                         f"(minimum {MIN_SIMILAR} contributions similaires).")
    src, tgt = canonical_variant(prop)
    src = (source_text or src).strip()
    tgt = (target_text or tgt).strip()
    src_norm = normalize(src)

    # traduction : la voix prononce la phrase ; dialogue : la voix prononce la réponse
    spoken = (lambda c: c.target_text) if prop.kind == DIALOGUE else (lambda c: c.source_text)
    spoken_ref = normalize(tgt) if prop.kind == DIALOGUE else src_norm
    with_audio = [c for c in prop.contributions if c.audio_path]
    best_audio = next((c.audio_path for c in with_audio if normalize(spoken(c)) == spoken_ref), None)
    if best_audio is None and with_audio:
        best_audio = with_audio[0].audio_path

    entry = TrainingEntry(
        proposition_id=prop.id, kind=prop.kind,
        source_lang=prop.source_lang, source_text=src, source_norm=src_norm,
        target_lang=prop.target_lang, target_text=tgt, target_norm=normalize(tgt),
        audio_path=best_audio, support_count=support_count(db, prop.id),
        approved_by=admin.id,
    )
    prop.status = APPROUVE
    prop.reviewed_by, prop.reviewed_at, prop.review_note = admin.id, utcnow(), note
    db.add(entry)
    db.commit()
    return entry


def reject(db: Session, prop: Proposition, admin: User, note: Optional[str] = None) -> None:
    if prop.status not in (EN_ATTENTE, COLLECTE):
        raise ValueError("Cette proposition a déjà été traitée")
    prop.status = REJETE
    prop.reviewed_by, prop.reviewed_at, prop.review_note = admin.id, utcnow(), note
    db.commit()
