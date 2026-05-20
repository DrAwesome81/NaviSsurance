from __future__ import annotations

import os
import threading
import time
from typing import Optional

from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QApplication, QWidget

from config import PROJECT_ROOT

try:
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
except Exception:
    QAudioOutput = None
    QMediaPlayer = None

# Pulse/Intel raised items and 🛡️ [Security-Relevant] from private memory can drive proactive notifications (Intelligence & Coordination tie-in)
# New: notifications now explicitly support Pulse private memory for Shield (additional notifications spot)
# Pulse private memory + Shield (notifications surface)
_SOUND_PATTERNS: dict[str, list[tuple[int, int]]] = {
    "chat": [(740, 45), (988, 70)],
    "complete": [(659, 80), (880, 90), (1175, 140)],
}
_NOTIFICATION_AUDIO_PATH = os.path.join(PROJECT_ROOT, "assets", "freesound_community-ding-36029.mp3")
_MEDIA_PLAYERS: dict[str, tuple[object, object]] = {}


def _play_asset_sound(kind: str) -> bool:
    if QMediaPlayer is None or QAudioOutput is None or not os.path.exists(_NOTIFICATION_AUDIO_PATH):
        return False
    try:
        player_info = _MEDIA_PLAYERS.get(kind)
        if player_info is None:
            audio = QAudioOutput()
            player = QMediaPlayer()
            player.setAudioOutput(audio)
            player.setSource(QUrl.fromLocalFile(_NOTIFICATION_AUDIO_PATH))
            _MEDIA_PLAYERS[kind] = (player, audio)
        else:
            player, audio = player_info
        audio.setVolume(0.55 if kind == "chat" else 0.72)
        player.stop()
        player.setPosition(0)
        player.play()
        return True
    except Exception:
        return False


def _play_beep_pattern(kind: str) -> bool:
    try:
        import winsound

        pattern = _SOUND_PATTERNS.get(kind) or _SOUND_PATTERNS["complete"]

        def _worker() -> None:
            for idx, (freq, duration_ms) in enumerate(pattern):
                try:
                    winsound.Beep(int(freq), int(duration_ms))
                except Exception:
                    break
                if idx < len(pattern) - 1:
                    time.sleep(0.03)

        threading.Thread(target=_worker, daemon=True).start()
        return True
    except Exception:
        return False


def play_notification_sound(kind: str = "complete") -> None:
    if _play_asset_sound(kind):
        return
    if _play_beep_pattern(kind):
        return
    try:
        app = QApplication.instance()
        if app is not None:
            app.beep()
    except Exception:
        pass


def _window(widget: Optional[QWidget]) -> Optional[QWidget]:
    if widget is None:
        return None
    try:
        return widget.window()
    except Exception:
        return None


def notify_chat_response(widget: Optional[QWidget], source: str = "Navi") -> None:
    win = _window(widget)
    if win is not None and hasattr(win, "notify_chat_response"):
        try:
            win.notify_chat_response(source)
            return
        except Exception:
            pass
    play_notification_sound("chat")


def notify_background_complete(widget: Optional[QWidget], title: str, message: str) -> None:
    win = _window(widget)
    if win is not None and hasattr(win, "notify_background_complete"):
        try:
            win.notify_background_complete(title, message)
            return
        except Exception:
            pass
    play_notification_sound("complete")
