"""Test du flux complet : contributions -> seuil de 10 -> admin -> dataset d'entraînement.

Lancer depuis backend/ :  python -m pytest tests -q   (ou  python tests/test_flow.py)
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["OKAPI_DATA_DIR"] = tempfile.mkdtemp(prefix="okapi_test_")
os.environ["OKAPI_LLM_ENABLED"] = "0"  # jamais d'appel réseau pendant les tests
os.environ["OKAPI_MODEL_DIR"] = os.path.join(os.environ["OKAPI_DATA_DIR"], "no-model")
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

        # La même personne ne compte qu'une fois
        for _ in range(3):
            r = c.post("/api/contributions/text", json=item, headers=users[0])
        assert r.json()["support"] == 1

        # 8 autres personnes, avec variantes proches (ponctuation / casse / faute légère)
        variants = ["mbote na yo!", "Mbote na yo.", "MBOTE NA YO", "Mbote na yo", "Mbote na yo",
                    "Mbote na yoo", "Mbote na yo", "Mbote na yo"]
        for h, v in zip(users[1:9], variants):
            r = c.post("/api/contributions/text", json={**item, "source_text": v}, headers=h)
        assert r.json()["support"] == 9 and r.json()["status"] == "collecte"

        pid = r.json()["proposition_id"]
        # L'admin ne peut pas approuver avant le minimum de 10
        assert c.post(f"/api/admin/propositions/{pid}/approve", headers=admin).status_code == 400

        # 10e personne confirme via la liste des propositions
        r = c.post(f"/api/contributions/proposals/{pid}/confirm", headers=users[9])
        assert r.json()["status"] == "en_attente_admin", r.json()

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
        assert stats["dataset_entrainement"] == 1 and stats["dataset_collecte"] == 13

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

        r = c.post("/api/converse", json={"lang": "ln", "message": "Ozali malamu?"}).json()
        assert r["reply"] is None and "Apprenez-moi" in r["hint"]

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


if __name__ == "__main__":
    test_full_flow()
    test_voice_contribution_and_audio_access()
    test_conversation_dialogue_and_ai()
    print("OK")
