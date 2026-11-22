"""Vocabulaire tshiluba ↔ français du blog « Des mots et des langues » (Patsou, 2015).

  python tools/import_eklablog_lua.py <page.html>

La page (https://desmotsetdeslangues.eklablog.com/tshiluba-a114499364) est téléchargée à la main ;
elle n'indique pas de licence : usage personnel du projet, ne pas redistribuer le fichier.
Sortie : dataset/sources/tshiluba/vocab_fr.jsonl  ({"fr", "lua": [...], "theme", "source"} par ligne)
"""
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dataset" / "sources" / "tshiluba" / "vocab_fr.jsonl"
URL = "https://desmotsetdeslangues.eklablog.com/tshiluba-a114499364"
SKIP = {"TSHILUBA", "ALPHABET TSHILUBA"}


def text_of(page: str) -> str:
    start = page.find("LES NOMBRES")
    body = page[start:]
    body = re.sub(r"<(?:br|/p|/tr|/li|/div|/h\d)[^>]*>", "\n", body)
    body = re.sub(r"<[^>]+>", " ", body)
    return html.unescape(body).replace("\xa0", " ").replace("՚", "'")


def main(path: str) -> None:
    lines = text_of(Path(path).read_text(encoding="utf-8")).splitlines()
    rows, theme = [], "nombres"
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith(("Remarque", "Vous aimerez", "Tags", "Partager")):
            if line.startswith(("Vous aimerez", "Tags", "Partager")):
                break
            continue
        if line.isupper() and len(line) > 3:
            if line not in SKIP:
                theme = line.lower()
            continue
        parts = re.split(r"\s{2,}|\t", line, maxsplit=1)
        if len(parts) != 2:
            continue
        fr, lua = parts[0].strip(), parts[1].strip()
        if re.fullmatch(r"\d+", fr):          # nombres : « 7   muanda mutekete »
            fr = fr
        lua_forms = [w.strip(" .;") for w in re.split(r",|\bou\b", lua) if w.strip(" .;")]
        if fr and lua_forms and len(fr) < 40:
            rows.append({"fr": fr, "lua": lua_forms, "theme": theme, "source": URL,
                         "licence": "non précisée (blog, usage personnel)"})
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    themes = {}
    for r in rows:
        themes[r["theme"]] = themes.get(r["theme"], 0) + 1
    print(f"{len(rows)} entrées -> {OUT}")
    print(themes)


if __name__ == "__main__":
    main(sys.argv[1])
