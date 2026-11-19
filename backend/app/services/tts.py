"""Synthèse vocale (texte -> voix) dans les langues nationales.

Voix Meta MMS-TTS (VITS) :
  - lingala : khof312/mms-tts-lin  (MMS converti pour transformers)
  - swahili : facebook/mms-tts-swh
Licence des voix MMS : CC BY-NC 4.0 (usage non commercial).
Le kikongo et le tshiluba n'ont pas encore de voix publique.

Les fichiers générés sont mis en cache dans AUDIO_DIR/tts/ (même texte = même fichier).
Comme pour la reconnaissance, une voix n'est utilisée que si elle est déjà téléchargée
(ou si OKAPI_TTS_AUTO_DOWNLOAD=1).
"""
import hashlib
import logging
import os
import threading
import wave
from pathlib import Path
from typing import Optional

from ..config import AUDIO_DIR

log = logging.getLogger("okapiai.tts")

VOICES = {
    "ln": os.getenv("OKAPI_TTS_LN", "khof312/mms-tts-lin"),
    "sw": os.getenv("OKAPI_TTS_SW", "facebook/mms-tts-swh"),
}
AUTO_DOWNLOAD = os.getenv("OKAPI_TTS_AUTO_DOWNLOAD") == "1"
ENABLED = os.getenv("OKAPI_TTS", "on") != "off"
TTS_DIR = AUDIO_DIR / "tts"
MAX_CHARS = 600


class Synthesizer:
    def __init__(self):
        self._lock = threading.Lock()
        self._voices: dict[str, tuple] = {}
        self._failed: set[str] = set()

    def supports(self, lang: str) -> bool:
        if not ENABLED or lang not in VOICES or lang in self._failed:
            return False
        if lang in self._voices:
            return True
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
        except ImportError:
            return False
        if AUTO_DOWNLOAD:
            return True
        from huggingface_hub import try_to_load_from_cache
        return isinstance(try_to_load_from_cache(VOICES[lang], "model.safetensors"), str)

    def _voice(self, lang: str):
        if lang not in self._voices:
            import torch
            from transformers import AutoTokenizer, VitsModel
            device = "cuda" if torch.cuda.is_available() and os.getenv("OKAPI_TTS_DEVICE") != "cpu" else "cpu"
            tok = AutoTokenizer.from_pretrained(VOICES[lang])
            model = VitsModel.from_pretrained(VOICES[lang]).to(device).eval()  # ~150 Mo
            self._voices[lang] = (tok, model)
            log.info("Voix %s chargée (%s, %s)", lang, VOICES[lang], device)
        return self._voices[lang]

    def warmup(self) -> None:
        """Charge les voix disponibles à l'avance (appelé au démarrage, en arrière-plan)."""
        for lang in VOICES:
            if self.supports(lang):
                with self._lock:
                    try:
                        self._voice(lang)
                    except Exception as exc:
                        log.warning("Voix %s indisponible : %s", lang, exc)
                        self._failed.add(lang)

    def path_for(self, text: str, lang: str) -> Path:
        digest = hashlib.sha1(f"{lang}|{text}".encode("utf-8")).hexdigest()[:24]
        return TTS_DIR / f"{lang}-{digest}.wav"

    def synthesize(self, text: str, lang: str) -> Optional[Path]:
        """Fichier WAV de `text` prononcé dans `lang`, ou None si impossible."""
        text = " ".join((text or "").split())[:MAX_CHARS]
        if not text or not self.supports(lang):
            return None
        path = self.path_for(text, lang)
        if path.exists():
            return path
        with self._lock:
            try:
                tok, model = self._voice(lang)
            except Exception as exc:
                log.warning("Voix %s indisponible : %s", lang, exc)
                self._failed.add(lang)
                return None
            try:
                import torch
                # Les voix MMS ne connaissent pas les guillemets ni certains signes : on les retire
                clean = text.replace("«", "").replace("»", "").replace("…", ".")
                inputs = tok(clean, return_tensors="pt").to(model.device)
                if inputs["input_ids"].shape[-1] == 0:
                    return None
                with torch.inference_mode():
                    wav = model(**inputs).waveform[0].float().cpu().numpy()
                pcm = (wav.clip(-1, 1) * 32767).astype("<i2").tobytes()
                TTS_DIR.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".tmp")
                with wave.open(str(tmp), "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(model.config.sampling_rate)
                    w.writeframes(pcm)
                tmp.replace(path)
                return path
            except Exception as exc:
                log.warning("Synthèse vocale impossible (%s) : %s", lang, exc)
                return None


synthesizer = Synthesizer()
