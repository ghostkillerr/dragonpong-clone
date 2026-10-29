"""Threaded newline-JSON transport for Tk's single-threaded event loop."""

from __future__ import annotations

import json
import os
import queue
import socket
import threading
from typing import Any

HOST = os.environ.get("DRAGONPONG_CLONE_HOST", "127.0.0.1")
PORT = int(os.environ.get("DRAGONPONG_CLONE_PORT", "8870"))


class Connection:
    def __init__(self) -> None:
        self.socket = socket.create_connection((HOST, PORT), timeout=3)
        self.socket.settimeout(None)
        self.events: queue.SimpleQueue[dict[str, Any]] = queue.SimpleQueue()
        self.lock = threading.Lock()
        self.closed = False
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def send(self, kind: str, **fields: Any) -> None:
        data = (json.dumps({"type": kind, "protocol": 2, **fields}, ensure_ascii=False) + "\n").encode()
        with self.lock:
            if self.closed:
                raise ConnectionError("connection closed")
            self.socket.sendall(data)

    def _read(self) -> None:
        try:
            reader = self.socket.makefile("rb")
            for line in reader:
                if len(line) > 4096:
                    raise ValueError("server message too long")
                message = json.loads(line)
                if isinstance(message, dict):
                    self.events.put(message)
        except (OSError, ValueError) as exc:
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
