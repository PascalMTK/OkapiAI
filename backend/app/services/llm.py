"""Conversation libre en langue nationale via une IA (optionnel), avec relais entre services.

Services pris en charge (activés dès que leur clé est définie, dans backend/.env) :
  - gemini   GEMINI_API_KEY      offre gratuite (Google AI Studio)
  - groq     GROQ_API_KEY        offre gratuite
  - claude   ANTHROPIC_API_KEY   payant (paquet `anthropic`), seulement si ajouté à la liste
Ordre d'essai : OKAPI_LLM_PROVIDERS (défaut : gemini,groq).
Si un service atteint sa limite gratuite (429), est en panne ou trop lent, OkapiAI passe
au suivant ; un service limité est mis de côté OKAPI_LLM_COOLDOWN secondes (défaut 60).

L'IA est ancrée sur le vocabulaire validé par la communauté et le dictionnaire
(exemples envoyés avec chaque message) : elle doit privilégier ces mots et tournures.
OKAPI_LLM_ENABLED=0 désactive toute IA (tests).
"""
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Optional

from ..config import LANGUAGES

log = logging.getLogger("okapiai.llm")

# Gemini gratuit répond d'habitude en 2-5 s mais traîne parfois : au-delà, Groq prend le relais
TIMEOUT = float(os.getenv("OKAPI_LLM_TIMEOUT", "7"))
COOLDOWN = float(os.getenv("OKAPI_LLM_COOLDOWN", "60"))

LANG_DETAILS = {
    "ln": "lingala (tel que parlé à Kinshasa et dans l'ouest de la RDC)",
    "sw": "swahili (de préférence le swahili du Congo / kingwana, tel que parlé dans l'est de la RDC)",
    "kg": "kikongo (tel que parlé en RDC ; kikongo ya leta si l'utilisateur l'emploie)",
    "lua": "tshiluba / ciluba (luba-kasaï, tel que parlé au Kasaï en RDC)",
}

SYSTEM_TEMPLATE = """Tu es OkapiAI, un assistant conversationnel congolais. Tu converses avec l'utilisateur en {lang_details}.

Règles :
- Avant de répondre, comprends exactement ce que dit l'utilisateur (écris-le en français dans « compris »), puis réponds DIRECTEMENT à ce message : s'il te pose une question (« bongo yo ? », « yo ? », « okei wapi ? »), réponds d'abord à cette question ; ne change pas de sujet.
- Ta réponse doit correspondre exactement au message de l'utilisateur : pas de sujet ajouté, pas d'informations hors sujet, pas de faits inventés. S'il demande une traduction, donne la traduction (sans autre ajout). S'il dit ce qu'il fait (« nakei na zando »), réagis à ce qu'IL fait (ex. souhaite-lui bonne route, demande ce qu'il va acheter) au lieu de le reprendre à ton compte.
- Tu es un assistant (tu ne manges pas, tu ne te déplaces pas) : réponds avec naturel et humour à ce genre de question, puis renvoie la question à l'utilisateur.
- Réponds TOUJOURS dans cette langue, même si l'utilisateur écrit en français ou dans une autre langue.
- N'utilise jamais l'anglais, pas même un mot (« faculty » -> dis « faculté », « school » -> « kelási ») : le seul emprunt permis est le français, comme on le fait au Congo.
- Converse simplement comme un humain, un ami congolais qui discute : naturel, spontané, à l'écoute. Tu n'es PAS un professeur : ne donne pas de leçon, n'explique pas de mots, ne corrige pas l'utilisateur et ne fais pas de remarques sur la langue, sauf s'il te le demande lui-même.
- Quand on te pose une question, réponds-y vraiment, comme le ferait une personne qui connaît le sujet (détails concrets, vie de tous les jours au Congo si c'est pertinent), sans phrase vague.
- Adapte la longueur comme dans une vraie discussion : une question ouverte (« parle-moi de… ») appelle quelques phrases ; une phrase simple, une salutation ou un « merci » appelle 1 à 2 phrases. Chaque phrase doit rester liée à ce que l'utilisateur a dit.
- Ta réponse est lue à voix haute par plusieurs voix. Si tu cites un mot ou une expression en français, entoure-le de balises <fr>…</fr> : « ndako » elingi koloba <fr>maison</fr>. Fais de même pour un mot d'une autre langue congolaise : <sw>…</sw>, <ln>…</ln>, <lua>…</lua>, <kg>…</kg>. Ainsi la voix française prononce correctement le mot français, puis la voix de la langue reprend. Si l'utilisateur demande comment prononcer ou dire un mot français, réponds aussi avec ces balises. Pas de balises dans « reply_fr » ni dans « compris ».
- Phrases simples et naturelles, adaptées à l'oral (la réponse peut être lue à voix haute) : pas de listes, pas de titres, pas d'emojis.
- Les exemples validés par la communauté (fournis avec chaque message) sont la référence : réutilise leur vocabulaire, leur orthographe et leurs tournures quand c'est pertinent.
- Les phrases marquées « corpus LRSC » sont du lingala correct lu par des locuteurs natifs, sans traduction : inspire-toi de leurs mots, de leurs conjugaisons et de leur orthographe, mais ne les recopie pas si elles n'ont pas de rapport avec la conversation.
- Si tu n'es pas sûr d'un mot, choisis une formulation plus simple que tu maîtrises plutôt que d'inventer un mot. Une réponse plus longue ne doit jamais être moins correcte : si tu maîtrises moins bien cette langue, fais des phrases simples et sûres (et sois un peu plus bref) plutôt que des phrases compliquées ou inventées. La traduction française doit dire exactement la même chose que ta réponse.
- Sois chaleureux et respectueux, comme dans une conversation entre Congolais.
- Fais vivre la conversation comme un humain : quand c'est naturel (pas à chaque fois), relance avec une courte question liée au sujet.
- Si l'utilisateur demande le sens d'un mot, explique-le dans la langue de la conversation (le sens peut être cité en français), en t'appuyant d'abord sur les entrées du dictionnaire fournies avec les exemples. Si le mot n'y figure pas et que tu n'es pas sûr, dis-le plutôt que d'inventer.
- Fournis aussi une traduction française fidèle de ta réponse, pour les personnes qui apprennent la langue.{phrasebook}"""

