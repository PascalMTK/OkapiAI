"""Vocabulaire des jeux d'apprentissage (quiz rapide, jeu de mémoire), par langue et par thème.

Ordre des sources pour une langue :
  1. traductions validées par la communauté (dataset_entrainement), avec la voix d'un locuteur ;
  2. vocabulaire de base ci-dessous (lingala vérifié avec le dictionnaire Wiktionnaire du projet ;
     tshiluba complété par le glossaire dataset/sources/tshiluba/vocab_fr.jsonl) ;
  3. swahili et kikongo : listes de départ à faire relire par des locuteurs (source affichée).
"""
import json
import random
import re

from ..config import DATASET_DIR

# (thème, [(français, mot dans la langue), ...])
_BASE: dict[str, list[tuple[str, list[tuple[str, str]]]]] = {
    "ln": [
        ("Salutations", [("bonjour", "mbote"), ("merci", "matondo"), ("merci beaucoup", "matondo mingi"),
                         ("de rien", "likambo te"), ("tu vas bien ?", "ozali malamu ?"), ("je vais bien", "nazali malamu"),
                         ("au revoir", "tikala malamu"), ("à bientôt", "tokomonana"), ("pardon", "limbisa ngai"),
                         ("oui", "ee"), ("non", "te"), ("bienvenue", "boyei malamu"), ("je t'aime", "nalingi yo"),
                         ("comment tu t'appelles ?", "kombo na yo nani ?"), ("j'ai faim", "nazali na nzala")]),
        ("Nombres", [("un", "moko"), ("deux", "mibale"), ("trois", "misato"), ("quatre", "minei"), ("cinq", "mitano"),
                     ("six", "motoba"), ("sept", "nsambo"), ("huit", "mwambe"), ("neuf", "libwa"), ("dix", "zomi")]),
        ("Famille", [("père", "tata"), ("mère", "mama"), ("enfant", "mwana"), ("frère ou sœur", "ndeko"),
                     ("homme", "mobali"), ("femme", "mwasi"), ("ami", "moninga"), ("famille", "libota"),
                     ("grand-parent", "nkoko")]),
        ("Corps", [("tête", "moto"), ("yeux", "miso"), ("oreille", "litoi"), ("nez", "zolo"), ("bouche", "monoko"),
                   ("main", "loboko"), ("pied", "lokolo"), ("cœur", "motema"), ("dent", "lino"), ("cheveux", "nsuki")]),
        ("Nourriture", [("eau", "mai"), ("nourriture", "bilei"), ("poisson", "mbisi"), ("viande", "nyama"),
                        ("pain", "mapa"), ("riz", "loso"), ("feuilles de manioc", "pondu"), ("sel", "mongwa"),
                        ("banane plantain", "makemba")]),
        ("Animaux", [("chien", "mbwa"), ("chat", "pusu"), ("poule", "nsoso"), ("chèvre", "ntaba"), ("vache", "ngombe"),
                     ("léopard", "nkoi"), ("éléphant", "nzoku"), ("serpent", "nyoka"), ("crocodile", "ngando"),
                     ("oiseau", "ndeke")]),
        ("Lieux et choses", [("maison", "ndako"), ("marché", "zando"), ("école", "kelasi"), ("voiture", "motuka"),
                             ("route", "nzela"), ("village", "mboka"), ("argent", "mbongo"), ("rivière", "ebale"),
                             ("hôpital", "lopitalo"), ("travail", "mosala")]),
        ("Temps", [("aujourd'hui", "lelo"), ("demain", "lobi"), ("maintenant", "sikoyo"), ("nuit", "butu"),
                   ("soleil", "moi"), ("pluie", "mbula"), ("lune", "sanza")]),
        ("Verbes", [("manger", "kolia"), ("boire", "komela"), ("dormir", "kolala"), ("parler", "koloba"),
                    ("aller", "kokende"), ("venir", "koya"), ("aimer", "kolinga"), ("lire", "kotanga"),
                    ("écrire", "kokoma"), ("savoir", "koyeba"), ("voir", "komona"), ("entendre", "koyoka"),
                    ("acheter", "kosomba"), ("vendre", "koteka"), ("apprendre", "koyekola")]),
    ],
    "sw": [
        ("Salutations", [("bonjour", "jambo"), ("comment vas-tu ?", "habari yako ?"), ("bien", "nzuri"),
                         ("merci", "asante"), ("merci beaucoup", "asante sana"), ("bienvenue", "karibu"),
                         ("oui", "ndiyo"), ("non", "hapana"), ("pardon", "samahani"), ("au revoir", "kwaheri"),
                         ("à bientôt", "tutaonana"), ("comment tu t'appelles ?", "jina lako nani ?"),
                         ("j'ai faim", "nina njaa"), ("je t'aime", "nakupenda")]),
        ("Nombres", [("un", "moja"), ("deux", "mbili"), ("trois", "tatu"), ("quatre", "nne"), ("cinq", "tano"),
                     ("six", "sita"), ("sept", "saba"), ("huit", "nane"), ("neuf", "tisa"), ("dix", "kumi")]),
        ("Famille", [("père", "baba"), ("mère", "mama"), ("enfant", "mtoto"), ("frère", "kaka"), ("sœur", "dada"),
                     ("grand-mère", "bibi"), ("grand-père", "babu"), ("ami", "rafiki"), ("homme", "mwanaume"),
                     ("femme", "mwanamke")]),
        ("Corps", [("tête", "kichwa"), ("œil", "jicho"), ("oreille", "sikio"), ("nez", "pua"), ("bouche", "mdomo"),
                   ("main", "mkono"), ("pied", "mguu"), ("cœur", "moyo"), ("dents", "meno"), ("cheveux", "nywele")]),
        ("Nourriture", [("eau", "maji"), ("nourriture", "chakula"), ("poisson", "samaki"), ("viande", "nyama"),
                        ("pain", "mkate"), ("riz cuit", "wali"), ("sel", "chumvi"), ("lait", "maziwa"),
                        ("banane", "ndizi")]),
        ("Animaux", [("chien", "mbwa"), ("chat", "paka"), ("poule", "kuku"), ("chèvre", "mbuzi"), ("vache", "ng'ombe"),
                     ("lion", "simba"), ("éléphant", "tembo"), ("serpent", "nyoka"), ("léopard", "chui"),
                     ("oiseau", "ndege")]),
        ("Lieux et choses", [("maison", "nyumba"), ("marché", "soko"), ("école", "shule"), ("voiture", "gari"),
                             ("route", "njia"), ("village", "kijiji"), ("argent", "pesa"), ("travail", "kazi"),
                             ("livre", "kitabu"), ("hôpital", "hospitali")]),
        ("Couleurs", [("blanc", "nyeupe"), ("noir", "nyeusi"), ("rouge", "nyekundu"), ("vert", "kijani"),
                      ("jaune", "njano")]),
        ("Temps", [("aujourd'hui", "leo"), ("demain", "kesho"), ("hier", "jana"), ("nuit", "usiku"),
                   ("matin", "asubuhi"), ("pluie", "mvua"), ("soleil", "jua")]),
        ("Verbes", [("manger", "kula"), ("boire", "kunywa"), ("dormir", "kulala"), ("parler", "kusema"),
                    ("aller", "kwenda"), ("venir", "kuja"), ("aimer", "kupenda"), ("lire", "kusoma"),
                    ("écrire", "kuandika"), ("savoir", "kujua"), ("voir", "kuona"), ("entendre", "kusikia"),
                    ("acheter", "kununua"), ("vendre", "kuuza")]),
    ],
    "kg": [
        ("Salutations", [("bonjour", "mbote"), ("tu vas bien ?", "nge ke mbote ?"), ("je vais bien", "mono ke mbote"),
                         ("merci", "matondo"), ("oui", "ee"), ("non", "ve"), ("au revoir", "kwenda mbote"),
                         ("comment tu t'appelles ?", "nkumbu na nge nani ?"), ("j'ai faim", "mono ke na nzala")]),
        ("Nombres", [("un", "mosi"), ("deux", "zole"), ("trois", "tatu"), ("quatre", "iya"), ("cinq", "tanu"),
                     ("six", "sambanu"), ("sept", "nsambwadi"), ("huit", "nana"), ("neuf", "uvwa"), ("dix", "kumi")]),
        ("Famille", [("père", "tata"), ("mère", "mama"), ("enfant", "mwana"), ("frère ou sœur", "mpangi"),
                     ("grand-parent", "nkaka")]),
        ("Corps", [("tête", "ntu"), ("yeux", "meso"), ("oreille", "kutu"), ("bouche", "munoko"), ("main", "diboko"),
                   ("pied", "kulu"), ("cœur", "ntima"), ("dents", "meno")]),
        ("Vie de tous les jours", [("maison", "nzo"), ("marché", "zandu"), ("eau", "maza"), ("nourriture", "madia"),
                                   ("chien", "mbwa"), ("poule", "nsusu"), ("vache", "ngombe"), ("serpent", "nyoka")]),
        ("Verbes", [("manger", "kudia"), ("boire", "kunwa"), ("parler", "kutuba"), ("aller", "kwenda"),
                    ("aimer", "kuzola"), ("voir", "kumona"), ("acheter", "kusumba")]),
    ],
    "lua": [
        ("Salutations", [("bonjour", "moyo"), ("bonjour (à toi)", "moyo webe"), ("bonjour (à vous)", "moyo wenu"),
                         ("tu vas bien ?", "udi muimpe ?"), ("je vais bien", "ndi muimpe"), ("merci", "tuasakidila"),
                         ("merci beaucoup", "tuasakidila bikole"), ("de rien", "kakuena bualu"), ("oui", "eyowa"),
                         ("au revoir", "shala bimpe"), ("à bientôt", "tuamonangana"), ("j'ai faim", "ndi ne nzala"),
                         ("comment tu t'appelles ?", "dîna diebe nganyi ?"), ("aujourd'hui", "lelu")]),
    ],
}

