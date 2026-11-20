from typing import Literal, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

from .config import CONGOLESE, LANGUAGES


def check_langs(src: str, tgt: str, require_congolese: bool = True, kind: str = "traduction") -> None:
    for code in (src, tgt):
        if code not in LANGUAGES:
            raise HTTPException(400, f"Langue inconnue : {code}")
    if kind == "dialogue":
        if src != tgt:
            raise HTTPException(400, "Un dialogue se fait dans une seule langue")
        if src not in CONGOLESE:
            raise HTTPException(400, "Les dialogues doivent être dans une langue congolaise")
        return
    if src == tgt:
        raise HTTPException(400, "Les deux langues doivent être différentes")
    if require_congolese and not ({src, tgt} & CONGOLESE):
        raise HTTPException(400, "Au moins une des langues doit être congolaise")


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)


class TranslateIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    source_lang: str
    target_lang: str


class ContributionIn(BaseModel):
    kind: Literal["traduction", "dialogue"] = "traduction"
    source_lang: str
    source_text: str = Field(min_length=1, max_length=1000)
    target_lang: str
    target_text: str = Field(min_length=1, max_length=1000)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str

    @field_validator("text")
    @classmethod
    def _clip(cls, v: str) -> str:
        # Un ancien tour trop long (réponse détaillée de l'IA) ne doit pas bloquer toute la suite
        # de la conversation par une erreur 422 : on le raccourcit.
        return v[:1000]


class ConverseIn(BaseModel):
    lang: str
    message: str = Field(min_length=1, max_length=1000)
    history: list[ChatTurn] = Field(default_factory=list)

    @field_validator("history")
    @classmethod
    def _recent(cls, v: list) -> list:
        return v[-20:]  # seuls les derniers échanges comptent ; une longue conversation ne doit pas échouer
    voice: bool = False  # voix live : réponses courtes, à l'oral, qui relancent l'échange


class ReviewIn(BaseModel):
    source_text: Optional[str] = None
    target_text: Optional[str] = None
    note: Optional[str] = None
