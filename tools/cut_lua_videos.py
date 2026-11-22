"""Vidéos YouTube SANS sous-titres (ex. cours de tshiluba) -> petits clips coupés aux silences.

  python tools/cut_lua_videos.py <url|id|playlist> ...        # télécharge + coupe
  python tools/cut_lua_videos.py --transcribe [<id> ...]      # pré-transcrit les clips (Whisper tshiluba)

Sortie (même format que tools/cut_videos.py) :
  dataset/raw/<id>/audio.wav, dataset/clips/<id>/<id>_0001.wav…, dataset/clips/<id>/metadata.jsonl
Chaque clip a "tshiluba" (vide, à remplir à la relecture), "asr_lua" (pré-transcription automatique,
souvent fausse sur les passages en français des cours) et needs_review=true.
"""
import json
import os
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cut_videos import CLIPS, RAW, ROOT, download, video_id  # noqa: E402

FRAME_S = 0.03     # analyse par trames de 30 ms
PAUSE_S = 0.45     # silence qui sépare deux morceaux
MIN_S, MAX_S, PAD_S = 0.8, 10.0, 0.15


def playlist_ids(url: str) -> list[str]:
    out = subprocess.run([sys.executable, "-m", "yt_dlp", "--js-runtimes", "node", "--flat-playlist", "--print", "%(id)s", url],
                         capture_output=True, text=True, check=True).stdout
    return [x.strip() for x in out.splitlines() if x.strip()]


def speech_segments(audio: np.ndarray, rate: int) -> list[tuple[float, float]]:
    """Morceaux de parole séparés par des silences (énergie par trame, seuil adaptatif)."""
    n = int(FRAME_S * rate)
    frames = audio[: len(audio) // n * n].reshape(-1, n)
    db = 10 * np.log10((frames.astype(np.float64) ** 2).mean(1) + 1e-10)
    floor, peak = np.percentile(db, 10), np.percentile(db, 95)
    voiced = db > floor + 0.35 * (peak - floor)
    segs, start, quiet = [], None, 0
    for i, v in enumerate(voiced):
        if v:
            start = i if start is None else start
            quiet = 0
        elif start is not None:
            quiet += 1
            if quiet * FRAME_S >= PAUSE_S:
                segs.append((start * FRAME_S, (i - quiet + 1) * FRAME_S))
                start, quiet = None, 0
    if start is not None:
        segs.append((start * FRAME_S, len(voiced) * FRAME_S))
    out = []
    for st, en in segs:              # coupe les morceaux trop longs en parts égales
        k = int(np.ceil((en - st) / MAX_S))
        step = (en - st) / k
        out += [(st + j * step, st + (j + 1) * step) for j in range(k)]
    return [(st, en) for st, en in out if en - st >= MIN_S]


def cut(vid: str) -> int:
    out = CLIPS / vid
    if (out / "metadata.jsonl").exists():
        print(f"[{vid}] déjà découpée, ignorée")
        return 0
    raw = download(vid)
    title = (raw / "title.txt").read_text(encoding="utf-8").strip() if (raw / "title.txt").exists() else ""
    with wave.open(str(raw / "audio.wav"), "rb") as src:
        rate, params = src.getframerate(), src.getparams()
        pcm = np.frombuffer(src.readframes(src.getnframes()), dtype=np.int16)
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(out / "metadata.jsonl", "w", encoding="utf-8") as meta:
        for st, en in speech_segments(pcm.astype(np.float32) / 32768, rate):
            a, b = max(0, int((st - PAD_S) * rate)), min(len(pcm), int((en + PAD_S) * rate))
            n += 1
            name = f"{vid}_{n:04d}.wav"
            with wave.open(str(out / name), "wb") as dst:
                dst.setparams(params)
                dst.writeframes(pcm[a:b].tobytes())
            meta.write(json.dumps({
                "audio": f"clips/{vid}/{name}", "video_id": vid, "title": title,
                "start": round(a / rate, 2), "end": round(b / rate, 2),
                "lang": "lua", "asr_lua": "", "tshiluba": "", "francais": "", "needs_review": True,
            }, ensure_ascii=False) + "\n")
    print(f"[{vid}] {n} clips -> {out}  ({title})")
    return n


def transcribe(ids: list[str]) -> None:
    """Pré-transcription par la reconnaissance tshiluba du site (sur le processeur par défaut)."""
    sys.path.insert(0, str(ROOT / "backend"))
    os.environ.setdefault("OKAPI_ASR_DEVICE", "cpu")
    from app.services.speech import TshilubaRecognizer, load_audio
    rec = TshilubaRecognizer()
    metas = [CLIPS / i / "metadata.jsonl" for i in ids] if ids else sorted(CLIPS.glob("*/metadata.jsonl"))
    for path in metas:
        rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
        if not rows or rows[0].get("lang") != "lua":
            continue
        todo = [r for r in rows if not r.get("asr_lua")]
        for r in todo:
            r["asr_lua"] = rec.transcribe_array(load_audio(ROOT / "dataset" / r["audio"])) or ""
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        print(f"[{path.parent.name}] {len(todo)} clips pré-transcrits", flush=True)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--transcribe"]:
        transcribe([video_id(a) for a in args[1:]])
    else:
        total = 0
        for arg in args:
            for vid in (playlist_ids(arg) if "list=" in arg and "v=" not in arg else [video_id(arg)]):
                try:
                    total += cut(vid)
                except subprocess.CalledProcessError as exc:
                    print(f"[{vid}] échec du téléchargement : {exc}")
        print(f"total : {total} clips")
