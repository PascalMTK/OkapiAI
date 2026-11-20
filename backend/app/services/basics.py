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
         "Nazali malamu, matondo. Bongo yo ?", "Je vais bien, merci. Et toi ?"),
        (["nazali malamu", "malamu", "nazali malamu matondo", "nazali malamu matondi", "malamu mingi",
          "nazali malamu mingi", "nazali kaka malamu"],
         "Esengo mingi ! Tosolola : olingi koyekola nini lelo ?",
         "Ça me fait très plaisir ! Discutons : qu'est-ce que tu veux apprendre aujourd'hui ?"),
        # « je vais bien, et toi ? » : on répond d'abord à la question
        (["nazali malamu yo", "nazali malamu bongo yo", "nazali malamu matondo yo", "nazali malamu matondo bongo yo",
          "nazali malamu matondi yo", "nazali malamu matondi bongo yo", "malamu bongo yo", "malamu yo",
          "malamu matondo yo", "nazali malamu na yo"],
         "Ngai pe nazali malamu, matondo ! Olingi tosolola likambo nini lelo ?",
         "Moi aussi je vais bien, merci ! De quoi veux-tu qu'on parle aujourd'hui ?"),
        (["okei wapi", "ozali kokende wapi", "okokende wapi", "ozali kokei wapi"],
         "Ngai nazali kaka awa elongo na yo ! Bongo yo, ozali kokende wapi ?",
         "Moi je reste ici avec toi ! Et toi, tu vas où ?"),
        (["ozali wapi", "ozali na esika nini"],
         "Nazali awa, na kati ya telefone to ordinateur na yo ! Bongo yo, ozali wapi ?",
         "Je suis ici, dans ton téléphone ou ton ordinateur ! Et toi, tu es où ?"),
        (["nazali na nzala", "nzala ezali koboma ngai", "nazali na nzala mingi"],
         "Ah, ozali na nzala ! Olingi kolia nini : fufu, loso to pondu ?",
         "Ah, tu as faim ! Qu'est-ce que tu veux manger : du fufu, du riz ou du pondu ?"),
        (["olei", "olei malamu", "olei te"],
         "Ngai nalyaka te, nazali mosungi ! Bongo yo, olei ?",
         "Moi je ne mange pas, je suis un assistant ! Et toi, tu as mangé ?"),
        (["nalembi", "nalembi mingi", "nazali kolemba"],
         "Pema moke, ndeko. Mosala ezalaki mingi lelo ?",
         "Repose-toi un peu, frère. Il y avait beaucoup de travail aujourd'hui ?"),
        (["nayoki te", "nasosoli te", "nayoki yo te", "nasosoli yo te"],
         "Limbisa ngai ! Nakoloba malembe. Tuna ngai lisusu.",
         "Pardon ! Je vais parler doucement. Repose-moi la question."),
        (["butu malamu", "lala malamu"],
         "Butu malamu ! Lala malamu, tokomonana lobi.", "Bonne nuit ! Dors bien, à demain."),
        (["kombo na yo nani", "ozali nani", "yo nani"],
         "Kombo na ngai OkapiAI. Nazali mosungi na yo ya lingala. Bongo yo, kombo na yo nani ?",
         "Je m'appelle OkapiAI. Je suis ton assistant de lingala. Et toi, comment t'appelles-tu ?"),
        (["matondo", "matondo mingi", "matondi", "matondi mingi", "merci"],
         "Likambo te !", "De rien !"),
        (["tokomonana", "kende malamu", "bokende malamu", "tikala malamu", "au revoir", "tokutana lobi",
          "tokomonana lobi", "nakei", "nakei sikoyo"],
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
    # Tshiluba (ciluba du Kasaï). Formes courantes, à faire relire par des locuteurs natifs :
    # le bouton « Corriger » de l'interface permet d'en proposer de meilleures.
    "lua": [
        (["moyo", "moyo webe", "moyo wenu", "moyo okapi", "bonjour", "salut"],
         "Moyo webe ! Udi muimpe ?", "Bonjour ! Tu vas bien ?"),
        (["udi muimpe", "udi bimpe", "moyo udi muimpe", "moyo udi bimpe", "bualu kayi"],
         "Ndi muimpe, tuasakidila. Ne wewe ?", "Je vais bien, merci. Et toi ?"),
        (["ndi muimpe", "ndi bimpe", "muimpe", "bimpe", "ndi muimpe tuasakidila", "ndi muimpe ne wewe"],
         "Bimpe bikole ! Udi musue kulonga tshinyi lelu ?", "Très bien ! Que veux-tu apprendre aujourd'hui ?"),
        (["dina diebe nganyi", "wewe nganyi", "udi nganyi"],
         "Dîna dianyi ndi OkapiAI. Ne wewe, dîna diebe nganyi ?", "Je m'appelle OkapiAI. Et toi, comment t'appelles-tu ?"),
        (["tuasakidila", "tuasakidila bikole", "merci"], "Kakuena bualu !", "De rien !"),
        (["shala bimpe", "ya bimpe", "tuamonangana", "au revoir"],
         "Shala bimpe ! Tuamonangana.", "Au revoir ! À bientôt."),
        (["ndi ne nzala"], "Udi ne nzala ? Udi musue kudia tshinyi ?", "Tu as faim ? Que veux-tu manger ?"),
        (["tshiena mumvue", "tshiena mumvue bimpe"],
         "Kakuena bualu. Tuyukile bitekete.", "Pas de souci. Parlons doucement."),
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