# Expressions courantes : sans elles, l'IA confond par ex. « okei wapi ? » (tu vas où ?) avec « tu es où ? »
PHRASEBOOK = {
    "ln": """

Expressions courantes du lingala de Kinshasa (sens exact) :
- mbote = bonjour ; sango nini ? = quoi de neuf ? ; ozali malamu ? = tu vas bien ? ; nazali malamu = je vais bien
- matondo (ou matondi) = merci ; likambo te = de rien / pas de souci ; bongo yo ? / yo ? = et toi ?
- ngai pe = moi aussi ; ee = oui ; te / ve = non ; limbisa ngai = pardon
- okei wapi ? / ozali kokende wapi ? = tu vas où ? ; ozali wapi ? = tu es où ? ; outi wapi ? = tu viens d'où ?
- nakei = je m'en vais ; tokomonana = à bientôt ; tokutana lobi = on se voit demain ; kende malamu = va en paix ; tikala malamu = reste en paix
- nazali na nzala = j'ai faim ; nazali na mposa ya mai = j'ai soif ; olei ? = tu as mangé ? ; nalei = j'ai mangé
- nalembi = je suis fatigué ; nazali na mpasi = j'ai mal / je souffre ; nazali na esengo = je suis content
- nayoki te / nasosoli te = je n'ai pas compris ; loba lisusu = répète ; loba malembe = parle doucement
- lobela ngai = raconte-moi / dis-moi ; nalingi yo = je t'aime ; lelo = aujourd'hui ; lobi = demain ou hier (selon le temps du verbe)""",
    "sw": """

Expressions courantes du swahili du Congo (kingwana) :
- jambo / habari = bonjour ; habari yako ? = comment vas-tu ? ; muzuri / nzuri = bien ; asante (sana) = merci (beaucoup)
- karibu = bienvenue / de rien ; ndiyo = oui ; hapana = non ; pole = désolé (compassion) ; samahani = pardon
- kwaheri = au revoir ; tutaonana = à bientôt ; jina lako nani ? = comment t'appelles-tu ? ; jina langu ni … = je m'appelle …
- nina njaa = j'ai faim ; sielewi = je ne comprends pas ; rudia tafadhali = répète s'il te plaît
- unaenda wapi ? = tu vas où ? ; ninaenda sokoni = je vais au marché ; nyumba = maison ; maji = eau ; chakula = nourriture""",
    "kg": """

Expressions courantes du kikongo ya leta (kituba) :
- mbote = bonjour ; nge ke mbote ? = tu vas bien ? ; mono ke mbote = je vais bien ; matondo = merci
- ee = oui ; ve = non ; kwenda mbote = au revoir (va bien) ; kubikala mbote = reste bien
- nkumbu na nge nani ? = comment t'appelles-tu ? ; nkumbu na mono … = je m'appelle …
- mono ke na nzala = j'ai faim ; nzo = maison ; zandu = marché ; maza = eau ; madia = nourriture""",
    "lua": """

Expressions courantes du tshiluba (ciluba du Kasaï) :
- moyo / moyo webe = bonjour (à toi) ; moyo wenu = bonjour (à vous) ; udi muimpe ? = tu vas bien ? ; ndi muimpe = je vais bien
- tuasakidila = merci ; tuasakidila bikole = merci beaucoup ; kakuena bualu = de rien / pas de problème ; ne wewe ? = et toi ?
- eyowa = oui ; tòo = non ; bimpe = bien ; bikole = beaucoup / très
- dîna diebe nganyi ? = comment t'appelles-tu ? ; dîna dianyi ndi … = je m'appelle …
- shala bimpe = au revoir (reste bien) ; ya bimpe = va bien ; tuamonangana = à bientôt
- ndi ne nzala = j'ai faim ; tshiena mumvue = je n'ai pas compris ; amba kabidi = redis / répète
- udi musue … ? = veux-tu … ? ; ndi musue … = je veux … ; lelu = aujourd'hui ; tshinyi = quoi ; kuepi = où
Les exemples de phrases tshiluba fournis viennent surtout de la Bible : prends-y l'orthographe et
les conjugaisons, mais parle comme dans la vie de tous les jours (pas de Yehowa, Nzambi ni tournures
bibliques sauf si l'utilisateur en parle).""",
}

