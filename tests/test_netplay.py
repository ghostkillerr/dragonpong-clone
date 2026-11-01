"""Authoritative online contact timing and flight prediction regressions."""
import math
import random
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from dragonpong.client import predict_ball
from dragonpong.engine import Match, Rules, TICK
from dragonpong.netplay import (MAX_CONTACT_LAG, ContactFrames, ServerClockFloor,
                               present_flight, predict_view, view_is_stale)
from dragonpong.server import Client, Room, Server


def make_room(player=0, speed=80, depth=2, lateral=0, paddle=0):
    host = Client(MagicMock(), 'host', room_id='room', player=0, protocol=3)
    guest = Client(MagicMock(), 'guest', room_id='room', player=1, protocol=3)
    for client in (host, guest):
        client.writer.drain = AsyncMock()
        client.writer.transport.get_write_buffer_size.return_value = 0
        client.strike_refs = True
    match = Match(Rules(shield=False, silent_ball=False), seed=17)
    match.ball_x = lateral
    match.ball_z = depth if player == 0 else 20 - depth
    match.vz = -speed if player == 0 else speed
    match.paddles[player] = paddle
    room = Room('room', host, guest, characters={0: 0, 1: 1}, match=match, started=True)
    server = Server()
    server.rooms['room'] = room
    return server, room, host if player == 0 else guest


class FlightPredictionTests(unittest.TestCase):
    def test_fresh_arrival_with_old_server_stamp_is_stale(self):
        clock = ServerClockFloor()
        clock.observe(500, 100)
        state = {'server_time': 500, '_received_at': 100.3}
        clock.tag(state, 100.3)
        self.assertTrue(view_is_stale(state, 100.3))
        self.assertFalse(view_is_stale({'_received_at': 100.3}, 100.3))

    def test_clock_floor_is_independent_of_clock_origin_and_never_goes_back(self):
        for origin in (-100000, 0, 123456):
            clock = ServerClockFloor()
            clock.observe(origin, 100)
            self.assertAlmostEqual(clock.at(100.2), origin + .2)
            clock.observe(origin + .1, 100.3)
            self.assertAlmostEqual(clock.at(100.3), origin + .3)
            clock.observe(origin + .5, 100.4)
            self.assertAlmostEqual(clock.at(100.5), origin + .6)

    def test_clock_floor_ignores_unusable_timestamps(self):
        clock = ServerClockFloor()
        for stamp in (None, True, '500', math.nan, math.inf):
            clock.observe(stamp, 100)
        self.assertIsNone(clock.at(101))
        state = {'server_time': 500, '_received_at': 100}
        clock.tag(state, 100)
        self.assertNotIn('_server_now_floor', state)

    def test_contact_view_uses_an_actual_native_tick_in_both_directions(self):
        for player in (0, 1):
            state = {'ball': [8, 18 if player == 0 else 2],
                     'velocity': [6, -120 if player == 0 else 120],
                     'frame_id': 1, 'flight_id': 1, 'phase': .003, 'sim_time': 0,
                     '_received_at': 100, 'pending_goal': False}
            presented = present_flight(state, 300, 100, player)
            depth = presented.flight.z if player == 0 else 20 - presented.flight.z
            self.assertTrue(presented.held)
            self.assertTrue(1 <= depth < 6)
            self.assertEqual(presented.flight, predict_view(state, presented.seconds))
            self.assertIs(presented.source, state)
            self.assertLess(presented.seconds, .15)

    def test_spectator_and_legacy_views_do_not_hold_contact(self):
        state = {'ball': [0, 18], 'velocity': [0, -120], 'phase': .003,
                 '_received_at': 100, 'pending_goal': False}
        for player, modern in ((None, True), (0, False)):
            presented = present_flight(state, 300, 100, player, modern)
            self.assertFalse(presented.held)
            self.assertLess(presented.flight.z, 1)

    def test_old_or_confirmed_goal_does_not_retain_contact(self):
        for barrier in ('source_age', 'server_age', 'sim_age', 'new_flight', 'winner'):
            frames = ContactFrames()
            source = {'ball': [0, 3], 'velocity': [0, -80], 'frame_id': 1,
                      'flight_id': 1, 'sim_time': 0, '_received_at': 100,
                      'pending_goal': False}
            frames.receive(source)
            state = {**source, 'ball': [0, .28], 'velocity': [0, 0],
                     'frame_id': 2, 'sim_time': .051, 'pending_goal': True,
                     '_received_at': 100.05}
            now = 100.05
            if barrier == 'source_age':
                now = 100.3
            elif barrier == 'server_age':
                frames.candidate['server_time'] = 500
                frames.candidate['_server_now_floor'] = 500.3
            elif barrier == 'sim_age':
                state['sim_time'] = .3
            elif barrier == 'new_flight':
                state['flight_id'] = 2
            else:
                state['winner'] = 1
            frames.receive(state)
            presented = present_flight(state, 80, now, 0)
            self.assertIs(presented.source, state)
            self.assertFalse(presented.held)

    def test_private_candidate_does_not_form_recursive_frame_history(self):
        frames = ContactFrames()
        state = {'ball': [0, 3], 'velocity': [0, -80], 'frame_id': 1,
                 'flight_id': 1, 'sim_time': 0, '_received_at': 100, 'events': []}
        frames.receive(state)
        state = {**state, 'velocity': [0, 0], 'pending_goal': True}
        for frame_id in range(2, 100):
            state = frames.receive({**state, 'frame_id': frame_id})
            self.assertEqual(state['_contact_candidate']['frame_id'], 1)
            self.assertNotIn('_contact_candidate', state['_contact_candidate'])
            self.assertNotIn('events', state['_contact_candidate'])

    def test_prediction_matches_5000_seeded_engine_flights(self):
        rng = random.Random(90217)
        for index in range(5000):
            player = index % 2
            match = Match(Rules(shield=True, silent_ball=False), seed=index)
            match.time = rng.choice((0, 2.0, 17.3))
            match._accumulator = rng.random() * TICK
            match.ball_x = rng.uniform(-9.2, 9.2)
            depth = rng.uniform(.3, 19)
            match.ball_z = depth if player == 0 else 20 - depth
            match.vx = rng.uniform(-80, 80)
            match.vz = rng.uniform(3, 160) * (-1 if player == 0 else 1)
            duration = rng.choice((0, TICK, .05, .1, .2))
            left = rng.choice((0, TICK, .05, 2.0))
            match.shield_until[player] = match.time + left if left else 0
            state = {'ball': [match.ball_x, match.ball_z], 'velocity': [match.vx, match.vz],
                     'phase': match._accumulator, 'sim_time': match.time,
                     'shield_left': [max(0, t - match.time) for t in match.shield_until]}
            projected = predict_view(state, duration)
            match.step(duration)
            with self.subTest(index=index):
                self.assertEqual((projected.x, projected.z), (match.ball_x, match.ball_z))

    def test_wall_prediction_matches_discrete_native_physics(self):
        match = Match(Rules(shield=False, silent_ball=False))
        match.ball_x, match.ball_z, match.vx, match.vz = 8.9, 10, 10, -10
        predicted = predict_ball([8.9, 10], [10, -10], .051)
        match.step(.051)
        self.assertEqual(predicted, (match.ball_x, match.ball_z))


