"""Corpus de phrases en lingala correct : LRSC (Lingala Read Speech Corpus).

2 940 phrases lues par 31 locuteurs, transcrites en lingala (avec ɛ / ɔ), licence CC BY 4.0
(https://huggingface.co/datasets/BantuLanguagesInitiative/LRSC).
Elles servent :
  - de modèles de « vrai lingala » envoyés à l'IA avec chaque message (vocabulaire, tournures) ;
  - d'exemples d'usage, avec l'enregistrement du locuteur, quand on demande le sens d'un mot.
Le corpus n'a pas de traduction française.

Tshiluba : même principe avec dataset/sources/tshiluba/phrases.jsonl (tools/import_tshiluba.py,
27 000 phrases surtout bibliques, CC BY 4.0), sans enregistrements.
"""
import json
import logging
import math
import re
import threading
from collections import defaultdict
from typing import Optional

from ..config import DATASET_DIR
from .lexicon import key

log = logging.getLogger("okapiai.corpus")

LRSC_DIR = DATASET_DIR / "sources" / "lrsc"
SOURCE = "LRSC (CC BY 4.0)"
_AUDIO = re.compile(r"^(train|validation|test)/[A-Za-z0-9_.-]+\.wav$")


class Corpus:
    def __init__(self, meta=LRSC_DIR / "metadata.jsonl", field: str = "lingala", source: str = SOURCE,
                 language: str = "lingala"):
        self.meta, self.field, self.source, self.language = meta, field, source, language
        self._lock = threading.Lock()
        self._rows: Optional[list[dict]] = None
        self._index: dict[str, list[int]] = {}
        self._idf: dict[str, float] = {}

    def _load(self) -> None:
        with self._lock:
            if self._rows is not None:
                return
            rows: list[dict] = []
            meta = self.meta
            if meta.exists():
                for line in meta.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    r = json.loads(line)
                    text = (r.get(self.field) or "").strip()
                    if len(text.split()) < 3:  # trop court pour servir d'exemple
                        continue
                    audio = (r.get("audio") or "").removeprefix("sources/lrsc/")
                    rows.append({"text": text, "tokens": set(key(text).split()),
                                 "audio": audio if _AUDIO.match(audio) else None,
                                 "speaker": r.get("speaker_id")})
            index: dict[str, list[int]] = defaultdict(list)
            for i, r in enumerate(rows):
                for t in r["tokens"]:
                    index[t].append(i)
            n = max(1, len(rows))
            self._idf = {t: math.log(1 + n / len(ids)) for t, ids in index.items()}
            self._index, self._rows = dict(index), rows
            log.info("Corpus %s : %d phrases, %d mots", self.language, len(rows), len(index))

    def size(self) -> int:
        self._load()
        return len(self._rows)

    def search(self, text: str, k: int = 6) -> list[dict]:
        """Phrases du corpus qui partagent le plus de mots (rares) avec `text`."""
        self._load()
        query = {t for t in key(text).split() if t in self._index}
        if not query:
            return []
        n = len(self._rows)
        scores: dict[int, float] = defaultdict(float)
        for t in query:
            ids = self._index[t]
            if len(ids) > n * 0.08:  # mots outils (na, ya, te…) : pas discriminants
                continue
            for i in ids:
                scores[i] += self._idf[t]
        ranked = sorted(scores.items(), key=lambda x: (-x[1] / (1 + 0.04 * len(self._rows[x[0]]["tokens"])), x[0]))
        return [self._public(self._rows[i]) for i, _ in ranked[:k]]

    def example_with(self, word: str) -> Optional[dict]:
        """Une phrase courte du corpus qui contient `word` (pour montrer le mot en contexte)."""
        self._load()
        w = key(word)
        candidates = self._index.get(w) or self._index.get(w[2:] if w[:2] in ("ba", "ma") else "", [])
        if not candidates:
            return None
        # phrase la plus courte, de préférence avec son enregistrement
        best = min(candidates, key=lambda i: (self._rows[i]["audio"] is None, len(self._rows[i]["tokens"]), i))
        return self._public(self._rows[best])

    def examples_for_ai(self, text: str, k: int = 6) -> list[dict]:
        return [{"texte": r["text"], "sens": f"(phrase en {self.language} correct, {self.source})"}
                for r in self.search(text, k)]

    def audio_path(self, rel: str):
        """Chemin d'un enregistrement du corpus, ou None (nom invalide / fichier absent)."""
        if not _AUDIO.match(rel or ""):
            return None
        path = (LRSC_DIR / rel).resolve()
        return path if path.is_file() and LRSC_DIR.resolve() in path.parents else None

    def _public(self, r: dict) -> dict:
        # l'audio n'est pas versionné (git) : on ne propose l'écoute que si le fichier est là
        has_audio = bool(r["audio"]) and (LRSC_DIR / r["audio"]).is_file()
        return {"text": r["text"], "source": self.source,
                "audio_url": f"/api/corpus/audio/{r['audio']}" if has_audio else None}


corpus = Corpus()
corpus_lua = Corpus(DATASET_DIR / "sources" / "tshiluba" / "phrases.jsonl", "text",
                    "corpus DanMM96, CC BY 4.0, surtout biblique", "tshiluba")