VOICE_RULE = """

Conversation orale en direct (comme un appel) :
- Parle comme au téléphone : 2 à 4 phrases courtes (environ 50 mots au plus), sans listes, sans emojis ni symboles : tout est lu à voix haute (les balises <fr>…</fr> restent permises et utiles).
- Réponds comme une personne au téléphone : une vraie réponse, naturelle, sans leçon ni explication de mots.
- Quand c'est naturel, relance avec UNE question simple sur la personne ou le sujet.
- Si le message est incompréhensible ou coupé, demande gentiment de répéter, dans la langue."""

TRANSLATE_TEMPLATE = """Tu es un traducteur expert du français vers le {lang_details}.
Traduis fidèlement la phrase de l'utilisateur, comme un locuteur natif la dirait dans la vie de tous les jours.
Règles :
- Traduis EXACTEMENT la phrase donnée, ni plus ni moins : pas d'explication, pas de question, pas de salutation, rien d'autre que la traduction.
- Utilise en priorité les mots fournis (dictionnaire, exemples validés). N'invente aucun mot : si tu n'es pas sûr, choisis la formulation la plus simple et la plus courante.
- Garde le temps, la personne et le sens de la phrase d'origine.
- Dans « reply_fr », retraduis mot à mot ta traduction en français (pour vérifier qu'elle dit bien la même chose).{phrasebook}"""

JSON_RULE = ('\n\nRéponds UNIQUEMENT avec un objet JSON, sans texte autour : '
             '{"compris": "<ce que l\'utilisateur a dit, en français>", '
             '"reply": "<ta réponse dans la langue de la conversation>", "reply_fr": "<sa traduction française>"}')

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "compris": {"type": "string", "description": "Ce que l'utilisateur a dit, en français"},
        "reply": {"type": "string", "description": "La réponse dans la langue de la conversation"},
        "reply_fr": {"type": "string", "description": "Traduction française de la réponse"},
    },
    "required": ["compris", "reply", "reply_fr"],
    "additionalProperties": False,
}


class ProviderError(Exception):
    def __init__(self, message: str, rate_limited: bool = False):
        super().__init__(message)
        self.rate_limited = rate_limited


