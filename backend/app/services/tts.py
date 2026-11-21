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
import json
import logging
import os
import re
import threading
import unicodedata
import wave
from pathlib import Path
from typing import Optional

from ..config import AUDIO_DIR
from .gpu import preferred_device

log = logging.getLogger("okapiai.tts")

VOICES = {
    "ln": os.getenv("OKAPI_TTS_LN", "khof312/mms-tts-lin"),
    "sw": os.getenv("OKAPI_TTS_SW", "facebook/mms-tts-swh"),
    # voix française : prononce les mots français cités dans une réponse, puis rend la main
    # à la voix de la langue nationale (voir split_voices)
    "fr": os.getenv("OKAPI_TTS_FR", "facebook/mms-tts-fra"),
}
if os.getenv("OKAPI_TTS_LUA", "") != "off":
    VOICES["lua"] = os.getenv("OKAPI_TTS_LUA") or VOICES["ln"]   # voix provisoire : la voix lingala
# Kikongo : pas encore de voix ; la voix lingala le lit (même alphabet, langues bantoues voisines)
# plutôt que de laisser OkapiAI muet. OKAPI_TTS_KG=off la désactive.
if os.getenv("OKAPI_TTS_KG", "") != "off":
    VOICES["kg"] = os.getenv("OKAPI_TTS_KG") or VOICES["ln"]
# Voix externes (ex. voix affinée sur notre dataset, tools/voice_server.py) : OKAPI_TTS_<LANG>_URL.
# Utilisées en priorité ; si elles ne répondent pas, on revient à la voix MMS.
REMOTE = {lang: url.rstrip("/") for lang in ("ln", "sw", "lua")
          if (url := os.getenv(f"OKAPI_TTS_{lang.upper()}_URL"))}
if "lua" in VOICES and "lua" not in REMOTE and "ln" in REMOTE:
    REMOTE["lua"] = REMOTE["ln"]
if "kg" in VOICES and "ln" in REMOTE:
    REMOTE["kg"] = REMOTE["ln"]
# Mots français cités dans une réponse : dits par la voix française MMS (défaut). Les voix des langues
# nationales ne disent que leur langue. OKAPI_TTS_FR_SAME_VOICE=1 : voix de la conversation à la place.
SAME_VOICE_FR = os.getenv("OKAPI_TTS_FR_SAME_VOICE", "0") == "1"
AUTO_DOWNLOAD = os.getenv("OKAPI_TTS_AUTO_DOWNLOAD") == "1"
ENABLED = os.getenv("OKAPI_TTS", "on") != "off"
TTS_DIR = AUDIO_DIR / "tts"
MAX_CHARS = 600
CACHE_VERSION = "v4"  # à changer quand la préparation du texte change (invalide l'ancien cache)
PAUSE_S = 0.35        # silence entre deux phrases
LEAD_S = 0.15         # silence avant le son (la 1re syllabe n'est plus avalée par le navigateur)


def speakable(text: str) -> str:
    """Texte que la voix MMS sait prononcer : elle ne connaît que a-z (sans tons).
    Sans ça, « tóyékola » devient « tykola » et « mbɔ́tɛ » devient « mbt »."""
    t = (text.replace("ɛ", "e").replace("Ɛ", "E").replace("ε", "e").replace("Ε", "E")
         .replace("ɔ", "o").replace("Ɔ", "O"))
    t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    t = re.sub(r"[«»\"“”()\[\]*_#]", " ", t)
    return " ".join(t.split())


def speakable_fr(text: str) -> str:
    """La voix française connaît les accents (é, è, ç, œ…) : on les garde, en minuscules."""
    t = text.lower().replace("’", "'")
    t = re.sub(r"[«»\"“”()\[\]*_#]", " ", t)
    return " ".join(t.split())


