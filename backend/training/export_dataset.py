"""Exporte le dataset d'ENTRAÎNEMENT (validé par l'admin) vers des fichiers prêts à l'emploi.

Usage (depuis backend/) :
    python -m training.export_dataset --out training/export

Produit :
    traduction.jsonl  -> paires {src_lang, tgt_lang, src, tgt} (dans les deux sens)
    voix.jsonl        -> {audio, lang, text} pour entraîner un modèle de reconnaissance vocale
                         (toutes les voix des propositions approuvées, pas seulement la principale)
"""
import argparse
import json
from pathlib import Path

from sqlalchemy import select

from app.config import AUDIO_DIR
from app.database import SessionLocal
from app.models import APPROUVE, Contribution, Proposition, TrainingEntry
from app.similarity import normalize


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="training/export")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as db:
        entries = list(db.scalars(select(TrainingEntry)))
        n_pairs = 0
        with open(out / "traduction.jsonl", "w", encoding="utf-8") as f:
            for e in entries:
                for s_lang, s, t_lang, t in ((e.source_lang, e.source_text, e.target_lang, e.target_text),
                                             (e.target_lang, e.target_text, e.source_lang, e.source_text)):
                    f.write(json.dumps({"src_lang": s_lang, "tgt_lang": t_lang, "src": s, "tgt": t},
                                       ensure_ascii=False) + "\n")
                    n_pairs += 1

        n_audio = 0
        approved = {e.proposition_id: e for e in entries}
        rows = db.scalars(select(Contribution).join(Proposition)
                          .where(Proposition.status == APPROUVE, Contribution.audio_path.is_not(None)))
        with open(out / "voix.jsonl", "w", encoding="utf-8") as f:
            for c in rows:
                entry = approved.get(c.proposition_id)
                # on garde le texte prononcé par la personne s'il correspond à la version validée
                text = c.source_text if normalize(c.source_text) == entry.source_norm else entry.source_text
                f.write(json.dumps({"audio": str((AUDIO_DIR / c.audio_path).resolve()),
                                    "lang": c.source_lang, "text": text}, ensure_ascii=False) + "\n")
                n_audio += 1

    print(f"{n_pairs} paires de traduction et {n_audio} enregistrements vocaux exportés dans {out}")


if __name__ == "__main__":
    main()
