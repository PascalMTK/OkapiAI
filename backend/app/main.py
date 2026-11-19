"""Point d'entrée OkapiAI.  Lancer :  uvicorn app.main:app --reload  (depuis backend/)"""
import logging
import re
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from .config import ADMIN_PASSWORD, ADMIN_USERNAME, AUDIO_DIR, FRONTEND_DIR
from .database import Base, SessionLocal, engine, get_db
from .models import Contribution, TrainingEntry, User
from .routers import admin, auth, chat, contributions, learn
from .security import hash_password, user_from_token
from .services.llm import claude_chat
from .services.speech import recognizer

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


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    _migrate()
    _bootstrap_admin()
    log.info("Conversation IA : %s", "activée" if claude_chat.enabled() else
             "désactivée (installez 'anthropic' et définissez ANTHROPIC_API_KEY)")
    yield


app = FastAPI(title="OkapiAI", version="0.1.0", lifespan=lifespan,
              description="Traduction, voix et apprentissage : lingala, swahili, kikongo, tshiluba.")

for r in (auth.router, chat.router, contributions.router, learn.router, admin.router):
    app.include_router(r)

@app.get("/api/features")
def features():
    return {"ai_conversation": claude_chat.enabled(),
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


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
