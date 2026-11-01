"""Connection work must never block the caller or wait forever for a peer."""
import asyncio
import io
import queue
import json
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from dragonpong.client import Connection
from dragonpong.netplay import STRIKE_FEATURE, present_flight, predict_view, view_is_stale, view_seconds
from dragonpong.server import Client, Room, Server


class ConnectionResponsivenessTests(unittest.TestCase):
    def paused_connection(self):
        with patch('dragonpong.client.threading.Thread.start'):
            connection = Connection()
        self.addCleanup(connection.close)
        return connection

    def test_ping_keeps_outstanding_nonce_and_measures_latest_rtt(self):
        connection = self.paused_connection()
        connection.protocol = 3
        with patch('dragonpong.client.time.monotonic', return_value=100):
            connection.ping()
        nonce = connection.ping_nonce
        connection.last_ping_at = 100.01  # Actual write time, not enqueue time.
        with patch('dragonpong.client.time.monotonic', return_value=102):
            connection.ping()
        self.assertEqual(connection.ping_nonce, nonce)
        self.assertEqual(connection.outgoing.qsize(), 1)
        with patch('dragonpong.client.time.monotonic', return_value=102.01):
            connection._message({'type': 'pong', 'nonce': nonce})
        self.assertAlmostEqual(connection.ping_ms, 2000)
        self.assertIsNone(connection.ping_nonce)
        connection._message({'type': 'pong', 'nonce': nonce})
        self.assertAlmostEqual(connection.ping_ms, 2000)  # Duplicate is ignored.

    def test_lost_ping_expires_once_instead_of_being_replaced(self):
        connection = self.paused_connection()
        connection.protocol = 3
        with patch('dragonpong.client.time.monotonic', return_value=100):
            connection.ping()
        with patch('dragonpong.client.time.monotonic', return_value=105.1):
            connection.ping()
            connection.ping()
        self.assertTrue(connection.closed)
        self.assertEqual(connection.events.get_nowait()['type'], 'connection_error')
        with self.assertRaises(queue.Empty):
            connection.events.get_nowait()

    def test_only_matching_pong_updates_server_clock(self):
        connection = self.paused_connection()
        connection.ping_nonce = 7
        connection.last_ping_at = 99.9
        with patch('dragonpong.client.time.monotonic', return_value=100):
            connection._message({'type': 'pong', 'nonce': 7, 'server_time': 500})
            self.assertEqual(connection.server_clock.at(100), 500)
            connection._message({'type': 'pong', 'nonce': 99, 'server_time': 999999})
        self.assertEqual(connection.server_clock.at(100), 500)

    def test_coalesced_pending_frame_keeps_issued_contact_and_clock_metadata(self):
        connection = self.paused_connection()
        connection.supports_strike_ref = True
        connection.server_clock.observe(500, 100)
        source = {'type': 'state', 'ball': [0, 3], 'velocity': [0, -80], 'frame_id': 7,
                  'flight_id': 3, 'sim_time': .1, 'server_time': 500, 'pending_goal': False, 'events': []}
        pending = {**source, 'frame_id': 8, 'ball': [0, .28], 'velocity': [0, 0],
                   'sim_time': .15, 'server_time': 500.05, 'pending_goal': True}
        with patch('dragonpong.client.time.monotonic', return_value=100.05):
            connection._message(source)
            connection._message(pending)
        latest = connection.events.get_nowait()
        self.assertEqual(latest['frame_id'], 8)
        self.assertEqual(latest['_contact_candidate']['frame_id'], 7)
        self.assertAlmostEqual(latest['_contact_candidate']['_server_now_floor'], 500.05)
        self.assertNotIn('_contact_candidate', latest['_contact_candidate'])

    def test_stale_game_command_is_not_replayed(self):
        connection = self.paused_connection()
        connection.socket = MagicMock()
        with patch('dragonpong.client.time.monotonic', return_value=100):
            connection.send('strike')
        with patch('dragonpong.client.time.monotonic', return_value=100.6):
            connection._write()
        connection.socket.sendall.assert_not_called()
        self.assertTrue(connection.closed)

    def test_outgoing_queue_is_bounded_without_waiting(self):
        connection = self.paused_connection()
        for _ in range(128):
            connection.send('step', direction=1)
        with self.assertRaises(ConnectionError):
            connection.send('step', direction=1)

    def test_send_and_close_do_not_wait_for_stalled_write(self):
        connection = self.paused_connection()
        entered = threading.Event()
        release = threading.Event()
        sock = MagicMock()
        connection.socket = sock

        def stalled_write(data):
            entered.set()
            release.wait(2)

        sock.sendall.side_effect = stalled_write
        connection.send('strike')
        sender = threading.Thread(target=connection._write)
        sender.start()
        try:
            self.assertTrue(entered.wait(1))
            started = time.monotonic()
            connection.send('step', direction=1)
            connection.close()
            self.assertLess(time.monotonic() - started, .2)
        finally:
            release.set()
            sender.join(2)

    def test_slow_connect_does_not_block_caller_and_can_be_cancelled(self):
        release = threading.Event()
        returned = threading.Event()
        connections = []
        sock = MagicMock()
        sock.makefile.return_value = io.BytesIO()
        sock.recv.return_value = b''

        def connect(*args, **kwargs):
            release.wait(2)
            return sock

        def construct():
            connections.append(Connection())
            returned.set()

        with patch('dragonpong.client.socket.create_connection', side_effect=connect):
            caller = threading.Thread(target=construct)
            caller.start()
            try:
                self.assertTrue(returned.wait(.2), 'Connecting blocked the UI caller')
                connections[0].close()
            finally:
                release.set()
                caller.join(2)
                for connection in connections:
                    connection.close()
                    connection.thread.join(2)
        sock.close.assert_called()


