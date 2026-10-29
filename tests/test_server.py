import asyncio
import json
import unittest

from dragonpong.server import Server


class ServerTests(unittest.IsolatedAsyncioTestCase):
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


if __name__ == "__main__":
    unittest.main()
