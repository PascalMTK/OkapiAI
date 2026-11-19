"""Dictionnaire lingala ↔ français construit à partir de `dataset/`.

Sources (chargées une seule fois, à la première question) :
  - dataset/sources/kaikki/kaikki.org-dictionary-Lingala.jsonl  (Wiktionnaire français, ~4 600 mots)
  - dataset/knowledge/lexique_wikipedia.jsonl                   (Wikipédia, ~115 mots et phrases)
Les traductions validées par la communauté (dataset_entrainement) restent prioritaires :
elles sont consultées par `conversation.py` avant ce dictionnaire.

Les clés sont comparées sans tons ni accents (mbɔ́tɛ = mbote, malámu = malamu).
"""
import json
import logging
import re
import threading
import unicodedata
from dataclasses import dataclass, field
from difflib import get_close_matches
from typing import Optional

from ..config import DATASET_DIR

log = logging.getLogger("okapiai.lexicon")

KAIKKI = DATASET_DIR / "sources" / "kaikki" / "kaikki.org-dictionary-Lingala.jsonl"
WIKI = DATASET_DIR / "knowledge" / "lexique_wikipedia.jsonl"

POS_FR = {"noun": "nom", "verb": "verbe", "adj": "adjectif", "adv": "adverbe", "intj": "interjection",
          "pron": "pronom", "prep": "préposition", "conj": "conjonction", "name": "nom propre",
          "num": "nombre", "phrase": "expression"}
_FORM = re.compile(r"^(infinitif|pluriel|variante orthographique|variante) de ", re.I)


def key(text: str) -> str:
    """Forme de comparaison : minuscules, sans tons/accents, ɛ→e, ɔ→o, sans ponctuation."""
    # ε (epsilon grec) apparaît à la place de ɛ dans certaines transcriptions (LRSC)
    t = (text or "").lower().replace("ɛ", "e").replace("ε", "e").replace("ɔ", "o").replace("’", "'")
    t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^\w\s'-]", " ", t).strip(" -'")
    return " ".join(t.split())


@dataclass
class Entry:
    word: str                       # orthographe d'origine (avec tons)
    pos: Optional[str] = None
    meanings: list[str] = field(default_factory=list)
    source: str = ""


