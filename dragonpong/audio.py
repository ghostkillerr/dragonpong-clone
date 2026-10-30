"""Original procedural sounds rendered through measured MIT KEMAR HRTFs.

An analytic binaural fallback remains available when the optional dataset is absent.
"""

from __future__ import annotations

import math
import threading
import io
import re
import wave
import zipfile
from functools import lru_cache
from pathlib import Path

import numpy as np

from .engine import COURT_LENGTH, Event
from .soundbank import SoundBank

RATE = 48_000
KEMAR_ZIP = Path(__file__).resolve().parents[1] / "assets" / "mit-kemar-compact.zip"


class KemarHRTF:
    """MIT KEMAR compact measured HRIRs, resampled from 44.1 to 48 kHz."""

    def __init__(self, path: Path = KEMAR_ZIP) -> None:
        self.responses: dict[tuple[int, int], np.ndarray] = {}
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                match = re.search(r"H(-?\d+)e(\d+)a\.wav$", name, re.IGNORECASE)
                if not match:
                    continue
                elevation, azimuth = map(int, match.groups())
                with wave.open(io.BytesIO(archive.read(name))) as sound:
                    if (sound.getnchannels(), sound.getsampwidth(), sound.getframerate()) != (2, 2, 44100):
                        raise ValueError("unexpected KEMAR HRIR format")
                    raw = np.frombuffer(sound.readframes(sound.getnframes()), dtype="<i2")
                samples = raw.reshape(-1, 2).astype(np.float32) / 32768.0
                source = np.arange(len(samples), dtype=np.float32) / 44100
                target = np.arange(round(len(samples) * RATE / 44100), dtype=np.float32) / RATE
                self.responses[elevation, azimuth] = np.column_stack(
                    [np.interp(target, source, samples[:, channel]) for channel in (0, 1)]
                ).astype(np.float32)
        if not self.responses:
            raise ValueError("KEMAR dataset is empty")

    def response(self, azimuth: float, elevation: float) -> np.ndarray:
        azimuth = max(-180.0, min(180.0, azimuth))
        elevation = max(-40.0, min(90.0, elevation))
        key = min(self.responses, key=lambda direction:
                  (direction[0] - elevation) ** 2 + (direction[1] - abs(azimuth)) ** 2)
        response = self.responses[key]
        return response if azimuth >= 0 else response[:, ::-1]


@lru_cache(maxsize=1)
def kemar() -> KemarHRTF | None:
    return KemarHRTF() if KEMAR_ZIP.exists() else None


def source_sound(kind: str, rate: int = RATE) -> np.ndarray:
    durations = {"wall": .10, "paddle": .14, "shield_hit": .25,
                 "shield_on": .34, "silent_on": .27, "goal": .58,
                 "win": .82, "serve": .11}
    seconds = durations.get(kind, .12)
    t = np.arange(max(1, round(seconds * rate)), dtype=np.float32) / rate
    tones = {"wall": 390, "paddle": 230, "shield_hit": 660,
             "shield_on": 820, "silent_on": 150, "goal": 110,
             "win": 550, "serve": 420}
    frequency = tones.get(kind, 300)
    chirp = np.sin(2 * np.pi * (frequency * t + 0.5 * frequency * .65 * t * t))
    harmonic = .25 * np.sin(2 * np.pi * frequency * 1.51 * t)
    envelope = (1 - np.exp(-t * 180)) * np.exp(-t * (8 if kind != "win" else 4))
    if kind in ("goal", "win"):
        harmonic += .3 * np.sin(2 * np.pi * frequency * 1.25 * t)
    return ((chirp + harmonic) * envelope * .55).astype(np.float32)


def _lowpass(signal: np.ndarray, amount: float) -> np.ndarray:
    """Short FIR low pass; bounded kernel keeps callback work outside DSP."""
    if amount <= .01:
        return signal
    taps = np.array([amount / 8, amount * 3 / 8, 1 - amount,
                     amount * 3 / 8, amount / 8], dtype=np.float32)
    return np.convolve(signal, taps, mode="same").astype(np.float32)


