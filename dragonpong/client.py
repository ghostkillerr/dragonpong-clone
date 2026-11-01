"""Threaded newline-JSON transport for Tk's single-threaded event loop."""

from __future__ import annotations

import json
import os
import queue
import select
import socket
import threading
import time
from collections import deque
from typing import Any

from .engine import COURT_LENGTH, HALF_WIDTH
from .netplay import STRIKE_FEATURE, ContactFrames, ServerClockFloor, predict_flight, view_seconds

HOST = os.environ.get("DRAGONPONG_CLONE_HOST", "127.0.0.1")
PORT = int(os.environ.get("DRAGONPONG_CLONE_PORT", "8870"))
LATEST_PROTOCOL = 3
PING_INTERVAL = .5
PING_TIMEOUT = 5.0
SEND_TIMEOUT = .5
MAX_OUTGOING = 128
MAX_LINE = 4096

FRAME_FIELDS = {"b": "ball", "v": "velocity", "p": "paddles", "s": "scores",
                "sr": "serving", "w": "winner", "si": "silent", "sh": "shields",
                "r": "ready", "e": "events"}


class LatestEventQueue:
    """Keep current match state without losing occasional gameplay events."""

    def __init__(self) -> None:
        self.items: deque[dict[str, Any]] = deque()
        self.lock = threading.Lock()

    def put(self, message: dict[str, Any]) -> None:
        with self.lock:
            if (message.get("type") == "state" and self.items and
                    self.items[-1].get("type") == "state" and
                    not any(event.get("kind") in ("goal", "win")
                            for event in self.items[-1].get("events", []))):
                old = self.items.pop()
                events = old.get("events", []) + message.get("events", [])
                if len(events) > 64:
                    important = {index for index, event in enumerate(events)
                                 if event.get("kind") not in ("move", "border")}
                    keep = set(sorted(important)[-64:])
                    keep.update(index for index in range(len(events) - 1, -1, -1)
                                if len(keep) < 64)
                    events = [event for index, event in enumerate(events) if index in keep]
                message = {**message, "events": events}
            self.items.append(message)

    def get_nowait(self) -> dict[str, Any]:
        with self.lock:
            if not self.items:
                raise queue.Empty
            return self.items.popleft()


