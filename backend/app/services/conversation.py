"""Converser avec le système en langue nationale.

Ordre :
  0. Question sur le sens d'un mot (« que veut dire ndako ? », « ndako elingi koloba nini ? »,
     « comment dit-on maison en lingala ? ») : traductions validées, puis dictionnaire
     (Wiktionnaire / Wikipédia), puis IA. La réponse est donnée dans la langue nationale
     avec sa traduction française.
  1. Dialogue validé par la communauté (dataset_entrainement, type "dialogue").
  2. Échanges de base intégrés (salutations, présentation, remerciements…).
  3. IA (Claude), ancrée sur les exemples validés et le dictionnaire.
  4. Sinon : le bot demande à l'utilisateur de lui apprendre une réponse.
Chaque réponse peut être corrigée par l'utilisateur -> nouvelle contribution "dialogue"
qui suivra la règle des 10 personnes + validation admin.
"""
import re
import unicodedata
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import LANGUAGES, LOOKUP_THRESHOLD
from ..models import DIALOGUE, TRADUCTION, TrainingEntry
from ..similarity import normalize, similarity
from . import translator
from .basics import basic_reply
from .corpus import corpus, corpus_lua
from .vocab_lua import vocab_lua
from .lexicon import COMMON_FR, key, lexicon
from .llm import claude_chat

MAX_EXAMPLES = 25

# ---------- Questions « que veut dire … ? » ----------
_T = r"(?P<t>[\w' -]{1,60}?)"
_NATL = r"(?:lingala|kiswahili|swahili|kikongo|tshiluba|ciluba)"
_MEANING = [re.compile(p) for p in (
    rf"^(?:que|qu'est ce que|qu est ce que|qu'est-ce que|ca|sa)?\s*(?:veut dire|veux dire|signifie)\s+{_T}$",
    rf"^(?:que|qu'est ce que|qu est ce que|qu'est-ce que)\s+{_T}\s+(?:veut dire|signifie)$",
    rf"^{_T}\s+(?:veut dire|signifie|ca veut dire)\s+quoi$",
    rf"^(?:c'est quoi|c est quoi|cest quoi)\s+{_T}$",
    rf"^(?:quel est le sens|quelle est la signification|quelle est la definition|la signification|le sens|"
    rf"la definition|signification|sens|definition|explique|explique moi|expliques moi)\s+(?:de|du|des|d')\s*{_T}$",
    rf"^{_T}\s+(?:elingi koloba|elakisi|elimboli|ezali|lilakisi)\s+nini$",
    rf"^(?:ndimbola|limbola|ndimbola ya|limbola ya|limbola ngai)\s+(?:ya\s+)?{_T}$",
    rf"^(?:maana ya|nini maana ya)\s+{_T}$",
    rf"^{_T}\s+(?:maana yake nini|ina maana gani|maana yake ni nini)$",
    rf"^(?:what does|what is the meaning of|meaning of)\s+{_T}(?:\s+mean)?$",
)]
_REVERSE = [re.compile(p) for p in (
    rf"^(?:comment|comment est ce qu')\s*(?:on dit|dit on|dit-on|dire|tu dis|dis tu|dis-tu|se dit|on peut dire)\s+{_T}"
    rf"(?:\s+en\s+(?:lingala|swahili|kikongo|tshiluba))?$",
    rf"^(?:traduis|traduire|traduction de|traduction du)\s+{_T}\s+en\s+(?:lingala|swahili|kikongo|tshiluba)$",
    rf"^(?:how do you say|how to say)\s+{_T}(?:\s+in\s+\w+)?$",
    # en lingala : « ndenge nini nakoloba merci na lingala ? », « ndenge nini balobaka … ? »
    rf"^ndenge nini\s+\w*(?:loba|lobaka|benga|bengaka|koma)\s+{_T}(?:\s+na\s+{_NATL})?$",
    rf"^(?:loba|lobela ngai|yebisa ngai)\s+{_T}\s+na\s+{_NATL}$",
    # « merci en lingala c'est quoi ? », « merci na lingala ezali nini ? »
    rf"^{_T}\s+(?:en|na)\s+{_NATL}\s+(?:c'est quoi|c est quoi|cest quoi|ca se dit comment|se dit comment|"
    rf"on dit comment|comment|ezali nini|ezali ndenge nini|balobaka ndenge nini|elobami ndenge nini|nini|boni)$",
    rf"^(?:dis moi|dis-moi|donne moi|donne-moi)\s+{_T}\s+en\s+{_NATL}$",
)]
_STRIP = re.compile(r"^(?:le mot|le terme|l'expression|la phrase|liloba|mot|neno|le|la|les|l')\s+|"
                    r"\s+(?:en lingala|en francais|na lingala|na lifalanse|en swahili|kwa kiswahili)$")


