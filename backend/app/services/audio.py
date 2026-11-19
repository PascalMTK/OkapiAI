import uuid

from fastapi import HTTPException, UploadFile

from ..config import AUDIO_DIR, MAX_AUDIO_BYTES

_EXT = {
    "audio/webm": ".webm", "audio/ogg": ".ogg", "audio/wav": ".wav", "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/x-m4a": ".m4a",
}


async def save_audio(upload: UploadFile) -> str:
    """Enregistre le fichier audio et retourne son nom (relatif à AUDIO_DIR)."""
    ctype = (upload.content_type or "").split(";")[0].strip()
    if ctype not in _EXT:
        raise HTTPException(400, f"Format audio non supporté : {ctype or 'inconnu'}")
    data = await upload.read()
    if not data:
        raise HTTPException(400, "Fichier audio vide")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Fichier audio trop volumineux (max 10 Mo)")
    name = f"{uuid.uuid4().hex}{_EXT[ctype]}"
    (AUDIO_DIR / name).write_bytes(data)
    return name
