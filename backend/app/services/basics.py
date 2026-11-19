"""Échanges de base intégrés (salutations, présentation, remerciements…).

Ils permettent au bot de converser dans la langue nationale même sans IA ni dialogue
validé. Les dialogues validés par la communauté restent prioritaires ; ceux-ci ne sont
qu'un point de départ, et les utilisateurs peuvent les corriger (bouton « Corriger »).
"""
import re
from typing import Optional

from .lexicon import key
from ..similarity import similarity

# (déclencheurs, réponse, traduction française)
BASICS: dict[str, list[tuple[list[str], str, str]]] = {
    "ln": [
        (["mbote", "mbote na yo", "mbote na bino", "mbote okapi", "bonjour", "salut"],
         "Mbote ! Ozali malamu ?", "Bonjour ! Tu vas bien ?"),
        (["sango nini", "mbote sango nini", "ozali malamu", "mbote ozali malamu", "ndenge nini", "boni"],
         "Nazali malamu, matondi. Bongo yo ?", "Je vais bien, merci. Et toi ?"),
        (["nazali malamu", "malamu", "nazali malamu matondi", "malamu mingi"],
         "Esengo mingi ! Tosolola : olingi koyekola nini lelo ?",
         "Ça me fait très plaisir ! Discutons : qu'est-ce que tu veux apprendre aujourd'hui ?"),
        (["kombo na yo nani", "ozali nani", "yo nani"],
         "Kombo na ngai OkapiAI. Nazali mosungi na yo ya lingala. Bongo yo, kombo na yo nani ?",
         "Je m'appelle OkapiAI. Je suis ton assistant de lingala. Et toi, comment t'appelles-tu ?"),
        (["matondi", "matondi mingi", "merci"],
         "Likambo te !", "De rien !"),
        (["tokomonana", "kende malamu", "bokende malamu", "tikala malamu", "au revoir"],
         "Kende malamu ! Tokomonana.", "Va en paix ! À bientôt."),
        (["olobaka lingala", "oyebi lingala", "toloba lingala"],
         "Ee, nalobaka lingala. Tosolola na lingala !", "Oui, je parle lingala. Parlons en lingala !"),
        (["nalingi koyekola lingala", "lakisa ngai lingala", "teya ngai lingala"],
         "Malamu mingi ! Tuna ngai ndimbola ya liloba moko, ndakisa : « ndako elingi koloba nini ? »",
         "Très bien ! Demande-moi le sens d'un mot, par exemple : « que veut dire ndako ? »"),
    ],
    "sw": [
        (["jambo", "habari", "habari yako", "habari gani", "mambo", "hujambo", "bonjour"],
         "Nzuri sana ! Habari yako ?", "Très bien ! Et toi, comment vas-tu ?"),
        (["nzuri", "nzuri sana", "sijambo", "salama"],
         "Vizuri ! Tuongee kidogo : unataka kujifunza nini leo ?",
         "Très bien ! Discutons un peu : que veux-tu apprendre aujourd'hui ?"),
        (["jina lako nani", "wewe ni nani"],
         "Jina langu ni OkapiAI. Na wewe, jina lako nani ?", "Je m'appelle OkapiAI. Et toi, comment t'appelles-tu ?"),
        (["asante", "asante sana", "merci"], "Karibu !", "De rien !"),
        (["kwa heri", "tutaonana", "au revoir"], "Kwa heri ! Tutaonana.", "Au revoir ! À bientôt."),
    ],
}

_NAME = {
    "ln": (re.compile(r"^(?:kombo na ngai|nkombo na ngai)\s+(?:ezali\s+)?(?P<n>[a-z' -]{2,30})$"),
           "Nasepeli koyeba yo, {n} ! Ozali malamu ?", "Ravi de te connaître, {n} ! Tu vas bien ?"),
    "sw": (re.compile(r"^(?:jina langu ni|mimi ni|naitwa)\s+(?P<n>[a-z' -]{2,30})$"),
           "Nafurahi kukujua, {n} ! Habari yako ?", "Ravi de te connaître, {n} ! Comment vas-tu ?"),
}
_NOT_NAMES = {"malamu", "malamu mingi", "nani", "mosungi", "mwana", "nzuri", "salama"}


def basic_reply(lang: str, message: str, threshold: float = 0.85) -> Optional[tuple[str, str]]:
    """(réponse, traduction française) si le message est un échange de base.
    Avec l'IA disponible, on passe un seuil plus strict pour lui laisser les messages plus riches."""
    k = key(message)
    if not k:
        return None
    name = _NAME.get(lang)
    if name:
        m = name[0].match(k)
        if m and m.group("n").strip() not in _NOT_NAMES:
            n = m.group("n").strip().title()
            return name[1].format(n=n), name[2].format(n=n)
    best, best_score = None, 0.0
    for triggers, reply, reply_fr in BASICS.get(lang, []):
        for t in triggers:
            s = similarity(k, t)
            if s > best_score:
                best, best_score = (reply, reply_fr), s
    return best if best_score >= threshold else None
