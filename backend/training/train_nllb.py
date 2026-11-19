"""Fine-tuning de NLLB-200 sur le dataset d'entraînement OkapiAI.

NLLB-200 (Meta) connaît déjà lingala (lin_Latn), swahili (swh_Latn), kikongo (kon_Latn)
et tshiluba (lua_Latn) : on l'adapte avec les données validées par la communauté.

Usage (depuis backend/, GPU recommandé) :
    pip install -r training/requirements.txt
    python -m training.export_dataset --out training/export
    python -m training.train_nllb --data training/export/traduction.jsonl --epochs 5

Le modèle est enregistré dans backend/models/okapi-nllb ; l'API l'utilise
automatiquement au prochain démarrage.
"""
import argparse
import random

from app.config import MODEL_DIR, NLLB_CODES


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="training/export/traduction.jsonl")
    ap.add_argument("--base", default="facebook/nllb-200-distilled-600M")
    ap.add_argument("--out", default=str(MODEL_DIR))
    ap.add_argument("--epochs", type=int, default=5)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--lr", type=float, default=5e-5)
    args = ap.parse_args()

    import torch
    from datasets import load_dataset
    from transformers import (AutoModelForSeq2SeqLM, AutoTokenizer, DataCollatorForSeq2Seq,
                              Seq2SeqTrainer, Seq2SeqTrainingArguments)

    tok = AutoTokenizer.from_pretrained(args.base)
    model = AutoModelForSeq2SeqLM.from_pretrained(args.base)

    ds = load_dataset("json", data_files=args.data)["train"]
    ds = ds.filter(lambda r: r["src_lang"] in NLLB_CODES and r["tgt_lang"] in NLLB_CODES)
    if len(ds) < 10:
        raise SystemExit(f"Seulement {len(ds)} paires : validez plus de données avant d'entraîner.")
    split = ds.train_test_split(test_size=0.1, seed=42)

    def encode(row):
        tok.src_lang = NLLB_CODES[row["src_lang"]]
        tok.tgt_lang = NLLB_CODES[row["tgt_lang"]]
        return tok(row["src"], text_target=row["tgt"], max_length=256, truncation=True)

    # encodage ligne par ligne car la langue change à chaque exemple
    train = split["train"].map(encode, remove_columns=split["train"].column_names)
    evals = split["test"].map(encode, remove_columns=split["test"].column_names)

    training_args = Seq2SeqTrainingArguments(
        output_dir=args.out + "-checkpoints",
        per_device_train_batch_size=args.batch,
        per_device_eval_batch_size=args.batch,
        learning_rate=args.lr,
        num_train_epochs=args.epochs,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=2,
        load_best_model_at_end=True,
        fp16=torch.cuda.is_available(),
        report_to=[],
        seed=random.randint(0, 10_000),
    )
    trainer = Seq2SeqTrainer(
        model=model, args=training_args, train_dataset=train, eval_dataset=evals,
        data_collator=DataCollatorForSeq2Seq(tok, model=model), processing_class=tok,
    )
    trainer.train()
    trainer.save_model(args.out)
    tok.save_pretrained(args.out)
    print(f"Modèle enregistré dans {args.out}")


if __name__ == "__main__":
    main()
