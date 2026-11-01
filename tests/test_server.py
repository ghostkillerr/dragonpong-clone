import asyncio
import json
import unittest

from dragonpong.server import Server


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_strike_reference_feature_is_opt_in(self):
        from dragonpong.netplay import STRIKE_FEATURE
        for protocol, features, expected in ((2, [STRIKE_FEATURE], False),
                                               (3, [], False),
                                               (3, [STRIKE_FEATURE], True)):
            reader, writer = await self.connect()
            await self.send(writer, 'create', name='test', protocol=protocol, features=features)
            room_id = (await self.receive(reader))['room_id']
            self.assertEqual(self.lobby.rooms[room_id].host.strike_refs, expected)

    async def test_disconnect_during_goal_grace_closes_without_provisional_score(self):
        from dragonpong.engine import Match, Rules, TICK
        from dragonpong.netplay import STRIKE_FEATURE
        host, hw = await self.connect()
        guest, gw = await self.connect()
        await self.send(hw, 'create', name='host', protocol=3, features=[STRIKE_FEATURE])
        room_id = (await self.receive(host))['room_id']
        await self.send(gw, 'join', name='guest', room_id=room_id)
        await self.receive(guest)
        room = self.lobby.rooms[room_id]
        room.match = Match(Rules(score=1, shield=False, silent_ball=False))
        room.characters = {0: 0, 1: 1}
        room.match.ball_z, room.match.vz = .9, -80
        room.started = True
        self.lobby.step_match(room, TICK)
        room.task = asyncio.create_task(self.lobby.run_match(room))
        state = await self.receive_type(host, 'state')
        self.assertTrue(state['pending_goal'])
        gw.close()
        await self.receive_type(host, 'room_closed')
        self.assertEqual(room.match.scores, [0, 0])
        self.assertIsNone(room.match.winner)
        self.assertNotIn(room_id, self.lobby.rooms)

    async def test_spectator_receives_finished_match_immediately(self):
        from dragonpong.engine import Match, Rules
        host, hw = await self.connect()
        guest, gw = await self.connect()
        await self.send(hw, 'create', name='bir')
        room_id = (await self.receive(host))['room_id']
        await self.send(gw, 'join', name='iki', room_id=room_id)
        await self.receive(guest)
        room = self.lobby.rooms[room_id]
        room.characters = {0: 0, 1: 1}
        room.match = Match(Rules(score=30))
        room.match.scores = [30, 5]
        room.match.winner = 0
        viewer, vw = await self.connect()
        await self.send(vw, 'spectate', name='izleyen', room_id=room_id)
        self.assertEqual((await self.receive(viewer))['type'], 'accepted')
        state = await self.receive(viewer)
        self.assertEqual(state['scores'], [30, 5])
        self.assertEqual(state['winner'], 0)
    async def asyncSetUp(self):
        self.lobby = Server()
        self.server = await asyncio.start_server(self.lobby.handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        self.writers = []

    async def asyncTearDown(self):
        for writer in self.writers:
            writer.close()
        await asyncio.gather(*(w.wait_closed() for w in self.writers), return_exceptions=True)
        for room in self.lobby.rooms.values():
            if room.task:
                room.task.cancel()
        self.server.close()
        await self.server.wait_closed()

    async def connect(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        self.writers.append(writer)
        return reader, writer

    async def send(self, writer, kind, **fields):
        writer.write((json.dumps({"type": kind, "protocol": 2, **fields}) + "\n").encode())
        await writer.drain()

    async def receive(self, reader):
        return json.loads(await asyncio.wait_for(reader.readline(), 2))

    async def test_two_rooms_match_independently(self):
        a, aw = await self.connect()
        b, bw = await self.connect()
        await self.send(aw, "create", name="ghostkiller")
        await self.send(bw, "create", name="baska")
        room_a = (await self.receive(a))["room_id"]
        room_b = (await self.receive(b))["room_id"]
        self.assertNotEqual(room_a, room_b)
        listing, lw = await self.connect()
        await self.send(lw, "rooms")
        self.assertEqual(len((await self.receive(listing))["rooms"]), 2)
        c, cw = await self.connect()
        d, dw = await self.connect()
        await self.send(cw, "join", name="birinci-arkadas", room_id=room_a)
        await self.send(dw, "join", name="ikinci-arkadas", room_id=room_b)
        self.assertEqual((await self.receive(c))["player"], 1)
        self.assertEqual((await self.receive(d))["player"], 1)
        for reader in (a, b, c, d):
            self.assertEqual((await self.receive(reader))["type"], "characters")
        for writer in (aw, bw, cw, dw):
            await self.send(writer, "character", value=0)
        for reader in (a, b, c, d):
            self.assertEqual((await self.receive(reader))["type"], "settings_required")
        for writer in (aw, bw):
            await self.send(writer, "configure", score=30, shield=True, silent_ball=True)
        for reader in (a, b, c, d):
            self.assertEqual((await self.receive(reader))["type"], "configured")
        await self.send(aw, "start")
        await self.send(bw, "start")
        for reader in (a, b, c, d):
            self.assertEqual((await self.receive(reader))["type"], "started")
            state = await self.receive(reader)
            self.assertEqual(state["type"], "state")
            self.assertEqual(state["scores"], [0, 0])

    async def test_spectator_is_room_scoped(self):
        a, aw = await self.connect()
        b, bw = await self.connect()
        await self.send(aw, "create", name="bir")
        await self.send(bw, "create", name="iki")
        room_a = (await self.receive(a))["room_id"]
        room_b = (await self.receive(b))["room_id"]
        spectator, sw = await self.connect()
        await self.send(sw, "spectate", name="izleyici", room_id=room_a)
        result = await self.receive(spectator)
        self.assertEqual(result["players"], ["bir", None])
        await self.send(sw, "perspective", player=1)
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(spectator.readline(), .05)
        await self.send(sw, "perspective", player=0)
        self.assertEqual((await self.receive(spectator))["player"], 0)
        self.assertNotEqual(room_a, room_b)

    async def receive_type(self, reader, expected):
        for _ in range(100):
            message = await self.receive(reader)
            if message['type'] == expected:
                return message
        self.fail(f'Missing {expected}')

    async def test_controls_spectator_and_score_flow(self):
        host, hw = await self.connect()
        guest, gw = await self.connect()
        viewer, vw = await self.connect()
        await self.send(hw, 'create', name='ghostkiller')
        room_id = (await self.receive(host))['room_id']
        await self.send(gw, 'join', name='arkadas', room_id=room_id)
        await self.receive(guest)
        await self.receive(host); await self.receive(guest)
        await self.send(hw, 'character', value=4)
        await self.send(gw, 'character', value=1)
        await self.receive(host); await self.receive(guest)
        await self.send(hw, 'configure', score=30, shield=True, silent_ball=False)
        await self.receive(host); await self.receive(guest)
        room = self.lobby.rooms[room_id]
        self.assertEqual(room.match.rules.score, 30)
        await self.send(hw, 'strike')  # Cannot serve before host Start.
        await self.send(hw, 'rooms')  # Same-stream ordering barrier.
        await self.receive_type(host, 'rooms')
        self.assertEqual(room.match.vz, 0)
        await self.send(vw, 'spectate', name='izleyici', room_id=room_id)
        await self.receive(viewer)
        await self.send(hw, 'start')
        for reader in (host, guest, viewer):
            await self.receive_type(reader, 'started')
        await self.send(hw, 'step', direction=1)
        await self.send(gw, 'step', direction=1)
        await self.send(vw, 'step', direction=1)
        await self.send(vw, 'strike')
        for reader, writer in ((host, hw), (guest, gw), (viewer, vw)):
            await self.send(writer, 'rooms')
            await self.receive_type(reader, 'rooms')
        self.assertEqual(room.match.paddles, [1, -1])
        self.assertEqual(room.match.vz, 0)
        await self.send(hw, 'strike')
        await self.send(hw, 'rooms')
        await self.receive_type(host, 'rooms')
        self.assertGreater(room.match.vz, 0)
        await self.send(vw, 'perspective', player=1)
        self.assertEqual((await self.receive_type(viewer, 'perspective'))['player'], 1)
        state = await self.receive_type(viewer, 'state')
        self.assertEqual(state['players'], ['ghostkiller', 'arkadas'])
        self.assertEqual(state['characters'], [4, 1])
        self.assertIn('shields', state)
        room.match.scores = [29, 0]
        room.match.ball_z, room.match.vz = 19.9, 3
        for _ in range(20):
            state = await self.receive_type(viewer, 'state')
            if state['winner'] is not None:
                break
        self.assertEqual(state['scores'], [30, 0])
        self.assertEqual(state['winner'], 0)

    async def test_old_protocol_is_explicitly_rejected(self):
        reader, writer = await self.connect()
        await self.send(writer, 'create', name='eski', protocol=1)
        self.assertEqual((await self.receive(reader))['type'], 'rejected')
        self.assertEqual(self.lobby.rooms, {})

    async def test_new_protocol_sends_full_state_then_compact_frames(self):
        host, hw = await self.connect()
        guest, gw = await self.connect()
        await self.send(hw, 'rooms')
        lobby = await self.receive(host)
        self.assertIn(3, lobby['protocols'])
        self.assertIn('step_ack', lobby['features'])
        await self.send(hw, 'create', name='bir', protocol=3)
        room_id = (await self.receive(host))['room_id']
        await self.send(gw, 'join', name='iki', room_id=room_id, protocol=3)
        await self.receive(guest)
        await self.receive_type(host, 'characters')
        await self.receive_type(guest, 'characters')
        await self.send(hw, 'character', value=0)
        await self.send(gw, 'character', value=1)
        await self.receive_type(host, 'settings_required')
        await self.receive_type(guest, 'settings_required')
        await self.send(hw, 'configure', score=3, shield=False, silent_ball=False)
        await self.receive_type(host, 'configured')
        await self.receive_type(guest, 'configured')
        await self.send(hw, 'start')
        await self.receive_type(host, 'started')
        first = await self.receive(host)
        second = await self.receive(host)
        self.assertEqual(first['type'], 'state')
        self.assertEqual(second['type'], 'frame')
        self.assertEqual(second['p'], first['paddles'])
        self.assertEqual(second['s'], first['scores'])
        self.assertEqual(second['a'], first['step_ack'])

    async def test_sequenced_steps_are_applied_once_and_acked_for_both_players(self):
        from dragonpong.engine import Match
        host, hw = await self.connect()
        guest, gw = await self.connect()
        await self.send(hw, 'create', name='bir', protocol=3)
        room_id = (await self.receive(host))['room_id']
        await self.send(gw, 'join', name='iki', room_id=room_id, protocol=3)
        await self.receive(guest)
        room = self.lobby.rooms[room_id]
        room.characters = {0: 0, 1: 1}
        room.match = Match()
        room.started = True
        await self.send(hw, 'step', direction=1, seq=1)
        await self.send(hw, 'step', direction=1, seq=1)
        await self.send(hw, 'step', direction=-1, seq=2)
        await self.send(gw, 'step', direction=1, seq=1)
        for reader, writer in ((host, hw), (guest, gw)):
            await self.send(writer, 'rooms')
            await self.receive_type(reader, 'rooms')
        self.assertEqual(room.match.paddles, [0, -1])
        self.assertEqual(self.lobby.snapshot(room)['step_ack'], [2, 1])
        self.assertEqual(len([event for event in room.match.events if event.kind == 'move']), 3)

    async def test_unsequenced_legacy_step_keeps_native_one_unit_behavior(self):
        from dragonpong.engine import Match
        host, writer = await self.connect()
        guest, gw = await self.connect()
        await self.send(writer, 'create', name='bir', protocol=2)
        room_id = (await self.receive(host))['room_id']
        await self.send(gw, 'join', name='iki', room_id=room_id, protocol=2)
        await self.receive(guest)
        room = self.lobby.rooms[room_id]
        room.characters = {0: 0, 1: 1}
        room.match = Match()
        room.started = True
        await self.send(writer, 'step', direction=1)
        await self.send(writer, 'rooms')
        await self.receive_type(host, 'rooms')
        self.assertEqual(room.match.paddles[0], 1)
        self.assertEqual(self.lobby.snapshot(room)['step_ack'][0], 0)

    async def test_sequenced_step_preserves_strike_and_ball_physics(self):
        from dragonpong.engine import Match, Rules
        host, writer = await self.connect()
        guest, gw = await self.connect()
        await self.send(writer, 'create', name='bir', protocol=3)
        room_id = (await self.receive(host))['room_id']
        await self.send(gw, 'join', name='iki', room_id=room_id, protocol=3)
        await self.receive(guest)
        room = self.lobby.rooms[room_id]
        room.characters = {0: 0, 1: 1}
        room.match = Match(Rules(shield=False, silent_ball=False), seed=17)
        baseline = Match(Rules(shield=False, silent_ball=False), seed=17)
        for match in (room.match, baseline):
            match.ball_x, match.ball_z, match.vz = 1, 3, -3
        room.started = True
        await self.lobby.dispatch(room.host, {'type': 'step', 'direction': 1, 'seq': 1})
        await self.lobby.dispatch(room.host, {'type': 'strike'})
        baseline.move_step(0, 1)
        baseline.strike(0)
        room.match.step(.017)
        baseline.step(.017)
        self.assertEqual((room.match.paddles, room.match.ball_x, room.match.ball_z,
                          room.match.vx, room.match.vz, room.match.scores),
                         (baseline.paddles, baseline.ball_x, baseline.ball_z,
                          baseline.vx, baseline.vz, baseline.scores))

    async def test_out_of_order_step_cannot_move_paddle(self):
        from dragonpong.engine import Match
        host, writer = await self.connect()
        guest, gw = await self.connect()
        await self.send(writer, 'create', name='bir', protocol=3)
        room_id = (await self.receive(host))['room_id']
        await self.send(gw, 'join', name='iki', room_id=room_id, protocol=3)
        await self.receive(guest)
        room = self.lobby.rooms[room_id]
        room.match = Match()
        room.started = True
        with self.assertRaises(ValueError):
            await self.lobby.dispatch(room.host, {'type': 'step', 'direction': 1, 'seq': 2})
        self.assertEqual(room.match.paddles[0], 0)
        self.assertEqual(room.host.last_step_seq, 0)

    async def test_border_step_is_acknowledged_without_crossing_boundary(self):
        from dragonpong.engine import Match
        host, writer = await self.connect()
        guest, gw = await self.connect()
        await self.send(writer, 'create', name='bir', protocol=3)
        room_id = (await self.receive(host))['room_id']
        await self.send(gw, 'join', name='iki', room_id=room_id, protocol=3)
        await self.receive(guest)
        room = self.lobby.rooms[room_id]
        room.match = Match()
        room.started = True
        room.match.paddles[0] = 9
        await self.lobby.dispatch(room.host, {'type': 'step', 'direction': 1, 'seq': 1})
        self.assertEqual(room.match.paddles[0], 9)
        self.assertEqual(room.host.last_step_seq, 1)
        self.assertEqual(room.match.events[-1].kind, 'border')

    async def test_step_ack_reaches_player_in_compact_network_frame(self):
        host, hw = await self.connect()
        guest, gw = await self.connect()
        await self.send(hw, 'create', name='bir', protocol=3)
        room_id = (await self.receive(host))['room_id']
        await self.send(gw, 'join', name='iki', room_id=room_id, protocol=3)
        await self.receive(guest)
        await self.receive_type(host, 'characters')
        await self.receive_type(guest, 'characters')
        await self.send(hw, 'character', value=0)
        await self.send(gw, 'character', value=1)
        await self.receive_type(host, 'settings_required')
        await self.receive_type(guest, 'settings_required')
        await self.send(hw, 'configure', score=3, shield=False, silent_ball=False)
        await self.receive_type(host, 'configured')
        await self.receive_type(guest, 'configured')
        await self.send(hw, 'start')
        await self.receive_type(host, 'started')
        await self.receive_type(host, 'state')
        await self.send(hw, 'step', direction=1, seq=1)
        for _ in range(20):
            frame = await self.receive_type(host, 'frame')
            if frame['a'][0] == 1:
                break
        self.assertEqual(frame['p'][0], 1)
        self.assertEqual(frame['a'][0], 1)

    async def test_early_strike_is_kept_until_ball_enters_hit_range(self):
        from dragonpong.engine import Match
        host, writer = await self.connect()
        await self.send(writer, 'create', name='bir')
        room_id = (await self.receive(host))['room_id']
        room = self.lobby.rooms[room_id]
        room.match = Match()
        room.started = True
        room.match.ball_z = 6.1
        room.match.vz = -3
        await self.send(writer, 'strike')
        await self.send(writer, 'rooms')
        await self.receive_type(host, 'rooms')
        self.assertLess(room.match.vz, 0)
        self.lobby.step_match(room, .051)
        self.assertGreater(room.match.vz, 0)

    async def test_buffered_strike_expires_before_later_rally(self):
        from dragonpong.engine import Match
        host, writer = await self.connect()
        await self.send(writer, 'create', name='bir')
        room_id = (await self.receive(host))['room_id']
        room = self.lobby.rooms[room_id]
        room.match = Match()
        room.started = True
        room.match.ball_z = 8
        room.match.vz = -3
        await self.send(writer, 'strike')
        await self.send(writer, 'rooms')
        await self.receive_type(host, 'rooms')
        room.match.step(.25)
        room.match.step(.017)
        room.match.ball_z = 5
        self.lobby.step_match(room, 0)
        self.assertLess(room.match.vz, 0)
        self.assertFalse(room.pending_strikes)

    async def test_misaligned_press_inside_hit_zone_is_not_buffered(self):
        from dragonpong.engine import Match
        host, writer = await self.connect()
        await self.send(writer, 'create', name='bir')
        room_id = (await self.receive(host))['room_id']
        room = self.lobby.rooms[room_id]
        room.match = Match()
        room.started = True
        room.match.ball_x = 8
        room.match.ball_z = 3
        room.match.vz = -3
        await self.send(writer, 'strike')
        await self.send(writer, 'rooms')
        await self.receive_type(host, 'rooms')
        room.match.paddles[0] = 8
        self.lobby.step_match(room, .017)
        self.assertLess(room.match.vz, 0)

    async def test_fast_ball_hits_buffered_strike_between_physics_ticks(self):
        from dragonpong.engine import Match
        host, writer = await self.connect()
        await self.send(writer, 'create', name='bir')
        room_id = (await self.receive(host))['room_id']
        room = self.lobby.rooms[room_id]
        room.match = Match()
        room.started = True
        room.match.ball_z = 6.1
        room.match.vz = -120
        await self.send(writer, 'strike')
        await self.send(writer, 'rooms')
        await self.receive_type(host, 'rooms')
        self.lobby.step_match(room, .05)
        self.assertGreater(room.match.vz, 0)
        self.assertEqual(room.match.scores, [0, 0])


if __name__ == "__main__":
    unittest.main()
