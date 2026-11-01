"""Source-only room server for the new clone. No original game protocol."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import secrets
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any

from .engine import COURT_LENGTH, Match, Rules, TICK
from .netplay import STRIKE_FEATURE, MAX_CONTACT_LAG, MAX_PREDICTION, MAX_VIEW_AGE, predict_view

MAX_LINE = 4096
STRIKE_BUFFER_SECONDS = .25
MAX_STATE_BACKLOG = 8192
MAX_PENDING_EVENTS = 20
SLOW_CLIENT_SECONDS = 3
CONTROL_SEND_TIMEOUT = 1.0


def compact_state(state: dict[str, Any]) -> dict[str, Any]:
    frame = {"type": "frame", "b": state["ball"], "v": state["velocity"],
            "p": state["paddles"], "s": state["scores"], "sr": state["serving"],
            "w": state["winner"], "si": state["silent"], "sh": state["shields"],
            "r": state["ready"], "e": state["events"], "a": state["step_ack"]}
    for short, long in {'n': 'frame_id', 'f': 'flight_id', 't': 'sim_time',
                        'q': 'phase', 'h': 'shield_left', 'g': 'pending_goal', 'c': 'server_time'}.items():
        if long in state:
            frame[short] = state[long]
    return frame


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
    strike_refs: bool = False
    last_press: int = 0
    views: deque = field(default_factory=lambda: deque(maxlen=64))

    def remember_view(self, state: dict) -> None:
        if self.strike_refs and 'frame_id' in state:
            self.views.append((time.monotonic(), {key: list(value) if isinstance(value, list) else value
                               for key, value in state.items() if key != 'events'}))

    async def send(self, message: dict[str, Any]) -> None:
        self.writer.write((json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
        await self.flush()

    async def flush(self) -> None:
        try:
            await asyncio.wait_for(self.writer.drain(), CONTROL_SEND_TIMEOUT)
        except TimeoutError:
            self.writer.transport.abort()
            raise
        except OSError:
            self.writer.close()
            raise

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
        if self.writer.transport.get_write_buffer_size() > MAX_STATE_BACKLOG and state['winner'] is None:
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
        self.remember_view(state)
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
    snapshot_seq: int = 0
    flight_id: int = 0
    pending_goal_until: float | None = None
    strike_stats: Counter = field(default_factory=Counter)
    last_update_at: float | None = None
    pending_events: list = field(default_factory=list)

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
        async def deliver(client: Client) -> None:
            try:
                await client.send(message)
            except (ConnectionError, OSError):
                pass
        await asyncio.gather(*(deliver(client) for client in room.clients))

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
            await client.send({"type": "pong", "nonce": nonce, 'server_time': time.monotonic()})
            return
        if kind == "rooms":
            await client.send({"type": "rooms", "rooms": self.room_list(),
                               "protocols": [2, 3], "features": ["step_ack", STRIKE_FEATURE]})
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
            features = message.get('features', [])
            client.strike_refs = (client.protocol == 3 and isinstance(features, list) and STRIKE_FEATURE in features)
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
        if kind in ('step', 'strike', 'serve') and room.match and room.started and room.last_update_at is not None:
            room.pending_events.extend(self.advance_to_now(room))
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
            room.last_update_at = time.monotonic()
            room.task = asyncio.create_task(self.run_match(room))
        elif kind == "step" and client.player is not None and room.match and room.started:
            self.move_step(room, client, message)
        elif kind in ("serve", "strike") and client.player is not None and room.match and room.started:
            if client.strike_refs:
                press = message.get('press')
                if type(press) is not int or not 1 <= press <= 2_147_483_647:
                    raise ValueError('invalid strike sequence')
                if press <= client.last_press:
                    return
                if press != client.last_press + 1:
                    raise ValueError('out-of-order strike sequence')
                client.last_press = press
                result = self.referenced_strike(room, client, message.get('view'))
                room.strike_stats[result] += 1
                await client.send({'type': 'strike_result', 'press': press, 'result': result})
            else:
                self.legacy_strike(room, client.player)
        elif kind == "perspective" and client in room.spectators:
            player = message.get("player")
            if player in (0, 1) and (player == 0 or room.guest is not None):
                client.perspective = player
                await client.send({"type": "perspective", "player": player})

    def new_flight(self, room: Room) -> None:
        room.flight_id += 1
        room.pending_goal_until = None
        room.pending_strikes.clear()

    def move_step(self, room: Room, client: Client, message: dict) -> None:
        value = message.get('direction')
        if type(value) is not int or value not in (-1, 1):
            raise ValueError('invalid movement')
        if 'seq' in message:
            seq = message['seq']
            if type(seq) is not int or not 1 <= seq <= 2_147_483_647:
                raise ValueError('invalid movement sequence')
            if seq <= client.last_step_seq:
                return
            if seq != client.last_step_seq + 1:
                raise ValueError('out-of-order movement sequence')
        room.match.move_step(client.player, value * (1 if client.player == 0 else -1))
        if 'seq' in message:
            client.last_step_seq = seq

    def native_strike(self, room: Room, player: int) -> bool:
        if room.match.strike(player):
            self.new_flight(room)
            return True
        return False

    def legacy_strike(self, room: Room, player: int) -> None:
        match = room.match
        if self.native_strike(room, player):
            return
        if ((match.vz < 0 if player == 0 else match.vz > 0) and
                (match.ball_z if player == 0 else COURT_LENGTH - match.ball_z) >= 6):
            room.pending_strikes[player] = match.time + STRIKE_BUFFER_SECONDS

    def referenced_strike(self, room: Room, client: Client, reference) -> str:
        match, player = room.match, client.player
        if match.winner is not None:
            return 'finished'
        if not isinstance(reference, dict):
            return 'invalid_view'
        frame, seconds = reference.get('frame'), reference.get('seconds')
        if (type(frame) is not int or type(seconds) not in (int, float) or
                not math.isfinite(seconds) or not 0 <= seconds <= MAX_PREDICTION):
            return 'invalid_view'
        found = next(((sent_at, state) for sent_at, state in reversed(client.views)
                      if state['frame_id'] == frame), None)
        if found is None:
            return 'unknown_view'
        sent_at, state = found
        lag = match.time - state['sim_time'] - seconds
        if (state['flight_id'] != room.flight_id or state['pending_goal'] or
                time.monotonic() - sent_at > MAX_VIEW_AGE or
                match.time - state['sim_time'] > MAX_VIEW_AGE or
                lag > MAX_CONTACT_LAG + 1e-9 or lag < -MAX_PREDICTION - 1e-9):
            return 'stale_view'
        if not match.vz and room.pending_goal_until is None:
            if any(state['velocity']):
                return 'stale_view'
            return 'serve' if self.native_strike(room, player) else 'not_ready'
        flight = predict_view(state, seconds)
        if not (flight.vz < 0 if player == 0 else flight.vz > 0):
            return 'wrong_direction'
        depth = flight.z if player == 0 else COURT_LENGTH - flight.z
        if depth < 1:
            return 'too_late'
        if abs(flight.x - match.paddles[player]) >= 3:
            return 'out_of_reach'
        if lag < -TICK:
            # A stale high RTT estimate can put the view ahead of the server.
            # Keep the intent briefly; only the normal native hit window may fire.
            incoming = match.vz < 0 if player == 0 else match.vz > 0
            if incoming and room.pending_goal_until is None:
                room.pending_strikes[player] = match.time + min(STRIKE_BUFFER_SECONDS, -lag + TICK)
                return 'buffered'
            return 'wrong_direction'
        if depth >= 6:
            current_depth = match.ball_z if player == 0 else COURT_LENGTH - match.ball_z
            incoming = match.vz < 0 if player == 0 else match.vz > 0
            if incoming and current_depth >= 6 and room.pending_goal_until is None:
                room.pending_strikes[player] = match.time + STRIKE_BUFFER_SECONDS
                return 'buffered'
            return 'out_of_range'
        compensated = room.pending_goal_until is not None or not match.can_strike(player)
        saved = match.ball_x, match.ball_z, match.vx, match.vz
        match.ball_x, match.ball_z, match.vx, match.vz = flight.x, flight.z, flight.vx, flight.vz
        if self.native_strike(room, player):
            return 'compensated' if compensated else 'hit'
        match.ball_x, match.ball_z, match.vx, match.vz = saved
        return 'out_of_range'

    async def run_match(self, room: Room) -> None:
        assert room.match and room.guest
        match = room.match
        if room.last_update_at is None:
            room.last_update_at = time.monotonic()
        try:
            while room.room_id in self.rooms and room.started:
                now = time.monotonic()
                events, room.pending_events = room.pending_events, []
                events.extend(self.advance_to_now(room, now))
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
                    async def finish(client: Client) -> None:
                        try:
                            await client.flush()
                        except OSError:
                            pass
                    await asyncio.gather(*(finish(client) for client in room.clients))
                    room.started = False
                    break
                await asyncio.sleep(max(0.0, 1 / 60 - (time.monotonic() - now)))
        except asyncio.CancelledError:
            raise

    def advance_to_now(self, room: Room, now: float | None = None) -> list:
        now = time.monotonic() if now is None else now
        previous = room.last_update_at
        room.last_update_at = now
        return self.step_match(room, min(.25, max(0, now - previous)) if previous is not None else 0)

    def step_match(self, room: Room, dt: float) -> list:
        match = room.match
        assert match
        if not math.isfinite(dt) or not 0 <= dt <= .25:
            raise ValueError('invalid time step')
        self.apply_pending_strikes(room)
        events = []
        remaining = dt
        while remaining > 1e-12:
            portion = min(max(1e-12, TICK - match._accumulator), remaining)
            player = 0 if match.vz < 0 else 1
            defender = room.host if player == 0 else room.guest
            depth = match.ball_z if player == 0 else COURT_LENGTH - match.ball_z
            goal_due = (match.vz and match.winner is None and depth < 1 and
                        not (match.rules.shield and match.shield_until[player] >= match.time + TICK))
            if goal_due and defender is not None and defender.strike_refs:
                if room.pending_goal_until is None:
                    room.pending_goal_until = match.time + MAX_CONTACT_LAG
                hold = match.time + TICK < room.pending_goal_until - 1e-9
            else:
                hold = False
            velocity = match.vx, match.vz
            if hold:
                match.vx = match.vz = 0
            chunk = match.step(portion)
            if hold:
                match.vx, match.vz = velocity
            events.extend(chunk)
            if any(event.kind in ('goal', 'shield_hit') for event in chunk):
                self.new_flight(room)
            self.apply_pending_strikes(room)
            remaining -= portion
        events.extend(match.step(0))
        return events

    def apply_pending_strikes(self, room: Room) -> None:
        match = room.match
        assert match
        for player, expiry in list(room.pending_strikes.items()):
            if player not in room.pending_strikes:
                continue
            incoming = match.vz < 0 if player == 0 else match.vz > 0
            if match.time > expiry or not incoming:
                room.pending_strikes.pop(player, None)
            elif (room.pending_goal_until is None and
                  (match.ball_z if player == 0 else COURT_LENGTH - match.ball_z) >= 1 and
                  match.can_strike(player)):
                self.native_strike(room, player)

    def snapshot(self, room: Room, events=()) -> dict:
        match = room.match
        assert match and room.guest
        room.snapshot_seq += 1
        return {"type": "state", "ball": [match.ball_x, match.ball_z],
                         "velocity": [0, 0] if room.pending_goal_until is not None else [match.vx, match.vz],
                         "paddles": list(match.paddles),
                         "scores": list(match.scores), "serving": match.serving,
                         "winner": match.winner, "silent": match.time < match.silent_until,
                         "shields": [match.time < expiry for expiry in match.shield_until],
                         "players": [room.host.name, room.guest.name],
                         "characters": [room.characters[0], room.characters[1]],
                         "step_ack": [room.host.last_step_seq, room.guest.last_step_seq],
                         "frame_id": room.snapshot_seq, "flight_id": room.flight_id,
                         "sim_time": match.time, "phase": match._accumulator,
                         "server_time": time.monotonic(),
                         "shield_left": [max(0, expiry - match.time) for expiry in match.shield_until],
                         "pending_goal": room.pending_goal_until is not None,
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