class Lexicon:
    def __init__(self):
        self._lock = threading.Lock()
        self._ln: Optional[dict[str, list[Entry]]] = None   # clé lingala -> entrées
        self._fr: dict[str, list[str]] = {}                 # clé française -> mots lingala

    # ---------- chargement ----------
    def _load(self) -> None:
        with self._lock:
            if self._ln is not None:
                return
            ln: dict[str, list[Entry]] = {}
            raw: list[dict] = []
            if KAIKKI.exists():
                raw = [json.loads(line) for line in KAIKKI.read_text(encoding="utf-8").splitlines() if line.strip()]
            real = {}  # mot -> sens réels (hors "Pluriel de …"), pour résoudre les renvois
            for r in raw:
                own = [g for s in r.get("senses", []) for g in s.get("glosses", []) if not _FORM.match(g)]
                if own:
                    real.setdefault(key(r["word"]), []).extend(own)
            for r in raw:
                meanings = []
                for s in r.get("senses", []):
                    for g in s.get("glosses", []):
                        m = _FORM.match(g)
                        target = (s.get("form_of") or [{}])[0].get("word") or (g[m.end():].rstrip(". ") if m else None)
                        if m and target and real.get(key(target)):
                            meanings.append(f"{g.rstrip('.')} : {', '.join(_clean(x) for x in real[key(target)][:2])}")
                        else:
                            meanings.append(_clean(g))
                meanings = _dedupe(meanings)
                if r.get("word") and meanings:
                    ln.setdefault(key(r["word"]), []).append(
                        Entry(r["word"], r.get("pos"), meanings, "Wiktionnaire"))
            if WIKI.exists():
                for line in WIKI.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        r = json.loads(line)
                        ln.setdefault(key(r["lingala"]), []).append(
                            Entry(r["lingala"], "phrase" if r.get("type") == "phrase" else None,
                                  [_clean(r["francais"])], "Wikipédia"))
            ranked: dict[str, dict[str, int]] = {}  # clé française -> {mot lingala: rang}
            for k, entries in ln.items():
                for e in entries:
                    for mi, meaning in enumerate(e.meanings):
                        if _FORM.match(meaning):
                            continue
                        for pi, part in enumerate(re.split(r"[,;/]| ou ", meaning)):
                            pk = key(re.sub(r"\(.*?\)", "", part))
                            if pk and len(pk.split()) <= 3:
                                rank = mi * 10 + pi  # le 1er sens du mot compte le plus
                                words = ranked.setdefault(pk, {})
                                words[e.word] = min(rank, words.get(e.word, rank))
            fr = {pk: [w for w, _ in sorted(ws.items(), key=lambda x: x[1])] for pk, ws in ranked.items()}
            self._ln, self._fr = ln, fr
            log.info("Lexique lingala : %d mots, %d sens français", len(ln), len(fr))

    # ---------- recherche ----------
    def size(self) -> int:
        self._load()
        return len(self._ln)

    def lookup(self, word: str, fuzzy: bool = True) -> tuple[Optional[str], list[Entry]]:
        """Mot lingala -> (clé trouvée, entrées). Tolère une petite faute si `fuzzy`."""
        self._load()
        k = key(word)
        if k in self._ln:
            return k, self._ln[k]
        # verbe sans "ko-" (-linga), racine seule, pluriel en ba- / ma- (bandako -> ndako)
        variants = (k.lstrip("-"), "-" + k, "-" + k[2:] if k.startswith("ko") else None,
                    k[2:] if k[:2] in ("ba", "ma", "mi", "bi") else None)
        for variant in variants:
            if variant and variant in self._ln:
                return variant, self._ln[variant]
        if fuzzy and len(k) >= 4:
            close = get_close_matches(k, self._ln.keys(), n=1, cutoff=0.86)
            if close:
                return close[0], self._ln[close[0]]
        return None, []

    def describe(self, entries: list[Entry], max_items: int = 3) -> list[dict]:
        """Regroupe les entrées d'un mot : [{word, pos, sens, note, source}], sans doublons.
        « Infinitif de -línga : Aimer » devient sens="aimer", note="infinitif de -línga"."""
        out = []
        for e in entries:
            senses, notes = [], []
            for m in e.meanings:
                form = _FORM.match(m)
                if form and ":" in m:
                    head, _, rest = m.partition(":")
                    if key(head[form.end():]) != key(e.word):  # « pluriel de ndáko » sur ndáko : inutile
                        notes.append(head.strip().lower())
                    m = rest
                elif form:
                    continue
                if m.lower().startswith(("accord de", "lettre")):  # notes de grammaire trop longues
                    continue
                m = m.strip()
                senses.append(m if e.pos == "name" else ", ".join(_lower_first(p.strip()) for p in m.split(",")))
            sens = "; ".join(_dedupe(senses)[:2])
            if not sens or key(sens) in {key(o["sens"]) for o in out}:
                continue
            out.append({"word": e.word, "pos": POS_FR.get(e.pos, e.pos), "sens": sens,
                        "note": ", ".join(_dedupe(notes)) or None, "source": e.source})
            if len(out) >= max_items:
                break
        return out

    def reverse(self, french: str) -> list[str]:
        """Mot ou expression française -> mots lingala."""
        self._load()
        return self._fr.get(key(french), [])[:4]

    def examples_for(self, text: str, limit: int = 12) -> list[dict]:
        """Entrées du dictionnaire pour les mots d'un message (ancrage de l'IA)."""
        self._load()
        out, seen = [], set()
        for w in key(text).split():
            if len(w) < 3 or w in seen:
                continue
            seen.add(w)
            k, entries = self.lookup(w, fuzzy=False)
            if entries:
                e = entries[0]
                out.append({"texte": e.word, "sens": "; ".join(e.meanings[:2]) + f" ({e.source})"})
            if len(out) >= limit:
                break
        return out


def _lower_first(s: str) -> str:
    """« Aimer » -> « aimer », mais garde les sigles (« ADN »)."""
    return s[:1].lower() + s[1:] if s[:1].isupper() and not s[1:2].isupper() else s


def _clean(g: str) -> str:
    return g.strip().rstrip(".").strip()


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for i in items:
        if i and i.lower() not in seen:
            seen.add(i.lower())
            out.append(i)
    return out


lexicon = Lexicon()
