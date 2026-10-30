"""Threaded newline-JSON transport for Tk's single-threaded event loop."""

from __future__ import annotations

import json
import os
import queue
import socket
import threading
import time
from collections import deque
from typing import Any

from .engine import COURT_LENGTH, HALF_WIDTH

HOST = os.environ.get("DRAGONPONG_CLONE_HOST", "127.0.0.1")
PORT = int(os.environ.get("DRAGONPONG_CLONE_PORT", "8870"))
LATEST_PROTOCOL = 3

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
    return {**previous, **{long_name: frame[short_name]
                          for short_name, long_name in FRAME_FIELDS.items()},
            "type": "state"}


def predict_ball(ball: list[float], velocity: list[float], seconds: float) -> tuple[float, float]:
    """Show where the authoritative ball should be when a new input arrives."""
    x = ball[0] + velocity[0] * seconds
    z = max(0.0, min(COURT_LENGTH, ball[1] + velocity[1] * seconds))
    while x > HALF_WIDTH or x < -HALF_WIDTH:
        x = 2 * HALF_WIDTH - x if x > HALF_WIDTH else -2 * HALF_WIDTH - x
    return x, z


class Connection:
    def __init__(self) -> None:
        self.socket = socket.create_connection((HOST, PORT), timeout=3)
        self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.socket.settimeout(None)
        self.events = LatestEventQueue()
        self.lock = threading.Lock()
        self.closed = False
        self.protocol = 2
        self.ping_ms: float | None = None
        self.last_ping_at = 0.0
        self.ping_nonce: int | None = None
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def send(self, kind: str, **fields: Any) -> None:
        data = (json.dumps({"type": kind, "protocol": self.protocol, **fields},
                           ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        with self.lock:
            if self.closed:
                raise ConnectionError("connection closed")
            self.socket.sendall(data)

    def ping(self) -> None:
        if self.protocol < 3:
            return
        now = time.monotonic()
        if now - self.last_ping_at < 2:
            return
        nonce = time.monotonic_ns() & ((1 << 63) - 1)
        self.last_ping_at = now
        self.ping_nonce = nonce
        self.send("ping", nonce=nonce)

    def _read(self) -> None:
        try:
            reader = self.socket.makefile("rb")
            last_state = None
            for line in reader:
                if len(line) > 4096:
                    raise ValueError("server message too long")
                message = json.loads(line)
                if isinstance(message, dict):
                    if message.get("type") == "rooms":
                        protocols = message.get("protocols", [])
                        if isinstance(protocols, list) and LATEST_PROTOCOL in protocols:
                            self.protocol = LATEST_PROTOCOL
                    if message.get("type") == "pong":
                        if message.get("nonce") == self.ping_nonce:
                            self.ping_ms = (time.monotonic() - self.last_ping_at) * 1000
                            self.ping_nonce = None
                        continue
                    if message.get("type") == "frame":
                        if last_state is None:
                            raise ValueError("frame before first state")
                        message = expand_frame(message, last_state)
                    if message.get("type") == "state":
                        message["_received_at"] = time.monotonic()
                        last_state = message
                    self.events.put(message)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.events.put({"type": "connection_error", "reason": str(exc)})
        finally:
            self.events.put({"type": "disconnected"})

    def close(self) -> None:
        with self.lock:
            self.closed = True
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.socket.close()
