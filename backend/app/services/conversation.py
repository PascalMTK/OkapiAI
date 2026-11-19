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
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import LANGUAGES, LOOKUP_THRESHOLD
from ..models import DIALOGUE, TRADUCTION, TrainingEntry
from ..similarity import normalize, similarity
from . import translator
from .basics import basic_reply
from .lexicon import key, lexicon
from .llm import claude_chat

MAX_EXAMPLES = 25

# ---------- Questions « que veut dire … ? » ----------
_T = r"(?P<t>[\w' -]{1,60}?)"
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
)]
_STRIP = re.compile(r"^(?:le mot|le terme|l'expression|la phrase|liloba|mot|neno|le|la|les|l')\s+|"
                    r"\s+(?:en lingala|en francais|na lingala|na lifalanse|en swahili|kwa kiswahili)$")


def parse_word_question(message: str) -> Optional[tuple[str, str]]:
    """('sens', mot) pour « que veut dire X », ('traduire', mot) pour « comment dit-on X »."""
    k = key(message.replace("?", " "))
    for kind, patterns in (("sens", _MEANING), ("traduire", _REVERSE)):
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
    "ln": {"sens": "« {w} » elingi koloba : {s}.", "traduire": "Na lingala, « {t} » ezali « {w} ».",
           "inconnu": "Nayebi naino liloba « {t} » te. Soki oyebi ndimbola na yango, lakisa ngai !",
           "ou": " to "},
    "sw": {"sens": "« {w} » maana yake ni : {s}.", "traduire": "Kwa Kiswahili, « {t} » ni « {w} ».",
           "inconnu": "Bado sijui neno « {t} ». Ukijua maana yake, nifundishe !", "ou": " au "},
}
_SAY_FR = {"sens": "« {w} »{p} signifie : {s}.", "traduire": "En {lang}, « {t} » se dit « {w} ».",
           "inconnu": "Je ne connais pas encore le mot « {t} ». Si tu connais son sens, apprends-le-moi !"}


def _say(lang: str, kind: str, **kw) -> tuple[str, str]:
    fr = _SAY_FR[kind].format(lang=LANGUAGES[lang].lower(), p=kw.pop("p", ""), **kw)
    local = _SAY.get(lang, {}).get(kind)
    return (local.format(**kw) if local else fr), fr


def answer_word_question(db: Session, lang: str, kind: str, term: str, history: list[dict]) -> dict:
    out = {"reply": None, "reply_fr": None, "method": None, "audio_url": None, "word": None}
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
                           word={"term": term, "meanings": meanings})
                return out
    else:
        # « comment dit-on X ? » : traduction validée, puis dictionnaire inversé
        t = translator.translate(db, term, "fr", lang)
        words = [t["translation"]] if t["method"] == "dataset" else (lexicon.reverse(term) if lang == "ln" else [])
        if words:
            reply, _ = _say(lang, "traduire", t=term, w=f" »{ou}« ".join(words[:2]))
            fr = _SAY_FR["traduire"].format(lang=LANGUAGES[lang].lower(), t=term, w=" » ou « ".join(words[:2]))
            out.update(reply=reply, reply_fr=fr, method="dataset" if t["method"] == "dataset" else "lexique",
                       audio_url=t.get("audio_url") if t["method"] == "dataset" else None,
                       word={"term": term, "translations": words[:4]})
            return out
    # 3. IA (si configurée), sinon : « je ne connais pas encore ce mot »
    question = f"Que veut dire « {term} » ?" if kind == "sens" else f"Comment dit-on « {term} » en {LANGUAGES[lang]} ?"
    ai = claude_chat.reply(lang, question, history, lexicon.examples_for(term) if lang == "ln" else [])
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


def converse(db: Session, lang: str, message: str, history: list[dict]) -> dict:
    out = {"lang": lang, "message": message, "reply": None, "reply_fr": None,
           "method": None, "audio_url": None, "word": None, "ai_available": claude_chat.enabled()}
    query = normalize(message)
    if not query:
        return out

    # 0. « Que veut dire … ? » / « Comment dit-on … ? »
    question = parse_word_question(message)
    if question:
        out.update(answer_word_question(db, lang, *question, history))
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
        examples += lexicon.examples_for(message)
    ai = claude_chat.reply(lang, message, history, examples)
    if ai:
        out.update(reply=ai["reply"], reply_fr=ai["reply_fr"], method="ia")
    return out