# « je vais au marché en lingala », « traduis : il pleut beaucoup », « comment dire j'ai faim en tshiluba ? »
_P = r"(?P<t>.{2,200}?)"
_PHRASE = [re.compile(p) for p in (
    rf"^(?:traduis|traduire|traduction|traduction de|traduis moi|traduis-moi|"
    rf"comment dire|comment on dit|comment dit on|comment dit-on|comment est ce qu'on dit|comment est-ce qu'on dit|"
    rf"comment je dis|comment je peux dire|comment tu dis|comment dis tu|comment dis-tu)\s*:?\s+"
    rf"(?:la phrase\s+|que\s+)?{_P}(?:\s+(?:en|na)\s+{_NATL})?$",
    # « dis … » seulement avec la langue : « dis-moi quelque chose » reste une conversation
    rf"^(?:dis|dis moi|dis-moi|dites|dites moi|dites-moi)\s*:?\s+(?:la phrase\s+|que\s+)?{_P}\s+(?:en|na)\s+{_NATL}$",
    rf"^ndenge nini\s+\w*(?:loba|lobaka)\s+{_P}\s+na\s+{_NATL}$",
    rf"^{_P}\s+(?:en|na)\s+{_NATL}(?:\s+(?:c'est quoi|stp|svp|s'il te plait|s'il te plaît|ca donne quoi|ça donne quoi))?$",
)]


_TALK = re.compile(r"\b(?:parle|parles|parler|parlez|parlons|discute|discuter|discutons|ecris|écris|écrire|ecrire|"
                   r"reponds|réponds|répondre|repondre|converse|converser|apprendre|apprends|enseigne|"
                   r"enseigner|chante|chanter|raconte|raconter|explique|expliquer)\s*(?:moi|nous)?$")


def parse_phrase_request(message: str) -> Optional[str]:
    """La phrase française à traduire quand l'utilisateur demande une traduction (sinon None)."""
    low = " ".join(re.sub(r"[?!«»\"“”]", " ", message.replace("’", "'")).lower().split()).strip(" .")
    for p in _PHRASE:
        m = p.match(low)
        if m:
            term = m.group("t").strip(" :.,'\"")
            # « je parle en lingala », « on discute en lingala ? » : c'est une conversation, pas une traduction
            if _TALK.search(term):
                return None
            if len(term.split()) >= 2:   # un seul mot : géré par « comment dit-on X »
                return term
    return None


def answer_phrase(db: Session, lang: str, phrase: str) -> dict:
    """Traduction d'une phrase, et rien d'autre : dataset validé, puis IA guidée par le dictionnaire,
    puis modèle de traduction / mot à mot."""
    out = {"reply": None, "reply_fr": phrase, "method": None, "audio_url": None, "word": None, "example": None}
    t = translator.translate(db, phrase, "fr", lang)
    if t["method"] == "dataset":
        out.update(reply=t["translation"], method="dataset", audio_url=t.get("audio_url"))
        return out
    hints = vocab_lua.examples_for(phrase) if lang == "lua" else []
    if lang == "ln":  # mots du dictionnaire pour chaque mot français de la phrase
        for w in dict.fromkeys(re.findall(r"[\wàâçéèêëîïôûùüœ'-]+", phrase.lower())):
            w = re.sub(r"^(?:l|d|j|m|t|s|n|qu)'", "", w)
            if len(w) > 2:
                tr = lexicon.reverse(w)
                if tr:
                    hints.append({"texte": " / ".join(tr[:3]), "sens": w})
    ai = claude_chat.translate(lang, phrase, hints)
    if ai:
        reply = ai["reply"].strip()
        out.update(reply=reply[:1].upper() + reply[1:], reply_fr=phrase[:1].upper() + phrase[1:], method="ia")
        return out
    if t.get("translation"):
        out.update(reply=t["translation"], method=t["method"])
    return out


