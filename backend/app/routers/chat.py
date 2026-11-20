"""Chatbot : traduction, conversation en langue nationale (texte et voix)."""
import json
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from ..config import AUDIO_DIR, CONGOLESE, LANGUAGES
from ..database import get_db
from ..schemas import ChatTurn, ConverseIn, TranslateIn, check_langs
from ..services import conversation, translator
from ..services.audio import save_audio
from ..services.corpus import corpus
from ..services.hearing import for_lang as hearing_for
from ..services.speech import recognizer
from ..services.tts import MAX_CHARS, synthesizer

router = APIRouter(prefix="/api", tags=["chat"])
AUTO = "auto"  # voix live : détecter la langue nationale parlée


def _understand(transcript, lang: str) -> dict:
    """Écoute tolérante (lingala, tshiluba) : la phrase comprise, plus ce qui a été réellement entendu
    (`heard`) et les mots rapprochés (`fixes`), pour montrer la bonne forme à l'apprenant."""
    h = hearing_for(lang)
    if not transcript or h is None:
        return {"transcript": transcript, "heard": transcript, "fixes": []}
    try:
        r = h.correct(transcript)
        return {"transcript": r["text"], "heard": r["heard"], "fixes": r["fixes"]}
    except Exception:  # jamais bloquant : on garde ce qui a été entendu
        return {"transcript": transcript, "heard": transcript, "fixes": []}


@router.get("/languages")
def languages():
    return [{"code": c, "name": n, "asr": recognizer.supports(c), "tts": synthesizer.supports(c)}
            for c, n in LANGUAGES.items()]


@router.get("/voice/capabilities")
def voice_capabilities():
    """Ce que la voix live sait faire : reconnaissance, voix du bot, détection automatique."""
    return {"auto_detect": recognizer.auto_langs(),
            "asr": [c for c in LANGUAGES if recognizer.supports(c)],
            "tts": [c for c in LANGUAGES if synthesizer.supports(c)]}


@router.get("/tts")
def tts(text: str = Query(..., min_length=1, max_length=MAX_CHARS), lang: str = Query(...)):
    """Fait parler OkapiAI : renvoie la phrase prononcée (WAV) dans la langue nationale."""
    if lang not in LANGUAGES:
        raise HTTPException(400, "Langue inconnue")
    path = synthesizer.synthesize(text, lang)
    if path is None:
        raise HTTPException(404, f"Pas de voix disponible pour le {LANGUAGES[lang].lower()}")
    # voix affinée : elle évolue pendant l'entraînement, le navigateur ne doit pas la garder
    cache = "no-store" if "-remote-" in path.name else "public, max-age=86400"
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": cache})


@router.get("/corpus/audio/{rel:path}")
def corpus_audio(rel: str):
    """Enregistrement d'une phrase du corpus LRSC (voix d'un vrai locuteur, CC BY 4.0)."""
    path = corpus.audio_path(rel)
    if path is None:
        raise HTTPException(404, "Enregistrement introuvable")
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "public, max-age=604800"})


# Phrase d'ouverture de la voix live : OkapiAI salue et pose une question
GREETINGS = {
    "ln": ("Mbote ! Nazali OkapiAI. Ozali malamu ? Olingi tosolola na nini lelo ?",
           "Bonjour ! Je suis OkapiAI. Tu vas bien ? De quoi veux-tu qu'on parle aujourd'hui ?"),
    "sw": ("Habari ! Mimi ni OkapiAI. Habari yako ? Ungependa tuzungumze kuhusu nini leo ?",
           "Bonjour ! Je suis OkapiAI. Comment vas-tu ? De quoi aimerais-tu qu'on parle aujourd'hui ?"),
    "lua": ("Moyo webe ! Ndi OkapiAI. Udi muimpe ? Udi musue tuyukile bua tshinyi lelu ?",
            "Bonjour ! Je suis OkapiAI. Tu vas bien ? De quoi veux-tu qu'on parle aujourd'hui ?"),
}
RETRY = {  # quand la voix n'a pas été comprise
    "ln": ("Nayoki yo malamu te. Loba lisusu ?", "Je ne t'ai pas bien entendu. Tu peux répéter ?"),
    "sw": ("Sikusikia vizuri. Rudia tafadhali ?", "Je ne t'ai pas bien entendu. Tu peux répéter ?"),
    "lua": ("Tshiena mumvue bimpe. Amba kabidi ?", "Je ne t'ai pas bien entendu. Tu peux répéter ?"),
}


