"""Reconnaissance vocale (voix -> texte).

Moteur principal : Meta MMS (facebook/mms-1b-all, wav2vec2 + adaptateurs par langue),
qui reconnaît le lingala, le swahili et le français. Le kikongo et le tshiluba n'ont pas
encore de modèle public : l'utilisateur tape ce qu'il a dit, et ces enregistrements
serviront à entraîner un modèle dédié.

Repli : faster-whisper (OKAPI_ASR=whisper), qui ne couvre que fr / sw / ln.

Le modèle n'est utilisé que s'il est déjà téléchargé (sinon la 1re requête bloquerait
le temps de télécharger ~4 Go). Pour le télécharger : voir le README, ou
OKAPI_ASR_AUTO_DOWNLOAD=1.
"""
import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import Optional

log = logging.getLogger("okapiai.speech")

ASR_ENGINE = os.getenv("OKAPI_ASR", "mms")             # mms | whisper | off
# Copie locale (backend/models/mms-1b-all, ex. sur un autre disque) si elle existe, sinon le cache Hugging Face
_LOCAL_MMS = Path(__file__).resolve().parents[2] / "models" / "mms-1b-all"
MMS_MODEL = os.getenv("OKAPI_ASR_MODEL") or (str(_LOCAL_MMS) if (_LOCAL_MMS / "model.safetensors").exists()
                                            else "facebook/mms-1b-all")
AUTO_DOWNLOAD = os.getenv("OKAPI_ASR_AUTO_DOWNLOAD") == "1"
# auto = carte graphique si disponible ; cpu = processeur (utile quand la carte est occupée, ~4 s/phrase)
ASR_DEVICE = os.getenv("OKAPI_ASR_DEVICE", "auto")
SURE = 0.92  # détection automatique : au-delà de cette confiance, inutile d'essayer l'autre langue
MMS_LANGS = {"ln": "lin", "sw": "swh", "fr": "fra"}
WHISPER_LANGS = {"fr": "fr", "sw": "sw", "ln": "ln"}
WHISPER_SIZE = os.getenv("OKAPI_WHISPER_MODEL", "small")
SAMPLE_RATE = 16000


def load_audio(path: Path):
    """N'importe quel format navigateur (webm/ogg/m4a/wav) -> float32 mono 16 kHz (numpy)."""
    import numpy as np
    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        ffmpeg = "ffmpeg"
    out = subprocess.run([ffmpeg, "-nostdin", "-loglevel", "error", "-i", str(path), "-f", "f32le",
                          "-ac", "1", "-ar", str(SAMPLE_RATE), "-"], capture_output=True, check=True)
    return np.frombuffer(out.stdout, dtype=np.float32)


class MMSRecognizer:
    def __init__(self):
        self._lock = threading.Lock()
        self._model = self._proc = self._device = None
        self._adapter = None
        self._failed = False

    def available(self) -> bool:
        if self._failed:
            return False
        if self._model is not None:
            return True
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
        except ImportError:
            return False
        if AUTO_DOWNLOAD:
            return True
        needed = ("model.safetensors", "adapter.lin.safetensors")
        if Path(MMS_MODEL).is_dir():
            return all((Path(MMS_MODEL) / f).is_file() for f in needed)
        from huggingface_hub import try_to_load_from_cache
        return all(isinstance(try_to_load_from_cache(MMS_MODEL, f), str) for f in needed)

    def _load(self):
        if self._model is not None or self._failed:
            return
        try:
            import torch
            from transformers import AutoProcessor, Wav2Vec2ForCTC
            self._device = ASR_DEVICE if ASR_DEVICE in ("cpu", "cuda") else ("cuda" if torch.cuda.is_available() else "cpu")
            if self._device == "cpu":
                torch.set_num_threads(max(2, (os.cpu_count() or 4) - 2))
            self._proc = AutoProcessor.from_pretrained(MMS_MODEL, target_lang="lin")
            model = Wav2Vec2ForCTC.from_pretrained(MMS_MODEL, target_lang="lin", ignore_mismatched_sizes=True)
            dtype = torch.float16 if self._device == "cuda" else torch.float32
            self._model = model.to(self._device, dtype).eval()
            self._adapter = "lin"
            log.info("MMS chargé (%s) sur %s", MMS_MODEL, self._device)
        except Exception as exc:
            log.warning("Reconnaissance vocale MMS indisponible : %s", exc)
            self._failed = True

    def _use(self, code: str):
        if self._adapter != code:
            self._proc.tokenizer.set_target_lang(code)
            self._model.load_adapter(code)
            self._adapter = code

    def _run(self, audio, code: str) -> tuple[str, float]:
        """(texte, confiance moyenne) pour un adaptateur de langue."""
        import torch
        self._use(code)
        inputs = self._proc(audio, sampling_rate=SAMPLE_RATE, return_tensors="pt")
        values = inputs.input_values.to(self._device, self._model.dtype)
        with torch.inference_mode():
            logits = self._model(values).logits[0].float()
        probs = logits.softmax(-1)
        ids = probs.argmax(-1)
        blank = self._proc.tokenizer.pad_token_id
        speech = ids != blank
        conf = float(probs.max(-1).values[speech].mean()) if speech.any() else 0.0
        return self._proc.decode(ids).strip(), conf

    def transcribe(self, audio, lang: str) -> Optional[str]:
        with self._lock:
            self._load()
            if self._model is None:
                return None
            return self._run(audio, MMS_LANGS[lang])[0] or None

    def detect(self, audio, langs: list[str]) -> tuple[Optional[str], Optional[str]]:
        """Essaie chaque langue et garde la transcription la plus sûre (même modèle, sans LID)."""
        with self._lock:
            self._load()
            if self._model is None:
                return None, None
            best = (None, None, -1.0)
            for lang in langs:
                text, conf = self._run(audio, MMS_LANGS[lang])
                log.info("Détection : %s -> %.3f « %s »", lang, conf, text[:60])
                if text and conf > best[2]:
                    best = (lang, text, conf)
                if conf >= SURE:
                    break  # langue reconnue avec assurance : on gagne le temps du 2e essai
            return best[0], best[1]


