"""Chatbot : traduction, conversation en langue nationale (texte et voix)."""
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from ..config import AUDIO_DIR, CONGOLESE, LANGUAGES
from ..database import get_db
from ..schemas import ChatTurn, ConverseIn, TranslateIn, check_langs
from ..services import conversation, translator
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


def _check_conv_lang(lang: str) -> None:
    if lang not in CONGOLESE:
        raise HTTPException(400, "La conversation se fait en lingala, swahili, kikongo ou tshiluba")


def _with_hint(res: dict) -> dict:
    if res["reply"] is None:
        res["hint"] = ("Je ne sais pas encore répondre à ce message dans cette langue. "
                       "Apprenez-moi : écrivez la réponse qu'une personne donnerait !")
    elif res["method"] == "ia":
        res["hint"] = "Réponse générée par l'IA : elle peut contenir des erreurs. Corrigez-la si besoin !"
    return res


@router.post("/converse")
def converse(body: ConverseIn, db: Session = Depends(get_db)):
    """Converser en langue nationale : le système répond dans la même langue."""
    _check_conv_lang(body.lang)
    history = [t.model_dump() for t in body.history]
    return _with_hint(conversation.converse(db, body.lang, body.message, history))


_history_adapter = TypeAdapter(list[ChatTurn])


@router.post("/voice/converse")
async def voice_converse(
    audio: UploadFile = File(...),
    lang: str = Form(...),
    history: str = Form("[]"),
    db: Session = Depends(get_db),
):
    """Conversation vocale : transcription (si disponible) puis réponse dans la même langue."""
    _check_conv_lang(lang)
    try:
        turns = [t.model_dump() for t in _history_adapter.validate_python(json.loads(history))][-20:]
    except (json.JSONDecodeError, ValidationError):
        raise HTTPException(400, "Historique invalide")
    name = await save_audio(audio)
    transcript = recognizer.transcribe(AUDIO_DIR / name, lang)
    out = {"audio_file": name, "transcript": transcript,
           "asr_available": recognizer.supports(lang), "answer": None}
    if transcript:
        out["answer"] = _with_hint(conversation.converse(db, lang, transcript, turns))
    return out