def expand_frame(frame: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    state = {**previous, **{long_name: frame[short_name]
                          for short_name, long_name in FRAME_FIELDS.items()},
             "type": "state"}
    if "a" in frame:
        state["step_ack"] = frame["a"]
    for short, long in {'n': 'frame_id', 'f': 'flight_id', 't': 'sim_time',
                        'q': 'phase', 'h': 'shield_left', 'g': 'pending_goal', 'c': 'server_time'}.items():
        if short in frame:
            state[long] = frame[short]
    return state


def predict_ball(ball: list[float], velocity: list[float], seconds: float) -> tuple[float, float]:
    flight = predict_flight(ball, velocity, seconds)
    return flight.x, flight.z


class PaddlePrediction:
    """Replay only unacknowledged local steps over the server paddle position."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.next_seq = 1
        self.last_ack = 0
        self.pending: deque[tuple[int, int]] = deque()

    def add(self, direction: int) -> int:
        if direction not in (-1, 1):
            raise ValueError("invalid movement")
        seq = self.next_seq
        self.next_seq += 1
        self.pending.append((seq, direction))
        return seq

    def acknowledge(self, seq: int) -> None:
        if type(seq) is not int or not self.last_ack <= seq < self.next_seq:
            return
        self.last_ack = seq
        while self.pending and self.pending[0][0] <= seq:
            self.pending.popleft()

    def position(self, server_x: float, player: int) -> float:
        factor = 1 if player == 0 else -1
        x = server_x
        for _, direction in self.pending:
            x = max(-HALF_WIDTH, min(HALF_WIDTH, x + factor * direction))
        return x


class Connection:
    def __init__(self) -> None:
        self.socket: socket.socket | None = None
        self.events = LatestEventQueue()
        self.lock = threading.Lock()
        self.outgoing: queue.Queue = queue.Queue(maxsize=MAX_OUTGOING)
        self.closed = False
        self.protocol = 2
        self.supports_step_ack = False
        self.supports_strike_ref = False
        self.next_press = 1
        self.ping_ms: float | None = None
        self.jitter_ms = 0.0
        self.last_ping_at = 0.0
        self.last_pong_at = 0.0
        self.ping_queued_at = 0.0
        self.ping_nonce: int | None = None
        self.last_state: dict[str, Any] | None = None
        self.contact_frames = ContactFrames()
        self.server_clock = ServerClockFloor()
        self.received_any = False
        self.sender: threading.Thread | None = None
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def send(self, kind: str, **fields: Any) -> None:
        if kind in ('create', 'join', 'spectate') and self.supports_strike_ref:
            fields['features'] = [STRIKE_FEATURE]
        with self.lock:
            if self.closed:
                raise ConnectionError("connection closed")
            if kind in ('strike', 'serve') and self.supports_strike_ref:
                fields['press'] = self.next_press
                self.next_press += 1
                if 'view' not in fields and self.last_state is not None:
                    fields['view'] = {'frame': self.last_state.get('frame_id'),
                                      'seconds': view_seconds(self.last_state, self.ping_ms, time.monotonic())}
            data = (json.dumps({"type": kind, "protocol": self.protocol, **fields},
                               ensure_ascii=False, separators=(",", ":")) + "\n").encode()
            try:
                self.outgoing.put_nowait((data, time.monotonic(), kind))
            except queue.Full:
                raise ConnectionError("Gönderim kuyruğu doldu; bağlantı yetişemiyor.") from None

    def _write(self) -> None:
        try:
            while not self.closed:
                try:
                    item = self.outgoing.get(timeout=.1)
                except queue.Empty:
                    continue
                if item is None or self.closed:
                    return
                data, queued_at, kind = item
                now = time.monotonic()
                if kind in ('step', 'strike', 'serve') and now - queued_at > SEND_TIMEOUT:
                    raise ConnectionError("Bağlantı gecikti; eski oyun komutları gönderilmedi.")
                if kind == 'ping':
                    with self.lock:
                        self.last_ping_at = now
                # Socket I/O never holds the UI lock. A stalled write has a deadline.
                self.socket.sendall(data)
        except OSError as exc:
            self._fail('connection_error', str(exc))

    def ping(self) -> None:
        now = time.monotonic()
        with self.lock:
            if self.closed or self.protocol < 3:
                return
            if self.ping_nonce is not None:
                timed_out = now - self.ping_queued_at >= PING_TIMEOUT
                nonce = None
            else:
                timed_out = False
                if now - self.ping_queued_at < PING_INTERVAL:
                    return
                nonce = time.monotonic_ns() & ((1 << 63) - 1)
                self.ping_nonce = nonce
                self.ping_queued_at = now
        if timed_out:
            self._fail('connection_error', 'Sunucu ping yanıtı vermiyor; bağlantı kesildi.')
        elif nonce is not None:
            try:
                self.send('ping', nonce=nonce)
            except OSError as exc:
                self._fail('connection_error', str(exc))

    def status_text(self) -> str:
        with self.lock:
            if self.closed:
                return 'Bağlantı kapalı'
            if self.socket is None:
                return 'Sunucuya bağlanılıyor'
            if self.protocol < 3:
                return 'Bu sunucuda ping ölçümü desteklenmiyor'
            if self.ping_ms is None or time.monotonic() - self.last_pong_at > 1.5:
                return 'Ping yanıtı bekleniyor'
            return f'Ping {round(self.ping_ms)} ms | Dalgalanma {round(self.jitter_ms)} ms'

    def _message(self, message: dict[str, Any]) -> None:
        self.received_any = True
        if message.get('type') == 'rooms':
            protocols = message.get('protocols', [])
            if isinstance(protocols, list) and LATEST_PROTOCOL in protocols:
                self.protocol = LATEST_PROTOCOL
            features = message.get('features', [])
            self.supports_step_ack = (self.protocol == LATEST_PROTOCOL and
                                      isinstance(features, list) and 'step_ack' in features)
            self.supports_strike_ref = (self.protocol == LATEST_PROTOCOL and
                                        isinstance(features, list) and STRIKE_FEATURE in features)
        if message.get('type') == 'pong':
            with self.lock:
                if self.ping_nonce is not None and message.get('nonce') == self.ping_nonce:
                    now = time.monotonic()
                    sample = max(0.0, (now - self.last_ping_at) * 1000)
                    if self.ping_ms is not None:
                        self.jitter_ms += (abs(sample - self.ping_ms) - self.jitter_ms) / 4
                    self.ping_ms = sample
                    self.last_pong_at = now
                    self.ping_nonce = None
                    self.server_clock.observe(message.get('server_time'), now)
            return
        if message.get('type') == 'frame':
            if self.last_state is None:
                raise ValueError('frame before first state')
            message = expand_frame(message, self.last_state)
        if message.get('type') == 'state':
            message['_received_at'] = time.monotonic()
            self.server_clock.tag(message, message['_received_at'])
            if self.supports_strike_ref:
                message = self.contact_frames.receive(message)
            self.last_state = message
        self.events.put(message)

    def _read(self) -> None:
        try:
            sock = socket.create_connection((HOST, PORT), timeout=3)
            with self.lock:
                if self.closed:
                    sock.close()
                    return
                self.socket = sock
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(SEND_TIMEOUT)
            self.sender = threading.Thread(target=self._write, daemon=True)
            self.sender.start()
            connected_at = time.monotonic()
            buffer = bytearray()
            while not self.closed:
                if not self.received_any and time.monotonic() - connected_at >= PING_TIMEOUT:
                    raise ConnectionError('Sunucu ilk isteğe yanıt vermiyor.')
                self.ping()
                if self.closed:
                    return
                if not select.select([sock], [], [], .05)[0]:
                    continue
                try:
                    data = sock.recv(MAX_LINE)
                except socket.timeout:
                    continue
                if not data:
                    self._fail('disconnected', 'Sunucu bağlantıyı kapattı.')
                    return
                buffer.extend(data)
                while b'\n' in buffer:
                    line, _, rest = buffer.partition(b'\n')
                    buffer = bytearray(rest)
                    if len(line) > MAX_LINE:
                        raise ValueError('server message too long')
                    message = json.loads(line)
                    if not isinstance(message, dict):
                        raise ValueError('invalid server message')
                    self._message(message)
                if len(buffer) > MAX_LINE:
                    raise ValueError('server message too long')
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self._fail('connection_error', str(exc))

    def _fail(self, kind: str, reason: str) -> None:
        self._shutdown({'type': kind, 'reason': reason})

    def close(self) -> None:
        self._shutdown()

    def _shutdown(self, message: dict[str, Any] | None = None) -> None:
        with self.lock:
            if self.closed:
                return
            self.closed = True
            if message is not None:
                self.events.put(message)
            sock = self.socket
            try:
                self.outgoing.put_nowait(None)
            except queue.Full:
                pass
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
