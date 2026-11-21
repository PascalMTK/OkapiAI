"""Petit serveur de voix : fait parler la voix affinée (ex. Florent) pour OkapiAI.

À lancer avec le Python où `coqui-tts` est installé :
  python tools/voice_server.py --speaker florent [--port 8100]
Puis, dans backend/.env :  OKAPI_TTS_LN_URL=http://127.0.0.1:8100

  GET /health            -> {"ok": true, "model": "..."}
  GET /tts?text=...      -> WAV (22 050 Hz)
Le serveur recharge tout seul la voix quand une nouvelle version est validée (voir _best).
N'écoute que sur 127.0.0.1.
"""
import argparse
import io
import json
import re
import sys
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train_voice import base_files, clean_text, lang_of, out_dir, training_active  # noqa: E402


def device() -> str:
    """cuda si la carte est libre ; cpu sans carte ou pendant un entraînement (train_voice.py)."""
    import torch
    return "cuda" if torch.cuda.is_available() and not training_active() else "cpu"

MAX_CHARS = 600
NOISE, NOISE_DP = 0.4, 0.3   # modifiables : --noise / --noise-dp
FR_VOICE = "facebook/mms-tts-fra"                                       # prononce le français
VC_MODEL = "voice_conversion_models/multilingual/multi-dataset/openvoice_v2"  # lui donne notre timbre
USE_VC = True                # --no-vc : mots français par simple réécriture phonétique

# Les voix n'ont appris que des lettres : un chiffre (« 2 bato », « 2026 ») faisait échouer la phrase
# entière, et OkapiAI se rabattait sur la voix de secours, bien plus lente. On les dit en toutes lettres.
NUMBERS = {
    "ln": {"units": ["", "moko", "mibale", "misato", "minei", "mitano", "motoba", "nsambo", "mwambe", "libwa"],
           "ten": "zomi", "tens": "ntuku", "hundred": "nkama", "thousand": "nkoto", "and": "na", "zero": "libungutulu"},
    "lua": {"units": ["", "umue", "ibidi", "isatu", "inayi", "itanu", "isambombo", "muanda mutekete",
                      "muanda mukulu", "tshitema"],
            "ten": "dikumi", "hundred": "lukama", "thousand": "tshinunu", "and": "ne", "zero": "zero",
            # accords : makumi abidi (20), nkama ibidi (200), binunu bibidi (2000)
            "tens_list": ["", "dikumi", "makumi abidi", "makumi asatu", "makumi anayi", "makumi atanu",
                          "makumi asambombo", "makumi muanda mutekete", "makumi muanda mukulu", "makumi tshitema"],
            "plural": {"lukama": "nkama", "tshinunu": "binunu"}},
}


def say_number(n: int, lang: str) -> str:
    w = NUMBERS.get(lang, NUMBERS["ln"])
    if n == 0:
        return w["zero"]
    parts = []
    for size, name in ((1000, w["thousand"]), (100, w["hundred"])):
        q, n = divmod(n, size)
        if q:
            plural = w.get("plural", {}).get(name, name)
            parts.append(f"{plural} {say_number(q, lang)}" if q > 1 else name)
    q, n = divmod(n, 10)
    if q:
        parts.append(w["tens_list"][q] if "tens_list" in w else
                     w["ten"] if q == 1 else f"{w['tens']} {w['units'][q]}")
    if n:
        parts.append(w["units"][n])
    return f" {w['and']} ".join(parts)


# Mots français dits avec LA MÊME voix que la langue nationale : la voix ne connaît que les sons bantous
# (a e i o u, sans nasales), on réécrit donc le français comme il se prononce, à la manière d'un
# locuteur de Kinshasa (« bonjour » -> « bojur », « maison » -> « mezo », « bureau » -> « biro »).
_FR_RULES = [
    # consonnes qui dépendent de la voyelle suivante : avant de toucher aux voyelles
    (r"aujourd'hui", "ojUrdwi"), (r"tion", "Sion"), (r"ch", "sh"), (r"gn", "ny"), (r"qu", "k"), (r"ph", "f"), (r"th", "t"), (r"ç", "s"),
    (r"c(?=[eiyéèêë])", "s"), (r"gu(?=[eiyéèêë])", "g"), (r"g(?=[eiyéèêë])", "j"), (r"c", "k"),
    (r"(?<=[aeiouyéèêàâôî])s(?=[aeiouyéèêàâôî])", "z"),
    # lettres finales muettes (« petites » -> « petit » -> « peti »), « -er / -ez / -et » -> « e »
    (r"(?<=\w\w)(?:er|ez|et)\b", "é"), (r"(?<=\w\w)(?:es|e|s|x)\b", ""), (r"(?<=\w\w)(?:t|d|p|s|z)\b", ""),
    # voyelles (U = « ou », mis de côté pour que le « u » français devienne « i »)
    (r"eau", "o"), (r"au", "o"), (r"o[uùû]", "U"), (r"oi", "wa"), (r"oy", "way"), (r"[uU]i", "wi"),
    (r"(?<![nN])y", "i"),
    (r"(?<=[aeiouU])ill", "y"), (r"ill", "iy"),
    (r"(?:ai|ei)[nm](?![aeiouynm])", "e"), (r"[iy][nm](?![aeiouynm])", "e"), (r"un\b", "e"),
    (r"[ae][nm](?![aeiouynm])", "a"), (r"o[nm](?![aeiouynm])", "o"),
    (r"(?:ai|ei|è|ê|ë|é)", "e"), (r"[eœ]u", "e"), (r"œ", "e"),
    (r"[uùû]", "i"), (r"U", "u"),  # « bureau » -> « biro », « bonjour » -> « bojur »
    (r"x", "ks"), (r"\bh", ""), (r"(?<![s])h", ""), (r"'", ""), (r"S", "s"),
    (r"([bdfgklmnprstvz])\1", r"\1"), (r"[àâ]", "a"), (r"[îï]", "i"), (r"ô", "o"),
]