def build_messages(lang: str, message: str, history: list[dict], examples: list[dict],
                   voice: bool = False) -> tuple[str, list[dict]]:
    """(prompt système, messages user/assistant alternés) communs à toutes les IA."""
    lang_name = LANGUAGES[lang]
    system = SYSTEM_TEMPLATE.format(lang_details=LANG_DETAILS.get(lang, lang_name),
                                    phrasebook=PHRASEBOOK.get(lang, "")) + (VOICE_RULE if voice else "")
    messages: list[dict] = []
    for turn in history[-10:]:
        if not messages and turn["role"] != "user":
            continue
        if messages and messages[-1]["role"] == turn["role"]:
            messages[-1]["content"] += "\n" + turn["text"]
        else:
            messages.append({"role": turn["role"], "content": turn["text"]})
    if messages and messages[-1]["role"] == "user":
        messages.pop()  # le message courant le remplace
    ex_lines = "\n".join(f"- {e['texte']}  =  {e['sens']}" for e in examples) or "(aucun pour l'instant)"
    messages.append({"role": "user", "content": (
        f"<exemples_valides langue=\"{lang_name}\">\n{ex_lines}\n</exemples_valides>\n\n"
        f"<message_utilisateur>\n{message}\n</message_utilisateur>")})
    return system, messages


def parse_reply(text: Optional[str]) -> Optional[dict]:
    """Extrait {"reply", "reply_fr"} ; tolère du texte autour du JSON ou une réponse en clair."""
    if not text or not text.strip():
        return None
    text = text.strip()
    candidates = [text]
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        candidates.insert(0, m.group(0))
    for c in candidates:
        try:
            data = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and str(data.get("reply") or "").strip():
            return {"reply": str(data["reply"]).strip(), "reply_fr": (str(data.get("reply_fr") or "")).strip() or None}
    if text.startswith("{"):
        return None  # JSON cassé : on n'affiche pas du code à l'utilisateur
    return {"reply": text, "reply_fr": None}


# ---------- Gemini et Groq (API compatible OpenAI) ----------
PRESETS = {
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
               # alias qui suit toujours le dernier Flash Lite (les versions numérotées sont retirées ;
               # le Flash complet est souvent saturé sur l'offre gratuite : OKAPI_GEMINI_MODEL=gemini-flash-latest)
               "key_env": "GEMINI_API_KEY", "model": "gemini-flash-lite-latest", "label": "Gemini"},
    "groq": {"base_url": "https://api.groq.com/openai/v1",
             "key_env": "GROQ_API_KEY", "model": "openai/gpt-oss-120b", "label": "Groq"},
}


class OpenAICompatProvider:
    def __init__(self, name: str):
        p = PRESETS[name]
        up = name.upper()
        self.name, self.label = name, p["label"]
        self.base_url = os.getenv(f"OKAPI_{up}_BASE_URL", p["base_url"]).rstrip("/")
        self.key = os.getenv(p["key_env"], "")
        self.model = os.getenv(f"OKAPI_{up}_MODEL", p["model"])
        self.json_mode = True

    def configured(self) -> bool:
        return bool(self.model and self.key)

    def complete(self, system: str, messages: list[dict]) -> Optional[dict]:
        body = {"model": self.model, "temperature": 0.5, "max_tokens": 1500,
                "messages": [{"role": "system", "content": system + JSON_RULE}, *messages]}
        if self.name == "groq":
            body["reasoning_effort"] = "low"   # gpt-oss réfléchit longtemps par défaut : réponse plus rapide
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        # User-Agent explicite : le pare-feu de Groq (Cloudflare) bloque celui de Python (erreur 1010)
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.key}",
                   "User-Agent": "OkapiAI/1.0"}
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=json.dumps(body).encode(),
                                     headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            if exc.code == 400 and self.json_mode and "response_format" in detail:
                self.json_mode = False  # modèle sans mode JSON : on réessaie sans
                return self.complete(system, messages)
            # 429 = limite gratuite, 503 = service saturé : on le met de côté un moment
            raise ProviderError(f"HTTP {exc.code} : {detail}", rate_limited=exc.code in (429, 503))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderError(f"injoignable : {exc}", rate_limited=True)  # trop lent : idem
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError("réponse inattendue")
        return parse_reply(text)