# ---------- Message écrit en français : on donne sa traduction ----------
# « bonjour » -> « Bonjour » en lingala, c'est « Mbote » ; « je vais au marché » -> « Nazali kokende na zando »
_FR_STOP = set("""je j moi me m tu toi il elle on nous vous ils elles le la les l un une des du de d au aux et ou
est suis es sommes etes sont ai as avons avez ont vais vas va allons allez vont mon ma mes ton ta tes son sa ses
notre votre nos vos leur leurs ce cet cette ces c qui que qu quoi quand comment pourquoi ou dans pour avec sans
sur sous chez pas ne n plus tres bien bonjour bonsoir salut merci oui non suis veux veut peux peut fait faire
aussi mais donc car tout tous toute toutes rien beaucoup peu ici la-bas aujourd'hui demain hier""".split())
_ELISION = re.compile(r"^(?:l|d|j|m|t|s|n|c|qu)'")


def _tokens(message: str) -> list[str]:
    return [_ELISION.sub("", w) for w in key(re.sub(r"[?!.,;:«»\"“”()]", " ", message.replace("’", "'"))).split()]


_DICT_FR: Optional[set[str]] = None


def _dictionary_french() -> set[str]:
    """Mots français du dictionnaire (gloses du Wiktionnaire), sans ceux qui sont aussi lingala."""
    global _DICT_FR
    if _DICT_FR is None:
        lexicon._load()
        _DICT_FR = ({w for f in list(lexicon._fr) + list(COMMON_FR) for w in key(f).split() if len(w) > 2}
                    - {w for k in lexicon._ln for w in k.split()})
    return _DICT_FR


def looks_french(lang: str, message: str) -> bool:
    """Le message est-il écrit en français (et non dans la langue de la conversation) ?"""
    from .hearing import for_lang
    toks = [t for t in _tokens(message) if t]
    if not toks or len(toks) > 30:
        return False
    h = for_lang(lang)
    if h is not None:
        h._load()
    national_words = h._freq if h is not None else {}
    if h is not None:
        french_words = h._french | {key(f) for f in COMMON_FR}
    else:
        french_words = _dictionary_french()

    def national(t):
        if t in _FR_STOP or t in french_words:
            return False
        return t in national_words or (lang == "ln" and bool(lexicon.lookup(t, fuzzy=False)[1]))

    fr = sum(1 for t in toks if t in _FR_STOP or t in french_words)
    nat = sum(1 for t in toks if national(t))
    if h is None:
        # swahili, kikongo : pas encore de vocabulaire pour reconnaître la langue, il faut donc
        # des mots français connus (« habari yako », « mbote » ne doivent pas être traduits)
        return fr >= max(1, len(toks) / 2)
    if len(toks) <= 2 and nat == 0:
        return True     # un mot qui n'est pas de la langue : « piscine », « rivière »
    return fr > nat and fr >= len(toks) / 2


