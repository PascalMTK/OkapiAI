"""Modèles de la base de données.

Deux datasets distincts :
  1. `dataset_collecte`     -> tout ce que les utilisateurs envoient (texte + voix), brut.
                               Les contributions similaires sont regroupées en `propositions`.
  2. `dataset_entrainement` -> uniquement les propositions qui ont atteint le minimum
                               de contributions similaires ET qui ont été approuvées par un admin.
                               C'est ce dataset qui sert à entraîner les modèles.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import ForeignKey, String, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Statuts d'une proposition
COLLECTE = "collecte"            # moins de MIN_SIMILAR contributions similaires
EN_ATTENTE = "en_attente_admin"  # seuil atteint, attend la décision de l'admin
APPROUVE = "approuve"            # copiée dans le dataset d'entraînement
REJETE = "rejete"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    is_admin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Proposition(Base):
    """Groupe de contributions similaires (même phrase + même traduction)."""
    __tablename__ = "propositions"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_lang: Mapped[str] = mapped_column(String(8), index=True)
    target_lang: Mapped[str] = mapped_column(String(8), index=True)
    source_norm: Mapped[str] = mapped_column(Text, index=True)
    target_norm: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default=COLLECTE, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    reviewed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[Optional[datetime]]
    review_note: Mapped[Optional[str]] = mapped_column(Text)

    contributions: Mapped[list["Contribution"]] = relationship(back_populates="proposition")
    training_entry: Mapped[Optional["TrainingEntry"]] = relationship(back_populates="proposition")


class Contribution(Base):
    """Dataset 1 : données collectées (brutes)."""
    __tablename__ = "dataset_collecte"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    proposition_id: Mapped[int] = mapped_column(ForeignKey("propositions.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="texte")  # "texte" | "voix"
    source_lang: Mapped[str] = mapped_column(String(8))
    source_text: Mapped[str] = mapped_column(Text)
    target_lang: Mapped[str] = mapped_column(String(8))
    target_text: Mapped[str] = mapped_column(Text)
    audio_path: Mapped[Optional[str]] = mapped_column(String(255))  # voix qui prononce source_text
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    proposition: Mapped[Proposition] = relationship(back_populates="contributions")
    user: Mapped[User] = relationship()


class TrainingEntry(Base):
    """Dataset 2 : données validées, utilisées pour l'entraînement."""
    __tablename__ = "dataset_entrainement"

    id: Mapped[int] = mapped_column(primary_key=True)
    proposition_id: Mapped[int] = mapped_column(ForeignKey("propositions.id"), unique=True)
    source_lang: Mapped[str] = mapped_column(String(8), index=True)
    source_text: Mapped[str] = mapped_column(Text)
    source_norm: Mapped[str] = mapped_column(Text, index=True)
    target_lang: Mapped[str] = mapped_column(String(8), index=True)
    target_text: Mapped[str] = mapped_column(Text)
    target_norm: Mapped[str] = mapped_column(Text, index=True)
    audio_path: Mapped[Optional[str]] = mapped_column(String(255))
    support_count: Mapped[int] = mapped_column(Integer, default=0)
    approved_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime] = mapped_column(default=utcnow)

    proposition: Mapped[Proposition] = relationship(back_populates="training_entry")