# ---------- Claude (payant, paquet `anthropic`) ----------
class ClaudeProvider:
    name, label = "claude", "Claude"

    def __init__(self):
        self._client = None
        self.model = os.getenv("OKAPI_LLM_MODEL", "claude-opus-5-5")
        self.effort = os.getenv("OKAPI_LLM_EFFORT", "low")  # conversation courte : effort bas suffit

    def configured(self) -> bool:
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))

    def complete(self, system: str, messages: list[dict]) -> Optional[dict]:
        import anthropic
        if self._client is None:
            self._client = anthropic.Anthropic(timeout=60.0)
        try:
            response = self._client.beta.messages.create(
                model=self.model, max_tokens=4000,
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                system=system, messages=messages,
                output_config={"effort": self.effort,
                               "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
            )
        except anthropic.RateLimitError:
            raise ProviderError("limite de requêtes atteinte", rate_limited=True)
        except anthropic.AuthenticationError:
            raise ProviderError("clé API invalide")
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"HTTP {exc.status_code} : {exc.message}")
        except anthropic.APIConnectionError:
            raise ProviderError("injoignable")
        if response.stop_reason in ("refusal", "max_tokens"):
            return None
        return parse_reply(next((b.text for b in response.content if b.type == "text"), None))


# ---------- Relais ----------
class LLMChain:
    def __init__(self):
        order = os.getenv("OKAPI_LLM_PROVIDERS", "gemini,groq")
        self.providers = []
        for name in (n.strip().lower() for n in order.split(",") if n.strip()):
            if name == "claude":
                self.providers.append(ClaudeProvider())
            elif name in PRESETS:
                self.providers.append(OpenAICompatProvider(name))
            else:
                log.warning("Service IA inconnu ignoré : %s", name)
        self._paused: dict[str, float] = {}
        self._lock = threading.Lock()
        self.last_provider: Optional[str] = None

    def active(self) -> list:
        if os.getenv("OKAPI_LLM_ENABLED") == "0":
            return []
        return [p for p in self.providers if p.configured()]

    def names(self) -> list[str]:
        return [p.label for p in self.active()]

    def enabled(self) -> bool:
        return bool(self.active())

    def reply(self, lang: str, message: str, history: list[dict], examples: list[dict],
              voice: bool = False) -> Optional[dict]:
        """{"reply", "reply_fr"} du premier service qui répond, ou None.
        `voice` : conversation orale en direct (réponses courtes qui relancent l'échange)."""
        if not self.active():
            return None
        return self._run(*build_messages(lang, message, history, examples, voice=voice))

    def translate(self, lang: str, text: str, hints: list[dict]) -> Optional[dict]:
        """Traduction stricte français -> `lang` : {"reply": traduction, "reply_fr": retraduction}."""
        if not self.active():
            return None
        lang_name = LANGUAGES[lang]
        system = TRANSLATE_TEMPLATE.format(lang_details=LANG_DETAILS.get(lang, lang_name),
                                           phrasebook=PHRASEBOOK.get(lang, ""))
        ex = "\n".join(f"- {h['texte']}  =  {h['sens']}" for h in hints) or "(aucun)"
        return self._run(system, [{"role": "user", "content": (
            f"<mots_utiles langue=\"{lang_name}\">\n{ex}\n</mots_utiles>\n\n"
            f"<phrase_a_traduire>\n{text}\n</phrase_a_traduire>")}])

    def _run(self, system: str, messages: list[dict]) -> Optional[dict]:
        providers = self.active()
        now = time.monotonic()
        ready = [p for p in providers if self._paused.get(p.name, 0) <= now] or providers
        for p in ready:
            try:
                out = p.complete(system, messages)
            except ProviderError as exc:
                log.warning("IA %s : %s -> service suivant", p.label, exc)
                if exc.rate_limited:
                    with self._lock:
                        self._paused[p.name] = time.monotonic() + COOLDOWN
                continue
            except Exception as exc:  # ne jamais casser la conversation à cause d'une IA
                log.warning("IA %s : erreur inattendue %s -> service suivant", p.label, exc)
                continue
            if out:
                self.last_provider = p.label
                return out
        return None


ai_chat = LLMChain()
claude_chat = ai_chat  # ancien nom, gardé pour compatibilité