def spatialize(mono: np.ndarray, event: Event, listener: int,
               listener_x: float = 0.0, rate: int = RATE) -> np.ndarray:
    """Convolve a positioned event with measured or analytic ear responses."""
    if listener not in (0, 1):
        raise ValueError("listener must be a player")
    direction = 1 if listener == 0 else -1
    dx = (event.x - listener_x) * direction
    dz = (event.z if listener == 0 else COURT_LENGTH - event.z) - 0.4
    dy = event.height - 1.55
    horizontal = math.hypot(dx, dz)
    distance = math.sqrt(dx * dx + dy * dy + dz * dz)
    azimuth = math.atan2(dx, dz)
    elevation = math.atan2(dy, max(.01, horizontal))
    measured = kemar()
    if measured is not None and rate == RATE:
        response = measured.response(math.degrees(azimuth), math.degrees(elevation))
        attenuation = min(1.0, 2.7 / (2.7 + distance * .20))
        return np.column_stack([
            np.convolve(mono, response[:, channel], mode="full")
            for channel in (0, 1)
        ]).astype(np.float32) * attenuation
    side = math.sin(azimuth)
    # 0.65 ms maximum interaural arrival delay for a human head.
    delay = min(34, round(abs(side) * .00065 * rate))
    near_gain = 1.0
    far_gain = max(.22, 1.0 - .58 * abs(side))
    attenuation = min(1.0, 2.7 / (2.7 + distance * .20))
    front_back = .38 if dz < 0 else 0.0
    height_tone = min(.22, abs(elevation) * .16)
    near = _lowpass(mono, front_back + height_tone)
    far = _lowpass(mono, min(.85, front_back + .28 * abs(side) + height_tone))
    output = np.zeros((len(mono) + delay, 2), dtype=np.float32)
    if side >= 0:
        output[:len(mono), 1] = near * near_gain * attenuation
        output[delay:delay + len(mono), 0] = far * far_gain * attenuation
    else:
        output[:len(mono), 0] = near * near_gain * attenuation
        output[delay:delay + len(mono), 1] = far * far_gain * attenuation
    return output


