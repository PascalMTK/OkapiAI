"""Turn the French Wikipedia article "Lingala" into dataset files.

Usage: python tools/import_wikipedia.py

Inputs (downloaded from the Wikipedia API into dataset/raw/wikipedia/):
  wiki_lingala_raw.json   plain-text extract
  wiki_lingala_html.json  parsed HTML (for the tables)
Outputs (dataset/knowledge/):
  wiki_lingala_sections.jsonl  one record per section: knowledge about the language
  lexique_wikipedia.jsonl      lingala <-> francais pairs taken from the tables
  grammaire_wikipedia.jsonl    conjugation / prefix tables, one record per row

Licence: Wikipedia text is CC BY-SA 4.0 - keep the "source" field (attribution) and
share derived data under the same licence.
"""
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

DATASET = Path(__file__).resolve().parent.parent / "dataset"
KB = DATASET / "knowledge"
RAW = DATASET / "raw" / "wikipedia"
SOURCE = {"source": "https://fr.wikipedia.org/wiki/Lingala", "licence": "CC BY-SA 4.0"}


def cell(c) -> str:
    for br in c.find_all("br"):
        br.replace_with(" ")
    return re.sub(r"\s+", " ", c.get_text("")).strip()


def sections():
    text = json.loads((RAW / "wiki_lingala_raw.json").read_text(encoding="utf-8"))["query"]["pages"][0]["extract"]
    skip = {"Notes et références", "Voir aussi", "Bibliographie", "Articles connexes", "Liens externes"}
    path, out = [], []
    for block in re.split(r"^(=+ .* =+)$", text, flags=re.M):
        m = re.match(r"^(=+) (.*) =+$", block.strip())
        if m:
            level = len(m.group(1)) - 1
            path = path[:level - 1] + [m.group(2)]
            continue
        body = block.strip()
        title = path[-1] if path else "Introduction"
        if body and title not in skip and not (set(path) & skip):
            out.append({"section": " > ".join(path) or "Introduction", "texte": body, **SOURCE})
    return out


def tables():
    html = json.loads((RAW / "wiki_lingala_html.json").read_text(encoding="utf-8"))["parse"]["text"]
    soup = BeautifulSoup(html, "html.parser")
    lex, gram = [], []
    for t in soup.select("table.wikitable"):
        h = t.find_previous(["h2", "h3", "h4"])
        sec = h.get_text(strip=True) if h else ""
        rows = [[cell(c) for c in r.find_all(["th", "td"])] for r in t.find_all("tr")]
        head, body = rows[0], [r for r in rows[1:] if any(r)]
        hl = [x.lower() for x in head]

        if sec == "Valeur des graphèmes":
            # "nyama (animal), matáta (difficulté)" -> pairs
            for r in body:
                for ln, fr in re.findall(r"([^,()]+?)\s*\(([^)]+)\)", r[-1]):
                    lex.append({"lingala": ln.strip(), "francais": fr.strip(), "type": "mot",
                                "note": f"exemple de la lettre {r[0]}", **SOURCE})
        elif sec == "Exemples" and hl[:2] == ["mot", "traduction"]:
            for r in body:
                if len(r) >= 2:
                    lex.append({"lingala": r[1], "francais": r[0], "type": "mot",
                                "prononciation": r[2] if len(r) > 2 else "", **SOURCE})
        elif "traduction" in hl:
            ti = hl.index("traduction")
            ex = [i for i, x in enumerate(hl) if x.startswith("exemple") or x in ("littéraire", "parlé")]
            for r in body:
                if len(r) <= ti:
                    continue
                for i in ex:
                    if i < len(r) and r[i]:
                        lex.append({"lingala": r[i], "francais": r[ti],
                                    "type": "phrase" if " " in r[i] else "mot",
                                    "note": f"{sec}: " + ", ".join(f"{head[j]}={r[j]}" for j in range(len(r)) if j not in ex and j != ti and r[j]),
                                    **SOURCE})
        if sec not in ("Valeur des graphèmes", "Exemples"):
            for r in body:
                gram.append({"tableau": sec, "colonnes": head, "valeurs": r, **SOURCE})
    return lex, gram


def write(name, rows):
    (KB / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"{name}: {len(rows)}")


if __name__ == "__main__":
    write("wiki_lingala_sections.jsonl", sections())
    lex, gram = tables()
    write("lexique_wikipedia.jsonl", lex)
    write("grammaire_wikipedia.jsonl", gram)