class BroadcastResponsivenessTests(unittest.IsolatedAsyncioTestCase):
    async def test_stalled_peer_is_closed_after_send_deadline(self):
        writer = MagicMock()
        blocked = asyncio.Event()
        writer.drain = blocked.wait
        with patch('dragonpong.server.CONTROL_SEND_TIMEOUT', .02):
            with self.assertRaises(TimeoutError):
                await Client(writer, 'slow').send({'type': 'started'})
        writer.transport.abort.assert_called_once()

    async def test_slow_peer_does_not_delay_healthy_peer(self):
        delivered = asyncio.Event()
        blocked = asyncio.Event()
        slow_writer = MagicMock()
        fast_writer = MagicMock()

        async def slow_drain():
            await blocked.wait()

        async def fast_drain():
            delivered.set()

        slow_writer.drain = slow_drain
        fast_writer.drain = fast_drain
        room = Room('room', Client(slow_writer, 'slow'), Client(fast_writer, 'fast'))
        task = asyncio.create_task(Server().broadcast(room, {'type': 'started'}))
        try:
            await asyncio.wait_for(delivered.wait(), .2)
        finally:
            blocked.set()
            await task


class ConnectionIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.connections = []
        self.writers = []
        self.tasks = set()
        self.lobby = Server()

    async def listen(self, handler=None):
        async def tracked(reader, writer):
            self.writers.append(writer)
            task = asyncio.current_task()
            self.tasks.add(task)
            try:
                await (handler or self.lobby.handle)(reader, writer)
            except OSError:
                pass  # Simulated peers are intentionally reset by timeout tests.
            finally:
                writer.close()
                self.tasks.discard(task)

        self.server = await asyncio.start_server(tracked, '127.0.0.1', 0)
        self.host_patch = patch('dragonpong.client.HOST', '127.0.0.1')
        self.port_patch = patch('dragonpong.client.PORT', self.server.sockets[0].getsockname()[1])
        self.host_patch.start()
        self.port_patch.start()

    def connect(self):
        connection = Connection()
        self.connections.append(connection)
        connection.send('rooms')
        return connection

    async def receive(self, connection, kind):
        async with asyncio.timeout(2):
            while True:
                try:
                    message = connection.events.get_nowait()
                    if message['type'] == kind:
                        return message
                except queue.Empty:
                    pass
                await asyncio.sleep(.005)

    async def asyncTearDown(self):
        for connection in self.connections:
            connection.close()
        self.server.close()
        await self.server.wait_closed()
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*list(self.tasks), return_exceptions=True)
        for writer in self.writers:
            writer.close()
        await asyncio.gather(*(w.wait_closed() for w in self.writers), return_exceptions=True)
        for connection in self.connections:
            await asyncio.to_thread(connection.thread.join, 1)
            if connection.sender:
                await asyncio.to_thread(connection.sender.join, 1)
        self.host_patch.stop()
        self.port_patch.stop()

    async def test_heartbeat_runs_without_ui_polling(self):
        await self.listen()
        connection = self.connect()
        await asyncio.sleep(.7)  # No UI tick, get_nowait, or manual ping call.
        self.assertEqual(connection.protocol, 3)
        self.assertIsInstance(connection.ping_ms, float)
        self.assertGreaterEqual(connection.ping_ms, 0)
        self.assertFalse(connection.closed)
        self.assertIn('Ping ', connection.status_text())

    async def test_delayed_pong_measures_network_round_trip(self):
        async def delayed(reader, writer):
            import json
            while line := await reader.readline():
                message = json.loads(line)
                if message['type'] == 'rooms':
                    reply = {'type': 'rooms', 'protocols': [2, 3], 'rooms': []}
                elif message['type'] == 'ping':
                    await asyncio.sleep(.08)
                    reply = {'type': 'pong', 'nonce': message['nonce']}
                else:
                    continue
                writer.write((json.dumps(reply) + '\n').encode())
                await writer.drain()

        await self.listen(delayed)
        connection = self.connect()
        async with asyncio.timeout(2):
            while connection.ping_ms is None:
                await asyncio.sleep(.005)
        self.assertGreaterEqual(connection.ping_ms, 60)
        self.assertLess(connection.ping_ms, 500)

    async def test_missing_pong_disconnects_even_with_incoming_states(self):
        async def no_pongs(reader, writer):
            await reader.readline()
            writer.write(b'{"type":"rooms","protocols":[2,3],"rooms":[]}\n')
            while True:
                writer.write(b'{"type":"state","ball":[0,0]}\n')
                await writer.drain()
                await asyncio.sleep(.01)

        await self.listen(no_pongs)
        with patch('dragonpong.client.PING_TIMEOUT', .15):
            connection = self.connect()
            error = await self.receive(connection, 'connection_error')
        self.assertIn('ping', error['reason'])
        self.assertTrue(connection.closed)

    async def test_initial_silent_server_times_out(self):
        async def silent(reader, writer):
            await reader.read()

        await self.listen(silent)
        with patch('dragonpong.client.PING_TIMEOUT', .1):
            connection = self.connect()
            error = await self.receive(connection, 'connection_error')
        self.assertIn('ilk isteğe', error['reason'])

    async def test_fragmented_messages_and_eof_have_one_terminal_event(self):
        async def fragmented(reader, writer):
            await reader.readline()
            for chunk in (b'{"type":"roo', b'ms","rooms":[]}\n{"type":',
                          b'"accepted","player":0}\n'):
                writer.write(chunk)
                await writer.drain()
                await asyncio.sleep(.01)

        await self.listen(fragmented)
        connection = self.connect()
        await self.receive(connection, 'rooms')
        self.assertEqual((await self.receive(connection, 'accepted'))['player'], 0)
        await self.receive(connection, 'disconnected')
        await asyncio.to_thread(connection.thread.join, 1)
        with self.assertRaises(queue.Empty):
            connection.events.get_nowait()

    async def test_real_socket_burst_preserves_contact_but_rejects_old_server_data(self):
        async def handler(reader, writer):
            greeted = False
            sent_first = False

            async def burst(age):
                stamp = time.monotonic() + 271828 - age  # Different server clock origin.
                source = {'type': 'state', 'ball': [0, 3], 'velocity': [0, -80],
                          'frame_id': 7 if age < .1 else 17,
                          'flight_id': 3 if age < .1 else 4,
                          'sim_time': .1, 'server_time': stamp - .051,
                          'pending_goal': False, 'events': []}
                pending = {**source, 'ball': [0, .28], 'velocity': [0, 0],
                           'frame_id': source['frame_id'] + 1, 'pending_goal': True,
                           'sim_time': .151, 'server_time': stamp}
                writer.write(('\n'.join(json.dumps(s) for s in (source, pending)) + '\n').encode())
                await writer.drain()

            while line := await reader.readline():
                message = json.loads(line)
                if message['type'] == 'rooms':
                    if greeted:
                        await burst(.65)
                    else:
                        greeted = True
                        writer.write((json.dumps({'type': 'rooms', 'rooms': [], 'protocols': [2, 3],
                                                  'features': [STRIKE_FEATURE]}) + '\n').encode())
                        await writer.drain()
                elif message['type'] == 'ping':
                    writer.write((json.dumps({'type': 'pong', 'nonce': message['nonce'],
                                              'server_time': time.monotonic() + 271828}) + '\n').encode())
                    await writer.drain()
                    if not sent_first:
                        sent_first = True
                        await burst(.05)

        await self.listen(handler)
        connection = self.connect()
        async with asyncio.timeout(2):
            while True:
                state = await self.receive(connection, 'state')
                if state.get('pending_goal'):
                    break
        self.assertTrue(state['pending_goal'])
        shown = present_flight(state, connection.ping_ms, time.monotonic(), 0)
        self.assertTrue(shown.held)
        self.assertEqual(shown.source['frame_id'], 7)
        self.assertTrue(1 <= shown.flight.z < 6)
        connection.send('rooms')
        async with asyncio.timeout(2):
            while True:
                state = await self.receive(connection, 'state')
                if state.get('pending_goal') and state.get('flight_id') == 4:
                    break
        self.assertEqual(state['flight_id'], 4)
        self.assertTrue(view_is_stale(state, time.monotonic()))
        shown = present_flight(state, connection.ping_ms, time.monotonic(), 0)
        self.assertFalse(shown.held)
        self.assertEqual(shown.flight.vz, 0)

    async def test_oversized_unterminated_message_is_rejected(self):
        async def oversized(reader, writer):
            await reader.readline()
            writer.write(b'x' * 4097)
            await writer.drain()
            await reader.read()

        await self.listen(oversized)
        connection = self.connect()
        error = await self.receive(connection, 'connection_error')
        self.assertIn('too long', error['reason'])

    async def test_two_threaded_clients_negotiate_play_and_ack_steps(self):
        await self.listen()
        host, guest = self.connect(), self.connect()
        for connection in (host, guest):
            await self.receive(connection, 'rooms')
            self.assertTrue(connection.supports_step_ack)
        host.send('create', name='host')
        room_id = (await self.receive(host, 'accepted'))['room_id']
        guest.send('join', name='guest', room_id=room_id)
        await self.receive(guest, 'accepted')
        for connection in (host, guest):
            await self.receive(connection, 'characters')
            connection.send('character', value=0)
        for connection in (host, guest):
            await self.receive(connection, 'settings_required')
        host.send('configure', score=3, shield=False, silent_ball=False)
        for connection in (host, guest):
            await self.receive(connection, 'configured')
        host.send('start')
        for connection in (host, guest):
            await self.receive(connection, 'state')
            connection.send('step', direction=1, seq=1)
        for connection in (host, guest):
            for _ in range(20):
                state = await self.receive(connection, 'state')
                if state['step_ack'] == [1, 1]:
                    break
            self.assertEqual(state['step_ack'], [1, 1])
            self.assertEqual(state['paddles'], [1, -1])
        host.send('strike')
        state = await self.receive(guest, 'state')
        for _ in range(20):
            if state['velocity'][1] > 0:
                break
            state = await self.receive(guest, 'state')
        self.assertGreater(state['velocity'][1], 0)
        guest.close()
        await self.receive(host, 'room_closed')

    async def test_delayed_contacts_through_real_tcp_proxy_in_both_directions(self):
        async def upstream_handler(reader, writer):
            self.writers.append(writer)
            task = asyncio.current_task()
            self.tasks.add(task)
            try:
                await self.lobby.handle(reader, writer)
            finally:
                self.tasks.discard(task)

        upstream = await asyncio.start_server(upstream_handler, '127.0.0.1', 0)

        async def relay(reader, writer, delay):
            while data := await reader.read(4096):
                await asyncio.sleep(delay)
                writer.write(data)
                await writer.drain()

        async def proxy(reader, writer):
            remote_reader, remote_writer = await asyncio.open_connection(
                '127.0.0.1', upstream.sockets[0].getsockname()[1])
            self.writers.append(remote_writer)
            tasks = [asyncio.create_task(relay(reader, remote_writer, .09)),
                     asyncio.create_task(relay(remote_reader, writer, .03))]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                remote_writer.close()

        try:
            await self.listen(proxy)
            host, guest = self.connect(), self.connect()
            for connection in (host, guest):
                await self.receive(connection, 'rooms')
                self.assertTrue(connection.supports_strike_ref)
            host.send('create', name='host')
            room_id = (await self.receive(host, 'accepted'))['room_id']
            guest.send('join', name='guest', room_id=room_id)
            await self.receive(guest, 'accepted')
            for connection in (host, guest):
                await self.receive(connection, 'characters')
                connection.send('character', value=0)
            for connection in (host, guest):
                await self.receive(connection, 'settings_required')
            host.send('configure', score=3, shield=False, silent_ball=False)
            for connection in (host, guest):
                await self.receive(connection, 'configured')
            host.send('start')
            for connection in (host, guest):
                await self.receive(connection, 'state')
            room = self.lobby.rooms[room_id]
            for player, connection in enumerate((host, guest)):
                with self.subTest(player=player):
                    room.match.ball_x = room.match.vx = 0
                    room.match.ball_z = 14 if player == 0 else 6
                    room.match.vz = -80 if player == 0 else 80
                    self.lobby.new_flight(room)
                    flight_id = room.flight_id
                    async with asyncio.timeout(2):
                        while True:
                            state = await self.receive(connection, 'state')
                            if state['flight_id'] != flight_id or state['pending_goal']:
                                continue
                            # Known configured path; RTT estimator has separate tests.
                            seconds = view_seconds(state, 120, time.monotonic())
                            shown = predict_view(state, seconds)
                            depth = shown.z if player == 0 else 20 - shown.z
                            if 1 <= depth < 5.8:
                                break
                    connection.send('strike', view={'frame': state['frame_id'], 'seconds': seconds})
                    result = await self.receive(connection, 'strike_result')
                    self.assertEqual(result['result'], 'compensated')
                    self.assertEqual(room.match.scores, [0, 0])
                    self.assertGreater(room.match.vz * (1 if player == 0 else -1), 0)
        finally:
            for connection in self.connections:
                connection.close()
            upstream.close()
            await asyncio.wait_for(upstream.wait_closed(), 2)
