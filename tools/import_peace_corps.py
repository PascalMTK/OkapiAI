"""Extract Lingala sentences and Q/A dialogues from the Peace Corps "Livre du formateur".

Usage: python tools/import_peace_corps.py

Input : dataset/sources/peace_corps/livre_formateur.pdf (1986 scan, OCR text layer)
Output: dataset/sources/peace_corps/
  phrases_ln.jsonl   every Lingala line found: {page, lecon, texte, role, qualite}
  dialogues_qa.jsonl question -> answer pairs ("- question" then "* answer" in the book)

The page layout is two columns: French instructions for the trainer on the left,
Lingala on the right. Each line is split on wide gaps and every segment is classed
as Lingala when most of its words are not French. OCR errors remain (qualite < 1 =
suspicious characters): review before training.
Licence: U.S. Peace Corps publication (U.S. government work).
"""
import json
import re
import subprocess
import sys
from pathlib import Path

from spellchecker import SpellChecker

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "dataset" / "sources" / "peace_corps"
PDF = SRC / "livre_formateur.pdf"
SOURCE = {"source": "Peace Corps, Lingala - Livre du formateur (1986)", "licence": "U.S. government work"}

FR = SpellChecker(language="fr")
WORD = re.compile(r"[A-Za-zÀ-ÿɛɔƐƆ']+")
# common Lingala words that also exist in the French dictionary
LN_HINT = {"na", "ya", "eza", "aza", "moto", "mama", "tata", "nga", "yo", "ye", "biso", "bino", "bango",
           "pe", "te", "malamu", "mbote", "sango", "nini", "nani", "wapi", "kombo", "oyo", "wana", "mboka",
           "ndako", "bana", "mai", "lisusu", "mingi", "moke", "monene", "kuna", "awa", "ee", "to"}
FR_HINT = {"le", "la", "les", "de", "des", "du", "et", "un", "une", "formateur", "stagiaire", "stagiaires",
           "verification", "pratique", "identification", "sens", "dit", "pose", "question", "repond", "repete"}


def pages():
    for p in range(1, 400):
        r = subprocess.run(["pdftotext", "-layout", "-f", str(p), "-l", str(p), str(PDF), "-"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            break
        yield p, r.stdout


def lingala_score(seg: str) -> float:
    words = [w.lower() for w in WORD.findall(seg)]
    if not words:
        return 0.0
    ln = 0
    for w in words:
        if w in FR_HINT:
            continue
        if w in LN_HINT or (len(w) > 2 and not FR.known([w])):
            ln += 1
    return ln / len(words)


def quality(seg: str) -> float:
    """share of characters that look like normal text (OCR junk lowers it)."""
    ok = sum(c.isalpha() or c in " '-,.?!()" for c in seg)
    return round(ok / max(1, len(seg)), 2)


def extract():
    phrases, lecon = [], ""
    for p, text in pages():
        m = re.search(r"\bL\.\s*([IVXL]+)\b", text)
        if m:
            lecon = m.group(1)
        cur = None
        for line in text.splitlines():
            for seg in re.split(r"\s{3,}", line.strip()):
                seg = seg.strip()
                if len(seg) < 3 or "livelingua" in seg.lower():
                    continue
                role = "question" if seg.startswith("-") else "reponse" if seg.startswith("*") else None
                body = seg.lstrip("-* ").strip()
                if lingala_score(body) < 0.6 or len(WORD.findall(body)) < 1:
                    continue
                # continuation line of the previous sentence (no marker, previous didn't end)
                if role is None and cur and not re.search(r"[.?!]$", cur["texte"]):
                    cur["texte"] += " " + body
                    cur["qualite"] = quality(cur["texte"])
                    continue
                cur = {"page": p, "lecon": lecon, "texte": body, "role": role or "phrase",
                       "qualite": quality(body), **SOURCE}
                phrases.append(cur)
        print(f"\rpage {p}", end="", file=sys.stderr)
    print(file=sys.stderr)
    return phrases


def dialogues(phrases):
    qa = []
    for a, b in zip(phrases, phrases[1:]):
        if a["role"] == "question" and b["role"] == "reponse" and a["page"] == b["page"]:
            qa.append({"page": a["page"], "lecon": a["lecon"], "question": a["texte"], "reponse": b["texte"],
                       "qualite": min(a["qualite"], b["qualite"]), **SOURCE})
    return qa


def write(name, rows):
    (SRC / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"{name}: {len(rows)}")


if __name__ == "__main__":
    ph = extract()
    write("phrases_ln.jsonl", ph)
    write("dialogues_qa.jsonl", dialogues(ph))
