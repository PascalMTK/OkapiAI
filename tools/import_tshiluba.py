"""Importe les phrases tshiluba (ciluba) utilisées par OkapiAI.

Usage : python tools/import_tshiluba.py

Entrées (téléchargées, non versionnées) :
  dataset/sources/tshiluba/corpus_brut.txt
      tshiluba_corpus.txt de https://huggingface.co/datasets/DanMM96/Tshiluba-dataset
      (27 000 phrases : Bibles 1996/2003, chansons, textes publics ; CC BY 4.0)
  D:/okapi-data/tshiluba-voix/data/*.parquet  (facultatif)
      https://huggingface.co/datasets/abdouaziz/tshiluba : 7 800 enregistrements transcrits ;
      la licence n'est pas indiquée : seules les transcriptions (texte) sont reprises ici,
      pour le vocabulaire de l'écoute tolérante, jamais les fichiers audio.
Sortie : dataset/sources/tshiluba/phrases.jsonl  ({"text", "source", "licence"} par ligne)

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
    if VOICE.is_dir():
        import pyarrow.parquet as pq
        for f in sorted(VOICE.glob("*.parquet")):
            for t in pq.read_table(f, columns=["transcription"]).column("transcription").to_pylist():
                add(t or "", "https://huggingface.co/datasets/abdouaziz/tshiluba (transcriptions)", "non indiquée")
    with open(OUT / "phrases.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(rows)} phrases ({n_text} textes, {len(rows) - n_text} transcriptions) -> {OUT / 'phrases.jsonl'}")


if __name__ == "__main__":
    main()