def _plain(text: str) -> str:
    """Écriture courante, sans les tons du dictionnaire : mbɔ́ngɔ -> mbongo."""
    t = unicodedata.normalize("NFD", text)
    t = "".join(c for c in t if not unicodedata.combining(c))
    for a, b in (("ɔ", "o"), ("ɛ", "e"), ("Ɔ", "O"), ("Ɛ", "E")):
        t = t.replace(a, b)
    return unicodedata.normalize("NFC", t)


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def translate_french(db: Session, lang: str, text: str) -> dict:
    """Traduction d'un mot ou d'une phrase française, et rien d'autre (aucune conversation) :
    dataset validé (avec l'enregistrement d'un locuteur), puis dictionnaire, puis IA guidée par
    le dictionnaire, puis modèle / mot à mot."""
    source = text.strip(" ?!.").strip()
    out = {"reply": None, "reply_fr": _cap(source), "method": None, "audio_url": None, "word": None,
           "example": None, "kind": "traduction", "source": _cap(source), "alternatives": [], "pron": None}
    t = translator.translate(db, source, "fr", lang)
    if t["method"] == "dataset":
        out.update(reply=_cap(t["translation"]), method="dataset", audio_url=t.get("audio_url"))
        return out
    # mot ou courte expression : le dictionnaire (« argent » -> mbongo, « la rivière » -> ebale)
    toks = _tokens(source)
    if 1 <= len(toks) <= 4:
        candidates = [source, " ".join(toks)]
        if len(toks) >= 2 and toks[0] in {"le", "la", "les", "un", "une", "des", "du", "de", "au", "aux"}:
            candidates.append(" ".join(toks[1:]))
        for c in candidates:
            words = lexicon.reverse(c) if lang == "ln" else vocab_lua.reverse(c) if lang == "lua" else []
            if words:
                first = _plain(words[0])
                out.update(reply=_cap(first), method="lexique",
                           alternatives=[_plain(w) for w in words[1:3] if _plain(w) != first],
                           pron=words[0] if words[0] != first else None)
                return out
    out.update({k: v for k, v in answer_phrase(db, lang, source).items() if k in ("reply", "method", "audio_url")})
    if out["reply"] and out["method"] != "dataset":
        out["reply"] = _plain(out["reply"])   # « Nakei na zándo » -> « Nakei na zando »
    if out["reply"] is None and lang == "ln":   # sans IA : mot à mot avec le dictionnaire
        parts, found = [], 0
        for w in toks:
            tr = lexicon.reverse(w) if w not in _FR_STOP else []
            parts.append(_plain(tr[0]) if tr else f"[{w}]")
            found += bool(tr)
        if found:
            out.update(reply=_cap(" ".join(parts)), method="mot_a_mot")
    return out


def parse_word_question(message: str) -> Optional[tuple[str, str]]:
    """('sens', mot) pour « que veut dire X », ('traduire', mot) pour « comment dit-on X »."""
    k = " ".join(key(re.sub(r"[?!.,«»\"“”]", " ", message)).split())
    for kind, patterns in (("traduire", _REVERSE), ("sens", _MEANING)):
        for p in patterns:
            m = p.match(k)
            if m:
                term = m.group("t").strip(" -'")
                for _ in range(2):
                    term = _STRIP.sub("", term).strip(" -'")
                if term and len(term.split()) <= 4:
                    return kind, term
    return None


# Gabarits de réponse dans la langue de la conversation (le sens reste en français)
_SAY = {
    # <fr>…</fr> : ces mots sont dits par la voix française, le reste par la voix de la langue
    "ln": {"sens": "« {w} » elingi koloba : <fr>{s}</fr>.", "traduire": "Na lingala, « <fr>{t}</fr> » ezali « {w} ».",
           "inconnu": "Nayebi naino liloba « {t} » te. Soki oyebi ndimbola na yango, lakisa ngai !",
           "ou": " to "},
    "sw": {"sens": "« {w} » maana yake ni : <fr>{s}</fr>.", "traduire": "Kwa Kiswahili, « <fr>{t}</fr> » ni « {w} ».",
           "inconnu": "Bado sijui neno « {t} ». Ukijua maana yake, nifundishe !", "ou": " au "},
}
_SAY_FR = {"sens": "« {w} »{p} signifie : {s}.", "traduire": "En {lang}, « {t} » se dit « {w} ».",
           "inconnu": "Je ne connais pas encore le mot « {t} ». Si tu connais son sens, apprends-le-moi !"}


