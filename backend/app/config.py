"""Configuration centrale d'OkapiAI (surchargeable par variables d'environnement)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # backend/
ROOT_DIR = BASE_DIR.parent                                  # racine du projet


def _load_env_file(path: Path) -> None:
    """Charge backend/.env (CLE=valeur par ligne) sans écraser les variables déjà définies."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env_file(Path(os.getenv("OKAPI_ENV_FILE", BASE_DIR / ".env")))
FRONTEND_DIR = ROOT_DIR / "frontend"
# Corpus lingala (dictionnaires Wiktionnaire / Wikipédia) utilisé pour expliquer les mots
DATASET_DIR = Path(os.getenv("OKAPI_DATASET_DIR", ROOT_DIR / "dataset"))

DATA_DIR = Path(os.getenv("OKAPI_DATA_DIR", BASE_DIR / "data"))
AUDIO_DIR = DATA_DIR / "audio"
MODEL_DIR = Path(os.getenv("OKAPI_MODEL_DIR", BASE_DIR / "models" / "okapi-nllb"))

DATA_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv("OKAPI_DATABASE_URL", f"sqlite:///{(DATA_DIR / 'okapiai.db').as_posix()}")

SECRET_KEY = os.getenv("OKAPI_SECRET_KEY", "change-moi-en-production-avec-une-cle-longue-et-secrete")
TOKEN_HOURS = int(os.getenv("OKAPI_TOKEN_HOURS", "72"))

# Compte admin créé au premier démarrage s'il n'existe aucun admin
ADMIN_USERNAME = os.getenv("OKAPI_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("OKAPI_ADMIN_PASSWORD", "admin123")

# --- Règles de validation du dataset ---
# Nombre minimum de contributions similaires (de personnes DIFFÉRENTES)
# avant qu'une proposition soit envoyée à l'admin.
MIN_SIMILAR = int(os.getenv("OKAPI_MIN_SIMILAR", "10"))
# Seuil de similarité textuelle (0..1) pour considérer deux contributions comme "similaires".
SIMILARITY_THRESHOLD = float(os.getenv("OKAPI_SIMILARITY_THRESHOLD", "0.85"))
# Seuil pour qu'une recherche de traduction dans le dataset soit acceptée.
LOOKUP_THRESHOLD = float(os.getenv("OKAPI_LOOKUP_THRESHOLD", "0.80"))

MAX_AUDIO_BYTES = 10 * 1024 * 1024

LANGUAGES = {
    "fr": "Français",
    "ln": "Lingala",
    "sw": "Swahili",
    "kg": "Kikongo",
    "lua": "Tshiluba",
}
CONGOLESE = {"ln", "sw", "kg", "lua"}

# Codes NLLB-200 (modèle de traduction Meta, supporte les 4 langues)
NLLB_CODES = {
    "fr": "fra_Latn",
    "ln": "lin_Latn",
    "sw": "swh_Latn",
    "kg": "kon_Latn",
    "lua": "lua_Latn",
}
