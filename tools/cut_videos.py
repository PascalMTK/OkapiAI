"""Download YouTube videos and cut them into short sentence clips for the Okapi dataset.

Usage: python tools/cut_videos.py <url_or_id> [<url_or_id> ...]

For each video:
  dataset/raw/<id>/audio.wav             16 kHz mono audio
  dataset/raw/<id>/audio.fr-orig.json3   YouTube auto captions (French ASR)
  dataset/clips/<id>/<id>_0001.wav ...   sentence clips
  dataset/clips/<id>/metadata.jsonl      one line per clip

The captions are YouTube's automatic French captions: Lingala words inside them are
often mis-transcribed, so every clip is marked needs_review=true and has empty
"lingala" / "francais" fields to fill in by hand.
"""
import json
import subprocess
import sys
import wave
from pathlib import Path

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "dataset" / "raw"
CLIPS = ROOT / "dataset" / "clips"

PAUSE_S = 0.6      # silence between words that ends a sentence
MAX_S = 10.0       # max clip length
MIN_S = 1.0        # drop clips shorter than this
PAD_S = 0.15       # padding added around each clip


def video_id(arg: str) -> str:
    if "v=" in arg:
        return arg.split("v=")[1].split("&")[0]
    if "/shorts/" in arg:
        return arg.split("/shorts/")[1].split("?")[0]
    if "youtu.be/" in arg:
        return arg.split("youtu.be/")[1].split("?")[0]
    return arg


def download(vid: str) -> Path:
    out = RAW / vid
    out.mkdir(parents=True, exist_ok=True)
    if (out / "audio.wav").exists() and list(out.glob("*.json3")):
        return out
    cmd = [
        sys.executable, "-m", "yt_dlp", "--js-runtimes", "node",
        "--ffmpeg-location", imageio_ffmpeg.get_ffmpeg_exe(),
        "-f", "bestaudio", "-x", "--audio-format", "wav",
        "--postprocessor-args", "ffmpeg:-ar 16000 -ac 1",
        "--write-auto-subs", "--sub-langs", ".*-orig",  # original-language ASR only (sometimes mis-detected, e.g. zu-orig) "--sub-format", "json3",
        "--print-to-file", "%(title)s", str(out / "title.txt"),
        "--no-progress", "-o", str(out / "audio.%(ext)s"),
        f"https://www.youtube.com/watch?v={vid}",
    ]
    subprocess.run(cmd, check=True)
    if not list(out.glob("*.json3")):
        # captions are sometimes silently dropped (YouTube rate limit): retry them alone
        subprocess.run([*cmd[:3], "--skip-download", "--write-auto-subs", "--sub-langs", ".*-orig",
                        "--sub-format", "json3", "-o", str(out / "audio.%(ext)s"), cmd[-1]])
    return out


def words_from_json3(path: Path):
    """Return a list of (start_s, end_s, word) from a YouTube json3 caption file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    words = []
    for ev in data.get("events", []):
        if "segs" not in ev or ev.get("aAppend"):
            continue
        t0 = ev.get("tStartMs", 0)
        dur = ev.get("dDurationMs", 0)
        segs = [s for s in ev["segs"] if s.get("utf8", "").strip()]
        for i, s in enumerate(segs):
            st = t0 + s.get("tOffsetMs", 0)
            nxt = t0 + segs[i + 1].get("tOffsetMs", 0) if i + 1 < len(segs) else t0 + dur
            words.append((st / 1000, max(nxt, st + 200) / 1000, s["utf8"].strip()))
    words.sort()
    # end of a word can't run past the start of the next one
    fixed = []
    for i, (st, en, w) in enumerate(words):
        if i + 1 < len(words):
            en = min(en, words[i + 1][0])
        fixed.append((st, en, w))
    return fixed


def group_sentences(words):
    sents, cur = [], []
    for st, en, w in words:
        if cur:
            gap = st - cur[-1][1]
            too_long = en - cur[0][0] > MAX_S
            if gap > PAUSE_S or too_long:
                sents.append(cur)
                cur = []
        cur.append((st, en, w))
        if w.endswith((".", "?", "!")):
            sents.append(cur)
            cur = []
    if cur:
        sents.append(cur)
    return [(s[0][0], s[-1][1], " ".join(x[2] for x in s)) for s in sents]


def cut(vid: str):
    raw = download(vid)
    subs = (sorted(raw.glob("*.fr-orig.json3")) or sorted(raw.glob("*-orig.json3"))
            or sorted(raw.glob("*.json3")))
    if not subs:
        print(f"[{vid}] no captions found, skipped")
        return 0
    asr_lang = subs[0].name.split(".")[-2]  # e.g. "fr-orig", "zu-orig"
    if asr_lang != "fr-orig":
        print(f"[{vid}] no French ASR, using {asr_lang} captions (text is a rough phonetic guess)")
    sents = group_sentences(words_from_json3(subs[0]))
    title = (raw / "title.txt").read_text(encoding="utf-8").strip() if (raw / "title.txt").exists() else ""

    out = CLIPS / vid
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    with wave.open(str(raw / "audio.wav"), "rb") as src, \
            open(out / "metadata.jsonl", "w", encoding="utf-8") as meta:
        rate, total = src.getframerate(), src.getnframes()
        for st, en, text in sents:
            if en - st < MIN_S:
                continue
            a = max(0, int((st - PAD_S) * rate))
            b = min(total, int((en + PAD_S) * rate))
            if b - a < MIN_S * rate:  # captions can run past the end of the audio
                continue
            src.setpos(a)
            frames = src.readframes(b - a)
            n += 1
            name = f"{vid}_{n:04d}.wav"
            with wave.open(str(out / name), "wb") as dst:
                dst.setparams(src.getparams())
                dst.writeframes(frames)
            meta.write(json.dumps({
                "audio": f"clips/{vid}/{name}",
                "video_id": vid,
                "title": title,
                "start": round(a / rate, 2),
                "end": round(b / rate, 2),
                "asr_fr": text,
                "asr_lang": asr_lang,
                "lingala": "",
                "francais": "",
                "needs_review": True,
            }, ensure_ascii=False) + "\n")
    print(f"[{vid}] {n} clips -> {out}")
    return n


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        cut(video_id(arg))