@router.get("/voice/start")
def voice_start(lang: str = "auto"):
    """Début de la voix live : salutation dans la langue + ce que l'on sait faire."""
    code = lang if lang in GREETINGS else "ln"
    reply, reply_fr = GREETINGS[code]
    retry = {c: {"reply": r, "reply_fr": f, "tts_url": tts_url(r, c)} for c, (r, f) in RETRY.items()}
    return {"lang": code, "reply": reply, "reply_fr": reply_fr, "tts_url": tts_url(reply, code),
            "retry": retry, "asr": recognizer.supports(code) or (lang == AUTO and bool(recognizer.auto_langs())),
            "auto_detect": recognizer.auto_langs()}


def tts_url(text: str, lang: str):
    return f"/api/tts?lang={lang}&text={quote(text)}" if text and synthesizer.supports(lang) else None


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
    heard = _understand(recognizer.transcribe(AUDIO_DIR / name, source_lang), source_lang)
    transcript = heard["transcript"]
    out = {"audio_file": name, **heard,
           "asr_available": recognizer.supports(source_lang), "translation": None}
    if transcript:
        out["translation"] = translator.translate(db, transcript, source_lang, target_lang)
    return out


def _check_conv_lang(lang: str) -> None:
    if lang not in CONGOLESE:
        raise HTTPException(400, "La conversation se fait en lingala, swahili, kikongo ou tshiluba")


def _with_hint(res: dict) -> dict:
    res["tts_url"] = None if res.get("audio_url") else tts_url(res.get("reply"), res["lang"])
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
    return _with_hint(conversation.converse(db, body.lang, body.message, history, voice=body.voice))


_history_adapter = TypeAdapter(list[ChatTurn])


@router.post("/voice/converse")
async def voice_converse(
    audio: UploadFile = File(...),
    lang: str = Form(...),
    history: str = Form("[]"),
    db: Session = Depends(get_db),
):
    """Conversation vocale : transcription puis réponse parlée dans la même langue.
    `lang="auto"` : OkapiAI reconnaît lui-même la langue nationale parlée (lingala / swahili)."""
    if lang != AUTO:
        _check_conv_lang(lang)
    try:
        turns = [t.model_dump() for t in _history_adapter.validate_python(json.loads(history))][-20:]
    except (json.JSONDecodeError, ValidationError):
        raise HTTPException(400, "Historique invalide")
    out = await _transcribe(audio, lang)
    if out["transcript"]:
        out["answer"] = _with_hint(conversation.converse(db, out["lang"], out["transcript"], turns, voice=True))
    return out


async def _transcribe(audio: UploadFile, lang: str) -> dict:
    name = await save_audio(audio)
    if lang == AUTO:
        detected, transcript = recognizer.detect_and_transcribe(AUDIO_DIR / name)
        lang = detected or "ln"
        asr = bool(recognizer.auto_langs())
    else:
        transcript, asr = recognizer.transcribe(AUDIO_DIR / name, lang), recognizer.supports(lang)
    return {"audio_file": name, **_understand(transcript, lang), "lang": lang, "asr_available": asr, "answer": None}


@router.post("/voice/transcribe")
async def voice_transcribe(audio: UploadFile = File(...), lang: str = Form(...)):
    """Voix live, 1re étape : ce que l'utilisateur a dit (et dans quelle langue).
    La réponse se demande ensuite à /api/converse avec voice=true : l'écran peut montrer
    la transcription pendant que l'IA réfléchit."""
    if lang != AUTO:
        _check_conv_lang(lang)
    return await _transcribe(audio, lang)