SOURCES = {
    "ln": "Vocabulaire de base (vérifié avec le Wiktionnaire)",
    "sw": "Vocabulaire de base OkapiAI (à faire relire par un locuteur)",
    "kg": "Vocabulaire de base OkapiAI (à faire relire par un locuteur)",
    "lua": "Vocabulaire de base OkapiAI",
}
LUA_GLOSSARY = DATASET_DIR / "sources" / "tshiluba" / "vocab_fr.jsonl"
_NUM_FR = {"1": "un", "2": "deux", "3": "trois", "4": "quatre", "5": "cinq", "6": "six", "7": "sept", "8": "huit",
           "9": "neuf", "10": "dix", "20": "vingt", "100": "cent", "1000": "mille"}
_THEME_LUA = {"le corps humain": "Corps", "les animaux": "Animaux", "la nature": "Nature", "les nombres": "Nombres",
              "la division du temps": "Temps", "les jours de la semaine": "Temps", "les mois de l'annee": "Temps",
              "les couleurs": "Couleurs", "les points cardinaux": "Nature", "les saisons": "Temps"}

_cache: dict[str, list[dict]] = {}


def _lua_glossary() -> list[dict]:
    out = []
    try:
        lines = LUA_GLOSSARY.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        r = json.loads(line)
        fr = r["fr"].strip()
        if fr.isdigit():
            if fr not in _NUM_FR:
                continue        # 13, 60… : on garde les nombres simples
            fr = _NUM_FR[fr]
        words = [w for w in r["lua"] if not w.startswith("-")]   # « -a kalabi » : forme d'adjectif
        if not words:
            continue
        word = re.sub(r"\s*\(.*?\)", "", words[0]).strip()
        out.append({"fr": fr, "word": word, "theme": _THEME_LUA.get(r.get("theme", ""), "Divers"),
                    "source": "Glossaire tshiluba (desmotsetdeslangues)"})
    return out


def base_items(lang: str) -> list[dict]:
    """Toutes les paires (français, mot) de base d'une langue, sans doublon."""
    if lang not in _cache:
        items = [{"fr": fr, "word": w, "theme": theme, "source": SOURCES.get(lang, "")}
                 for theme, pairs in _BASE.get(lang, []) for fr, w in pairs]
        if lang == "lua":
            items += _lua_glossary()
        seen, uniq = set(), []
        for it in items:
            k = (it["fr"].lower(), it["word"].lower())
            if k not in seen and it["fr"] and it["word"]:
                seen.add(k)
                uniq.append(it)
        _cache[lang] = uniq
    return _cache[lang]


def pick(items: list[dict], n: int, rng: random.Random) -> list[dict]:
    """n paires au hasard, sans deux fois le même mot ni le même sens."""
    pool = items[:]
    rng.shuffle(pool)
    seen_fr, seen_w, out = set(), set(), []
    for it in pool:
        a, b = it["fr"].lower(), it["word"].lower()
        if a in seen_fr or b in seen_w:
            continue
        seen_fr.add(a); seen_w.add(b); out.append(it)
        if len(out) == n:
            break
    return out
