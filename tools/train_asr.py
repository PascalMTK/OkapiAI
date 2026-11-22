"""Affinage de la reconnaissance vocale lingala (MMS, adaptateur « lin ») sur LRSC.

Seul l'adaptateur de langue (≈2 M paramètres + tête de sortie) est entraîné ; le modèle de base
(1 milliard de paramètres) reste figé en fp16 pour tenir dans 4 Go de carte graphique.

  python tools/train_asr.py eval                      # WER/CER de l'adaptateur d'origine sur LRSC test
  python tools/train_asr.py eval --adapter affine     # idem avec l'adaptateur affiné
  python tools/train_asr.py train --epochs 4          # affinage (sauvegarde le meilleur sur validation)

L'adaptateur affiné est écrit dans backend/models/mms-lin-affine/adapter.lin.safetensors ;
backend/app/services/speech.py l'utilise automatiquement s'il existe (OKAPI_ASR_LN_ADAPTER=off pour l'ignorer).
"""
import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MMS = ROOT / "backend" / "models" / "mms-1b-all"
OUT = ROOT / "backend" / "models" / "mms-lin-affine"
LRSC = ROOT / "dataset" / "sources" / "lrsc"
TRAINING_FLAG = ROOT / "backend" / "models" / "entrainement-en-cours.json"
SR = 16000


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def rows(split):
    out = []
    for line in (LRSC / "metadata.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["split"] == split and r.get("lingala") and not r.get("needs_review"):
            out.append(r)
    return out


def load_wav(rel):
    import soundfile as sf
    import numpy as np
    audio, sr = sf.read(str(ROOT / "dataset" / rel), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(1)
    if sr != SR:
        import torch, torchaudio
        audio = torchaudio.functional.resample(torch.from_numpy(audio), sr, SR).numpy()
    return np.ascontiguousarray(audio)


def normalize(text, vocab):
    text = " ".join(text.lower().replace("’", "'").split())
    return "".join(c for c in text if c == " " or c in vocab).strip()


def edit(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def load_model(device):
    import torch
    from transformers import AutoProcessor, Wav2Vec2ForCTC
    proc = AutoProcessor.from_pretrained(str(MMS), target_lang="lin")
    model = Wav2Vec2ForCTC.from_pretrained(str(MMS), target_lang="lin", ignore_mismatched_sizes=True,
                                           torch_dtype=torch.float16)
    return proc, model.to(device)


def adapter_params(model):
    return model._get_adapters()          # {nom: paramètre} : adaptateurs de chaque couche + lm_head


def evaluate(model, proc, data, device, limit=None, show=0):
    import torch
    model.eval()
    vocab = set(proc.tokenizer.get_vocab())
    we = wn = ce = cn = 0
    for k, r in enumerate(data[:limit] if limit else data):
        ref = normalize(r["lingala"], vocab)
        x = proc(load_wav(r["audio"]), sampling_rate=SR, return_tensors="pt").input_values.to(device)
        with torch.inference_mode(), torch.autocast("cuda", torch.float16, enabled=device == "cuda"):
            logits = model(x.to(model.dtype if device != "cuda" else torch.float16)).logits[0]
        hyp = proc.decode(logits.float().argmax(-1)).strip()
        we += edit(ref.split(), hyp.split()); wn += len(ref.split())
        ce += edit(ref, hyp); cn += len(ref)
        if k < show:
            log(f"  réf: {ref}\n           lu : {hyp}")
    return we / max(wn, 1), ce / max(cn, 1)


def load_affine(model):
    from safetensors.torch import load_file
    state = load_file(str(OUT / "adapter.lin.safetensors"))
    missing = model.load_state_dict({k: v.to(model.dtype) for k, v in state.items()}, strict=False)
    assert not missing.unexpected_keys, missing.unexpected_keys


def cmd_eval(args):
    import torch
    device = "cuda" if torch.cuda.is_available() and not args.cpu else "cpu"
    proc, model = load_model(device)
    if device == "cpu":
        model = model.float()
    if args.adapter == "affine":
        load_affine(model)
    data = rows(args.split)
    wer, cer = evaluate(model, proc, data, device, args.limit, show=5)
    log(f"adaptateur {args.adapter} — {args.split} ({len(data[:args.limit] if args.limit else data)} clips) : "
        f"WER {wer:.1%}  CER {cer:.1%}")


def cmd_train(args):
    import torch
    from safetensors.torch import save_file
    torch.manual_seed(0); random.seed(0)
    TRAINING_FLAG.write_text(json.dumps({"pid": os.getpid(), "quoi": "train_asr lingala"}), encoding="utf-8")
    log("carte graphique réservée : le site passe sur le processeur (20 s)…")
    time.sleep(20)
    try:
        device = "cuda"
        proc, model = load_model(device)
        vocab = set(proc.tokenizer.get_vocab())
        model.freeze_base_model()
        params = adapter_params(model)
        for p in model.parameters():
            p.requires_grad = False
        for p in params.values():           # poids entraînés en fp32 (autocast calcule en fp16)
            p.data = p.data.float()
            p.requires_grad = True
        model.config.ctc_loss_reduction = "mean"
        model.config.ctc_zero_infinity = True
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        n = sum(p.numel() for p in params.values())
        log(f"{n/1e6:.2f} M paramètres entraînés")

        train, val = rows("train"), rows("validation")
        train = [r for r in train if r["duration"] <= args.max_s]
        log(f"train {len(train)} clips, validation {len(val)}")
        opt = torch.optim.AdamW(params.values(), lr=args.lr, weight_decay=0.0)
        steps = args.epochs * len(train) // args.accum
        sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=args.lr, total_steps=steps + 1, pct_start=0.1)
        scaler = torch.amp.GradScaler("cuda")

        base_wer, base_cer = evaluate(model, proc, val, device, args.val_limit)
        log(f"départ — validation WER {base_wer:.1%}  CER {base_cer:.1%}")
        best = base_wer
        OUT.mkdir(parents=True, exist_ok=True)
        step = 0
        for epoch in range(args.epochs):
            random.shuffle(train)
            model.train()
            t0, run = time.time(), 0.0
            for i, r in enumerate(train):
                x = proc(load_wav(r["audio"]), sampling_rate=SR, return_tensors="pt").input_values.to(device)
                labels = torch.tensor([proc.tokenizer(normalize(r["lingala"], vocab)).input_ids], device=device)
                with torch.autocast("cuda", torch.float16):
                    loss = model(x.half(), labels=labels).loss / args.accum
                scaler.scale(loss).backward()
                run += loss.item() * args.accum
                if (i + 1) % args.accum == 0:
                    scaler.unscale_(opt)
                    torch.nn.utils.clip_grad_norm_(params.values(), 1.0)
                    scaler.step(opt); scaler.update(); opt.zero_grad(set_to_none=True); sched.step()
                    step += 1
                    if step % 5 == 0:
                        log(f"époque {epoch+1} pas {step}/{steps} perte {run/(5*args.accum):.3f} "
                            f"({(time.time()-t0)/(i+1):.2f} s/clip, mémoire {torch.cuda.max_memory_allocated()/2**30:.2f} Go)")
                        run = 0.0
                    if step % args.eval_every == 0 or step == steps:
                        wer, cer = evaluate(model, proc, val, device, args.val_limit)
                        mark = ""
                        if wer < best:
                            best = wer
                            save_file({k: v.detach().half().cpu().contiguous() for k, v in params.items()},
                                      str(OUT / "adapter.lin.safetensors"))
                            (OUT / "score.json").write_text(json.dumps(
                                {"pas": step, "wer_validation": wer, "cer_validation": cer,
                                 "wer_depart": base_wer, "cer_depart": base_cer}, indent=1), encoding="utf-8")
                            mark = "  ← meilleur, sauvegardé"
                        log(f"pas {step} — validation WER {wer:.1%}  CER {cer:.1%}{mark}")
                        model.train()
        log(f"fini. meilleur WER validation {best:.1%} (départ {base_wer:.1%})")
    finally:
        TRAINING_FLAG.unlink(missing_ok=True)


def cmd_eval_lua(args):
    """Tshiluba (Whisper affiné, celui du site) sur la partie test du corpus abdouaziz/tshiluba."""
    import io
    import re
    import numpy as np
    import pyarrow.parquet as pq
    import soundfile as sf
    sys.path.insert(0, str(ROOT / "backend"))
    os.environ.setdefault("OKAPI_ASR_DEVICE", "cpu" if args.cpu else "cuda")
    from app.services.speech import TshilubaRecognizer
    rec = TshilubaRecognizer()
    data = Path(os.getenv("OKAPI_TSHILUBA_VOIX", "D:/okapi-data/tshiluba-voix")) / "data" / "test-00000-of-00001.parquet"
    table = pq.read_table(data).to_pylist()
    random.Random(0).shuffle(table)
    norm = lambda t: " ".join(re.sub(r"[^\w' ]", " ", t.lower()).split())
    we = wn = ce = cn = 0
    for k, r in enumerate(table[: args.limit]):
        audio, sr = sf.read(io.BytesIO(r["audio"]["bytes"]), dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(1)
        if sr != SR:
            import torch, torchaudio
            audio = torchaudio.functional.resample(torch.from_numpy(audio), sr, SR).numpy()
        ref, hyp = norm(r["transcription"]), norm(rec.transcribe_array(np.ascontiguousarray(audio)) or "")
        we += edit(ref.split(), hyp.split()); wn += len(ref.split())
        ce += edit(ref, hyp); cn += len(ref)
        if k < 5:
            log(f"  réf: {ref}\n           lu : {hyp}")
    log(f"tshiluba — test ({min(args.limit, len(table))} clips) : WER {we/max(wn,1):.1%}  CER {ce/max(cn,1):.1%}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("eval")
    e.add_argument("--adapter", choices=["origine", "affine"], default="origine")
    e.add_argument("--split", default="test")
    e.add_argument("--limit", type=int)
    e.add_argument("--cpu", action="store_true")
    lu = sub.add_parser("eval-lua")
    lu.add_argument("--limit", type=int, default=200)
    lu.add_argument("--cpu", action="store_true")
    t = sub.add_parser("train")
    t.add_argument("--epochs", type=int, default=4)
    t.add_argument("--lr", type=float, default=1e-3)
    t.add_argument("--accum", type=int, default=8)
    t.add_argument("--max-s", type=float, default=15.0)
    t.add_argument("--eval-every", type=int, default=100)
    t.add_argument("--val-limit", type=int, default=150)
    args = ap.parse_args()
    {"eval": cmd_eval, "eval-lua": cmd_eval_lua, "train": cmd_train}[args.cmd](args)


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
