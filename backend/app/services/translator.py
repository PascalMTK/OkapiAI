"""Traduction : dataset d'entraînement d'abord, puis modèle entraîné (NLLB), puis mot à mot."""
import logging
import threading
from typing import Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..config import LOOKUP_THRESHOLD, MODEL_DIR, NLLB_CODES
from ..models import TRADUCTION, TrainingEntry
from ..similarity import normalize, similarity

log = logging.getLogger("okapiai.translator")


def audio_url(path: Optional[str]) -> Optional[str]:
    return f"/api/audio/{path}" if path else None


def _entries(db: Session, src: str, tgt: str) -> list[TrainingEntry]:
    return list(db.scalars(select(TrainingEntry).where(TrainingEntry.kind == TRADUCTION, or_(
        and_(TrainingEntry.source_lang == src, TrainingEntry.target_lang == tgt),
        and_(TrainingEntry.source_lang == tgt, TrainingEntry.target_lang == src),
    ))))


def _best_match(entries: list[TrainingEntry], query_norm: str, src: str):
    """Cherche dans les deux sens. Retourne (score, texte_traduit, audio)."""
    best = (0.0, None, None)
    for e in entries:
        if e.source_lang == src:
            score, text, audio = similarity(query_norm, e.source_norm), e.target_text, None
        else:
            # entrée inversée : la traduction est dans la langue de l'audio enregistré
            score, text, audio = similarity(query_norm, e.target_norm), e.source_text, e.audio_path
        if score > best[0]:
            best = (score, text, audio)
    return best


class NLLBModel:
    """Charge paresseusement le modèle fine-tuné (s'il existe)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._model = None
        self._tokenizer = None
        self._failed = False

    def available(self) -> bool:
        return not self._failed and (MODEL_DIR / "config.json").exists()

    def _load(self):
        with self._lock:
            if self._model is not None or self._failed:
                return
            try:
                from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
                self._tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
                self._model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_DIR)
                log.info("Modèle chargé depuis %s", MODEL_DIR)
            except Exception as exc:  # transformers absent ou modèle invalide
                log.warning("Impossible de charger le modèle : %s", exc)
                self._failed = True

    def translate(self, text: str, src: str, tgt: str) -> Optional[str]:
        if not self.available():
            return None
        self._load()
        if self._model is None:
            return None
        tok = self._tokenizer
        tok.src_lang = NLLB_CODES[src]
        inputs = tok(text, return_tensors="pt", truncation=True, max_length=256)
        out = self._model.generate(
            **inputs, max_new_tokens=256,
            forced_bos_token_id=tok.convert_tokens_to_ids(NLLB_CODES[tgt]),
        )
        return tok.batch_decode(out, skip_special_tokens=True)[0]


nllb = NLLBModel()


def translate(db: Session, text: str, src: str, tgt: str) -> dict:
    query = normalize(text)
    result = {"input": text, "source_lang": src, "target_lang": tgt,
              "translation": None, "method": None, "confidence": 0.0,
              "audio_url": None, "words": []}
    if not query:
        return result

    entries = _entries(db, src, tgt)

    # 1. Phrase complète dans le dataset validé
    score, text_out, audio = _best_match(entries, query, src)
    if text_out and score >= LOOKUP_THRESHOLD:
        result.update(translation=text_out, method="dataset",
                      confidence=round(score, 3), audio_url=audio_url(audio))
        return result

    # 2. Modèle entraîné
    model_out = nllb.translate(text, src, tgt)
    if model_out:
        result.update(translation=model_out, method="modele", confidence=None)
        return result

    # 3. Mot à mot (traduction partielle)
    words, found = [], 0
    for w in query.split():
        s, t, a = _best_match(entries, w, src)
        if t and s >= 0.9:
            words.append({"mot": w, "traduction": t, "audio_url": audio_url(a)})
            found += 1
        else:
            words.append({"mot": w, "traduction": None, "audio_url": None})
    if found:
        result.update(
            translation=" ".join(x["traduction"] or f"[{x['mot']}]" for x in words),
            method="mot_a_mot", confidence=round(found / len(words), 3), words=words)
    return result