def _say(lang: str, kind: str, **kw) -> tuple[str, str]:
    fr = _SAY_FR[kind].format(lang=LANGUAGES[lang].lower(), p=kw.pop("p", ""), **kw)
    local = _SAY.get(lang, {}).get(kind)
    # pas de gabarit dans cette langue : la phrase est en français, donc dite par la voix française
    return (local.format(**kw) if local else f"<fr>{fr}</fr>"), fr


def answer_word_question(db: Session, lang: str, kind: str, term: str, history: list[dict]) -> dict:
    out = {"reply": None, "reply_fr": None, "method": None, "audio_url": None, "word": None, "example": None}
    ou = _SAY.get(lang, {}).get("ou", " ou ")
    if kind == "sens":
        # 1. traduction validée par la communauté
        t = translator.translate(db, term, lang, "fr")
        if t["method"] == "dataset":
            reply, fr = _say(lang, "sens", w=term, s=t["translation"])
            out.update(reply=reply, reply_fr=fr, method="dataset", audio_url=t.get("audio_url"),
                       word={"term": term, "meanings": [{"word": term, "sens": t["translation"], "source": "Communauté"}]})
            return out
        # 2. dictionnaire (lingala seulement)
        if lang == "ln":
            found, entries = lexicon.lookup(term)
            meanings = lexicon.describe(entries)
            if meanings:
                main, used = meanings[0], meanings[:2]
                if len({m["word"] for m in used}) > 1:  # homonymes : motó (tête) / mɔ̌tɔ (feu)
                    w, sens = term, " ; ".join(f"{m['sens']} ({m['word']})" for m in used)
                    details = ""
                else:
                    w, sens = main["word"], " ; ".join(m["sens"] for m in used)
                    details = ", ".join(x for x in (main.get("pos"), main.get("note")) if x)
                reply, fr = _say(lang, "sens", w=w, s=sens, p=f" ({details})" if details else "")
                if found != key(term):
                    plural = key(term)[2:] == found
                    fr += (f" « {term} » est le pluriel de « {main['word']} »." if plural
                           else f" (mot le plus proche de « {term} »)")
                out.update(reply=reply, reply_fr=fr, method="lexique",
                           word={"term": term, "meanings": meanings},
                           example=corpus.example_with(term) or corpus.example_with(main["word"]))
                return out
    else:
        # « comment dit-on X ? » : traduction validée, puis dictionnaire inversé
        t = translator.translate(db, term, "fr", lang)
        words = [t["translation"]] if t["method"] == "dataset" else (
            lexicon.reverse(term) if lang == "ln" else vocab_lua.reverse(term) if lang == "lua" else [])
        if words:
            reply, _ = _say(lang, "traduire", t=term, w=f" »{ou}« ".join(words[:2]))
            fr = _SAY_FR["traduire"].format(lang=LANGUAGES[lang].lower(), t=term, w=" » ou « ".join(words[:2]))
            out.update(reply=reply, reply_fr=fr, method="dataset" if t["method"] == "dataset" else "lexique",
                       audio_url=t.get("audio_url") if t["method"] == "dataset" else None,
                       word={"term": term, "translations": words[:4]})
            return out
        # « ndako na lingala ezali nini ? » : le mot est déjà du lingala -> on donne son sens
        if lang == "ln" and lexicon.lookup(term, fuzzy=False)[1]:
            return answer_word_question(db, lang, "sens", term, history)
    # 3. IA (si configurée), sinon : « je ne connais pas encore ce mot »
    question = f"Que veut dire « {term} » ?" if kind == "sens" else f"Comment dit-on « {term} » en {LANGUAGES[lang]} ?"
    hints = (lexicon.examples_for(term) + corpus.examples_for_ai(term, k=4) if lang == "ln"
             else vocab_lua.examples_for(term) + corpus_lua.examples_for_ai(term, k=4) if lang == "lua" else [])
    ai = claude_chat.reply(lang, question, history, hints)
    if ai:
        out.update(reply=ai["reply"], reply_fr=ai["reply_fr"], method="ia")
        return out
    reply, fr = _say(lang, "inconnu", t=term)
    out.update(reply=reply, reply_fr=fr, method="inconnu")
    return out


