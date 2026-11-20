"""Écoute tolérante : comprendre un apprenant même s'il prononce mal.

La reconnaissance vocale écrit ce qu'elle entend ; un débutant dit souvent « mbote » comme
« bote », « malamu » comme « maramou », « kinshasa » comme « kinchasa »… Ici, chaque mot
inconnu est rapproché du mot lingala connu le plus proche, en ignorant les différences
typiques d'un apprenant, puis la phrase entière est rapprochée d'une phrase courante.

Vocabulaire : dictionnaire (lexicon), phrases du corpus LRSC (lues par des natifs) et
échanges de base ; un mot fréquent dans le corpus l'emporte sur un mot rare.
"""
import json
import logging
import re
import threading
from collections import Counter
from difflib import SequenceMatcher, get_close_matches
from typing import Optional

from ..config import DATASET_DIR
from .lexicon import key, lexicon

log = logging.getLogger("okapiai.hearing")

LRSC = DATASET_DIR / "sources" / "lrsc" / "metadata.jsonl"
PHRASE_CUTOFF = 0.82   # ressemblance minimale pour reconnaître une phrase courante entière


def soft(text: str) -> str:
    """Forme « d'oreille » : ce qu'un apprenant confond devient identique."""
    t = key(text)
    t = t.replace("ou", "u").replace("ch", "s").replace("sh", "s").replace("qu", "k").replace("q", "k")
    t = re.sub(r"c(?=[aou])", "k", t)
    t = t.replace("r", "l").replace("y", "i").replace("w", "u")
    t = re.sub(r"gu(?=[ie])", "g", t)             # « mingui », « mingwi » = mingi
    t = re.sub(r"[mn](?=[bdgkpstvzfj])", "", t)   # mb, nd, ng, nz, nk… : la nasale s'entend peu
    t = re.sub(r"(.)\1+", r"\1", t)                # lettres doublées
    return t


# Préfixes sujet/temps et terminaisons des verbes : « nakolia », « tolei », « alingaki »
_PREFIXES = sorted({p + t for p in ("na", "o", "a", "to", "bo", "ba", "e", "mo", "li", "ma", "bi", "")
                    for t in ("ko", "zo", "")} - {""}, key=len, reverse=True)
_SUFFIXES = ("aki", "ake", "aka", "ki", "i", "a", "e", "")


class Hearing:
    def __init__(self):
        self._lock = threading.Lock()
        self._freq: Optional[Counter] = None        # mot -> fréquence
        self._by_soft: dict[str, str] = {}          # forme d'oreille -> mot le plus fréquent
        self._phrases: list[tuple[str, str]] = []   # (forme d'oreille, phrase courante)
        self._french: set[str] = set()              # mots français : on les laisse tels quels

    def _load(self) -> None:
        with self._lock:
            if self._freq is not None:
                return
            from .basics import BASICS
            freq: Counter = Counter()
            if LRSC.exists():
                for line in LRSC.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        freq.update(key(json.loads(line).get("lingala", "")).split())
            phrases = []
            for triggers, reply, _ in BASICS.get("ln", []):
                for t in triggers:
                    freq.update({w: 50 for w in key(t).split()})   # mots de tous les jours
                    if len(t.split()) >= 2:
                        phrases.append((soft(t), key(t)))
                freq.update({w: 20 for w in key(reply).split()})
            lexicon._load()
            for k in lexicon._ln:
                if " " not in k and k.isalpha():
                    freq[k] += 1
            # Le lingala parlé mélange du français (« malade », « université ») : ces mots-là
            # ne sont pas des fautes de prononciation.
            from .lexicon import COMMON_FR
            french = {w for k in list(lexicon._fr) + list(COMMON_FR) for w in key(k).split() if len(w) > 2}
            by_soft: dict[str, str] = {}
            for w, _ in freq.most_common():             # le plus fréquent gagne
                by_soft.setdefault(soft(w), w)
            self._freq, self._by_soft, self._phrases, self._french = freq, by_soft, phrases, french - set(freq)
            log.info("Écoute tolérante : %d mots, %d phrases courantes", len(freq), len(phrases))

    def _known_verb(self, w: str) -> bool:
        """Forme conjuguée d'un verbe connu (ko + racine dans le vocabulaire ou le dictionnaire)."""
        for p in _PREFIXES:
            if not w.startswith(p) or len(w) - len(p) < 2:
                continue
            rest = w[len(p):]
            # même forme avec un autre sujet (« olei » connu -> « tolei », « nalei »)
            if len(rest) >= 3 and any(q + rest in self._freq for q in ("na", "o", "a", "to", "bo", "ba", "e")):
                return True
            for suf in _SUFFIXES:
                if suf and not rest.endswith(suf):
                    continue
                stem = rest[:len(rest) - len(suf)] if suf else rest
                if len(stem) < 2:
                    continue
                for v in ("ko" + stem + "a", "ko" + stem, "ko" + stem + "e"):
                    if v in self._freq or (len(v) > 3 and lexicon.lookup(v, fuzzy=False)[1]):
                        return True
        return False

    def _known(self, w: str) -> bool:
        return len(w) < 2 or w in self._freq or w in self._french or not w.isalpha() or self._known_verb(w)

    def _word(self, w: str) -> str:
        if self._known(w):
            return w
        s = soft(w)
        if s in self._by_soft:
            return self._by_soft[s]
        if len(s) < 4:              # trop court pour deviner sans risque
            return w
        close = get_close_matches(s, [k for k in self._by_soft if abs(len(k) - len(s)) <= 2],
                                  n=5, cutoff=0.8 if len(s) >= 6 else 0.84)
        if not close:
            return w
        # même début de mot d'abord (on entend surtout mal le milieu et la fin), puis la
        # ressemblance, puis la fréquence
        best = max(close, key=lambda c: (c[0] == s[0], round(SequenceMatcher(None, s, c).ratio(), 2),
                                         self._freq[self._by_soft[c]]))
        if best[0] != s[0]:
            return w
        return self._by_soft[best]

    def correct(self, text: str) -> dict:
        """{"text": phrase comprise, "heard": phrase entendue, "fixes": [[entendu, compris], …]}"""
        self._load()
        heard = (text or "").strip()
        words = key(heard).split()
        out, i = [], 0
        while i < len(words):
            w = words[i]
            # mot coupé en deux par la reconnaissance (« nazo lia » -> « nazolia ») : seulement
            # si l'un des morceaux n'existe pas seul
            if i + 1 < len(words) and (w + words[i + 1]) in self._freq and \
                    (w not in self._freq or words[i + 1] not in self._freq):
                out.append(w + words[i + 1])
                i += 2
                continue
            out.append(self._word(w))
            i += 1
        fixed = " ".join(out)
        # phrase courante entière (salutations, questions de base), seulement s'il reste un mot
        # incompris : une phrase faite de mots connus garde son sens (« tolei » ≠ « olei »)
        s = soft(fixed) if not all(self._known(w) for w in out) else ""
        best, score = None, 0.0
        for ps, phrase in self._phrases:
            if abs(len(ps) - len(s)) <= max(3, len(ps) // 3):
                r = SequenceMatcher(None, s, ps).ratio()
                if r > score:
                    best, score = phrase, r
        if best and score >= PHRASE_CUTOFF and best != fixed:
            fixed = best
        fixes = [[a, b] for a, b in zip(key(heard).split(), fixed.split()) if a != b] \
            if len(fixed.split()) == len(words) else ([[key(heard), fixed]] if fixed != key(heard) else [])
        return {"text": fixed if fixed != key(heard) else heard, "heard": heard, "fixes": fixes}


hearing = Hearing()
