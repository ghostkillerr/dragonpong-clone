"""Replaceable local WAV assets. Original reference sounds are not MIT assets."""
from __future__ import annotations

import os
import sys
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np

RATE = 48000
EVENT_FILES = {
    'rolling': 'Pong/Rolling.wav', 'wall': 'Pong/Ballborder.wav',
    'border': 'Pong/Border.wav', 'move': 'Pong/Move.wav',
    'serve': 'Pong/Hit.wav', 'paddle': 'Pong/Hit.wav', 'goal': 'Pong/Goal1.wav',
    'shield_on': 'Misc/shieldon.wav', 'shield_loop': 'Misc/shieldloop.wav',
    'shield_hit': 'Misc/shieldhit.wav', 'shield_off': 'Misc/shieldoff.wav',
    'silent_on': 'Misc/disappear.wav', 'silent_off': 'Misc/appear.wav',
    'win': 'Music/GAME_WON.wav', 'lose': 'Music/game_lost.wav',
}


def asset_root() -> Path:
    override = os.environ.get('DRAGONPONG_SOUND_DIR')
    if override:
        return Path(override)
    base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
    return base / 'reference_sounds' / 'Sounds'


def decode_wav(path: Path, rate: int = RATE) -> np.ndarray:
    with wave.open(str(path), 'rb') as wav:
        channels, width, source_rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
        raw = wav.readframes(wav.getnframes())
    if width == 1:
        values = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) / 128
    elif width == 2:
        values = np.frombuffer(raw, dtype='<i2').astype(np.float32) / 32768
    elif width == 3:
        triples = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        values = triples[:, 0] | triples[:, 1] << 8 | triples[:, 2] << 16
        values = ((values ^ 0x800000) - 0x800000).astype(np.float32) / 8388608
    elif width == 4:
        values = np.frombuffer(raw, dtype='<i4').astype(np.float32) / 2147483648
    else:
        raise ValueError(f'Unsupported PCM width: {width}')
    mono = values.reshape(-1, channels).mean(axis=1)
    if len(mono) == 0:
        raise ValueError(f'Empty sound: {path}')
    if source_rate != rate:
        mono = np.interp(np.arange(round(len(mono) * rate / source_rate)) * source_rate / rate,
                         np.arange(len(mono)), mono).astype(np.float32)
    return mono


class SoundBank:
    def __init__(self, root: Path | None = None):
        self.root = root if root is not None else asset_root()
        # Windows assets contain mixed case filenames; keep packages portable.
        self.files = {p.relative_to(self.root).as_posix().lower(): p
                      for p in self.root.rglob('*.wav')} if self.root.exists() else {}

    @lru_cache(maxsize=32)
    def get(self, relative: str) -> np.ndarray | None:
        path = self.files.get(relative.lower())
        return decode_wav(path) if path else None

    def event(self, kind: str) -> np.ndarray | None:
        relative = EVENT_FILES.get(kind)
        return self.get(relative) if relative else None
