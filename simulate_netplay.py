"""Deterministic TCP-order network matrix; no public server or audio device.

Uses the production server, wire frames, event coalescer, paddle replay, and
flight prediction. Delays model ordered TCP delivery/retransmission stalls,
not independent UDP packet loss. Real socket coverage lives in tests/.
"""
from __future__ import annotations

import argparse
from collections import Counter
import heapq
import hashlib
import itertools
import json
from pathlib import Path
import queue
import random
from unittest.mock import patch

from dragonpong.client import LatestEventQueue, PaddlePrediction, expand_frame
from dragonpong.engine import Match, Rules, TICK
from dragonpong.netplay import (MAX_CONTACT_LAG, MAX_PREDICTION, MAX_VIEW_AGE,
                               ContactFrames, present_flight, predict_view, view_is_stale, view_seconds)
from dragonpong.server import Client, Room, Server


PROFILES = {
    'local_10ms': (.005, .005, 0, 0),
    'normal_60ms': (.03, .03, .01, 0),
    'mobile_160ms': (.06, .1, .035, 0),
    'asymmetric_down_165ms': (.15, .015, .02, 0),
    'asymmetric_up_165ms': (.015, .15, .02, 0),
    'high_300ms': (.15, .15, .03, 0),
    'tcp_retransmit_180ms': (.04, .04, .015, .18),
    'outage_650ms': (.04, .04, .01, .65),
}


class Writer:
    def __init__(self):
        self.transport = self
        self.packets = []
        self.closed = False

    def get_write_buffer_size(self):
        return 0

    def write(self, data):
        self.packets.append(data)

    def close(self):
        self.closed = True


def simulate(player, speed, profile, path, press_depth, input_pause, seed, ping_factor=1,
             contact_presentation=True):
    down, up, jitter, burst = PROFILES[profile]
    rng_down, rng_up = random.Random(seed), random.Random(seed + 91)
    x, vx = {'center': (0, 0), 'right_wall': (8, 6), 'left_wall': (-8, -6)}[path]
    host, guest = Client(Writer(), 'host', player=0, protocol=3), Client(Writer(), 'guest', player=1, protocol=3)
    client = (host, guest)[player]
    host.strike_refs = guest.strike_refs = True
    match = Match(Rules(shield=False, silent_ball=False), seed=seed)
    match._accumulator = .003
    match.ball_x, match.vx = x, vx
    match.ball_z = 18 if player == 0 else 2
    match.vz = -speed if player == 0 else speed
    match.paddles[player] = x
    room = Room('matrix', host, guest, characters={0: 0, 1: 1}, match=match, started=True)
    server = Server()
    server.rooms[room.room_id] = room
    inbox, prediction = LatestEventQueue(), PaddlePrediction()
    contact_frames = ContactFrames()
    wire_state = app_state = None
    pending, serial = [], itertools.count()
    now = 0.0
    last_down = last_up = -1.0
    next_frame = next_render = next_move = 0.0
    packet_count = 0
    issued = False
    intended_paddle = None
    command = None
    result = 'no_playable_view'
    legacy_miss = False
    eligible = False
    steps = 0
    trace = []
    held_at_press = False

    def send_command(message, pause=0):
        nonlocal last_up
        last_up = max(last_up, now + pause + max(0, up + rng_up.uniform(-jitter, jitter)))
        heapq.heappush(pending, (last_up, next(serial), 'command', message))

    # Patch only within this synchronous simulation. No real waits or threads.
    with patch('dragonpong.server.time.monotonic', side_effect=lambda: now):
        horizon = 18 / speed + 2
        while now <= horizon:
            if now + 1e-9 >= next_frame:
                state = server.snapshot(room)
                client.send_state(state)
                for data in client.writer.packets:
                    packet_count += 1
                    delay = max(0, down + rng_down.uniform(-jitter, jitter))
                    if burst and packet_count % 19 == 1:
                        delay += burst
                    last_down = max(last_down, now + delay)
                    heapq.heappush(pending, (last_down, next(serial), 'state', json.loads(data)))
                client.writer.packets.clear()
                next_frame += 1 / 60
            while pending and pending[0][0] <= now + 1e-9:
                _, _, kind, message = heapq.heappop(pending)
                if kind == 'state':
                    if message['type'] == 'frame':
                        message = expand_frame(message, wire_state)
                    message['_received_at'] = now
                    if contact_presentation:
                        # A conservative established pre-match pong bound. The
                        # simulation clock is the server's wall-clock origin.
                        message['_server_now_floor'] = now - down - up
                        contact_frames.receive(message)
                    wire_state = message
                    inbox.put(message)
                elif message['type'] == 'step':
                    server.move_step(room, client, message)
                else:
                    reference, pressed_at = message['view'], message['pressed_at']
                    lag = match.time - message['view_time']
                    eligible = (room.flight_id == message['flight'] and match.winner is None and
                                match.time - message['source_time'] <= MAX_VIEW_AGE and
                                -MAX_PREDICTION - 1e-9 <= lag <= MAX_CONTACT_LAG + 1e-9)
                    # Counterfactual: immediate authoritative contact, no grace.
                    legacy_miss = (room.pending_goal_until is not None or bool(sum(match.scores)) or
                                   not match.can_strike(player))
                    if match.paddles[player] != intended_paddle:
                        raise AssertionError('TCP-ordered paddle did not match the local press')
                    result = server.referenced_strike(room, client, reference)
                    if result == 'buffered':
                        before_flight = room.flight_id
                        buffer_hit = False
                        for _ in range(64):
                            now += 1 / 240
                            steps += 1
                            events = server.step_match(room, 1 / 240)
                            buffer_hit |= any(e.kind == 'paddle' and e.player == player for e in events)
                            if not room.pending_strikes:
                                break
                        result = 'buffered_hit' if buffer_hit and room.flight_id != before_flight else 'buffer_expired'
                    accepted = result in ('hit', 'compensated', 'buffered_hit')
                    if accepted != eligible:
                        trace.append({'at': round(now, 6), 'result': result, 'eligible': eligible,
                                      'lag_ms': round(lag * 1000, 3),
                                      'input_age_ms': round((now - pressed_at) * 1000, 3),
                                      'scores': list(match.scores), 'pending_goal': room.pending_goal_until})
                    return {'player': player, 'speed': speed, 'profile': profile, 'path': path,
                            'press_depth': press_depth, 'input_pause': input_pause, 'seed': seed,
                            'ping_factor': ping_factor, 'result': result, 'eligible': eligible,
                            'held_at_press': held_at_press,
                            'legacy_miss': legacy_miss, 'lag_ms': round(lag * 1000, 3),
                            'failure': trace, 'steps': steps}
            if now + 1e-9 >= next_render:
                while True:
                    try:
                        app_state = inbox.get_nowait()
                        prediction.acknowledge(app_state['step_ack'][player])
                    except queue.Empty:
                        break
                if (app_state is not None and not issued and
                        (not contact_presentation or not view_is_stale(app_state, now))):
                    if contact_presentation:
                        presentation = present_flight(app_state, (down + up) * 1000 * ping_factor, now, player)
                        source, seconds, shown = presentation.source, presentation.seconds, presentation.flight
                    else:
                        source = app_state
                        seconds = view_seconds(source, (down + up) * 1000 * ping_factor, now)
                        shown = predict_view(source, seconds)
                    local_x = prediction.position(app_state['paddles'][player], player)
                    if now >= next_move and abs(shown.x - local_x) >= .75:
                        direction = (1 if shown.x > local_x else -1) * (1 if player == 0 else -1)
                        seq = prediction.add(direction)
                        send_command({'type': 'step', 'seq': seq, 'direction': direction})
                        local_x = prediction.position(app_state['paddles'][player], player)
                        next_move = now + .063
                    depth = shown.z if player == 0 else 20 - shown.z
                    incoming = shown.vz < 0 if player == 0 else shown.vz > 0
                    if (incoming and not source['pending_goal'] and 1 <= depth < press_depth and
                            abs(shown.x - local_x) < 3 and not sum(app_state['scores'])):
                        issued, intended_paddle = True, local_x
                        held_at_press = contact_presentation and presentation.held
                        command = {'type': 'strike', 'view': {'frame': source['frame_id'], 'seconds': seconds},
                                   'view_time': source['sim_time'] + seconds,
                                   'source_time': source['sim_time'], 'flight': source['flight_id'],
                                   'pressed_at': now}
                        send_command(command, input_pause)
                next_render += 1 / 60
            server.step_match(room, 1 / 240)
            steps += 1
            now += 1 / 240
    return {'player': player, 'speed': speed, 'profile': profile, 'path': path,
            'press_depth': press_depth, 'input_pause': input_pause, 'seed': seed,
            'ping_factor': ping_factor, 'result': result, 'eligible': False,
            'held_at_press': held_at_press,
            'legacy_miss': False, 'failure': [], 'steps': steps}


