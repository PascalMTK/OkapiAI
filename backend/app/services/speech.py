"""Reconnaissance vocale optionnelle via faster-whisper.

Whisper reconnaît le français, le swahili et le lingala.
Le kikongo et le tshiluba ne sont pas supportés : l'utilisateur tape la transcription,
et ces enregistrements serviront plus tard à entraîner un modèle vocal dédié.
"""
import logging
import os
import threading
from pathlib import Path
from typing import Optional

log = logging.getLogger("okapiai.speech")

WHISPER_LANGS = {"fr": "fr", "sw": "sw", "ln": "ln"}
WHISPER_SIZE = os.getenv("OKAPI_WHISPER_MODEL", "small")


class SpeechRecognizer:
    def __init__(self):
        self._model = None
        self._lock = threading.Lock()
        self._failed = False

    def supports(self, lang: str) -> bool:
        return lang in WHISPER_LANGS and self._installed()

    def _installed(self) -> bool:
        if self._failed:
            return False
        try:
            import faster_whisper  # noqa: F401
            return True
        except ImportError:
            return False

    def transcribe(self, path: Path, lang: str) -> Optional[str]:
        if not self.supports(lang):
            return None
        with self._lock:
            if self._model is None:
                try:
                    from faster_whisper import WhisperModel
                    self._model = WhisperModel(WHISPER_SIZE, device="auto", compute_type="int8")
                except Exception as exc:
                    log.warning("Whisper indisponible : %s", exc)
                    self._failed = True
                    return None
        segments, _ = self._model.transcribe(str(path), language=WHISPER_LANGS[lang])
        return " ".join(s.text.strip() for s in segments).strip() or None


recognizer = SpeechRecognizer()
