"""Conversation libre en langue nationale via Claude (optionnel).

Activé seulement si le paquet `anthropic` est installé ET qu'une clé est configurée
(ANTHROPIC_API_KEY ou ANTHROPIC_AUTH_TOKEN), ou si OKAPI_LLM_ENABLED=1.
Le modèle est ancré sur le vocabulaire validé par la communauté (exemples envoyés
avec chaque message) : il doit privilégier ces mots et tournures.
"""
import json
import logging
import os
from typing import Optional

from ..config import LANGUAGES

log = logging.getLogger("okapiai.llm")

LLM_MODEL = os.getenv("OKAPI_LLM_MODEL", "claude-opus-5-5")
LLM_EFFORT = os.getenv("OKAPI_LLM_EFFORT", "low")  # conversation courte : effort bas suffit

LANG_DETAILS = {
    "ln": "lingala (tel que parlé à Kinshasa et dans l'ouest de la RDC)",
    "sw": "swahili (de préférence le swahili du Congo / kingwana, tel que parlé dans l'est de la RDC)",
    "kg": "kikongo (tel que parlé en RDC ; kikongo ya leta si l'utilisateur l'emploie)",
    "lua": "tshiluba / ciluba (luba-kasaï, tel que parlé au Kasaï en RDC)",
}

SYSTEM_TEMPLATE = """Tu es OkapiAI, un assistant conversationnel congolais. Tu converses avec l'utilisateur en {lang_details}.

Règles :
- Réponds TOUJOURS dans cette langue, même si l'utilisateur écrit en français ou dans une autre langue.
- Phrases courtes, simples et naturelles, adaptées à l'oral (la réponse peut être lue à voix haute).
- Les exemples validés par la communauté (fournis avec chaque message) sont la référence : réutilise leur vocabulaire, leur orthographe et leurs tournures quand c'est pertinent.
- Si tu n'es pas sûr d'un mot, choisis une formulation plus simple que tu maîtrises plutôt que d'inventer un mot.
- Sois chaleureux et respectueux, comme dans une conversation entre Congolais.
- Fournis aussi une traduction française fidèle de ta réponse, pour les personnes qui apprennent la langue."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string", "description": "La réponse dans la langue de la conversation"},
        "reply_fr": {"type": "string", "description": "Traduction française de la réponse"},
    },
    "required": ["reply", "reply_fr"],
    "additionalProperties": False,
}


class ClaudeChat:
    def __init__(self):
        self._client = None

    def enabled(self) -> bool:
        if os.getenv("OKAPI_LLM_ENABLED") == "0":
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")
                    or os.getenv("OKAPI_LLM_ENABLED") == "1")

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(timeout=60.0)
        return self._client

    def reply(self, lang: str, message: str, history: list[dict],
              examples: list[dict]) -> Optional[dict]:
        """Retourne {"reply", "reply_fr"} ou None si indisponible / refus / erreur."""
        if not self.enabled():
            return None
        import anthropic

        lang_name = LANGUAGES[lang]
        system = SYSTEM_TEMPLATE.format(lang_details=LANG_DETAILS.get(lang, lang_name))

        # historique : doit commencer par "user" et alterner
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

        try:
            response = self._get_client().beta.messages.create(
                model=LLM_MODEL,
                max_tokens=4000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=system,
                messages=messages,
                output_config={"effort": LLM_EFFORT,
                               "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
            )
        except anthropic.AuthenticationError:
            log.error("Clé API Claude invalide : conversation IA désactivée")
            return None
        except anthropic.RateLimitError:
            log.warning("Limite de requêtes Claude atteinte")
            return None
        except anthropic.APIStatusError as exc:
            log.warning("Erreur API Claude %s : %s", exc.status_code, exc.message)
            return None
        except anthropic.APIConnectionError:
            log.warning("Impossible de joindre l'API Claude")
            return None

        if response.stop_reason in ("refusal", "max_tokens"):
            log.info("Réponse IA non utilisable (stop_reason=%s)", response.stop_reason)
            return None
        text = next((b.text for b in response.content if b.type == "text"), None)
        if not text:
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        if not data.get("reply"):
            return None
        return {"reply": data["reply"].strip(), "reply_fr": (data.get("reply_fr") or "").strip() or None}


claude_chat = ClaudeChat()