def run_matrix(contact_presentation=True):
    cases = []
    for args in itertools.product((0, 1), (3, 15, 40, 80, 120), PROFILES,
                                  ('center', 'right_wall', 'left_wall'), (5.8, 2.5),
                                  (0, .08, .35), (11, 29)):
        cases.append(simulate(*args, contact_presentation=contact_presentation))
    # Stale RTT estimates are exercised separately from delay/jitter themselves.
    for args in itertools.product((0, 1), (15, 80), ('mobile_160ms', 'asymmetric_up_165ms'),
                                  ('center', 'right_wall'), (5.8,), (0,), (41,)):
        for factor in (0, .25, 2):
            cases.append(simulate(*args, ping_factor=factor, contact_presentation=contact_presentation))
    failures = [case for case in cases if case['failure']]
    issued = [case for case in cases if case['result'] != 'no_playable_view']
    accepted = [case for case in issued if case['result'] in ('hit', 'compensated', 'buffered_hit')]
    return {'schema': 2, 'presentation': 'contact' if contact_presentation else 'original',
            'cases': len(cases), 'physics_steps': sum(c['steps'] for c in cases),
            'issued_presses': len(issued), 'accepted': len(accepted),
            'rescued_vs_immediate_contact': sum(c['legacy_miss'] for c in accepted),
            'accepted_held_views': sum(c['held_at_press'] for c in accepted),
            'results': dict(Counter(c['result'] for c in cases)),
            'source_sha256': {name: hashlib.sha256((Path(__file__).resolve().parent / name).read_bytes()).hexdigest()
                              for name in ('dragonpong/engine.py', 'dragonpong/server.py',
                                           'dragonpong/client.py', 'dragonpong/netplay.py',
                                           'dragonpong/native_ui.py',
                                           'run_offline.py', 'simulate_netplay.py')},
            'failures': failures, 'details': cases,
            'scope': 'Deterministic ordered TCP delay/jitter/retransmission and input-pause model; not live internet.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('netplay_simulation.json'))
    parser.add_argument('--presentation', choices=('original', 'contact'), default='contact')
    args = parser.parse_args()
    report = run_matrix(args.presentation == 'contact')
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'details'}, ensure_ascii=False))
    raise SystemExit(bool(report['failures']))
