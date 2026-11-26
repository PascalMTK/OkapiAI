"""Point d'entrée OkapiAI.  Lancer :  uvicorn app.main:app --reload  (depuis backend/)"""
import logging
import os
import re
import threading
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from .config import ADMIN_PASSWORD, ADMIN_USERNAME, AUDIO_DIR, FRONTEND_DIR, MIN_SIMILAR
from .database import Base, SessionLocal, engine, get_db
from .models import Contribution, TrainingEntry, User
from .routers import admin, auth, chat, contributions, learn
from .security import hash_password, user_from_token
from .services.llm import claude_chat
from .services.speech import recognizer
from .services.tts import synthesizer

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("okapiai")


def _bootstrap_admin() -> None:
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.is_admin.is_(True))):
            return
        existing = db.scalar(select(User).where(User.username == ADMIN_USERNAME))
        if existing:
            existing.is_admin = True
        else:
            db.add(User(username=ADMIN_USERNAME, password_hash=hash_password(ADMIN_PASSWORD), is_admin=True))
        db.commit()
        log.warning("Compte admin '%s' prêt. Changez le mot de passe (OKAPI_ADMIN_PASSWORD) !", ADMIN_USERNAME)


def _migrate() -> None:
    """Ajoute les colonnes apparues après la première version (bases existantes)."""
    insp = inspect(engine)
    for table in ("propositions", "dataset_entrainement"):
        if "kind" not in {c["name"] for c in insp.get_columns(table)}:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN kind VARCHAR(16) NOT NULL DEFAULT 'traduction'"))
            log.info("Migration : colonne 'kind' ajoutée à %s", table)

    # Un seul vote par personne et par proposition : fusionner les doublons
    # (on garde la contribution la plus ancienne, avec la première voix trouvée), puis index unique.
    if "uq_collecte_user_proposition" not in {i["name"] for i in insp.get_indexes("dataset_collecte")}:
        with engine.begin() as conn:
            dupes = conn.execute(text(
                "SELECT user_id, proposition_id FROM dataset_collecte "
                "GROUP BY user_id, proposition_id HAVING COUNT(*) > 1")).all()
            removed = 0
            for user_id, prop_id in dupes:
                rows = conn.execute(text(
                    "SELECT id, audio_path FROM dataset_collecte WHERE user_id = :u AND proposition_id = :p "
                    "ORDER BY id"), {"u": user_id, "p": prop_id}).all()
                keep = rows[0]
                audio = keep.audio_path or next((r.audio_path for r in rows if r.audio_path), None)
                if audio and not keep.audio_path:
                    conn.execute(text("UPDATE dataset_collecte SET audio_path = :a, kind = 'voix' WHERE id = :i"),
                                 {"a": audio, "i": keep.id})
                ids = [r.id for r in rows[1:]]
                conn.execute(text(f"DELETE FROM dataset_collecte WHERE id IN ({','.join(map(str, ids))})"))
                removed += len(ids)
            conn.execute(text("CREATE UNIQUE INDEX uq_collecte_user_proposition "
                              "ON dataset_collecte (user_id, proposition_id)"))
        log.info("Migration : un vote par personne (%d doublon(s) fusionné(s))", removed)


def _prepare_live_phrases() -> None:
    """Salutation et « répète » de la voix live, synthétisés d'avance dans chaque langue."""
    from .routers.chat import GREETINGS, RETRY
    synthesizer.prepare([(text, lang) for table in (GREETINGS, RETRY) for lang, (text, _) in table.items()])


def _warm_language_data() -> None:
    try:
        from .services.corpus import corpus, corpus_lua
        from .services.hearing import for_lang
        from .services.lexicon import lexicon
        lexicon.size(), corpus.size(), corpus_lua.size()
        for lang in ("ln", "lua"):
            h = for_lang(lang)
            if h is not None:
                h.correct("mbote")
    except Exception as exc:  # jamais bloquant : tout se chargera au 1er message
        log.warning("Préchargement des données de langue : %s", exc)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    _migrate()
    _bootstrap_admin()
    log.info("Conversation IA : %s", f"activée ({' → '.join(claude_chat.names())})" if claude_chat.enabled() else
             "désactivée (ajoutez GEMINI_API_KEY, GROQ_API_KEY ou OPENROUTER_API_KEY dans backend/.env)")
    if os.getenv("OKAPI_VOICE_WARMUP", "1") == "1":
        # Charge la reconnaissance vocale et les voix sans bloquer le démarrage du serveur
        threading.Thread(target=lambda: (recognizer.warmup(), synthesizer.warmup(), _prepare_live_phrases()),
                         daemon=True).start()
        # Dictionnaire et corpus chargés d'avance : sinon le 1er message après un démarrage attend ~10 s
        threading.Thread(target=_warm_language_data, daemon=True).start()
        # Entraînement d'une voix en cours : les modèles laissent la carte graphique, puis y reviennent
        from .services.gpu import watch
        watch([recognizer.mms.move, recognizer.lua.move, synthesizer.move])
    yield


app = FastAPI(title="OkapiAI", version="0.1.0", lifespan=lifespan,
              description="Traduction, voix et apprentissage : lingala, swahili, kikongo, tshiluba.")

for r in (auth.router, chat.router, contributions.router, learn.router, admin.router):
    app.include_router(r)


@app.middleware("http")
async def revalidate_frontend(request, call_next):
    """Le navigateur doit revérifier l'interface à chaque visite : après une mise à jour,
    une ancienne version de app.js en cache ne casse plus la page."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/api/features")
def features():
    return {"ai_conversation": claude_chat.enabled(), "min_similar": MIN_SIMILAR,
            "speech_recognition": [c for c in ("fr", "ln", "sw") if recognizer.supports(c)]}


_AUDIO_NAME = re.compile(r"^[0-9a-f]{32}\.(webm|ogg|wav|mp3|m4a)$")


@app.get("/api/audio/{name}")
def get_audio(name: str, token: Optional[str] = None, db: Session = Depends(get_db)):
    """Les voix validées sont publiques ; les voix brutes sont réservées à l'admin
    (passer ?token=... car la balise <audio> n'envoie pas d'en-tête Authorization)."""
    if not _AUDIO_NAME.match(name) or not (AUDIO_DIR / name).exists():
        raise HTTPException(404, "Audio introuvable")
    public = db.scalar(select(TrainingEntry.id).where(TrainingEntry.audio_path == name))
    if not public:
        user = user_from_token(token, db) if token else None
        owner = user and db.scalar(select(Contribution.id).where(
            Contribution.audio_path == name, Contribution.user_id == user.id))
        if not (user and (user.is_admin or owner)):
            raise HTTPException(403, "Audio non validé")
    return FileResponse(AUDIO_DIR / name)


@app.get("/admin", include_in_schema=False)
@app.get("/admin/", include_in_schema=False)
def admin_page():
    """Lien direct vers le panneau admin : même page, l'onglet Admin s'ouvre automatiquement."""
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
