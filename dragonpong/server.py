"""Source-only room server for the new clone. No original game protocol."""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from .engine import COURT_LENGTH, Match, Rules, TICK

MAX_LINE = 4096
STRIKE_BUFFER_SECONDS = .25
MAX_STATE_BACKLOG = 8192
MAX_PENDING_EVENTS = 20
SLOW_CLIENT_SECONDS = 3


def compact_state(state: dict[str, Any]) -> dict[str, Any]:
    return {"type": "frame", "b": state["ball"], "v": state["velocity"],
            "p": state["paddles"], "s": state["scores"], "sr": state["serving"],
            "w": state["winner"], "si": state["silent"], "sh": state["shields"],
            "r": state["ready"], "e": state["events"], "a": state["step_ack"]}


@dataclass(eq=False)
class Client:
    writer: asyncio.StreamWriter
    name: str
    room_id: str | None = None
    player: int | None = None
    perspective: int = 0
    direction: float = 0.0
    protocol: int = 2
    state_sent: bool = False
    pending_events: list[dict[str, Any]] = field(default_factory=list)
    slow_since: float | None = None
    last_step_seq: int = 0

    async def send(self, message: dict[str, Any]) -> None:
        self.writer.write((json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
        await self.writer.drain()

    def send_state(self, state: dict[str, Any], *, emit: bool = True) -> None:
        self.pending_events.extend(state["events"])
        if len(self.pending_events) > MAX_PENDING_EVENTS:
            # Repeated movement sounds are expendable; goals and hits are not.
            excess = len(self.pending_events) - MAX_PENDING_EVENTS
            retained = []
            for event in self.pending_events:
                if excess and event["kind"] in ("move", "border"):
                    excess -= 1
                else:
                    retained.append(event)
            self.pending_events = retained
            if len(retained) > MAX_PENDING_EVENTS:
                self.writer.close()
                return
        if not emit:
            return
        now = time.monotonic()
        if self.writer.transport.get_write_buffer_size() > MAX_STATE_BACKLOG:
            if self.slow_since is None:
                self.slow_since = now
            elif now - self.slow_since > SLOW_CLIENT_SECONDS:
                self.writer.close()
            return
        self.slow_since = None
        payload = {**state, "events": self.pending_events}
        if self.protocol == 3 and self.state_sent:
            payload = compact_state(payload)
        self.writer.write((json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
        self.pending_events = []
        self.state_sent = True


@dataclass
class Room:
    room_id: str
    host: Client
    guest: Client | None = None
    spectators: set[Client] = field(default_factory=set)
    characters: dict[int, int] = field(default_factory=dict)
    match: Match | None = None
    task: asyncio.Task | None = None
    started: bool = False
    pending_strikes: dict[int, float] = field(default_factory=dict)
    frame_index: int = 0

    @property
    def clients(self) -> list[Client]:
        return [self.host] + ([self.guest] if self.guest else []) + list(self.spectators)


class Server:
    def __init__(self) -> None:
        self.rooms: dict[str, Room] = {}

    def room_list(self) -> list[dict[str, Any]]:
        return [{"room_id": room.room_id, "host_name": room.host.name,
                 "guest_name": room.guest.name if room.guest else None,
                 "state": "playing" if room.started else "joining" if room.guest else "waiting",
                 "joinable": room.guest is None}
                for room in self.rooms.values()]

    async def broadcast(self, room: Room, message: dict[str, Any]) -> None:
        for client in room.clients:
            try:
                await client.send(message)
            except (ConnectionError, OSError):
                pass

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        client = Client(writer, "")
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                if len(line) > MAX_LINE:
                    raise ValueError("message too long")
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError("invalid message")
                await self.dispatch(client, message)
        except (ValueError, ConnectionError, OSError, asyncio.LimitOverrunError):
            pass
        finally:
            await self.leave(client)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    async def dispatch(self, client: Client, message: dict[str, Any]) -> None:
        kind = message.get("type")
        if kind == "ping":
            nonce = message.get("nonce")
            if type(nonce) is not int or not 0 <= nonce < 2**63:
                raise ValueError("invalid ping")
            await client.send({"type": "pong", "nonce": nonce})
            return
        if kind == "rooms":
            await client.send({"type": "rooms", "rooms": self.room_list(),
                               "protocols": [2, 3], "features": ["step_ack"]})
            return
        if kind in ("create", "join", "spectate"):
            if type(message.get('protocol')) is not int or message['protocol'] not in (2, 3):
                await client.send({'type': 'rejected', 'reason': 'Güncel kaynak klon v2 paketini kullanın.'})
                return
            if client.room_id is not None:
                raise ValueError("already in a room")
            name = message.get("name")
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 24:
                raise ValueError("invalid name")
            client.name = name.strip()
            client.protocol = message["protocol"]
            if kind == "create":
                if len(self.rooms) >= 128:
                    await client.send({"type": "rejected", "reason": "room capacity"})
                    return
                room_id = secrets.token_hex(8)
                room = Room(room_id, client)
                client.room_id, client.player = room_id, 0
                self.rooms[room_id] = room
                await client.send({"type": "accepted", "room_id": room_id, "player": 0})
                return
            room_id = message.get("room_id")
            room = self.rooms.get(room_id) if isinstance(room_id, str) else None
            if not room:
                await client.send({"type": "rejected", "reason": "room unavailable"})
                return
            if kind == "join":
                if room.guest is not None:
                    await client.send({"type": "rejected", "reason": "room full"})
                    return
                room.guest = client
                client.room_id, client.player = room_id, 1
                await client.send({"type": "accepted", "room_id": room_id, "player": 1})
                await self.broadcast(room, {"type": "characters", "players":
                                            [room.host.name, room.guest.name]})
            else:
                room.spectators.add(client)
                client.room_id = room_id
                await client.send({"type": "accepted", "room_id": room_id,
                                   "player": None, "players":
                                   [room.host.name, room.guest.name if room.guest else None]})
                if room.match and (room.started or room.match.winner is not None):
                    await client.send(self.snapshot(room))
                    client.state_sent = True
            return
        if not client.room_id:
            raise ValueError("join a room first")
        room = self.rooms.get(client.room_id)
        if not room:
            raise ValueError("room closed")
        if kind == "character" and client.player is not None:
            if room.started or room.match is not None:
                return
            character = message.get("value")
            if type(character) is not int or not 0 <= character <= 4:
                raise ValueError("invalid character")
            room.characters[client.player] = character
            if len(room.characters) == 2:
                await self.broadcast(room, {"type": "settings_required", "host": room.host.name})
        elif kind == "configure" and client is room.host and len(room.characters) == 2:
            if room.match is not None:
                return
            score = message.get("score")
            shield = message.get("shield")
            silent_ball = message.get("silent_ball")
            if (type(score) is not int or type(shield) is not bool or
                    type(silent_ball) is not bool):
                raise ValueError("invalid settings")
            rules = Rules(score=score, shield=shield, silent_ball=silent_ball)
            room.match = Match(rules)
            await self.broadcast(room, {"type": "configured", "score": rules.score,
                                        "shield": rules.shield, "silent_ball": rules.silent_ball})
        elif kind == "start" and client is room.host and room.match and not room.started:
            room.started = True
            await self.broadcast(room, {"type": "started"})
            room.task = asyncio.create_task(self.run_match(room))
        elif kind == "step" and client.player is not None and room.match and room.started:
            value = message.get("direction")
            if type(value) is not int or value not in (-1, 1):
                raise ValueError("invalid movement")
            if "seq" in message:
                seq = message["seq"]
                if type(seq) is not int or not 1 <= seq <= 2_147_483_647:
                    raise ValueError("invalid movement sequence")
                if seq <= client.last_step_seq:
                    return
                if seq != client.last_step_seq + 1:
                    raise ValueError("out-of-order movement sequence")
            room.match.move_step(client.player, value * (1 if client.player == 0 else -1))
            if "seq" in message:
                client.last_step_seq = seq
        elif kind in ("serve", "strike") and client.player is not None and room.match and room.started:
            match = room.match
            player = client.player
            if match.strike(player):
                room.pending_strikes.pop(player, None)
            elif ((match.vz < 0 if player == 0 else match.vz > 0) and
                  (match.ball_z if player == 0 else COURT_LENGTH - match.ball_z) >= 6):
                # A press just before the hit zone should survive one network/frame delay.
                room.pending_strikes[player] = match.time + STRIKE_BUFFER_SECONDS
        elif kind == "perspective" and client in room.spectators:
            player = message.get("player")
            if player in (0, 1) and (player == 0 or room.guest is not None):
                client.perspective = player
                await client.send({"type": "perspective", "player": player})

    async def run_match(self, room: Room) -> None:
        assert room.match and room.guest
        match = room.match
        previous = time.monotonic()
        try:
            while room.room_id in self.rooms and room.started:
                now = time.monotonic()
                dt = min(.05, now - previous)
                previous = now
                events = self.step_match(room, dt)
                state = self.snapshot(room, events)
                room.frame_index += 1
                for client in room.clients:
                    try:
                        client.send_state(state, emit=(client.player is not None or
                                                        room.frame_index % 3 == 1 or
                                                        match.winner is not None))
                    except (ConnectionError, OSError):
                        client.writer.close()
                if match.winner is not None:
                    room.started = False
                    break
                await asyncio.sleep(max(0.0, 1 / 60 - (time.monotonic() - now)))
        except asyncio.CancelledError:
            raise

    def step_match(self, room: Room, dt: float) -> list:
        match = room.match
        assert match
        self.apply_pending_strikes(room)
        if not room.pending_strikes:
            return match.step(dt)
        # Check between physics ticks so a fast ball cannot cross the entire
        # hit zone during one delayed server frame.
        events = []
        remaining = dt
        while remaining > 0:
            portion = min(TICK, remaining)
            events.extend(match.step(portion))
            self.apply_pending_strikes(room)
            remaining -= portion
        events.extend(match.step(0))
        return events

    def apply_pending_strikes(self, room: Room) -> None:
        match = room.match
        assert match
        for player, expiry in list(room.pending_strikes.items()):
            incoming = match.vz < 0 if player == 0 else match.vz > 0
            if match.time > expiry or not incoming:
                room.pending_strikes.pop(player, None)
            elif match.can_strike(player):
                match.strike(player)
                room.pending_strikes.pop(player, None)

    def snapshot(self, room: Room, events=()) -> dict:
        match = room.match
        assert match and room.guest
        return {"type": "state", "ball": [match.ball_x, match.ball_z],
                         "velocity": [match.vx, match.vz], "paddles": match.paddles,
                         "scores": match.scores, "serving": match.serving,
                         "winner": match.winner, "silent": match.time < match.silent_until,
                         "shields": [match.time < expiry for expiry in match.shield_until],
                         "players": [room.host.name, room.guest.name],
                         "characters": [room.characters[0], room.characters[1]],
                         "step_ack": [room.host.last_step_seq, room.guest.last_step_seq],
                         "ready": match.time >= match.ready_at,
                         "events": [event.__dict__ for event in events]}

    async def leave(self, client: Client) -> None:
        room = self.rooms.get(client.room_id) if client.room_id else None
        if not room:
            return
        if client in room.spectators:
            room.spectators.discard(client)
        elif client is room.host or client is room.guest:
            self.rooms.pop(room.room_id, None)
            if room.task:
                room.task.cancel()
            await self.broadcast(room, {"type": "room_closed"})
            for other in room.clients:
                if other is not client:
                    other.writer.close()
        client.room_id = None


async def serve(host: str, port: int) -> None:
    lobby = Server()
    server = await asyncio.start_server(lobby.handle, host, port, limit=MAX_LINE)
    async with server:
        await server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8870)
    args = parser.parse_args()
    asyncio.run(serve(args.host, args.port))


if __name__ == "__main__":
    main()