def _relevance(query: str, words: set[str], text_norm: str) -> float:
    tw = set(text_norm.split())
    overlap = len(words & tw) / max(1, len(words | tw))
    return max(overlap, similarity(query, text_norm) * 0.8)


def grounding_examples(db: Session, lang: str, query: str) -> list[dict]:
    """Exemples validés (dialogues + traductions) les plus proches du message."""
    words = set(query.split())
    scored = []
    rows = db.scalars(select(TrainingEntry).where(
        or_(TrainingEntry.source_lang == lang, TrainingEntry.target_lang == lang)))
    for e in rows:
        if e.kind == DIALOGUE:
            score = _relevance(query, words, e.source_norm)
            item = {"texte": f"« {e.source_text} » → réponse : « {e.target_text} »", "sens": "(dialogue)"}
        elif e.kind == TRADUCTION:
            in_lang, other = ((e.source_text, e.source_norm), e.target_text) if e.source_lang == lang \
                else ((e.target_text, e.target_norm), e.source_text)
            score = _relevance(query, words, in_lang[1])
            item = {"texte": in_lang[0], "sens": other}
        else:
            continue
        scored.append((score, e.id, item))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [it for _, _, it in scored[:MAX_EXAMPLES]]


def converse(db: Session, lang: str, message: str, history: list[dict], voice: bool = False) -> dict:
    out = {"lang": lang, "message": message, "reply": None, "reply_fr": None,
           "method": None, "audio_url": None, "word": None, "example": None,
           "ai_available": claude_chat.enabled()}
    query = normalize(message)
    if not query:
        return out

    # 0. « Que veut dire … ? » / « Comment dit-on … ? »
    question = parse_word_question(message)
    if question and question[0] == "traduire" and looks_french(lang, question[1]):
        out.update(translate_french(db, lang, question[1]))
        return out
    if question:
        out.update(answer_word_question(db, lang, *question, history))
        return out
    # « je vais au marché en lingala » : la traduction de la phrase, sans rien ajouter
    phrase = parse_phrase_request(message)
    if phrase:
        out.update(translate_french(db, lang, phrase))
        return out
    # Écrit en français (« argent », « je vais au marché ») : on donne la traduction, en texte
    if not voice and looks_french(lang, message):
        out.update(translate_french(db, lang, message))
        return out

    # 1. Dialogue validé
    best, best_score = None, 0.0
    for e in db.scalars(select(TrainingEntry).where(
            TrainingEntry.kind == DIALOGUE, TrainingEntry.source_lang == lang)):
        s = similarity(query, e.source_norm)
        if s > best_score:
            best, best_score = e, s
    if best is not None and best_score >= LOOKUP_THRESHOLD:
        fr = translator.translate(db, best.target_text, lang, "fr")
        out.update(reply=best.target_text, reply_fr=fr["translation"], method="dataset",
                   audio_url=translator.audio_url(best.audio_path))
        return out

    # 2. Échanges de base (salutations, présentation…)
    basic = basic_reply(lang, message, threshold=0.95 if claude_chat.enabled() else 0.85)
    if basic:
        out.update(reply=basic[0], reply_fr=basic[1], method="base")
        return out

    # Un mot lingala seul (« ndako ») : on donne son sens
    if lang == "ln" and len(query.split()) <= 2 and lexicon.lookup(message, fuzzy=False)[1]:
        out.update(answer_word_question(db, lang, "sens", message.strip(" ?!."), history))
        return out

    # 3. IA ancrée sur le dataset validé et le dictionnaire
    examples = grounding_examples(db, lang, query)
    if lang == "ln":
        examples += lexicon.examples_for(message) + corpus.examples_for_ai(message)
    elif lang == "lua":
        examples += vocab_lua.examples_for(message) + corpus_lua.examples_for_ai(message, k=4)
    ai = claude_chat.reply(lang, message, history, examples, voice=voice)
    if ai:
        out.update(reply=ai["reply"], reply_fr=ai["reply_fr"], method="ia")
    return out
