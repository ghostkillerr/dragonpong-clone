"""Transport freshness, compact state, and slow-client behavior."""
import queue
import io
import json
import unittest
from unittest.mock import MagicMock, patch

from dragonpong.client import Connection, LatestEventQueue, expand_frame, predict_ball
from dragonpong.server import Client, Server, Room, compact_state
from dragonpong.engine import Event, Match


class FakeTransport:
    def __init__(self):
        self.buffer_size = 0

    def get_write_buffer_size(self):
        return self.buffer_size


class FakeWriter:
    def __init__(self):
        self.transport = FakeTransport()
        self.writes = []
        self.closed = False

    def write(self, data):
        self.writes.append(data)

    def close(self):
        self.closed = True


class TransportTests(unittest.TestCase):
    def state(self, events=()):
        host = Client(FakeWriter(), 'bir', player=0)
        guest = Client(FakeWriter(), 'iki', player=1)
        room = Room('room', host, guest=guest, characters={0: 0, 1: 1}, match=Match())
        return Server().snapshot(room, events)

    def test_compact_frame_reconstructs_full_state(self):
        full = self.state()
        full['ball'] = [2, 3]
        compact = compact_state(full)
        self.assertEqual(expand_frame(compact, self.state()), full)
        self.assertLess(len(str(compact)), len(str(full)))

    def test_old_states_are_coalesced_without_losing_gameplay_events(self):
        inbox = LatestEventQueue()
        inbox.put({'type': 'state', 'ball': [1, 1], 'events': [{'kind': 'paddle'}]})
        inbox.put({'type': 'state', 'ball': [2, 2], 'events': [{'kind': 'goal'}]})
        current = inbox.get_nowait()
        self.assertEqual(current['ball'], [2, 2])
        self.assertEqual([event['kind'] for event in current['events']], ['paddle', 'goal'])
        with self.assertRaises(queue.Empty):
            inbox.get_nowait()

    def test_control_message_keeps_its_order_between_states(self):
        inbox = LatestEventQueue()
        inbox.put({'type': 'state', 'events': []})
        inbox.put({'type': 'started'})
        inbox.put({'type': 'state', 'events': []})
        self.assertEqual([inbox.get_nowait()['type'] for _ in range(3)],
                         ['state', 'started', 'state'])

    def test_goal_state_is_not_erased_by_later_frames(self):
        inbox = LatestEventQueue()
        inbox.put({'type': 'state', 'scores': [1, 0], 'events': [{'kind': 'goal'}]})
        inbox.put({'type': 'state', 'scores': [1, 0], 'events': []})
        self.assertEqual(inbox.get_nowait()['events'][0]['kind'], 'goal')
        self.assertEqual(inbox.get_nowait()['events'], [])

    def test_ball_prediction_reflects_side_wall_and_stops_at_goal(self):
        x, z = predict_ball([8, 1], [10, -10], .2)
        self.assertAlmostEqual(x, 8)
        self.assertEqual(z, 0)

    def test_slow_client_skips_old_state_and_replays_event(self):
        writer = FakeWriter()
        client = Client(writer, 'bir', player=0)
        state = self.state([Event('paddle', 0, 0)])
        writer.transport.buffer_size = 9000
        client.send_state(state)
        self.assertEqual(writer.writes, [])
        writer.transport.buffer_size = 0
        client.send_state(self.state())
        self.assertIn(b'"kind":"paddle"', writer.writes[0])
        self.assertFalse(client.pending_events)

    def test_movement_burst_does_not_disconnect_players_or_drop_goal(self):
        writer = FakeWriter()
        client = Client(writer, 'bir', player=0)
        events = [Event('move', 0, 0) for _ in range(30)] + [Event('goal', 0, 0)]
        client.send_state(self.state(events))
        self.assertFalse(writer.closed)
        self.assertIn(b'"kind":"goal"', writer.writes[0])

    def test_client_negotiates_new_protocol_and_falls_back_to_old_server(self):
        for advertised, expected in (([2, 3], 3), (None, 2)):
            with self.subTest(advertised=advertised):
                sock = MagicMock()
                room_list = {'type': 'rooms', 'rooms': []}
                if advertised is not None:
                    room_list['protocols'] = advertised
                sock.makefile.return_value = io.BytesIO((json.dumps(room_list) + '\n').encode())
                with patch('dragonpong.client.socket.create_connection', return_value=sock):
                    connection = Connection()
                connection.thread.join(1)
                connection.send('create', name='bir')
                self.assertEqual(connection.protocol, expected)
                self.assertEqual(json.loads(sock.sendall.call_args.args[0])['protocol'], expected)
                sock.setsockopt.assert_called_once()
                connection.close()


if __name__ == '__main__':
    unittest.main()
