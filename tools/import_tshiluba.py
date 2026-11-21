"""Importe les phrases tshiluba (ciluba) utilisées par OkapiAI.

Usage : python tools/import_tshiluba.py [--audio] [--transcriptions]

Entrées (téléchargées, non versionnées) :
  dataset/sources/tshiluba/corpus_brut.txt
      tshiluba_corpus.txt de https://huggingface.co/datasets/DanMM96/Tshiluba-dataset
      (27 000 phrases : Bibles 1996/2003, chansons, textes publics ; CC BY 4.0)
  D:/okapi-data/tshiluba-voix/data/*.parquet  (facultatif)
      https://huggingface.co/datasets/abdouaziz/tshiluba : 7 800 enregistrements transcrits ;
      la licence n'est pas indiquée : on n'en reprend que les clips Common Voice (CC0) avec
      --audio ; ses autres transcriptions ne sont ajoutées qu'avec --transcriptions.
Sortie : dataset/sources/tshiluba/phrases.jsonl  ({"text", "source", "licence"} par ligne)
         dataset/sources/tshiluba/audio/*.mp3 + audio.jsonl : les clips Common Voice (CC0) du corpus
         vocal, que le chat fait écouter sous ses réponses (fichiers audio non versionnés)

Attention : la majorité des phrases viennent de la Bible ; le vocabulaire de tous les jours
est donc moins présent que dans le corpus lingala (LRSC).
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dataset" / "sources" / "tshiluba"
RAW = OUT / "corpus_brut.txt"
VOICE = Path(os.getenv("OKAPI_TSHILUBA_VOIX", "D:/okapi-data/tshiluba-voix")) / "data"


def clean(line: str) -> str:
    line = re.sub(r"\s+", " ", line).strip(" \t-•*")
    return line if 2 <= len(line.split()) <= 60 and not re.search(r"https?://|\d{3,}", line) else ""


def extract_audio() -> int:
    """Clips Common Voice (CC0) du corpus vocal, lus par petits paquets (peu de mémoire)."""
    import pyarrow.parquet as pq
    dst = OUT / "audio"
    dst.mkdir(exist_ok=True)
    rows = []
    for f in sorted(VOICE.glob("*.parquet")):
        for batch in pq.ParquetFile(f).iter_batches(batch_size=16):
            for r in batch.to_pylist():
                a, text = r.get("audio") or {}, (r.get("transcription") or "").strip()
                name = str(a.get("path") or "")
                if not name.startswith("common_voice_lua_") or not text or not a.get("bytes"):
                    continue
                name = re.sub(r"[^A-Za-z0-9_.-]", "", name)
                if not (dst / name).exists():
                    (dst / name).write_bytes(a["bytes"])
                rows.append({"text": text, "audio": f"audio/{name}", "source": "Common Voice (tshiluba)", "licence": "CC0"})
    with open(OUT / "audio.jsonl", "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(rows)


def main() -> None:
    if not RAW.exists():
        sys.exit(f"Fichier absent : {RAW} (voir l'en-tête du script)")
    rows, seen = [], set()

    def add(text: str, source: str, licence: str) -> None:
        t = clean(text)
        if t and t.lower() not in seen:
            seen.add(t.lower())
            rows.append({"text": t, "source": source, "licence": licence})

    for line in RAW.read_text(encoding="utf-8").splitlines():
        add(line, "https://huggingface.co/datasets/DanMM96/Tshiluba-dataset", "CC BY 4.0")
    n_text = len(rows)
    if VOICE.is_dir() and "--transcriptions" in sys.argv:
        import pyarrow.parquet as pq
        for f in sorted(VOICE.glob("*.parquet")):
            if f.name.endswith(".part"):
                continue
            for batch in pq.ParquetFile(f).iter_batches(batch_size=256, columns=["transcription"]):
                for t in batch.column(0).to_pylist():
                    add(t or "", "https://huggingface.co/datasets/abdouaziz/tshiluba (transcriptions)", "non indiquée")
    with open(OUT / "phrases.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(rows)} phrases ({n_text} textes, {len(rows) - n_text} transcriptions) -> {OUT / 'phrases.jsonl'}")
    if VOICE.is_dir() and "--audio" in sys.argv:
        print(f"{extract_audio()} clips Common Voice -> {OUT / 'audio'}")


if __name__ == "__main__":
    main()
