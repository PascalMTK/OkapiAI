"""Synthèse vocale (texte -> voix) dans les langues nationales.

Voix Meta MMS-TTS (VITS) :
  - lingala : khof312/mms-tts-lin  (MMS converti pour transformers)
  - swahili : facebook/mms-tts-swh
Licence des voix MMS : CC BY-NC 4.0 (usage non commercial).
Le kikongo et le tshiluba n'ont pas encore de voix publique. En attendant une voix tshiluba
entraînée, le tshiluba est lu par la voix lingala (même alphabet, sons bantous proches) ;
OKAPI_TTS_LUA=off la désactive.

Les fichiers générés sont mis en cache dans AUDIO_DIR/tts/ (même texte = même fichier).
Comme pour la reconnaissance, une voix n'est utilisée que si elle est déjà téléchargée
(ou si OKAPI_TTS_AUTO_DOWNLOAD=1).
"""
import hashlib
import logging
import os
import re
import threading
import unicodedata
import wave
from pathlib import Path
from typing import Optional

from ..config import AUDIO_DIR

log = logging.getLogger("okapiai.tts")

VOICES = {
    "ln": os.getenv("OKAPI_TTS_LN", "khof312/mms-tts-lin"),
    "sw": os.getenv("OKAPI_TTS_SW", "facebook/mms-tts-swh"),
}
if os.getenv("OKAPI_TTS_LUA", "") != "off":
    VOICES["lua"] = os.getenv("OKAPI_TTS_LUA") or VOICES["ln"]   # voix provisoire : la voix lingala
# Voix externes (ex. voix affinée sur notre dataset, tools/voice_server.py) : OKAPI_TTS_<LANG>_URL.
# Utilisées en priorité ; si elles ne répondent pas, on revient à la voix MMS.
REMOTE = {lang: url.rstrip("/") for lang in ("ln", "sw", "lua")
          if (url := os.getenv(f"OKAPI_TTS_{lang.upper()}_URL"))}
if "lua" in VOICES and "lua" not in REMOTE and "ln" in REMOTE:
    REMOTE["lua"] = REMOTE["ln"]
AUTO_DOWNLOAD = os.getenv("OKAPI_TTS_AUTO_DOWNLOAD") == "1"
ENABLED = os.getenv("OKAPI_TTS", "on") != "off"
TTS_DIR = AUDIO_DIR / "tts"
MAX_CHARS = 600
CACHE_VERSION = "v2"  # à changer quand la préparation du texte change (invalide l'ancien cache)
PAUSE_S = 0.35        # silence entre deux phrases


def speakable(text: str) -> str:
    """Texte que la voix MMS sait prononcer : elle ne connaît que a-z (sans tons).
    Sans ça, « tóyékola » devient « tykola » et « mbɔ́tɛ » devient « mbt »."""
    t = (text.replace("ɛ", "e").replace("Ɛ", "E").replace("ε", "e").replace("Ε", "E")
         .replace("ɔ", "o").replace("Ɔ", "O"))
    t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    t = re.sub(r"[«»\"“”()\[\]*_#]", " ", t)
    return " ".join(t.split())


def sentences(text: str) -> list[str]:
    """Découpe en phrases : la voix ignore la ponctuation, on ajoute donc les pauses nous-mêmes."""
    parts = re.split(r"(?<=[.!?;:…])\s+|\n+", text)
    return [p.strip(" .,!?;:…") for p in parts if re.search(r"\w", p)]


class Synthesizer:
    def __init__(self):
        self._lock = threading.Lock()
        self._voices: dict[str, tuple] = {}
        self._failed: set[str] = set()
        self._remote_state: dict[str, tuple[bool, float]] = {}

    def _remote_ok(self, lang: str) -> bool:
        """La voix externe répond-elle ? (vérifié au plus une fois toutes les 30 s)"""
        import time
        import urllib.request
        url = REMOTE.get(lang)
        if not url:
            return False
        now = time.monotonic()
        cached = self._remote_state.get(lang)
        if cached and now - cached[1] < 30:
            return cached[0]
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=2) as r:
                ok = r.status == 200
        except Exception:
            ok = False
        self._remote_state[lang] = (ok, now)
        return ok

    def engine(self, lang: str) -> Optional[str]:
        """Nom de la voix utilisée pour `lang` (externe affinée ou MMS)."""
        if self._remote_ok(lang):
            return "remote"
        return "mms" if self._mms_supports(lang) else None

    def supports(self, lang: str) -> bool:
        return ENABLED and self.engine(lang) is not None

    def _mms_supports(self, lang: str) -> bool:
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
            if self._mms_supports(lang):
                with self._lock:
                    try:
                        self._voice(lang)
                    except Exception as exc:
                        log.warning("Voix %s indisponible : %s", lang, exc)
                        self._failed.add(lang)

    def path_for(self, text: str, lang: str, engine: str = "mms") -> Path:
        digest = hashlib.sha1(f"{CACHE_VERSION}|{engine}|{lang}|{text}".encode("utf-8")).hexdigest()[:24]
        return TTS_DIR / f"{lang}-{engine}-{digest}.wav"

    def _synthesize_remote(self, text: str, lang: str) -> Optional[Path]:
        import urllib.parse
        import urllib.request
        # pas de cache : la voix affinée change pendant l'entraînement
        path = TTS_DIR / f"{lang}-remote-{hashlib.sha1(text.encode('utf-8')).hexdigest()[:24]}.wav"
        try:
            url = f"{REMOTE[lang]}/tts?text={urllib.parse.quote(text)}"
            with urllib.request.urlopen(url, timeout=30) as r:
                data = r.read()
        except Exception as exc:
            log.warning("Voix externe %s indisponible : %s -> voix MMS", lang, exc)
            self._remote_state[lang] = (False, __import__("time").monotonic())
            return None
        TTS_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def synthesize(self, text: str, lang: str) -> Optional[Path]:
        """Fichier WAV de `text` prononcé dans `lang`, ou None si impossible."""
        text = " ".join((text or "").split())[:MAX_CHARS]
        if not text or not self.supports(lang):
            return None
        if self.engine(lang) == "remote":
            path = self._synthesize_remote(text, lang)
            if path is not None or not self._mms_supports(lang):
                return path
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
                import numpy as np
                import torch
                rate = model.config.sampling_rate
                pieces = []
                for sentence in sentences(speakable(text)):
                    inputs = tok(sentence, return_tensors="pt").to(model.device)
                    if inputs["input_ids"].shape[-1] <= 1:
                        continue
                    with torch.inference_mode():
                        wav = model(**inputs).waveform[0].float().cpu().numpy()
                    if pieces:
                        pieces.append(np.zeros(int(rate * PAUSE_S), dtype=np.float32))
                    pieces.append(wav)
                if not pieces:
                    return None
                wav = np.concatenate(pieces)
                pcm = (wav.clip(-1, 1) * 32767).astype("<i2").tobytes()
                TTS_DIR.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".tmp")
                with wave.open(str(tmp), "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(rate)
                    w.writeframes(pcm)
                tmp.replace(path)
                return path
            except Exception as exc:
                log.warning("Synthèse vocale impossible (%s) : %s", lang, exc)
                return None


synthesizer = Synthesizer()