def french_for_voice(text: str) -> str:
    t = text.lower().replace("’", "'")
    t = re.sub(r"\b([ldjmtsnc]|qu)'", r"\1e ", t)     # l'école -> le ecole
    for pat, rep in _FR_RULES:
        t = re.sub(pat, rep, t)
    return t


def spell_numbers(text: str, lang: str) -> str:
    def one(m):
        digits = m.group(0).replace(" ", "")
        return f" {say_number(int(digits), lang)} " if len(digits) <= 6 else " "
    return re.sub(r"\d+", one, text)


class Voice:
    def __init__(self, speaker: str):
        self.speaker = speaker
        self.lock = threading.Lock()
        self.synth = None
        self.model_path = None
        self.mtime = None
        self.vc = None            # conversion de voix (mots français), chargée à la 1re demande
        self.fr_failed = False

    def _best(self):
        """Voix affinée validée (approved_model.pth, écrit par `train_voice.py check` quand la voix
        se comprend bien), sinon la voix lingala d'origine (Open Bible), toujours claire.
        Un best_model.pth seul ne suffit pas : il peut ressembler au locuteur mais mal articuler."""
        runs = sorted(out_dir(self.speaker).glob(f"run-{self.speaker}-*"), key=lambda p: p.stat().st_mtime)
        for run in reversed(runs):
            ok = run / "approved_model.pth"
            if ok.exists() and (run / "config.json").exists():
                return ok, run / "config.json"
        if lang_of(self.speaker) != "ln":
            return None, None   # pas de voix lingala de secours : un autre accent que celui de la langue
        try:
            ck, cfg = base_files()
            return Path(ck), Path(cfg)
        except Exception:
            return None, None

    def _ensure(self):
        best, cfg = self._best()
        if best is None:
            raise RuntimeError("aucun modèle sauvegardé pour l'instant")
        mtime = best.stat().st_mtime
        if self.synth is None or best != self.model_path or mtime != self.mtime:
            import torch
            from TTS.utils.synthesizer import Synthesizer
            self.synth = Synthesizer(tts_checkpoint=str(best), tts_config_path=str(cfg),
                                     use_cuda=device() == "cuda")
            # Moins de hasard à la lecture : par défaut (0,667 / 1,0) la voix tire au sort une partie du
            # rythme et du timbre, d'où des hésitations et des mots avalés. Mesuré (MMS relit la voix) :
            # Florent 12 % -> 5,7 % de lettres mal lues avec 0,4 / 0,3.
            m = self.synth.tts_model
            m.inference_noise_scale, m.inference_noise_scale_dp = NOISE, NOISE_DP
            self.model_path, self.mtime = best, mtime
            print(f"Voix {self.speaker} chargée : {best}", flush=True)

    # ---- Mots français avec le timbre de cette voix ----
    # La voix française MMS prononce correctement le mot, puis OpenVoice v2 lui donne le timbre du
    # locuteur (enregistrements de data/wavs). Mesuré (reconnaissance française) : « je suis fatigué »
    # est bien compris, contre « lieli fative » avec la simple réécriture. Repli : french_for_voice.
    def _ensure_fr(self) -> bool:
        if self.fr_failed:
            return False
        if self.vc is None:
            try:
                from transformers import AutoTokenizer, VitsModel
                from TTS.api import TTS
                dev = device()
                refs = sorted((out_dir(self.speaker) / "data" / "wavs").glob("*.wav"))[:8]
                if not refs:
                    raise RuntimeError("aucun enregistrement du locuteur (data/wavs)")
                self.fr_tok = AutoTokenizer.from_pretrained(FR_VOICE)
                self.fr_model = VitsModel.from_pretrained(FR_VOICE).to(dev).eval()
                self.vc = TTS(VC_MODEL).to(dev)
                self.refs = [str(r) for r in refs]
                print(f"Français avec le timbre de {self.speaker} : prêt ({dev})", flush=True)
            except Exception as exc:
                print(f"Conversion de voix indisponible ({exc}) : réécriture phonétique", flush=True)
                self.fr_failed = True
                return False
        return True

    def move(self, dev: str) -> None:
        """Pendant un entraînement : tout sur le processeur (la carte va à l'entraînement), puis retour."""
        with self.lock:
            if self.synth is not None and self.synth.use_cuda != (dev == "cuda"):
                self.synth.tts_model.to(dev)
                self.synth.use_cuda = dev == "cuda"
            if self.vc is not None:
                self.fr_model.to(dev)
                self.vc.to(dev)
            if dev == "cpu":
                import torch
                torch.cuda.empty_cache()
        print(f"Voix {self.speaker} sur {dev}", flush=True)

    def french_wav(self, text: str) -> Optional[bytes]:
        import tempfile
        import numpy as np
        import torch
        t = " ".join(re.sub(r"[«»\"“”()\[\]*_#]", " ", text.lower().replace("’", "'")).split())
        with self.lock:
            if not t or not self._ensure_fr():
                return None
            inputs = self.fr_tok(t, return_tensors="pt").to(self.fr_model.device)
            if inputs["input_ids"].shape[-1] <= 1:
                return None
            with torch.inference_mode():
                src = self.fr_model(**inputs).waveform[0].float().cpu().numpy()
            with tempfile.TemporaryDirectory() as d:
                src_path, out_path = Path(d) / "fr.wav", Path(d) / "out.wav"
                with wave.open(str(src_path), "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(self.fr_model.config.sampling_rate)
                    w.writeframes((np.clip(src, -1, 1) * 32767).astype("<i2").tobytes())
                self.vc.voice_conversion_to_file(source_wav=str(src_path), target_wav=self.refs,
                                                 file_path=str(out_path))
                return out_path.read_bytes()

    def wav(self, text: str, lang: str = "") -> bytes:
        """`lang="fr"` : texte français, dit avec le timbre de cette voix (conversion de voix,
        sinon réécrit comme il se prononce)."""
        if lang == "fr":
            if USE_VC:
                try:
                    out = self.french_wav(text)
                    if out:
                        return out
                except Exception as exc:
                    print(f"Conversion de voix : {exc} -> réécriture phonétique", flush=True)
            text = french_for_voice(text)
        import numpy as np
        text = spell_numbers(text.replace("«", " ").replace("»", " ").replace("…", "."), lang_of(self.speaker))
        prepared = clean_text(text)
        if not prepared:
            raise ValueError("texte vide après préparation")
        with self.lock:
            self._ensure()
            audio = np.asarray(self.synth.tts(prepared, split_sentences=True), dtype=np.float32)
            rate = self.synth.output_sample_rate
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
        return buf.getvalue()


def make_handler(voice: Voice):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/health":
                best, _ = voice._best()
                return self._send(200 if best else 503, json.dumps(
                    {"ok": best is not None, "speaker": voice.speaker, "model": str(best) if best else None}).encode(),
                    "application/json")
            if url.path == "/tts":
                text = (parse_qs(url.query).get("text") or [""])[0][:MAX_CHARS]
                try:
                    lang = (parse_qs(url.query).get("lang") or [""])[0]
                    return self._send(200, voice.wav(text, lang), "audio/wav")
                except Exception as exc:
                    return self._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")
            self._send(404, b"{}", "application/json")

    return Handler


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--speaker", default="florent")
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--noise", type=float, default=NOISE, help="hasard du timbre (défaut du modèle : 0.667)")
    ap.add_argument("--noise-dp", type=float, default=NOISE_DP, help="hasard du rythme (défaut du modèle : 1.0)")
    ap.add_argument("--no-vc", action="store_true", help="mots français sans conversion de voix")
    a = ap.parse_args()
    NOISE, NOISE_DP, USE_VC = a.noise, a.noise_dp, not a.no_vc
    voice = Voice(a.speaker)
    server = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(voice))
    print(f"Serveur de voix ({a.speaker}) sur http://127.0.0.1:{a.port}", flush=True)
    # Charge la voix tout de suite : sinon la 1re phrase d'OkapiAI attend ~30 s
    def warm():
        voice.wav("mbote")
        if USE_VC:
            voice.wav("bonjour", "fr")   # charge aussi la conversion (~2 s), sinon le 1er mot français attend
    threading.Thread(target=warm, daemon=True).start()

    def follow_gpu():   # un entraînement démarre ou finit : la voix change de processeur
        import time
        last = device()
        while True:
            time.sleep(5)
            now = device()
            if now != last:
                try:
                    voice.move(now)
                    last = now
                except Exception as exc:
                    print(f"Déplacement vers {now} impossible : {exc}", flush=True)
    threading.Thread(target=follow_gpu, daemon=True).start()
    server.serve_forever()
