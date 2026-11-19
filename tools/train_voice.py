"""Affine la voix lingala VITS (Open Bible) sur un locuteur du corpus LRSC.

Usage (avec un Python où `coqui-tts` est installé, voir le README) :
  python tools/train_voice.py prepare --speaker florent     # prépare les données
  python tools/train_voice.py train   --speaker florent     # affinage (plusieurs heures, GPU conseillé)
  python tools/train_voice.py sample  --speaker florent     # génère des phrases de test

Données  : dataset/sources/lrsc/  (CC BY 4.0) -> backend/models/voix-<speaker>/data/
           wavs/<id>.wav (22 050 Hz mono, silences coupés) + metadata.csv (format LJSpeech)
Départ   : multilingual-tts/VITS-OpenBible-Lingala (CC BY-SA 4.0)
Résultat : backend/models/voix-<speaker>/run-*/best_model.pth (+ config.json)
"""
import argparse
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

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


def prepare(speaker: str) -> None:
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


def train(speaker: str, epochs: int, batch: int) -> None:
    from trainer import Trainer, TrainerArgs
    from TTS.config.shared_configs import BaseDatasetConfig
    from TTS.tts.configs.vits_config import VitsConfig
    from TTS.tts.datasets import load_tts_samples
    from TTS.tts.models.vits import Vits

    ckpt, cfg_path = base_files()
    data = out_dir(speaker) / "data"
    config = VitsConfig()
    config.load_json(cfg_path)
    config.datasets = [BaseDatasetConfig(formatter="ljspeech", path=str(data), meta_file_train="metadata.csv",
                                         language="ln")]
    config.output_path = str(out_dir(speaker))
    config.run_name = f"run-{speaker}"
    config.batch_size, config.eval_batch_size = batch, batch
    config.epochs = epochs
    config.lr_gen = config.lr_disc = 5e-5          # affinage : pas trop fort pour ne pas tout oublier
    config.run_eval = True
    config.test_delay_epochs = 0
    config.test_sentences = [[s] for s in TEST_SENTENCES]
    config.print_step, config.save_step, config.save_n_checkpoints = 25, 1000, 1
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
    for i, s in enumerate(TEST_SENTENCES, 1):
        wav = np.asarray(synth.tts(s, split_sentences=True), dtype=np.float32)
        with wave.open(str(dst / f"p{i}_florent.wav" if speaker == "florent" else dst / f"p{i}_{speaker}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(synth.output_sample_rate)
            w.writeframes((np.clip(wav, -1, 1) * 32767).astype("<i2").tobytes())
    print(f"Échantillons ({model.name}) -> {dst}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["prepare", "train", "sample"])
    ap.add_argument("--speaker", default="florent")
    ap.add_argument("--epochs", type=int, default=120)
    ap.add_argument("--batch", type=int, default=8)
    a = ap.parse_args()
    {"prepare": lambda: prepare(a.speaker), "train": lambda: train(a.speaker, a.epochs, a.batch),
     "sample": lambda: sample(a.speaker)}[a.step]()