# Une réponse peut citer des mots d'une autre langue : l'IA les balise (<fr>maison</fr>) et chaque
# morceau est dit par la voix de sa langue (voix française pour le français, puis relais à la voix
# lingala / tshiluba…). Les balises n'apparaissent jamais à l'écran.
_TAG = re.compile(r"<(fr|ln|sw|kg|lua)>(.*?)</\1>", re.S | re.I)
_ANY_TAG = re.compile(r"</?(?:fr|ln|sw|kg|lua)>", re.I)


def display_text(text: Optional[str]) -> Optional[str]:
    """Texte affiché : balises retirées (le mot cité garde ses guillemets s'il en avait)."""
    if not text:
        return text
    t = _TAG.sub(lambda m: m.group(2), text)
    return re.sub(r"[ \t]{2,}", " ", _ANY_TAG.sub("", t)).strip()


def split_voices(text: Optional[str], lang: str) -> list[dict]:
    """[{"lang", "text"}…] dans l'ordre : morceaux balisés dans leur langue, le reste dans `lang`."""
    out: list[dict] = []

    def add(code: str, chunk: str):
        chunk = _ANY_TAG.sub("", chunk)
        if not re.search(r"\w", chunk):
            if out:  # ponctuation seule : collée au morceau précédent
                out[-1]["text"] += chunk.rstrip()
            return
        if out and out[-1]["lang"] == code:
            out[-1]["text"] += " " + chunk.strip()
        else:
            out.append({"lang": code, "text": chunk.strip()})

    pos = 0
    for m in _TAG.finditer(text or ""):
        add(lang, text[pos:m.start()])
        add(m.group(1).lower(), m.group(2))
        pos = m.end()
    add(lang, (text or "")[pos:])
    for seg in out:  # guillemets et parenthèses orphelins en bord de morceau
        seg["text"] = seg["text"].strip(" «»\"“”()")
    return [s for s in out if re.search(r"\w", s["text"])]


