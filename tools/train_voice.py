"""Affine la voix lingala VITS (Open Bible) sur un locuteur du corpus LRSC.

Usage (avec un Python où `coqui-tts` est installé, voir le README) :
  python tools/train_voice.py prepare --speaker florent     # prépare les données
  python tools/train_voice.py train   --speaker florent     # affinage (plusieurs heures, GPU conseillé)
  python tools/train_voice.py check   --speaker florent     # valide la voix (backend lancé)
  python tools/train_voice.py sample  --speaker florent     # génère des phrases de test
  python tools/train_voice.py train   --speaker florent --fp16 --epochs 30   # rapide (carte 4 Go)

Données  : dataset/sources/lrsc/  (CC BY 4.0) -> backend/models/voix-<speaker>/data/
           wavs/<id>.wav (22 050 Hz mono, silences coupés) + metadata.csv (format LJSpeech)
Départ   : multilingual-tts/VITS-OpenBible-Lingala (CC BY-SA 4.0)
Résultat : backend/models/voix-<speaker>/run-*/checkpoint_*.pth ; `check` fait écouter chacun par
           la reconnaissance vocale et copie le meilleur compréhensible dans approved_model.pth,
           la seule voix affinée que sert tools/voice_server.py (sinon : la voix d'origine).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
LRSC = ROOT / "dataset" / "sources" / "lrsc"
BASE_REPO = "multilingual-tts/VITS-OpenBible-Lingala"
RATE = 22050
CHARS = set("abcdefghijklmnoprstuvwyz")
TEST_SENTENCES = [
    "mbote mingi ngai nazali malamu mpe yo ozali ndenge nini lelo",
    "na kinshasa bato balingaka fufu mingi elongo na madesu",
    "kombo na ngai okapiai nazali mosungi na yo ya lingala",
]
# Voix entraînables : locuteur -> langue. « tshiluba » = voix tshiluba (corpus abdouaziz/tshiluba)
LANG_OF = {"tshiluba": "lua"}
SENTENCES = {
    "ln": TEST_SENTENCES,
    "lua": ["moyo webe udi muimpe ndi muimpe tuasakidila bikole",
            "muana wanyi udi kuenda ku kalasa lelu",
            "dina dianyi ndi okapiai ndi musue kukuambuluisha"],
}
CHECK_EXTRA = {
    "ln": ["lobi tokokende na zando kosomba mbisi mpe pondu", "mama azali kolamba bilei na ndako",
           "olingi tosolola likambo nini lelo"],
    "lua": ["shala bimpe tuamonangana", "ndi musue kulonga tshiluba", "bantu ba bungi badi mu nzubu"],
}
TSHILUBA_VOIX = Path(os.getenv("OKAPI_TSHILUBA_VOIX", "D:/okapi-data/tshiluba-voix")) / "data"


def lang_of(speaker: str) -> str:
    return LANG_OF.get(speaker, "ln")


def out_dir(speaker: str) -> Path:
    return ROOT / "backend" / "models" / f"voix-{speaker}"


def clean_text(text: str) -> str | None:
    """Même préparation que la voix du serveur : sans tons, ɛ/ε->e, ɔ->o ; None si inutilisable."""
    t = text.lower().replace("ɛ", "e").replace("ε", "e").replace("ɔ", "o").replace("’", "'")
    t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    t = t.replace("x", "ks").replace("q", "k")
    t = re.sub(r"[^a-z' ,.?!-]", " ", t) if not re.search(r"\d", t) else None
    if t is None:
        return None
    t = " ".join(t.split())
    letters = {c for c in t if c.isalpha()}
    return t if t and letters <= CHARS else None


def ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def prepare_parquet(speaker: str, max_clips: int) -> None:
    """Voix tshiluba : enregistrements du corpus abdouaziz/tshiluba (fichiers parquet), un seul lecteur."""
    import wave
    import pyarrow.parquet as pq
    data = out_dir(speaker) / "data"
    (data / "wavs").mkdir(parents=True, exist_ok=True)
    trim = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse,"
            "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse")
    lines, skipped, seconds = [], 0, 0.0
    files = sorted(TSHILUBA_VOIX.glob("*.parquet"))
    if not files:
        sys.exit(f"Aucun fichier parquet dans {TSHILUBA_VOIX}")
    for f in files:
        for i, row in enumerate(pq.read_table(f).to_pylist()):
            if len(lines) >= max_clips:
                break
            text = clean_text(row.get("transcription") or "")
            audio = (row.get("audio") or {}).get("bytes")
            # Un seul lecteur : les fichiers « Line-*.wav » (voix d'homme régulière, 44-48 kHz) ;
            # les clips Common Voice (« common_voice_lua_* ») mélangent beaucoup de voix.
            if not str((row.get("audio") or {}).get("path") or "").startswith("Line-"):
                continue
            if not text or not audio:
                skipped += 1
                continue
            uid = f"{f.stem.split('-')[0]}_{i:05d}"
            dst = data / "wavs" / f"{uid}.wav"
            if not dst.exists():
                subprocess.run([ffmpeg(), "-nostdin", "-loglevel", "error", "-y", "-i", "-", "-af", trim, "-ac", "1",
                                "-ar", str(RATE), "-sample_fmt", "s16", str(dst)], input=audio, check=True)
            with wave.open(str(dst)) as w:
                dur = w.getnframes() / w.getframerate()
            if not 0.8 <= dur <= 12:      # trop court, ou trop long pour la carte de 4 Go
                skipped += 1
                continue
            seconds += dur
            lines.append(f"{uid}|{text}|{text}")
    (data / "metadata.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{speaker} : {len(lines)} phrases, {seconds / 60:.1f} min ({skipped} écartées) -> {data}")


def prepare(speaker: str, max_clips: int = 100000) -> None:
    if lang_of(speaker) == "lua":
        return prepare_parquet(speaker, max_clips)
    rows = [json.loads(l) for l in (LRSC / "metadata.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [r for r in rows if r["speaker_id"] == speaker]
    data = out_dir(speaker) / "data"
    (data / "wavs").mkdir(parents=True, exist_ok=True)
    trim = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse,"
            "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse")
    lines, skipped, seconds = [], 0, 0.0
    for r in rows:
        text = clean_text(r["lingala"])
        src = ROOT / "dataset" / r["audio"]
        if not text or not src.exists():
            skipped += 1
            continue
        uid = Path(r["audio"]).stem
        dst = data / "wavs" / f"{uid}.wav"
        if not dst.exists():
            subprocess.run([ffmpeg(), "-nostdin", "-loglevel", "error", "-y", "-i", str(src), "-af", trim,
                            "-ac", "1", "-ar", str(RATE), "-sample_fmt", "s16", str(dst)], check=True)
        import wave
        with wave.open(str(dst)) as w:
            dur = w.getnframes() / w.getframerate()
        if dur < 0.8:
            skipped += 1
            continue
        seconds += dur
        lines.append(f"{uid}|{text}|{text}")
    (data / "metadata.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{speaker} : {len(lines)} phrases, {seconds / 60:.1f} min ({skipped} écartées) -> {data}")


def base_files():
    from huggingface_hub import hf_hub_download
    return hf_hub_download(BASE_REPO, "model_last.pth"), hf_hub_download(BASE_REPO, "config.json")


def train(speaker: str, epochs: int, batch: int, resume: bool = False, lr: float = 5e-5,
          freeze_text: Optional[bool] = None, fp16: bool = False) -> None:
    lang = lang_of(speaker)
    if freeze_text is None:   # nouvelle langue : le lecteur de texte doit apprendre ses sons
        freeze_text = lang == "ln"
    from trainer import Trainer, TrainerArgs
    from TTS.config.shared_configs import BaseDatasetConfig
    from TTS.tts.configs.vits_config import VitsConfig
    from TTS.tts.datasets import load_tts_samples
    from TTS.tts.models.vits import Vits

    ckpt, cfg_path = base_files()
    if resume:  # repart du meilleur modèle déjà affiné sur ce locuteur, au lieu de la voix Open Bible
        run = latest_run(speaker)
        saved = sorted(run.glob("checkpoint_*.pth"), key=lambda p: int(p.stem.split("_")[1]))
        ckpt = str(run / "best_model.pth" if (run / "best_model.pth").exists() else saved[-1])
        print(f"Reprise depuis {ckpt}", flush=True)
    data = out_dir(speaker) / "data"
    config = VitsConfig()
    config.load_json(cfg_path)
    config.datasets = [BaseDatasetConfig(formatter="ljspeech", path=str(data), meta_file_train="metadata.csv",
                                         language=lang)]
    config.output_path = str(out_dir(speaker))
    config.run_name = f"run-{speaker}"
    config.batch_size, config.eval_batch_size = batch, batch
    config.epochs = epochs
    config.lr_gen = config.lr_disc = lr            # affinage : pas trop fort pour ne pas tout oublier
    config.run_eval = True
    config.test_delay_epochs = 0
    config.test_sentences = [[s] for s in SENTENCES[lang]]
    # Précision complète par défaut (en fp16, quelques pas partent en NaN) ; --fp16 est ~5x plus
    # rapide sur une carte de 4 Go, et les pas en NaN sont simplement ignorés.
    config.mixed_precision = fp16
    # Le lecteur de texte (encodeur) reste celui de la voix d'origine, qui articule bien le lingala :
    # seuls le timbre, le rythme et l'accent du locuteur s'apprennent. Sans ce gel, 24 min de
    # données suffisaient à rendre la voix à moitié incompréhensible (52 % de lettres fausses).
    config.model_args.freeze_encoder = freeze_text
    # Points de sauvegarde réguliers : `check` choisit celui qui se comprend le mieux
    config.print_step, config.save_step, config.save_n_checkpoints = 25, 250, 6
    config.save_best_after = 500
    config.num_loader_workers = config.num_eval_loader_workers = 0   # Windows
    config.max_audio_len = 12 * RATE                # évite de saturer les 4 Go de VRAM
    config.max_text_len = 400                       # la config d'origine met None, refusé par coqui-tts 0.28
    config.dashboard_logger = "tensorboard"

    n = sum(1 for l in (data / "metadata.csv").read_text(encoding="utf-8").splitlines() if l.strip())
    train_samples, eval_samples = load_tts_samples(config, eval_split=True, eval_split_size=min(0.1, 8 / n))
    model = Vits(config)  # coqui-tts >= 0.25 : construit lui-même l'AudioProcessor et le tokenizer
    print(f"Affinage sur {len(train_samples)} phrases (+{len(eval_samples)} pour l'évaluation)", flush=True)
    trainer = Trainer(TrainerArgs(restore_path=ckpt), config, config.output_path, model=model,
                      train_samples=train_samples, eval_samples=eval_samples)
    trainer.fit()


def latest_run(speaker: str) -> Path:
    runs = sorted(out_dir(speaker).glob(f"run-{speaker}-*"), key=lambda p: p.stat().st_mtime)
    if not runs:
        sys.exit("Aucun entraînement trouvé : lancez d'abord « train ».")
    return runs[-1]


def sample(speaker: str) -> None:
    import numpy as np
    import torch
    from TTS.utils.synthesizer import Synthesizer
    run = latest_run(speaker)
    model = next((p for p in (run / "best_model.pth", *sorted(run.glob("checkpoint_*.pth"))) if p.exists()), None)
    if model is None:
        sys.exit(f"Pas encore de modèle sauvegardé dans {run}")
    synth = Synthesizer(tts_checkpoint=str(model), tts_config_path=str(run / "config.json"),
                        use_cuda=torch.cuda.is_available())
    dst = ROOT / "comparaison-voix"
    dst.mkdir(exist_ok=True)
    import wave
    for i, s in enumerate(SENTENCES[lang_of(speaker)], 1):
        wav = np.asarray(synth.tts(s, split_sentences=True), dtype=np.float32)
        with wave.open(str(dst / f"p{i}_florent.wav" if speaker == "florent" else dst / f"p{i}_{speaker}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(synth.output_sample_rate)
            w.writeframes((np.clip(wav, -1, 1) * 32767).astype("<i2").tobytes())
    print(f"Échantillons ({model.name}) -> {dst}")


MAX_CER = 0.12   # au-delà, la voix est jugée trop difficile à comprendre
ASR_URL = "http://127.0.0.1:8000/api/voice/transcribe"


def _asr(wav_bytes: bytes, lang: str = "ln") -> str:
    """Ce que la reconnaissance vocale d'OkapiAI (backend lancé) entend dans un WAV."""
    import urllib.request
    import uuid
    b = uuid.uuid4().hex
    head = (f'--{b}\r\nContent-Disposition: form-data; name="lang"\r\n\r\n{lang}\r\n--{b}\r\n'
            'Content-Disposition: form-data; name="audio"; filename="a.wav"\r\nContent-Type: audio/wav\r\n\r\n')
    body = head.encode() + wav_bytes + f"\r\n--{b}--\r\n".encode()
    req = urllib.request.Request(ASR_URL, body, {"Content-Type": f"multipart/form-data; boundary={b}"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r).get("transcript") or ""


def _cer(ref: str, hyp: str) -> float:
    ref, hyp = ref.replace(" ", ""), (clean_text(hyp) or "").replace(" ", "")
    d = list(range(len(hyp) + 1))
    for i, a in enumerate(ref, 1):
        prev, d[0] = d[0], i
        for j, c in enumerate(hyp, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (a != c))
    return d[-1] / len(ref)


def check(speaker: str) -> None:
    """Fait écouter chaque sauvegarde du dernier entraînement par la reconnaissance vocale et
    valide la plus récente qui se comprend bien (approved_model.pth, servie par voice_server)."""
    import io
    import wave
    import numpy as np
    import torch
    from TTS.utils.synthesizer import Synthesizer
    run = latest_run(speaker)
    cands = sorted(run.glob("checkpoint_*.pth"), key=lambda p: int(p.stem.split("_")[1]))
    scores = {}
    for ck in cands:
        synth = Synthesizer(tts_checkpoint=str(ck), tts_config_path=str(run / "config.json"),
                            use_cuda=torch.cuda.is_available())
        errs = []
        for s in SENTENCES[lang_of(speaker)] + CHECK_EXTRA[lang_of(speaker)]:
            torch.manual_seed(0)
            wav = np.asarray(synth.tts(s), dtype=np.float32)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(synth.output_sample_rate)
                w.writeframes((np.clip(wav, -1, 1) * 32767).astype("<i2").tobytes())
            errs.append(_cer(s, _asr(buf.getvalue(), lang_of(speaker))))
        scores[ck.name] = sum(errs) / len(errs)
        print(f"{ck.name:22} lettres mal comprises : {scores[ck.name]:.0%}", flush=True)
        del synth
        torch.cuda.empty_cache()
    (run / "check.json").write_text(json.dumps(scores, indent=1), encoding="utf-8")
    ok = [c for c in cands if scores[c.name] <= MAX_CER]
    if not ok:
        print(f"Aucune sauvegarde sous {MAX_CER:.0%} : la voix d'origine reste utilisée.")
        return
    best = ok[-1]  # la plus entraînée parmi celles qui se comprennent : la plus proche du locuteur
    state = torch.load(best, map_location="cpu", weights_only=False)
    torch.save({"model": state["model"], "config": state.get("config"), "step": state.get("step")},
               run / "approved_model.pth")
    print(f"Validée : {best.name} ({scores[best.name]:.0%}) -> {run / 'approved_model.pth'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["prepare", "train", "check", "sample"])
    ap.add_argument("--speaker", default="florent")
    ap.add_argument("--epochs", type=int, default=120)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--resume", action="store_true", help="repartir du meilleur modèle du dernier entraînement")
    ap.add_argument("--lr", type=float, default=5e-5, help="taux d'apprentissage (plus bas pour une reprise)")
    ap.add_argument("--no-freeze", action="store_true", help="entraîner aussi le lecteur de texte (lingala : déconseillé)")
    ap.add_argument("--max-clips", type=int, default=100000, help="prepare : nombre maximum de phrases")
    ap.add_argument("--fp16", action="store_true", help="calcul rapide en demi-précision")
    a = ap.parse_args()
    {"prepare": lambda: prepare(a.speaker, a.max_clips),
     "train": lambda: train(a.speaker, a.epochs, a.batch, a.resume, a.lr, False if a.no_freeze else None, a.fp16),
     "check": lambda: check(a.speaker),
     "sample": lambda: sample(a.speaker)}[a.step]()
