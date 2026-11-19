"""Pre-transcribe the Lingala parts of the clips with Meta MMS (Lingala adapter).

Usage: python tools/transcribe_ln.py [<video_id> ...]   (run tools/tag_language.py first)

For every clip tagged "ln" or "mixte":
  - transcribes each Lingala span's audio with facebook/mms-1b-all + adapter "lin"
  - looks the result up in the Wikipedia lexicon (fuzzy match) to suggest a spelling
    and a French translation
Adds to each row of dataset/clips/<id>/metadata.jsonl:
  ln_mms        [{"t0", "t1", "asr_fr", "mms", "lexique": [{"lingala", "francais", "score"}]}]
The "lingala" / "francais" fields stay for the human review.
"""
import difflib
import json
import sys
import unicodedata
from pathlib import Path

import soundfile as sf
import torch
from transformers import AutoProcessor, Wav2Vec2ForCTC

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cut_videos import CLIPS, RAW, ROOT  # noqa: E402

MODEL = "facebook/mms-1b-all"
PAD_S = 0.25
LEX_PATH = ROOT / "dataset" / "knowledge" / "lexique_wikipedia.jsonl"


def plain(s: str) -> str:
    """lowercase, no tones/accents, ɛ->e ɔ->o, for fuzzy matching."""
    s = s.lower().replace("ɛ", "e").replace("ɔ", "o")
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def load_lexicon():
    rows = [json.loads(l) for l in LEX_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
    return {plain(r["lingala"]): r for r in rows}


def lookup(text, lex, n=3):
    keys = list(lex)
    out = []
    for tok in {text, *text.split()}:
        for k in difflib.get_close_matches(plain(tok), keys, n=n, cutoff=0.7):
            r = lex[k]
            out.append({"lingala": r["lingala"], "francais": r["francais"],
                        "score": round(difflib.SequenceMatcher(None, plain(tok), k).ratio(), 2)})
    uniq = {(o["lingala"], o["francais"]): o for o in sorted(out, key=lambda o: o["score"])}
    return sorted(uniq.values(), key=lambda o: -o["score"])[:n]


def load_model():
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    proc = AutoProcessor.from_pretrained(MODEL, target_lang="lin")
    model = Wav2Vec2ForCTC.from_pretrained(MODEL, target_lang="lin", ignore_mismatched_sizes=True)
    model = model.to(dev, torch.float16 if dev == "cuda" else torch.float32).eval()
    return proc, model, dev


def transcribe(audio, rate, proc, model, dev):
    inp = proc(audio, sampling_rate=rate, return_tensors="pt")
    with torch.no_grad():
        logits = model(inp["input_values"].to(dev, model.dtype)).logits
    return proc.decode(logits[0].argmax(-1)).strip()


def spans_of(row):
    """Group consecutive Lingala words into (t0, t1, asr_text)."""
    words, out, cur = row.get("words", []), [], []
    for i, w in enumerate(words + [{"lang": "fr", "t": row["end"]}]):
        if w["lang"] == "ln":
            cur.append(i)
        elif cur:
            t0 = words[cur[0]]["t"]
            t1 = words[cur[-1] + 1]["t"] if cur[-1] + 1 < len(words) else row["end"]
            out.append((t0, t1, " ".join(words[j]["w"] for j in cur)))
            cur = []
    return out


def run(vid, proc, model, dev, lex):
    meta_path = CLIPS / vid / "metadata.jsonl"
    rows = [json.loads(l) for l in meta_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not any("lang" in r for r in rows):
        print(f"[{vid}] not tagged yet, run tag_language.py first")
        return
    wav, rate = sf.read(RAW / vid / "audio.wav", dtype="float32")
    n = 0
    for r in rows:
        if r.get("lang") not in ("ln", "mixte"):
            continue
        res = []
        for t0, t1, asr in spans_of(r):
            a, b = int(max(0, t0 - PAD_S) * rate), int((t1 + PAD_S) * rate)
            if b - a < int(0.4 * rate):
                continue
            text = transcribe(wav[a:b], rate, proc, model, dev)
            res.append({"t0": round(t0, 2), "t1": round(t1, 2), "asr_fr": asr, "mms": text,
                        "lexique": lookup(text, lex) or lookup(asr, lex)})
            n += 1
        r["ln_mms"] = res
    meta_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"[{vid}] {n} lingala spans transcribed", flush=True)


if __name__ == "__main__":
    vids = sys.argv[1:] or sorted(p.name for p in CLIPS.iterdir() if p.is_dir())
    lex = load_lexicon()
    proc, model, dev = load_model()
    print(f"model on {dev}, lexicon {len(lex)} entries")
    for vid in vids:
        run(vid, proc, model, dev, lex)
