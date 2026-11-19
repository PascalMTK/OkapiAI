"""Chatbot de traduction (texte) et chat vocal."""
from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from ..config import AUDIO_DIR, LANGUAGES
from ..database import get_db
from ..schemas import TranslateIn, check_langs
from ..services import translator
from ..services.audio import save_audio
from ..services.speech import recognizer

router = APIRouter(prefix="/api", tags=["chat"])


@router.get("/languages")
def languages():
    return [{"code": c, "name": n, "asr": recognizer.supports(c)} for c, n in LANGUAGES.items()]


@router.post("/translate")
def translate(body: TranslateIn, db: Session = Depends(get_db)):
    check_langs(body.source_lang, body.target_lang, require_congolese=False)
    return translator.translate(db, body.text, body.source_lang, body.target_lang)


@router.post("/chat")
def chat(body: TranslateIn, db: Session = Depends(get_db)):
    """Comme /translate mais formule une réponse de chatbot."""
    check_langs(body.source_lang, body.target_lang, require_congolese=False)
    res = translator.translate(db, body.text, body.source_lang, body.target_lang)
    tgt = LANGUAGES[body.target_lang]
    if res["method"] == "dataset":
        reply = f"En {tgt} : « {res['translation']} »"
    elif res["method"] == "modele":
        reply = f"En {tgt} (traduction du modèle) : « {res['translation']} »"
    elif res["method"] == "mot_a_mot":
        reply = (f"Je n'ai pas la phrase complète, voici une traduction mot à mot en {tgt} : "
                 f"« {res['translation']} ». Les mots entre [ ] sont inconnus.")
    else:
        reply = (f"Je ne connais pas encore cette phrase en {tgt}. "
                 "Si vous la connaissez, ajoutez-la dans l'onglet « Contribuer » !")
    return {"reply": reply, **res}


@router.post("/voice/chat")
async def voice_chat(
    audio: UploadFile = File(...),
    source_lang: str = Form(...),
    target_lang: str = Form(...),
    db: Session = Depends(get_db),
):
    """Reçoit un enregistrement, le transcrit (si possible) puis le traduit.

    Le fichier est conservé temporairement et son nom est renvoyé (`audio_file`)
    pour que l'utilisateur puisse ensuite l'ajouter au dataset sans le renvoyer.
    """
    check_langs(source_lang, target_lang, require_congolese=False)
    name = await save_audio(audio)
    transcript = recognizer.transcribe(AUDIO_DIR / name, source_lang)
    out = {"audio_file": name, "transcript": transcript,
           "asr_available": recognizer.supports(source_lang), "translation": None}
    if transcript:
        out["translation"] = translator.translate(db, transcript, source_lang, target_lang)
    return out
