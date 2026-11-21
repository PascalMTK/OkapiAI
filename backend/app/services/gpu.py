"""Partage de la carte graphique avec l'entraînement des voix.

Pendant `tools/train_voice.py train`, le fichier models/entrainement-en-cours.json existe : les modèles
du site (reconnaissance vocale, voix MMS) passent alors sur le processeur pour laisser la carte (4 Go)
à l'entraînement, et reviennent sur la carte quand il se termine. Le site reste en ligne, juste plus lent.
Un fichier laissé par un entraînement interrompu (processus disparu) est ignoré.
"""
import json
import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger("okapiai.gpu")

TRAINING_FLAG = Path(__file__).resolve().parents[2] / "models" / "entrainement-en-cours.json"
CHECK_S = 5.0


def _alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259    # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def training_active() -> bool:
    try:
        pid = int(json.loads(TRAINING_FLAG.read_text(encoding="utf-8"))["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return _alive(pid)


def preferred_device(override: str = "auto") -> str:
    """cuda si la carte est libre, cpu pendant un entraînement (ou si `override` l'impose)."""
    if override in ("cpu", "cuda"):
        return override
    try:
        import torch
        has_cuda = torch.cuda.is_available()
    except ImportError:
        return "cpu"
    return "cuda" if has_cuda and not training_active() else "cpu"


def watch(movers: list) -> None:
    """Toutes les 5 s : si l'entraînement démarre ou finit, chaque `mover(device)` déplace ses modèles."""
    def loop():
        last = None
        while True:
            dev = preferred_device()
            if dev != last:
                if last is not None:
                    log.info("Carte graphique %s : modèles du site sur %s",
                             "prise par l'entraînement" if dev == "cpu" else "libérée", dev)
                for move in movers:
                    try:
                        move(dev)
                    except Exception as exc:
                        log.warning("Déplacement vers %s impossible : %s", dev, exc)
                if dev == "cpu":
                    try:
                        import torch
                        torch.cuda.empty_cache()
                    except Exception:
                        pass
                last = dev
            time.sleep(CHECK_S)
    threading.Thread(target=loop, daemon=True, name="gpu-watch").start()