class AudioOutput:
    """Mix short pre-rendered events in a low-latency PortAudio callback."""

    @property
    def listener(self):
        return self._listener

    @listener.setter
    def listener(self, player):
        if player not in (0, 1):
            raise ValueError('invalid listener')
        if hasattr(self, '_lock') and player != self._listener:
            with self._lock:
                # Pre-rendered tails belong to the previous listener's ears.
                self._voices.clear()
                self._ball_history.fill(0)
        self._listener = player

    def __init__(self, listener: int = 0) -> None:
        self.listener = listener
        self.listener_x = 0.0
        self._voices: list[tuple[np.ndarray, int]] = []
        self._ball: Event | None = None
        self._ball_sample = 0
        self._ball_history = np.zeros(140, dtype=np.float32)
        self._lock = threading.Lock()
        self._stream = None
        self.callback_count = 0
        self.bank = SoundBank()
        self._rolling = self.bank.event('rolling')
        self._shield_loop = self.bank.event('shield_loop')
        self._shields: list[Event] = []
        self._shield_sample = 0
        self._music = None
        self._music_sample = 0
        self._music_path = None
        self.music_gain = .4

    def start(self) -> None:
        import sounddevice as sd
        kemar()  # Keep ZIP decoding off the realtime audio callback.
        self._stream = sd.OutputStream(samplerate=RATE, channels=2, dtype="float32",
                                       blocksize=512, latency="low", callback=self._callback)
        self._stream.start()

    def close(self) -> None:
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def play(self, event: Event) -> None:
        kind = 'lose' if event.kind == 'win' and event.player != self.listener else event.kind
        mono = (self.bank.get(f'Pong/Goal{event.variant}.wav')
                if kind == 'goal' else self.bank.event(kind))
        if mono is None:
            mono = source_sound(kind)
        voice = spatialize(mono, event, self.listener, self.listener_x)
        with self._lock:
            self._voices.append((voice, 0))

    def play_file(self, path: str, gain: float = 1.0, delay: float = 0.0,
                  event: Event | None = None) -> None:
        mono = self.bank.get(path)
        if mono is not None:
            voice = (np.column_stack((mono, mono)) if event is None else
                     spatialize(mono, event, self.listener, self.listener_x)) * gain
            with self._lock:
                self._voices.append((voice, -round(delay * RATE)))

    def goal_sequence(self, event: Event, characters: list[int], scores: list[int]) -> None:
        scorer = event.player
        if scorer not in (0, 1):
            return
        loser = 1 - scorer
        # Native local-goal path waits 3s after each character response.
        self.play_file(f'Chars/{characters[scorer] + 1}/score{event.reaction}.wav',
                       event=Event('voice', 0, scorer * COURT_LENGTH))
        self.play_file(f'Chars/{characters[loser] + 1}/opscore{event.opponent_reaction}.wav',
                       delay=3, event=Event('voice', 0, loser * COURT_LENGTH))
        self.play_file('announcer/scores.wav', delay=6)
        # Original recordings stop at 21; the accessible score text handles any target.
        for index, player in enumerate((self.listener, 1 - self.listener)):
            if 0 <= scores[player] <= 21:
                self.play_file(f'announcer/{scores[player]}.wav', delay=6.5 + index * .5)

    def match_result(self, winner: int, characters: list[int]) -> None:
        won = winner == self.listener
        self.play_file('announcer/youwin.wav' if won else 'announcer/theywin.wav')
        player = self.listener
        self.play_file(f"Chars/{characters[player] + 1}/{'win' if won else 'lose'}.wav", delay=1.5)

    def music(self, path: str | None) -> None:
        if path == self._music_path:
            return
        mono = self.bank.get(path) if path else None
        with self._lock:
            self._music = mono
            self._music_sample = 0
            self._music_path = path

    def reset(self) -> None:
        with self._lock:
            self._voices.clear()
            self._ball = None
            self._shields = []
            self._ball_history.fill(0)

    def set_shields(self, events: list[Event]) -> None:
        with self._lock:
            self._shields = events

    def set_ball(self, event: Event | None) -> None:
        with self._lock:
            if event is None:
                self._ball_history.fill(0)
            self._ball = event

    def _callback(self, outdata, frames, _time_info, _status) -> None:
        self.callback_count += 1
        outdata.fill(0)
        with self._lock:
            if self._music is not None:
                mono = self._music[(np.arange(frames) + self._music_sample) % len(self._music)]
                outdata[:] += mono[:, None] * self.music_gain
                self._music_sample += frames
            if self._shield_loop is not None:
                mono = self._shield_loop[(np.arange(frames) + self._shield_sample) % len(self._shield_loop)]
                for shield in self._shields:
                    # Short shield blocks; measured HRTF work stays bounded.
                    outdata[:] += spatialize(mono, shield, self.listener, self.listener_x)[:frames] * .2
                self._shield_sample += frames
            if self._ball is not None:
                ball = self._ball
                direction = 1 if self.listener == 0 else -1
                dx = (ball.x - self.listener_x) * direction
                dz = ball.z if self.listener == 0 else COURT_LENGTH - ball.z
                distance = math.sqrt(dx * dx + dz * dz + (ball.height - 1.55) ** 2)
                gain = .055 * min(1.0, 2.7 / (2.7 + distance * .20))
                t = (np.arange(frames, dtype=np.float32) + self._ball_sample) / RATE
                mono = (.65 * np.sin(2 * np.pi * 140 * t) +
                        .35 * np.sin(2 * np.pi * 1350 * t)).astype(np.float32)
                if self._rolling is not None:
                    mono = self._rolling[(np.arange(frames) + self._ball_sample) % len(self._rolling)]
                    gain = .55 * min(1.0, 2.7 / (2.7 + distance * .20))
                measured = kemar()
                if measured is not None:
                    elevation = math.degrees(math.atan2(ball.height - 1.55, max(.01, math.hypot(dx, dz))))
                    response = measured.response(math.degrees(math.atan2(dx, dz)), elevation)
                    history = np.concatenate((self._ball_history, mono))
                    for channel in (0, 1):
                        filtered = np.convolve(history, response[:, channel], mode="full")
                        outdata[:, channel] += filtered[len(self._ball_history):len(self._ball_history) + frames] * gain
                    self._ball_history = history[-len(self._ball_history):]
                else:
                    side = dx / max(.01, math.hypot(dx, dz))
                    outdata[:, 0] += mono * gain * (1 - .35 * max(0.0, side))
                    outdata[:, 1] += mono * gain * (1 + .35 * min(0.0, side))
                self._ball_sample += frames
            remaining = []
            for voice, offset in self._voices:
                start = min(frames, max(0, -offset))
                if offset < 0:
                    offset += start
                length = min(frames - start, len(voice) - max(0, offset))
                if length > 0:
                    outdata[start:start + length] += voice[offset:offset + length]
                    offset += length
                if offset < len(voice):
                    remaining.append((voice, offset))
            self._voices = remaining
        np.clip(outdata, -1, 1, out=outdata)
