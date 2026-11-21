"""Mots français dans une réponse en langue nationale, dits par LA MÊME voix.

Les voix des langues nationales n'ont appris que des sons bantous (a e i o u, pas de « u » ni de
nasales françaises) : on réécrit les mots français comme ils se prononcent, à la manière d'un locuteur
de Kinshasa, puis la voix de la conversation dit toute la phrase d'un seul trait (pas de 2e voix).
Les mots français sont ceux que l'IA balise (<fr>…</fr>) et ceux reconnus automatiquement
(vocabulaire français du dictionnaire, lettres propres au français comme è, ç, à).
"""
import re

# « bonjour » -> « bojur », « maison » -> « mezo », « bureau » -> « biro »
_FR_RULES = [
    # consonnes qui dépendent de la voyelle suivante : avant de toucher aux voyelles
    (r"aujourd'hui", "ojUrdwi"), (r"tion", "Sion"), (r"ch", "sh"), (r"gn", "ny"), (r"qu", "k"), (r"ph", "f"), (r"th", "t"), (r"ç", "s"),
    (r"c(?=[eiyéèêë])", "s"), (r"gu(?=[eiyéèêë])", "g"), (r"g(?=[eiyéèêë])", "j"), (r"c", "k"),
    (r"(?<=[aeiouyéèêàâôî])s(?=[aeiouyéèêàâôî])", "z"),
    # « -er / -ez / -et » -> « é » ; consonne finale muette (« petit » -> « peti »), PUIS « e » muet
    # (« mode » -> « mod », « grandes » -> « grand » : la consonne devant le « e » se prononce)
    (r"(?<=\w\w)(?:er|ez|et)\b", "é"), (r"(?<=\w\w)(?:t|d|p|s|z|x)\b", ""), (r"(?<=\w\w)(?:es|e)\b", ""),
    # voyelles (U = « ou », mis de côté pour que le « u » français devienne « i »)
    (r"eau", "o"), (r"au", "o"), (r"o[uùû]", "U"), (r"oi", "wa"), (r"oy", "way"), (r"[uU]i", "wi"),
    (r"(?<![nN])y", "i"),
    (r"(?<=[aeiouU])ill", "y"), (r"ill", "iy"),
    (r"(?:ai|ei)[nm](?![aeiouynm])", "e"), (r"[iy][nm](?![aeiouynm])", "e"), (r"un\b", "e"),
    (r"[ae][nm](?![aeiouynm])", "a"), (r"o[nm](?![aeiouynm])", "o"),
    (r"(?:ai|ei|è|ê|ë|é)", "e"), (r"[eœ]u", "e"), (r"œ", "e"),
    (r"[uùû]", "i"), (r"U", "u"),  # « bureau » -> « biro », « bonjour » -> « bojur »
    (r"x", "ks"), (r"\bh", ""), (r"(?<![s])h", ""), (r"'", ""), (r"S", "s"),
    (r"([bdfgklmnprstvz])\1", r"\1"), (r"[àâ]", "a"), (r"[îï]", "i"), (r"ô", "o"),
]


def french_for_voice(text: str) -> str:
    t = text.lower().replace("’", "'")
    t = re.sub(r"\b([ldjmtsnc]|qu)'", r"\1e ", t)     # l'école -> le ecole
    for pat, rep in _FR_RULES:
        t = re.sub(pat, rep, t)
    return t


_TAG = re.compile(r"<(fr|ln|sw|kg|lua)>(.*?)</\1>", re.S | re.I)
_ANY_TAG = re.compile(r"</?(?:fr|ln|sw|kg|lua)>", re.I)
_FRENCH_LETTERS = re.compile(r"[èêëçàâùûîïôœ]")
_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")


def for_national_voice(text: str, is_french=None) -> str:
    """Texte prêt pour la voix d'une langue nationale : mots français (balisés ou reconnus par
    `is_french(mot)`) réécrits comme ils se prononcent, balises retirées."""
    def word(m):
        w = m.group(0)
        if _FRENCH_LETTERS.search(w.lower()):
            return french_for_voice(w)
        # noms propres (« Kinshasa », « Matadi ») : laissés tels quels
        if is_french is not None and len(w) > 2 and not w[:1].isupper() and is_french(w):
            return french_for_voice(w)
        return w

    out, pos = [], 0
    for m in _TAG.finditer(text or ""):   # les morceaux balisés <fr> ne sont réécrits qu'une fois
        out.append(_WORD.sub(word, _ANY_TAG.sub("", text[pos:m.start()])))
        out.append(french_for_voice(m.group(2)) if m.group(1).lower() == "fr" else m.group(2))
        pos = m.end()
    out.append(_WORD.sub(word, _ANY_TAG.sub("", (text or "")[pos:])))
    return "".join(out)
