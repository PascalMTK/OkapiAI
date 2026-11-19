"""Tag every word / clip of the dataset as French (fr) or Lingala (ln).

Usage: python tools/tag_language.py [<video_id> ...]   (default: every video in dataset/clips)

Three signals per word, combined into a Lingala score in [0, 1]:
  1. audio  - Meta MMS-LID (facebook/mms-lid-126) run on 2 s windows of the audio,
              probability of Lingala vs French
  2. lexicon - word not in a French dictionary
  3. asr     - low confidence of YouTube's French ASR on that word

Rewrites dataset/clips/<id>/metadata.jsonl adding:
  lang       "fr" | "ln" | "mixte"
  p_ln       share of the clip's words tagged Lingala
  words      [{"w", "t", "lang", "score"}]
  ln_spans   Lingala word runs found in the clip (still French-ASR spelling)
and writes dataset/vocab_candidates.jsonl: each Lingala run with the French words
around it (the teacher usually says "zolo, le nez"), to validate by hand.
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from spellchecker import SpellChecker
from transformers import AutoFeatureExtractor, Wav2Vec2ForSequenceClassification

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cut_videos import CLIPS, RAW, ROOT  # noqa: E402

MODEL = "facebook/mms-lid-126"
WIN_S, HOP_S, BATCH = 2.0, 0.5, 8
W_AUDIO, W_LEX, W_ASR = 0.6, 0.25, 0.15
LN_THRESHOLD = 0.5

FR = SpellChecker(language="fr")
WORD_RE = re.compile(r"[a-zà-ÿœæ']+", re.I)


def load_model():
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    fe = AutoFeatureExtractor.from_pretrained(MODEL)
    model = Wav2Vec2ForSequenceClassification.from_pretrained(
        MODEL, torch_dtype=torch.float16 if dev == "cuda" else torch.float32).to(dev).eval()
    labels = {v: int(k) for k, v in model.config.id2label.items()}
    return fe, model, dev, labels["lin"], labels["fra"]


def audio_ln_curve(wav, rate, fe, model, dev, i_ln, i_fr):
    """p(Lingala | Lingala or French) for each window centre, every HOP_S seconds."""
    win, hop = int(WIN_S * rate), int(HOP_S * rate)
    starts = list(range(0, max(1, len(wav) - win), hop))
    out = []
    for b in range(0, len(starts), BATCH):
        chunk = [wav[s:s + win] for s in starts[b:b + BATCH]]
        inp = fe(chunk, sampling_rate=rate, return_tensors="pt", padding=True)
        x = inp["input_values"].to(dev, model.dtype)
        with torch.no_grad():
            logits = model(x).logits.float()
        two = torch.softmax(logits[:, [i_ln, i_fr]], dim=-1)[:, 0]
        out.extend(two.cpu().tolist())
        if b % (BATCH * 200) == 0:
            print(f"    audio {starts[b] / rate / 60:5.1f} / {len(wav) / rate / 60:.1f} min", flush=True)
    centres = np.array(starts) / rate + WIN_S / 2
    return centres, np.array(out)


def words_with_conf(json3: Path):
    data = json.loads(json3.read_text(encoding="utf-8"))
    words = []
    for ev in data.get("events", []):
        if "segs" not in ev or ev.get("aAppend"):
            continue
        for s in ev["segs"]:
            w = s.get("utf8", "").strip()
            if w:
                words.append((ev.get("tStartMs", 0) / 1000 + s.get("tOffsetMs", 0) / 1000, w, s.get("acAsrConf", 255)))
    return sorted(words)


def is_french(w: str) -> bool:
    toks = WORD_RE.findall(w.lower())
    if not toks:
        return True  # punctuation, [Musique] ...
    return all(len(t) <= 2 or t in FR or bool(FR.known([t])) for t in toks)


def tag_video(vid, fe, model, dev, i_ln, i_fr, vocab_out):
    raw = RAW / vid
    subs = sorted(raw.glob("*.fr-orig.json3")) or sorted(raw.glob("*.json3"))
    meta_path = CLIPS / vid / "metadata.jsonl"
    if not subs or not meta_path.exists():
        print(f"[{vid}] missing captions or clips, skipped")
        return
    print(f"[{vid}] audio language detection...", flush=True)
    wav, rate = sf.read(raw / "audio.wav", dtype="float32")
    centres, p_audio = audio_ln_curve(wav, rate, fe, model, dev, i_ln, i_fr)
    words = words_with_conf(subs[0])
    times = np.array([w[0] for w in words])

    rows = [json.loads(l) for l in meta_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    counts = {"fr": 0, "ln": 0, "mixte": 0}
    for r in rows:
        lo, hi = np.searchsorted(times, r["start"]), np.searchsorted(times, r["end"])
        tagged = []
        for t, w, conf in words[lo:hi]:
            pa = float(np.interp(t, centres, p_audio))
            lex = 0.0 if is_french(w) else 1.0
            asr = 1.0 - conf / 255
            score = W_AUDIO * pa + W_LEX * lex + W_ASR * asr
            tagged.append({"w": w, "t": round(t, 2), "lang": "ln" if score >= LN_THRESHOLD else "fr",
                           "score": round(score, 2)})
        n_ln = sum(x["lang"] == "ln" for x in tagged)
        share = n_ln / len(tagged) if tagged else 0.0
        r["lang"] = "ln" if share >= 0.7 else "fr" if share < 0.15 else "mixte"
        r["p_ln"] = round(share, 2)
        r["words"] = tagged

        spans, cur = [], []
        for i, x in enumerate(tagged + [{"lang": "fr"}]):
            if x["lang"] == "ln":
                cur.append(i)
            elif cur:
                spans.append(cur)
                cur = []
        r["ln_spans"] = [" ".join(tagged[i]["w"] for i in s) for s in spans]
        for s in spans:
            before = " ".join(x["w"] for x in tagged[max(0, s[0] - 4):s[0]])
            after = " ".join(x["w"] for x in tagged[s[-1] + 1:s[-1] + 6])
            vocab_out.write(json.dumps({
                "video_id": vid, "audio": r["audio"], "t": tagged[s[0]]["t"],
                "lingala_asr": r["ln_spans"][spans.index(s)],
                "contexte_avant": before, "contexte_apres": after,
                "lingala": "", "francais": "", "valide": False,
            }, ensure_ascii=False) + "\n")
        counts[r["lang"]] += 1

    meta_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"[{vid}] {counts}", flush=True)


def is_tagged(vid):
    p = CLIPS / vid / "metadata.jsonl"
    return p.exists() and '"lang":' in p.read_text(encoding="utf-8")


if __name__ == "__main__":
    import io
    force = "--force" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--force"]
    vids = args or sorted(p.name for p in CLIPS.iterdir() if p.is_dir())
    todo = [v for v in vids if force or not is_tagged(v)]
    print(f"{len(todo)} videos to tag ({len(vids) - len(todo)} already tagged, use --force to redo)")
    if not todo:
        sys.exit()
    fe, model, dev, i_ln, i_fr = load_model()
    print(f"model on {dev}")
    vocab_path = ROOT / "dataset" / "vocab_candidates.jsonl"
    for vid in todo:
        buf = io.StringIO()
        tag_video(vid, fe, model, dev, i_ln, i_fr, buf)
        # replace only this video's candidates, keep the others
        old = vocab_path.read_text(encoding="utf-8").splitlines() if vocab_path.exists() else []
        kept = [l for l in old if l.strip() and json.loads(l)["video_id"] != vid]
        vocab_path.write_text("".join(l + "\n" for l in kept) + buf.getvalue(), encoding="utf-8")
