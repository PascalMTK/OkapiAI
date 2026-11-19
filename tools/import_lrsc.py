"""Import the Lingala Read Speech Corpus (LRSC) from Hugging Face.

Usage: python tools/import_lrsc.py

Input : dataset/raw/lrsc/{train,validation,test}.parquet
        (https://huggingface.co/datasets/BantuLanguagesInitiative/LRSC, parquet export)
Output: dataset/sources/lrsc/
  <split>/<utterance_id>.wav   16 kHz mono read Lingala speech
  metadata.jsonl               one line per clip, same keys as dataset/clips metadata

The transcriptions are clean Lingala (with ɛ/ɔ), so needs_review is false.
There is no French translation: "francais" stays empty.
Licence: CC BY 4.0 (cite BantuLanguagesInitiative/LRSC).
"""
import json
import re
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "dataset" / "raw" / "lrsc"
OUT = ROOT / "dataset" / "sources" / "lrsc"
SOURCE = {"source": "https://huggingface.co/datasets/BantuLanguagesInitiative/LRSC", "licence": "CC BY 4.0"}
SAFE = re.compile(r"[^A-Za-z0-9_.-]")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    total, seconds = 0, 0.0
    with open(OUT / "metadata.jsonl", "w", encoding="utf-8") as meta:
        for split in ("train", "validation", "test"):
            path = RAW / f"{split}.parquet"
            if not path.exists():
                print(f"missing {path}, skipped")
                continue
            (OUT / split).mkdir(exist_ok=True)
            table = pq.ParquetFile(path)
            for batch in table.iter_batches(batch_size=64):
                for row in batch.to_pylist():
                    name = SAFE.sub("_", row["utterance_id"]) + ".wav"
                    wav = OUT / split / name
                    if not wav.exists():
                        wav.write_bytes(row["audio"]["bytes"])
                    meta.write(json.dumps({
                        "audio": wav.relative_to(ROOT / "dataset").as_posix(),
                        "utterance_id": row["utterance_id"],
                        "split": split,
                        "speaker_id": row["speaker_id"],
                        "gender": row["gender"],
                        "duration": round(row["duration_s"], 3),
                        "lingala": row["transcription"].strip(),
                        "francais": "",
                        "needs_review": False,
                        **SOURCE,
                    }, ensure_ascii=False) + "\n")
                    total += 1
                    seconds += row["duration_s"]
    print(f"{total} clips, {seconds / 3600:.2f} h -> {OUT}")


if __name__ == "__main__":
    main()
