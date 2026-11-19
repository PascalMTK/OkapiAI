"""Import the MALOBA French -> Lingala corpus (Congo Digital Services) into the dataset.

Prerequisites (gated dataset):
  1. accept the conditions on
     https://huggingface.co/datasets/Congo-digital-service/maloba-llm-alpaca-harmonise
  2. huggingface-cli login     (or: python -m huggingface_hub.commands.huggingface_cli login)

Usage: python tools/import_maloba.py

Output: dataset/sources/maloba/
  trd.jsonl       399 human translations (dans_test_v1 = true -> 79 held-out test rows)
  h2.jsonl        4,874 pairs (trd + post-edited / hand-typed questions)
  reponses.jsonl  4,777 monolingual Lingala answers
  ATTRIBUTION.md  attribution required by NOODL-1.0

Licence NOODL-1.0: royalty-free only for users in developing countries; high-income
or commercial users must agree benefit sharing with CDS before use. Redistribution is
restricted (s. 3.2.2): this folder is git-ignored, do not publish it.
"""
import json
from pathlib import Path

from datasets import load_dataset

REPO = "Congo-digital-service/maloba-llm-alpaca-harmonise"
# revisions documented in the dataset card, pinned for reproducibility
REVISIONS = {"trd": "c43dc00e0a2d8708fc185483e840829c16dfe695",
             "h2": "c0457f8e43254d868b797052c9feef44049401e9",
             "reponses": "abd5b38bd4c46ae0182207cc4513ff2e6cd94f5d"}
OUT = Path(__file__).resolve().parent.parent / "dataset" / "sources" / "maloba"
ATTRIBUTION = """MALOBA project: Lingala data created by Congo Digital Services (CDS SARL,
https://www.congo-digital.com/) and the MALOBA community of annotators, with UNDP Republic
of Congo (language digitalisation initiative). Licensed under NOODL-1.0.
Source: https://huggingface.co/datasets/Congo-digital-service/maloba-llm-alpaca-harmonise
Licence: https://licensingafricandatasets.com/nwulite-obodo-license
Modified: converted to JSON Lines for the Okapi dataset; content unchanged.
"""


def default(o):
    return o.tolist() if hasattr(o, "tolist") else str(o)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ATTRIBUTION.md").write_text(ATTRIBUTION, encoding="utf-8")
    for cfg, rev in REVISIONS.items():
        ds = load_dataset(REPO, cfg, split="train", revision=rev)
        with open(OUT / f"{cfg}.jsonl", "w", encoding="utf-8") as f:
            for row in ds:
                f.write(json.dumps(row, ensure_ascii=False, default=default) + "\n")
        print(f"{cfg}: {len(ds)} rows, columns {ds.column_names}")
