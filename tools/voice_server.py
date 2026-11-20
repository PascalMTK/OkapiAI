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
import sys
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train_voice import base_files, clean_text, out_dir  # noqa: E402

MAX_CHARS = 600


class Voice:
    def __init__(self, speaker: str):
        self.speaker = speaker
        self.lock = threading.Lock()
        self.synth = None
        self.model_path = None
        self.mtime = None

    def _best(self):
        """Voix affinée validée (approved_model.pth, écrit par `train_voice.py check` quand la voix
        se comprend bien), sinon la voix lingala d'origine (Open Bible), toujours claire.
        Un best_model.pth seul ne suffit pas : il peut ressembler au locuteur mais mal articuler."""
        runs = sorted(out_dir(self.speaker).glob(f"run-{self.speaker}-*"), key=lambda p: p.stat().st_mtime)
        for run in reversed(runs):
            ok = run / "approved_model.pth"
            if ok.exists() and (run / "config.json").exists():
                return ok, run / "config.json"
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
                                     use_cuda=torch.cuda.is_available())
            self.model_path, self.mtime = best, mtime
            print(f"Voix {self.speaker} chargée : {best}", flush=True)

    def wav(self, text: str) -> bytes:
        import numpy as np
        prepared = clean_text(text.replace("«", " ").replace("»", " ").replace("…", "."))
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
                    return self._send(200, voice.wav(text), "audio/wav")
                except Exception as exc:
                    return self._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")
            self._send(404, b"{}", "application/json")

    return Handler


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--speaker", default="florent")
    ap.add_argument("--port", type=int, default=8100)
    a = ap.parse_args()
    voice = Voice(a.speaker)
    server = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(voice))
    print(f"Serveur de voix ({a.speaker}) sur http://127.0.0.1:{a.port}", flush=True)
    # Charge la voix tout de suite : sinon la 1re phrase d'OkapiAI attend ~30 s
    threading.Thread(target=lambda: voice.wav("mbote"), daemon=True).start()
    server.serve_forever()