class ContactTimingTests(unittest.IsolatedAsyncioTestCase):
    async def test_packet_burst_keeps_valid_contact_through_pending_goal(self):
        for player in (0, 1):
            server, room, client = make_room(player, depth=3)
            frames = ContactFrames()
            source = server.snapshot(room)
            client.send_state(source)
            source['_received_at'] = 100
            frames.receive(source)
            server.step_match(room, .051)
            pending = server.snapshot(room)
            client.send_state(pending)
            pending['_received_at'] = 100.05
            frames.receive(pending)
            self.assertTrue(pending['pending_goal'])
            presented = present_flight(pending, 80, 100.05, player)
            self.assertEqual(presented.source['frame_id'], source['frame_id'])
            reference = {'frame': presented.source['frame_id'], 'seconds': presented.seconds}
            self.assertEqual(server.referenced_strike(room, client, reference), 'compensated')
            self.assertEqual(room.match.scores, [0, 0])
            self.assertGreater(room.match.vz * (1 if player == 0 else -1), 0)

    def send_view(self, server, room, client):
        state = server.snapshot(room)
        client.send_state(state)
        return {'frame': state['frame_id'], 'seconds': 0}

    def advance(self, server, room, seconds):
        events = []
        while seconds > 1e-12:
            portion = min(.05, seconds)
            events.extend(server.step_match(room, portion))
            seconds -= portion
        return events

    async def test_contact_boundaries_are_strict_in_both_directions(self):
        for player in (0, 1):
            for x, depth, expected in ((2.999, 3, 'hit'), (3, 3, 'out_of_reach'),
                                       (-3, 3, 'out_of_reach'), (0, 5.999, 'hit'),
                                       (0, 6, 'buffered'), (0, .99, 'too_late'),
                                       (0, 1, 'hit')):
                with self.subTest(player=player, x=x, depth=depth):
                    server, room, client = make_room(player, depth=depth, lateral=x)
                    reference = self.send_view(server, room, client)
                    self.assertEqual(server.referenced_strike(room, client, reference), expected)

    async def test_short_server_stalls_catch_up_once_for_either_task_order(self):
        for player in (0, 1):
            for stall in (.02, .05, .12, .24):
                for clock_first in (False, True):
                    with self.subTest(player=player, stall=stall, clock_first=clock_first):
                        clock = [100.0]
                        server, room, client = make_room(player, speed=15, depth=5)
                        with patch('dragonpong.server.time.monotonic', side_effect=lambda: clock[0]):
                            reference = self.send_view(server, room, client)
                            reference['seconds'] = min(.05, stall)
                            room.last_update_at = clock[0]
                            clock[0] += stall
                            if clock_first:
                                room.pending_events.extend(server.advance_to_now(room))
                            await server.dispatch(client, {'type': 'strike', 'press': 1, 'view': reference})
                            self.assertEqual(room.strike_stats['hit'], 1)
                            expected_time = int((stall + 1e-12) / TICK) * TICK
                            self.assertAlmostEqual(room.match.time, expected_time)
                            events = room.pending_events + server.advance_to_now(room)
                            self.assertAlmostEqual(room.match.time, expected_time)
                            self.assertEqual(sum(e.kind == 'paddle' for e in events), 1)
                            self.assertFalse(any(e.kind == 'goal' for e in events))

    async def test_long_server_freeze_rejects_old_press_without_resurrection(self):
        clock = [100.0]
        server, room, client = make_room()
        with patch('dragonpong.server.time.monotonic', side_effect=lambda: clock[0]):
            reference = self.send_view(server, room, client)
            room.last_update_at = clock[0]
            clock[0] += .6
            await server.dispatch(client, {'type': 'strike', 'press': 1, 'view': reference})
            self.assertEqual(room.strike_stats['stale_view'], 1)
            clock[0] += .1
            server.advance_to_now(room)
            self.assertEqual(room.match.scores, [0, 1])

    async def test_early_press_hits_fast_ball_between_server_frames(self):
        for player in (0, 1):
            server, room, client = make_room(player, speed=120, depth=6.1)
            reference = self.send_view(server, room, client)
            self.assertEqual(server.referenced_strike(room, client, reference), 'buffered')
            server.step_match(room, .05)
            self.assertGreater(room.match.vz * (1 if player == 0 else -1), 0)
            self.assertEqual(room.match.scores, [0, 0])
            self.assertFalse(room.pending_strikes)

    async def test_overestimated_ping_buffers_future_view_without_early_hit(self):
        server, room, client = make_room(speed=40, depth=8)
        reference = self.send_view(server, room, client)
        reference['seconds'] = .1
        self.assertEqual(server.referenced_strike(room, client, reference), 'buffered')
        self.assertEqual(room.match.ball_z, 8)
        self.assertLess(room.match.vz, 0)
        server.step_match(room, .1)
        self.assertGreater(room.match.vz, 0)
        self.assertFalse(room.pending_strikes)

    async def test_compensation_applies_silent_and_shield_rolls_only_once(self):
        class Rolls:
            def __init__(self):
                self.values = iter((1, 1, 7, 13))
            def randrange(self, bound):
                return next(self.values)

        server, room, client = make_room()
        room.match.rules = Rules(shield=True, silent_ball=True)
        room.match.rng = Rolls()
        room.match.silent_until = math.inf
        reference = self.send_view(server, room, client)
        server.step_match(room, .051)
        self.assertEqual(server.referenced_strike(room, client, reference), 'compensated')
        self.assertAlmostEqual(room.match.shield_until[0], room.match.time + 30)
        self.assertEqual(room.match.silent_until, math.inf)
        self.assertEqual([e.kind for e in room.match.events],
                         ['paddle', 'silent_off', 'shield_on', 'silent_on'])
        self.assertEqual(room.match.scores, [0, 0])

    async def test_no_input_scores_once_and_final_goal_cannot_be_undone(self):
        for player in (0, 1):
            server, room, client = make_room(player)
            room.match.rules = Rules(score=1, shield=False, silent_ball=False)
            reference = self.send_view(server, room, client)
            self.advance(server, room, .1)
            self.assertEqual(room.match.scores, [0, 0])
            self.assertIsNotNone(room.pending_goal_until)
            self.advance(server, room, .3)
            self.assertEqual(room.match.scores[1 - player], 1)
            self.assertEqual(room.match.winner, 1 - player)
            self.assertEqual(server.referenced_strike(room, client, reference), 'finished')
            self.advance(server, room, .5)
            self.assertEqual(sum(room.match.scores), 1)

    async def test_complete_online_score_cycles_and_serves(self):
        for target in (1, 3, 10, 30):
            with self.subTest(target=target):
                server, room, _ = make_room()
                room.match.rules = Rules(score=target, shield=False, silent_ball=False)
                events = []
                points = 0
                while room.match.winner is None:
                    player = points % 2
                    room.match.ball_z = 2 if player == 0 else 18
                    room.match.vz = -80 if player == 0 else 80
                    events.extend(self.advance(server, room, .4))
                    points += 1
                    self.assertEqual(sum(room.match.scores), points)
                    if room.match.winner is None:
                        events.extend(self.advance(server, room, 7.3))
                        client = (room.host, room.guest)[player]
                        reference = self.send_view(server, room, client)
                        self.assertEqual(server.referenced_strike(room, client, reference), 'serve')
                self.assertEqual(max(room.match.scores), target)
                self.assertEqual(sum(e.kind == 'goal' for e in events), points)
                self.assertEqual(sum(e.kind == 'win' for e in events), 1)

    async def test_old_contact_cannot_turn_into_serve_after_goal_pause(self):
        server, room, client = make_room()
        reference = self.send_view(server, room, client)
        self.advance(server, room, 8)
        self.assertEqual(server.referenced_strike(room, client, reference), 'stale_view')
        self.assertEqual(room.match.vz, 0)

    async def test_compensated_angle_uses_contact_that_player_heard(self):
        for player in (0, 1):
            server, room, client = make_room(player, depth=4.5, paddle=1)
            room.match.vx = 20
            reference = self.send_view(server, room, client)
            self.advance(server, room, .1)
            self.assertGreater(room.match.ball_x, room.match.paddles[player])
            self.assertEqual(server.referenced_strike(room, client, reference), 'compensated')
            self.assertLess(room.match.vx, 0)

    async def test_fresh_frame_does_not_allow_hitting_ball_going_away(self):
        server, room, _ = make_room(player=1)
        reference = self.send_view(server, room, room.host)
        self.assertEqual(server.referenced_strike(room, room.host, reference), 'wrong_direction')
        self.assertGreater(room.match.vz, 0)

    async def test_reference_limits_and_unissued_frames_are_rejected(self):
        for kind in ('expired_contact', 'expired_wall_time', 'unknown', 'foreign',
                     'unsent', 'old_flight', 'nan', 'infinite', 'negative', 'too_far', 'boolean'):
            with self.subTest(kind=kind):
                server, room, client = make_room(speed=3, depth=4)
                if kind == 'unsent':
                    client.writer.transport.get_write_buffer_size.return_value = 10000
                reference = self.send_view(server, room, client)
                if kind == 'expired_contact':
                    self.advance(server, room, MAX_CONTACT_LAG + TICK)
                elif kind == 'expired_wall_time':
                    sent_at, state = client.views.pop()
                    client.views.append((sent_at - 1, state))
                elif kind == 'unknown':
                    reference['frame'] += 100
                elif kind == 'foreign':
                    client = room.guest
                elif kind == 'old_flight':
                    server.new_flight(room)
                elif kind in ('nan', 'infinite', 'negative', 'too_far', 'boolean'):
                    reference['seconds'] = {'nan': math.nan, 'infinite': math.inf,
                                            'negative': -.1, 'too_far': .21, 'boolean': True}[kind]
                before = room.match.ball_x, room.match.ball_z, room.match.vz, list(room.match.scores)
                self.assertNotIn(server.referenced_strike(room, client, reference), ('hit', 'compensated', 'buffered'))
                self.assertEqual((room.match.ball_x, room.match.ball_z, room.match.vz, room.match.scores), before)

    async def test_ordered_movement_then_contact_uses_actual_player_paddle(self):
        for player in (0, 1):
            server, room, client = make_room(player, lateral=3)
            reference = self.send_view(server, room, client)
            await server.dispatch(client, {'type': 'step', 'direction': 1 if player == 0 else -1, 'seq': 1})
            await server.dispatch(client, {'type': 'strike', 'press': 1, 'view': reference})
            self.assertEqual(room.match.paddles[player], 1)
            self.assertEqual(room.match.ball_x, 1)
            self.assertEqual(client.last_step_seq, 1)
            self.assertIn('hit', room.strike_stats)

    async def test_duplicate_and_previous_flight_press_cannot_hit_twice(self):
        server, room, client = make_room()
        reference = self.send_view(server, room, client)
        await server.dispatch(client, {'type': 'strike', 'press': 1, 'view': reference})
        velocity = room.match.vx, room.match.vz
        await server.dispatch(client, {'type': 'strike', 'press': 1, 'view': reference})
        await server.dispatch(client, {'type': 'strike', 'press': 2, 'view': reference})
        self.assertEqual((room.match.vx, room.match.vz), velocity)
        self.assertEqual(room.strike_stats['hit'], 1)
        self.assertEqual(room.strike_stats['stale_view'], 1)

    async def test_buffer_expires_and_cannot_leak_to_next_flight(self):
        for reversal in (False, True):
            server, room, client = make_room(speed=3, depth=8)
            reference = self.send_view(server, room, client)
            self.assertEqual(server.referenced_strike(room, client, reference), 'buffered')
            if reversal:
                server.new_flight(room)
            else:
                self.advance(server, room, .3)
            self.assertFalse(room.pending_strikes)
            room.match.ball_z = 3
            server.step_match(room, TICK)
            self.assertLess(room.match.vz, 0)

    async def test_shield_reversal_invalidates_old_contact(self):
        server, room, client = make_room()
        room.match.rules = Rules(shield=True, silent_ball=True)
        room.match.shield_until[0] = 30
        room.match.silent_until = math.inf
        reference = self.send_view(server, room, client)
        self.advance(server, room, .051)
        self.assertGreater(room.match.vz, 0)
        self.assertEqual(server.referenced_strike(room, client, reference), 'stale_view')
        self.assertEqual(room.match.scores, [0, 0])
        self.assertIsNone(room.pending_goal_until)

    async def test_miss_at_side_is_not_saved_by_later_movement(self):
        server, room, client = make_room(lateral=6)
        reference = self.send_view(server, room, client)
        self.assertEqual(server.referenced_strike(room, client, reference), 'out_of_reach')
        self.assertFalse(room.pending_strikes)
        room.match.paddles[0] = 6
        self.advance(server, room, .4)
        self.assertEqual(room.match.scores, [0, 1])

    async def test_pending_goal_frame_is_not_a_new_hit_window(self):
        server, room, client = make_room()
        self.advance(server, room, .051)
        reference = self.send_view(server, room, client)
        self.assertEqual(server.referenced_strike(room, client, reference), 'stale_view')

    async def test_legacy_defender_keeps_immediate_goal_behavior(self):
        server, room, client = make_room()
        client.strike_refs = False
        server.step_match(room, .051)
        self.assertEqual(room.match.scores, [0, 1])
        self.assertIsNone(room.pending_goal_until)

    async def test_spectator_cannot_strike_or_submit_reference(self):
        server, room, client = make_room()
        reference = self.send_view(server, room, client)
        viewer = Client(MagicMock(), 'viewer', room_id='room', strike_refs=True)
        room.spectators.add(viewer)
        await server.dispatch(viewer, {'type': 'strike', 'press': 1, 'view': reference})
        self.assertEqual(room.match.vz, -80)
        self.assertFalse(room.strike_stats)

    async def test_snapshot_is_immutable_when_match_moves_or_scores(self):
        server, room, client = make_room()
        state = server.snapshot(room)
        client.send_state(state)
        room.match.paddles[0] = 5
        room.match.scores[1] = 1
        self.assertEqual(state['paddles'], [0, 0])
        self.assertEqual(state['scores'], [0, 0])
        self.assertEqual(client.views[-1][1]['paddles'], [0, 0])

    async def test_press_seen_in_range_survives_arrival_after_goal_plane(self):
        for player in (0, 1):
            with self.subTest(player=player):
                server, room, client = make_room(player)
                state = server.snapshot(room)
                client.send_state(state)
                server.step_match(room, .034)
                await server.dispatch(client, {'type': 'strike', 'press': 1,
                                              'view': {'frame': state.get('frame_id', 0), 'seconds': 0}})
                self.assertEqual(room.match.scores, [0, 0])
                self.assertGreater(room.match.vz * (1 if player == 0 else -1), 0)
