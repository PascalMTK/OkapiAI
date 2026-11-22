"""Petit glossaire tshiluba ↔ français (nombres, temps, corps, animaux, nature…).

Source : dataset/sources/tshiluba/vocab_fr.jsonl (tools/import_eklablog_lua.py). Sert à ancrer l'IA
(mots exacts à utiliser) et à répondre directement à « comment dit-on X en tshiluba ? ».
"""
import json
import re

from ..config import DATASET_DIR
from .lexicon import key

PATH = DATASET_DIR / "sources" / "tshiluba" / "vocab_fr.jsonl"
_ARTICLE = re.compile(r"^(?:le|la|les|l'|un|une|des|du|de la|de l')\s*")


def _fr_key(text: str) -> str:
    return _ARTICLE.sub("", key(text))


class VocabLua:
    def __init__(self):
        self._fr: dict[str, list[str]] = {}    # « coeur » -> ["muoyo"]
        self._lua: dict[str, str] = {}         # « muoyo » -> « coeur »
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        try:
            lines = PATH.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for line in lines:
            r = json.loads(line)
            fr = _fr_key(r["fr"])
            self._fr.setdefault(fr, [])
            for w in r["lua"]:
                if w not in self._fr[fr]:
                    self._fr[fr].append(w)
                k, prev = key(w), self._lua.get(key(w))
                if prev is None:
                    self._lua[k] = r["fr"]
                elif r["fr"] not in prev:
                    self._lua[k] = f"{prev} / {r['fr']}"

    def reverse(self, fr: str) -> list[str]:
        """Mots tshiluba pour un mot ou une expression en français."""
        self._load()
        return self._fr.get(_fr_key(fr), [])

    def meaning(self, lua: str):
        self._load()
        return self._lua.get(key(lua))

    def examples_for(self, text: str, limit: int = 10) -> list[dict]:
        """Entrées du glossaire pour les mots (français ou tshiluba) d'un message : ancrage de l'IA."""
        self._load()
        words = key(text).split()
        out, seen = [], set()
        # expressions de 1 à 3 mots (« saison des pluies », « muanda mutekete »)
        for n in (3, 2, 1):
            for i in range(len(words) - n + 1):
                g = " ".join(words[i:i + n])
                if g in seen or (n == 1 and len(g) < 3):
                    continue
                if g in self._lua:
                    out.append({"texte": g, "sens": f"{self._lua[g]} (glossaire tshiluba)"})
                elif _fr_key(g) in self._fr:
                    out.append({"texte": " / ".join(self._fr[_fr_key(g)][:3]), "sens": f"{g} (glossaire tshiluba)"})
                else:
                    continue
                seen.add(g)
                if len(out) >= limit:
                    return out
        return out


vocab_lua = VocabLua()