def national_text(text: str, lang: str) -> str:
    """Phrase prête pour la voix de `lang` : mots français (balisés <fr> ou reconnus) réécrits
    comme ils se prononcent, pour que la même voix dise toute la phrase."""
    from .frenchspeak import for_national_voice
    try:
        from .hearing import for_lang
        h = for_lang("ln" if lang == "kg" else lang)
        is_french = h.is_french if h is not None else None
    except Exception:
        is_french = None
    return " ".join(for_national_voice(text, is_french).split())


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
        self._remote_version: dict[str, str] = {}   # version de la voix entraînée (cache)

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
                self._remote_version[lang] = json.loads(r.read() or b"{}").get("version") or ""
        except Exception:   # 503 = la voix se réchauffe encore : voix de secours en attendant
            ok = False
        # re-vérifiée vite tant qu'elle n'est pas prête (démarrage), puis toutes les 30 s
        self._remote_state[lang] = (ok, now if ok else now - 25)
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
            # même voix pour plusieurs langues (lingala pour tshiluba / kikongo) : un seul modèle en mémoire
            shared = next((l for l in self._voices if VOICES.get(l) == VOICES[lang]), None)
            if shared is not None:
                self._voices[lang] = self._voices[shared]
                return self._voices[lang]
            from transformers import AutoTokenizer, VitsModel
            device = preferred_device(os.getenv("OKAPI_TTS_DEVICE", "auto"))   # cpu pendant un entraînement
            tok = AutoTokenizer.from_pretrained(VOICES[lang])
            model = VitsModel.from_pretrained(VOICES[lang]).to(device).eval()  # ~150 Mo
            self._voices[lang] = (tok, model)
            log.info("Voix %s chargée (%s, %s)", lang, VOICES[lang], device)
        return self._voices[lang]

    def move(self, device: str) -> None:
        """Voix MMS chargées -> `device` (cpu pendant un entraînement des voix, cuda ensuite)."""
        if os.getenv("OKAPI_TTS_DEVICE", "auto") in ("cpu", "cuda"):
            return
        with self._lock:
            for lang, (tok, model) in list(self._voices.items()):
                if model.device.type != device:
                    model.to(device)   # en place : les langues qui partagent ce modèle suivent

    def warmup(self) -> None:
        """Charge les voix disponibles à l'avance (appelé au démarrage, en arrière-plan), et fait un
        premier calcul avec chacune : sur la carte graphique, le tout premier est très lent (~10 s)."""
        import torch
        for lang in VOICES:
            if self._mms_supports(lang):
                with self._lock:
                    try:
                        tok, model = self._voice(lang)
                        for s in ("mbote", "mbote na yo, ozali malamu mpenza lelo"):
                            with torch.inference_mode():
                                model(**tok(s, return_tensors="pt").to(model.device))
                    except Exception as exc:
                        log.warning("Voix %s indisponible : %s", lang, exc)
                        self._failed.add(lang)

    def prepare(self, phrases: list[tuple[str, str]], wait_s: float = 120.0) -> None:
        """Phrases dites à chaque Voix live (salutation, « répète ») préparées d'avance, avec la voix
        entraînée dès qu'elle est prête : la 1re réponse d'OkapiAI part tout de suite."""
        import time
        end = time.monotonic() + wait_s
        while time.monotonic() < end and any(l in REMOTE and not self._remote_ok(l) for _, l in phrases):
            time.sleep(5)
        for text, lang in phrases:
            try:
                self.synthesize(text, lang)
            except Exception as exc:
                log.warning("Préparation de « %s » (%s) : %s", text[:30], lang, exc)
        log.info("Phrases de la voix live prêtes (%d)", len(phrases))

    def path_for(self, text: str, lang: str, engine: str = "mms") -> Path:
        digest = hashlib.sha1(f"{CACHE_VERSION}|{engine}|{lang}|{text}".encode("utf-8")).hexdigest()[:24]
        return TTS_DIR / f"{lang}-{engine}-{digest}.wav"

    def _synthesize_remote(self, text: str, lang: str, text_lang: str = "") -> Optional[Path]:
        """Voix externe de `lang` ; `text_lang="fr"` : elle dit un texte français (même voix)."""
        import urllib.parse
        import urllib.request
        # cache lié à la version de la voix : une nouvelle voix validée ne ressert pas les anciens sons
        tag = f"{lang}-{text_lang}" if text_lang else lang
        version = self._remote_version.get(lang, "")
        digest = hashlib.sha1(f"{CACHE_VERSION}|{version}|{text}".encode("utf-8")).hexdigest()[:24]
        path = TTS_DIR / f"{tag}-remote-{digest}.wav"
        if version and path.exists():
            return path
        try:
            url = f"{REMOTE[lang]}/tts?text={urllib.parse.quote(text)}"
            if text_lang:
                url += f"&lang={text_lang}"
            with urllib.request.urlopen(url, timeout=30) as r:
                data = r.read()
        except Exception as exc:
            log.warning("Voix externe %s indisponible : %s -> voix MMS", lang, exc)
            self._remote_state[lang] = (False, __import__("time").monotonic())
            return None
        TTS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        return path

    def synthesize(self, text: str, lang: str, voice: Optional[str] = None) -> Optional[Path]:
        """Fichier WAV de `text` prononcé dans `lang`, ou None si impossible.
        `voice` (texte français seulement) : la voix de la langue nationale de la conversation dit
        aussi les mots français, pour garder la même voix ; sinon voix française MMS."""
        text = " ".join((text or "").split())[:MAX_CHARS]
        if lang != "fr":
            # une seule voix : les mots français de la phrase sont dits par la voix de la langue
            text = national_text(text, lang)
        if not text:
            return None
        if lang == "fr" and voice and SAME_VOICE_FR and self._remote_ok(voice):
            path = self._synthesize_remote(text, voice, text_lang="fr")
            if path is not None:
                return path
        if not self.supports(lang):
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
                for sentence in sentences(speakable_fr(text) if lang == "fr" else speakable(text)):
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
                # court silence au début : sans lui, le navigateur avale la première syllabe
                wav = np.concatenate([np.zeros(int(rate * LEAD_S), dtype=np.float32), *pieces,
                                      np.zeros(int(rate * 0.08), dtype=np.float32)])
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
