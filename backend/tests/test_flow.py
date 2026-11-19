"""Test du flux complet : contributions -> seuil de 10 -> admin -> dataset d'entraînement.

Lancer depuis backend/ :  python -m pytest tests -q   (ou  python tests/test_flow.py)
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["OKAPI_DATA_DIR"] = tempfile.mkdtemp(prefix="okapi_test_")
os.environ["OKAPI_LLM_ENABLED"] = "0"  # jamais d'appel réseau pendant les tests
os.environ["OKAPI_ENV_FILE"] = os.path.join(os.environ["OKAPI_DATA_DIR"], "aucun.env")  # pas les vraies clés
os.environ["OKAPI_MODEL_DIR"] = os.path.join(os.environ["OKAPI_DATA_DIR"], "no-model")
os.environ["OKAPI_VOICE_WARMUP"] = "0"  # pas de chargement des modèles vocaux pendant les tests
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services import conversation  # noqa: E402


def _user(c, name):
    r = c.post("/api/auth/register", json={"username": name, "password": "secret123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_full_flow():
    with TestClient(app) as c:
        admin = {"Authorization": "Bearer " + c.post(
            "/api/auth/login", json={"username": "admin", "password": "admin123"}).json()["token"]}
        users = [_user(c, f"user{i}") for i in range(10)]
        item = {"source_lang": "ln", "source_text": "Mbote na yo", "target_lang": "fr",
                "target_text": "Bonjour à toi"}

        # Inconnu avant validation
        assert c.post("/api/translate", json={"text": "Mbote na yo", "source_lang": "ln",
                                              "target_lang": "fr"}).json()["translation"] is None

        # La même personne ne vote qu'une fois : les envois suivants sont refusés
        r = c.post("/api/contributions/text", json=item, headers=users[0])
        assert r.json()["support"] == 1
        pid = r.json()["proposition_id"]
        for again in (item, {**item, "source_text": "mbote na yo !"}):
            r2 = c.post("/api/contributions/text", json=again, headers=users[0])
            assert r2.status_code == 409, r2.text
        assert c.post(f"/api/contributions/proposals/{pid}/confirm", headers=users[0]).status_code == 409
        props = c.get("/api/contributions/proposals", headers=users[0]).json()
        assert next(p for p in props if p["id"] == pid)["voted"] is True
        assert next(p for p in c.get("/api/contributions/proposals", headers=users[1]).json()
                    if p["id"] == pid)["voted"] is False

        # 8 autres personnes, avec variantes proches (ponctuation / casse / faute légère)
        variants = ["mbote na yo!", "Mbote na yo.", "MBOTE NA YO", "Mbote na yo", "Mbote na yo",
                    "Mbote na yoo", "Mbote na yo", "Mbote na yo"]
        for h, v in zip(users[1:9], variants):
            r = c.post("/api/contributions/text", json={**item, "source_text": v}, headers=h)
        assert r.json()["support"] == 9 and r.json()["status"] == "collecte"

        pid = r.json()["proposition_id"]
        # L'admin ne peut pas approuver avant le minimum de 10
        assert c.post(f"/api/admin/propositions/{pid}/approve", headers=admin).status_code == 400

        # 10e personne confirme via la liste des propositions, une seule fois
        r = c.post(f"/api/contributions/proposals/{pid}/confirm", headers=users[9])
        assert r.json()["status"] == "en_attente_admin", r.json()
        assert c.post(f"/api/contributions/proposals/{pid}/confirm", headers=users[9]).status_code in (404, 409)

        pending = c.get("/api/admin/propositions", headers=admin).json()
        assert [p["id"] for p in pending] == [pid]

        # Un non-admin ne peut pas approuver
        assert c.post(f"/api/admin/propositions/{pid}/approve", headers=users[0]).status_code == 403

        assert c.post(f"/api/admin/propositions/{pid}/approve", headers=admin).status_code == 200

        # Traduction dans les deux sens depuis le dataset d'entraînement
        t = c.post("/api/translate", json={"text": "mbote na yo", "source_lang": "ln", "target_lang": "fr"}).json()
        assert t["translation"] == "Bonjour à toi" and t["method"] == "dataset"
        t = c.post("/api/translate", json={"text": "Bonjour à toi", "source_lang": "fr", "target_lang": "ln"}).json()
        assert t["translation"] == "Mbote na yo"

        # Une contribution sans rapport crée une nouvelle proposition
        r = c.post("/api/contributions/text", headers=users[0], json={
            "source_lang": "sw", "source_text": "Habari yako", "target_lang": "fr", "target_text": "Comment vas-tu"})
        assert r.json()["proposition_id"] != pid and r.json()["support"] == 1

        stats = c.get("/api/admin/stats", headers=admin).json()
        assert stats["dataset_entrainement"] == 1 and stats["dataset_collecte"] == 11

        assert c.get("/api/learn/cards?lang=ln").json()[0]["meaning"] == "Bonjour à toi"
        assert "Mbote na yo" in c.get("/api/admin/export/entrainement.jsonl", headers=admin).text


def test_voice_contribution_and_audio_access():
    with TestClient(app) as c:
        h = _user(c, "voixuser")
        other = _user(c, "autre")
        fake = ("a.webm", b"\x1a\x45\xdf\xa3fake-webm", "audio/webm")
        r = c.post("/api/contributions/voice", headers=h, files={"audio": fake}, data={
            "source_lang": "lua", "source_text": "Moyo webe", "target_lang": "fr", "target_text": "Bonjour"})
        assert r.status_code == 200, r.text
        mine = c.get("/api/contributions/mine", headers=h).json()
        url = mine[0]["audio_url"]
        assert mine[0]["kind"] == "voix" and url
        tok_h = h["Authorization"].split()[1]
        tok_o = other["Authorization"].split()[1]
        assert c.get(url).status_code == 403                      # non validée -> privée
        assert c.get(f"{url}?token={tok_o}").status_code == 403   # autre utilisateur
        assert c.get(f"{url}?token={tok_h}").status_code == 200   # propriétaire

        # Une 2e voix sur la même proposition est refusée (un seul vote)
        r = c.post("/api/contributions/voice", headers=h, files={"audio": fake}, data={
            "source_lang": "lua", "source_text": "Moyo webe", "target_lang": "fr", "target_text": "Bonjour"})
        assert r.status_code == 409, r.text

        # Ajouter sa voix à un vote texte ne crée pas de 2e vote
        item = {"source_lang": "lua", "source_text": "Wewe biani", "target_lang": "fr", "target_text": "Comment vas-tu"}
        assert c.post("/api/contributions/text", json=item, headers=other).status_code == 200
        r = c.post("/api/contributions/voice", headers=other, files={"audio": fake}, data=item)
        assert r.status_code == 200 and r.json()["support"] == 1, r.text
        mine_o = c.get("/api/contributions/mine", headers=other).json()
        assert len(mine_o) == 1 and mine_o[0]["kind"] == "voix"

        r = c.post("/api/contributions/voice", headers=h, files={"audio": ("x.txt", b"hi", "text/plain")},
                   data={"source_lang": "lua", "source_text": "a", "target_lang": "fr", "target_text": "b"})
        assert r.status_code == 400


def _admin(c):
    return {"Authorization": "Bearer " + c.post(
        "/api/auth/login", json={"username": "admin", "password": "admin123"}).json()["token"]}


def test_conversation_dialogue_and_ai():
    with TestClient(app) as c:
        admin = _admin(c)
        users = [_user(c, f"conv{i}") for i in range(10)]
        dlg = {"kind": "dialogue", "source_lang": "ln", "source_text": "Ozali malamu?",
               "target_lang": "ln", "target_text": "Ee, nazali malamu. Na yo?"}

        # Message inconnu (sans IA) : le bot demande qu'on lui apprenne la réponse
        r = c.post("/api/converse", json={"lang": "ln", "message": "Motuka na yo ezali langi nini?"}).json()
        assert r["reply"] is None and "Apprenez-moi" in r["hint"]

        # Échange de base : le bot répond dans la langue, avec la traduction française
        r = c.post("/api/converse", json={"lang": "ln", "message": "Ozali malamu?"}).json()
        assert r["method"] == "base" and r["reply"].startswith("Nazali malamu") and r["reply_fr"]

        # dialogue dans deux langues différentes : refusé ; conversation en français : refusée
        bad = {**dlg, "target_lang": "fr"}
        assert c.post("/api/contributions/text", json=bad, headers=users[0]).status_code == 400
        assert c.post("/api/converse", json={"lang": "fr", "message": "salut"}).status_code == 400

        for h in users:
            r = c.post("/api/contributions/text", json=dlg, headers=h)
        assert r.json()["status"] == "en_attente_admin" and r.json()["kind"] == "dialogue"
        pid = r.json()["proposition_id"]
        pending = c.get("/api/admin/propositions", headers=admin).json()
        assert any(p["id"] == pid and p["kind"] == "dialogue" for p in pending)
        assert c.post(f"/api/admin/propositions/{pid}/approve", headers=admin).status_code == 200

        r = c.post("/api/converse", json={"lang": "ln", "message": "ozali malamu"}).json()
        assert r["reply"] == "Ee, nazali malamu. Na yo?" and r["method"] == "dataset"

        # les dialogues ne polluent ni la traduction ni l'apprentissage
        t = c.post("/api/translate", json={"text": "Ozali malamu?", "source_lang": "ln", "target_lang": "fr"}).json()
        assert t["method"] != "dataset"
        assert all(card["text"] != "Ozali malamu?" for card in c.get("/api/learn/cards?lang=ln&limit=50").json())

        # IA simulée : reçoit les exemples validés, répond dans la langue
        seen = {}

        def fake_reply(lang, message, history, examples):
            seen.update(lang=lang, history=history, examples=examples)
            return {"reply": "Nazali malamu mingi", "reply_fr": "Je vais très bien"}

        orig_enabled, orig_reply = conversation.claude_chat.enabled, conversation.claude_chat.reply
        conversation.claude_chat.enabled = lambda: True
        conversation.claude_chat.reply = fake_reply
        try:
            r = c.post("/api/converse", json={"lang": "ln", "message": "Mbote, ozali malamu mingi?",
                                              "history": [{"role": "user", "text": "Mbote"},
                                                          {"role": "assistant", "text": "Mbote na yo"}]}).json()
        finally:
            conversation.claude_chat.enabled, conversation.claude_chat.reply = orig_enabled, orig_reply
        assert r["method"] == "ia" and r["reply"] == "Nazali malamu mingi" and r["reply_fr"] == "Je vais très bien"
        assert "erreurs" in r["hint"] and seen["lang"] == "ln" and len(seen["history"]) == 2
        assert any("Ozali malamu?" in e["texte"] for e in seen["examples"])
        # l'IA reçoit aussi des phrases de lingala correct du corpus LRSC
        assert any("LRSC" in e["sens"] for e in seen["examples"]), seen["examples"]


def test_word_meaning():
    from app.services.conversation import parse_word_question
    assert parse_word_question("Que veut dire ndako ?") == ("sens", "ndako")
    assert parse_word_question("C'est quoi le mot « mwasi » ?") == ("sens", "mwasi")
    assert parse_word_question("Ndako elingi koloba nini?") == ("sens", "ndako")
    assert parse_word_question("Signification de mbote en lingala") == ("sens", "mbote")
    assert parse_word_question("Comment dit-on maison en lingala ?") == ("traduire", "maison")
    assert parse_word_question("Mbote, ozali malamu?") is None

    with TestClient(app) as c:
        ask = lambda msg: c.post("/api/converse", json={"lang": "ln", "message": msg}).json()
        r = ask("Que veut dire ndako ?")
        assert r["method"] == "lexique" and "elingi koloba" in r["reply"] and "maison" in r["reply"], r
        assert "signifie" in r["reply_fr"] and r["word"]["meanings"][0]["word"] == "ndáko"

        r = ask("ndako")  # mot seul
        assert r["method"] == "lexique" and "maison" in r["reply"]
        # exemple d'usage tiré du corpus LRSC (avec l'enregistrement s'il est présent sur le disque)
        assert r["example"] and "ndako" in r["example"]["text"] and "LRSC" in r["example"]["source"]
        if r["example"]["audio_url"]:
            audio = c.get(r["example"]["audio_url"])
            assert audio.status_code == 200 and audio.headers["content-type"] == "audio/wav"
        assert c.get("/api/corpus/audio/../../.env").status_code == 404  # pas d'accès hors du corpus
        assert c.get("/api/corpus/audio/train/..%2F..%2Fmetadata.jsonl").status_code == 404

        r = ask("mbɔ́tɛ elingi koloba nini?")  # avec les tons
        assert r["method"] == "lexique" and "bonjour" in r["reply"]

        r = ask("Comment dit-on maison en lingala ?")
        assert r["method"] == "lexique" and "ndáko" in r["reply"] and r["reply"].startswith("Na lingala")

        r = ask("Que veut dire xqzwv ?")  # mot inconnu : réponse en lingala, pas d'invention
        assert r["method"] == "inconnu" and r["reply"].startswith("Nayebi naino")

        # Un mot validé par la communauté passe avant le dictionnaire
        users = [_user(c, f"mot{i}") for i in range(10)]
        item = {"source_lang": "ln", "source_text": "matondi", "target_lang": "fr", "target_text": "merci"}
        for h in users:
            r2 = c.post("/api/contributions/text", json=item, headers=h)
        pid = r2.json()["proposition_id"]
        assert c.post(f"/api/admin/propositions/{pid}/approve", headers=_admin(c)).status_code == 200
        r = ask("que signifie matondi")
        assert r["method"] == "dataset" and "merci" in r["reply"]


def test_voice_live_conversation():
    """Voix live : langue détectée, réponse dans cette langue, avec une voix à écouter."""
    from app.routers import chat as chat_router
    from app.services.tts import synthesizer

    rec, syn = chat_router.recognizer, synthesizer
    saved = (rec.detect_and_transcribe, rec.auto_langs, rec.transcribe, rec.supports, syn.supports, syn.synthesize)
    wav = Path(os.environ["OKAPI_DATA_DIR"]) / "fake.wav"
    wav.write_bytes(b"RIFF0000WAVEfmt ")
    try:
        rec.auto_langs = lambda: ["ln", "sw"]
        rec.detect_and_transcribe = lambda path: ("sw", "habari yako")
        rec.supports = lambda lang: lang in ("ln", "sw")
        rec.transcribe = lambda path, lang: "mbote"
        syn.supports = lambda lang: lang in ("ln", "sw")
        syn.synthesize = lambda text, lang: wav if lang in ("ln", "sw") else None
        fake = ("a.webm", b"\x1a\x45\xdf\xa3fake-webm", "audio/webm")
        with TestClient(app) as c:
            caps = c.get("/api/voice/capabilities").json()
            assert caps["auto_detect"] == ["ln", "sw"] and "ln" in caps["tts"]

            # détection automatique : l'utilisateur parle swahili -> OkapiAI répond en swahili
            r = c.post("/api/voice/converse", files={"audio": fake}, data={"lang": "auto"}).json()
            assert r["lang"] == "sw" and r["transcript"] == "habari yako"
            assert r["answer"]["method"] == "base" and r["answer"]["reply"].startswith("Nzuri")
            assert r["answer"]["tts_url"].startswith("/api/tts?lang=sw&text=")

            # langue choisie : lingala
            r = c.post("/api/voice/converse", files={"audio": fake}, data={"lang": "ln"}).json()
            assert r["lang"] == "ln" and r["answer"]["reply"].startswith("Mbote")
            audio = c.get(r["answer"]["tts_url"])
            assert audio.status_code == 200 and audio.headers["content-type"] == "audio/wav"

            # pas de voix pour le kikongo : pas d'URL, et /api/tts répond 404
            r = c.post("/api/converse", json={"lang": "kg", "message": "mbote"}).json()
            assert r.get("tts_url") is None
            assert c.get("/api/tts", params={"lang": "kg", "text": "mbote"}).status_code == 404
    finally:
        (rec.detect_and_transcribe, rec.auto_langs, rec.transcribe, rec.supports, syn.supports, syn.synthesize) = saved


def test_free_ai_relay():
    """Gemini atteint sa limite gratuite (429) -> OkapiAI passe à Groq ; puis Gemini est mis de côté."""
    import json as _json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from app.services import llm

    calls = []

    class Fake(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = _json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            service = self.path.split("/")[1]
            calls.append((service, self.headers["Authorization"], body["model"]))
            if service == "gemini":
                self.send_response(429)
                self.end_headers()
                self.wfile.write(b'{"error": "quota"}')
                return
            content = 'Voici : {"reply": "Nazali malamu, bongo yo?", "reply_fr": "Je vais bien, et toi ?"}'
            payload = _json.dumps({"choices": [{"message": {"content": content}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)

    server = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    env = {"GEMINI_API_KEY": "g-key", "GROQ_API_KEY": "q-key",
           "OKAPI_GEMINI_BASE_URL": f"http://127.0.0.1:{port}/gemini",
           "OKAPI_GROQ_BASE_URL": f"http://127.0.0.1:{port}/groq",
           "OKAPI_LLM_PROVIDERS": "gemini,groq", "OKAPI_LLM_ENABLED": "1"}
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        chain = llm.LLMChain()
        assert chain.names() == ["Gemini", "Groq"]
        r = chain.reply("ln", "Ozali malamu?", [], [])
        assert r == {"reply": "Nazali malamu, bongo yo?", "reply_fr": "Je vais bien, et toi ?"}
        assert chain.last_provider == "Groq"
        assert [c[0] for c in calls] == ["gemini", "groq"]
        assert calls[0][1] == "Bearer g-key" and calls[1][2] == "openai/gpt-oss-120b"
        # Gemini limité : il est mis de côté, le message suivant va directement à Groq
        chain.reply("ln", "Sango nini?", [], [])
        assert [c[0] for c in calls] == ["gemini", "groq", "groq"]
        # aucune clé -> aucune IA
        for k in ("GEMINI_API_KEY", "GROQ_API_KEY"):
            os.environ.pop(k)
        assert llm.LLMChain().enabled() is False
    finally:
        server.shutdown()
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    assert llm.parse_reply("Mbote!") == {"reply": "Mbote!", "reply_fr": None}
    assert llm.parse_reply('{"reply": ') is None


if __name__ == "__main__":
    test_free_ai_relay()
    test_full_flow()
    test_voice_contribution_and_audio_access()
    test_conversation_dialogue_and_ai()
    test_word_meaning()
    test_voice_live_conversation()
    print("OK")
