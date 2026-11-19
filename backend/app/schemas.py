from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field

from .config import CONGOLESE, LANGUAGES


def check_langs(src: str, tgt: str, require_congolese: bool = True) -> None:
    for code in (src, tgt):
        if code not in LANGUAGES:
            raise HTTPException(400, f"Langue inconnue : {code}")
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
    source_lang: str
    source_text: str = Field(min_length=1, max_length=1000)
    target_lang: str
    target_text: str = Field(min_length=1, max_length=1000)


class ReviewIn(BaseModel):
    source_text: Optional[str] = None
    target_text: Optional[str] = None
    note: Optional[str] = None