class WhisperRecognizer:
    def __init__(self):
        self._model = None
        self._lock = threading.Lock()
        self._failed = False

    def available(self) -> bool:
        if self._failed:
            return False
        try:
            import faster_whisper  # noqa: F401
            return True
        except ImportError:
            return False

    def transcribe(self, path: Path, lang: str) -> Optional[str]:
        # On décode nous-mêmes avec ffmpeg : le lecteur intégré de faster-whisper (PyAV) peut être
        # incompatible avec la version installée (« unexpected keyword argument 'metadata_errors' »).
        return self.transcribe_array(load_audio(path), lang)

    def transcribe_array(self, audio, lang: str) -> Optional[str]:
        with self._lock:
            if self._model is None:
                try:
                    from faster_whisper import WhisperModel
                    self._model = WhisperModel(WHISPER_SIZE, device="auto", compute_type="int8")
                except Exception as exc:
                    log.warning("Whisper indisponible : %s", exc)
                    self._failed = True
                    return None
            segments, _ = self._model.transcribe(audio, language=WHISPER_LANGS[lang],
                                                 vad_filter=True, beam_size=5)
            return " ".join(s.text.strip() for s in segments).strip() or None


class SpeechRecognizer:
    def __init__(self):
        self.mms = MMSRecognizer()
        self.whisper = WhisperRecognizer()

    def _engine(self, lang: str):
        if ASR_ENGINE in ("mms", "auto") and lang in MMS_LANGS and self.mms.available():
            return self.mms
        if ASR_ENGINE in ("whisper", "mms", "auto") and lang in WHISPER_LANGS and self.whisper.available():
            return self.whisper
        return None

    def supports(self, lang: str) -> bool:
        return ASR_ENGINE != "off" and self._engine(lang) is not None

    def transcribe(self, path: Path, lang: str) -> Optional[str]:
        engine = self._engine(lang) if ASR_ENGINE != "off" else None
        if engine is None:
            return None
        try:
            if engine is self.mms:
                return self.mms.transcribe(load_audio(path), lang)
            return engine.transcribe(path, lang)
        except Exception as exc:  # fichier illisible, ffmpeg absent…
            log.warning("Transcription impossible (%s) : %s", lang, exc)
            return None

    def warmup(self) -> None:
        """Charge le modèle MMS à l'avance (appelé au démarrage, en arrière-plan)."""
        if ASR_ENGINE != "off" and self.mms.available():
            with self.mms._lock:
                self.mms._load()
        elif ASR_ENGINE != "off" and self.whisper.available():
            import numpy as np
            try:  # charge Whisper et fait un 1er passage à vide (sinon 20 s au 1er message)
                self.whisper.transcribe_array(np.zeros(SAMPLE_RATE, dtype=np.float32), "ln")
            except Exception as exc:
                log.warning("Préchargement de Whisper impossible : %s", exc)

    def auto_langs(self) -> list[str]:
        """Langues nationales que l'on sait reconnaître automatiquement."""
        return [l for l in ("ln", "sw") if self.supports(l)]

    def detect_and_transcribe(self, path: Path) -> tuple[Optional[str], Optional[str]]:
        """(langue, texte) : quelle langue nationale l'utilisateur a-t-il parlée ?"""
        langs = self.auto_langs()
        if not langs:
            return None, None
        try:
            if all(self._engine(l) is self.mms for l in langs):
                return self.mms.detect(load_audio(path), langs)
            text = self.transcribe(path, langs[0])
            return (langs[0], text) if text else (None, None)
        except Exception as exc:
            log.warning("Détection de langue impossible : %s", exc)
            return None, None


recognizer = SpeechRecognizer()
