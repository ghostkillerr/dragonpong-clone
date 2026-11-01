"""Real native Windows widgets; audio mocked and profile isolated."""
import json
import queue
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import run_offline
from dragonpong.netplay import ContactFrames


class UITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.profile = Path(self.temp.name) / 'profile.json'
        self.patches = [patch.object(run_offline, 'PROFILE', self.profile),
                        patch.object(run_offline, 'AudioOutput'),
                        patch.object(run_offline, 'ControllerInput')]
        for item in self.patches:
            item.start()
        self.game = run_offline.Game()
        self.game.root.withdraw()

    def tearDown(self):
        self.game.close()
        for item in self.patches:
            item.stop()
        self.temp.cleanup()

    def start_offline(self):
        self.game.name.delete(0, 'end')
        self.game.name.insert(0, 'ghostkiller')
        self.game.offline_character_menu()
        self.assertEqual(len(self.game.character['values']), 5)
        self.game.character.current(4)
        self.game.offline_settings()
        self.game.score.delete(0, 'end')
        self.game.score.insert(0, '30')
        self.game.shield.set(False)
        self.game.silent.set(True)
        self.game.difficulty.set('Ultra')
        self.game.start()

    def test_character_then_settings_and_saved_preferences(self):
        self.start_offline()
        self.assertEqual(self.game.characters, [4, 0])
        self.assertEqual(self.game.match.rules.score, 30)
        self.assertFalse(self.game.match.rules.shield)
        self.assertTrue(self.game.match.rules.silent_ball)
        self.assertEqual(json.loads(self.profile.read_text(encoding='utf-8'))['name'], 'ghostkiller')
        self.assertEqual(run_offline.load_profile()['difficulty'], 'Ultra')

    def test_up_strikes_and_each_arrow_moves_one_unit(self):
        self.start_offline()
        self.game.key_down(SimpleNamespace(keysym='Right'))
        self.assertEqual(self.game.match.paddles[0], 1)
        self.game.key_down(SimpleNamespace(keysym='Up'))
        self.assertGreater(self.game.match.vz, 0)
        self.game.match.ball_x, self.game.match.ball_z, self.game.match.vz = 1, 3, -3
        self.game.key_down(SimpleNamespace(keysym='Up'))
        self.assertGreater(self.game.match.vz, 0)
        self.game.key_down(SimpleNamespace(keysym='Escape'))
        self.assertIsNone(self.game.match)
        self.assertEqual(self.game.name.get(), 'ghostkiller')

    def test_close_during_controller_poll_does_not_touch_destroyed_controls(self):
        self.start_offline()
        def close_while_polling(active):
            self.game.close()
            return []
        self.game.controller.poll.side_effect = close_while_polling
        self.game.tick()
        self.assertFalse(self.game.canvas.winfo_exists())
        self.game.close()  # Repeated close is safe as well.

    def test_return_to_background_created_match_restores_keyboard_focus(self):
        self.start_offline()
        root = self.game.root
        with patch.object(root.native, 'IsActive', return_value=True), \
                patch.object(run_offline.ui.wx.Window, 'FindFocus', return_value=root.native), \
                patch.object(self.game.canvas, 'focus_set') as focus:
            root._restore_focus()
        focus.assert_called_once()

    def test_activation_preserves_native_control_focus_and_ignores_background(self):
        root = self.game.root
        with patch.object(root.native, 'IsActive', return_value=True), \
                patch.object(run_offline.ui.wx.Window, 'FindFocus', return_value=self.game.name.native), \
                patch.object(self.game.name, 'focus_set') as focus:
            root._restore_focus()
        focus.assert_not_called()
        with patch.object(root.native, 'IsActive', return_value=False), \
                patch.object(self.game.name, 'focus_set') as focus:
            root._restore_focus()
        focus.assert_not_called()

    def test_frame_focus_does_not_drop_gameplay_keys(self):
        self.start_offline()
        event = SimpleNamespace(GetKeyCode=lambda: run_offline.ui.wx.WXK_RIGHT, Skip=MagicMock())
        with patch.object(run_offline.ui.wx.Window, 'FindFocus', return_value=self.game.root.native):
            self.game.root._on_key(event)
        self.assertEqual(self.game.match.paddles[0], 1)

    def test_game_canvas_tab_navigates_without_a_game_command(self):
        self.start_offline()
        for backward in (False, True):
            event = SimpleNamespace(GetKeyCode=lambda: run_offline.ui.wx.WXK_TAB,
                                    ShiftDown=lambda: backward, Skip=MagicMock())
            with patch.object(run_offline.ui.wx.Window, 'FindFocus', return_value=self.game.canvas.native), \
                    patch.object(self.game.canvas.native, 'Navigate', return_value=True) as navigate, \
                    patch.dict(self.game.root.callbacks, {'<KeyPress>': MagicMock()}) as callbacks:
                self.game.root._on_key(event)
                navigate.assert_called_once()
                self.assertEqual(navigate.call_args.args[0],
                                 run_offline.ui.wx.NavigationKeyEvent.IsBackward if backward else
                                 run_offline.ui.wx.NavigationKeyEvent.IsForward)
                callbacks['<KeyPress>'].assert_not_called()

    def test_container_focus_is_replaced_by_the_current_game_canvas(self):
        self.start_offline()
        with patch.object(self.game.root.native, 'IsActive', return_value=True), \
                patch.object(run_offline.ui.wx.Window, 'FindFocus', return_value=self.game.container.native), \
                patch.object(self.game.canvas, 'focus_set') as focus:
            self.game.root._restore_focus()
        focus.assert_called_once()

    def test_native_tab_focus_is_remembered_for_window_reactivation(self):
        self.start_offline()
        button, = [w for w in self.game.container.children if w.kind == 'Button']
        event = run_offline.ui.wx.FocusEvent(run_offline.ui.wx.wxEVT_SET_FOCUS)
        button.native.GetEventHandler().ProcessEvent(event)
        self.assertIs(self.game.root.desired_focus, button)
        # A container can temporarily receive focus while screens change.
        self.game.container.native.GetEventHandler().ProcessEvent(
            run_offline.ui.wx.FocusEvent(run_offline.ui.wx.wxEVT_SET_FOCUS))
        self.assertIs(self.game.root.desired_focus, button)

    def test_new_screen_does_not_keep_previous_connection_notice(self):
        self.game.title_message('Previous connection closed')
        self.game.offline_character_menu()
        self.assertEqual(self.game.root.last_announcement, '')
        self.assertEqual(self.game.root.notice.GetLabel(), '')

    def test_spectator_arrows_only_change_perspective(self):
        self.game.connection = MagicMock()
        self.game.online_state = {'players': ['bir', 'iki']}
        self.game.online_player = None
        self.game.key_down(SimpleNamespace(keysym='Right'))
        self.game.connection.send.assert_called_once_with('perspective', player=1)

    def test_online_ball_uses_round_trip_time_for_display_prediction(self):
        self.game.connection = MagicMock()
        self.game.connection.ping_ms = 100
        state = {'ball': [0, 10], 'velocity': [10, -10], '_received_at': 100}
        with patch.object(run_offline.time, 'monotonic', return_value=100.05):
            x, z = self.game.online_ball(state)
        baseline = run_offline.Match()
        baseline.ball_z, baseline.vx, baseline.vz = 10, 10, -10
        baseline.step(.15)
        self.assertEqual((x, z), (baseline.ball_x, baseline.ball_z))

    def test_modern_ball_uses_half_rtt_and_native_tick_phase(self):
        self.game.connection = MagicMock()
        self.game.connection.supports_strike_ref = True
        self.game.connection.ping_ms = 100
        state = {'ball': [0, 10], 'velocity': [10, -10], '_received_at': 100, 'phase': .01}
        with patch.object(run_offline.time, 'monotonic', return_value=100.05):
            actual = self.game.online_ball(state)
        baseline = run_offline.Match()
        baseline.ball_z, baseline.vx, baseline.vz, baseline._accumulator = 10, 10, -10, .01
        baseline.step(.1)
        self.assertEqual(actual, (baseline.ball_x, baseline.ball_z))

    def test_strike_references_exact_last_audio_view(self):
        self.game.connection = MagicMock()
        self.game.connection.supports_strike_ref = True
        self.game.connection.ping_ms = 100
        self.game.online_player = 0
        self.game.online_state = {'ball': [0, 5], 'velocity': [2, -10], '_received_at': 100,
                                 'frame_id': 7, 'silent': False, 'paddles': [0, 0], 'shields': []}
        with patch.object(run_offline.time, 'monotonic', return_value=100.02):
            point = self.game.refresh_online_audio()
        reference = dict(self.game.presented_view)
        rolling = self.game.audio.set_ball.call_args.args[0]
        self.assertEqual((rolling.x, rolling.z), point)
        with patch.object(run_offline.time, 'monotonic', return_value=100.03):
            self.game.key_down(SimpleNamespace(keysym='Up'))
        self.game.connection.send.assert_called_once_with('strike', view=reference)

    def test_audio_moves_between_network_packets(self):
        self.game.connection = MagicMock()
        self.game.connection.supports_strike_ref = True
        self.game.connection.ping_ms = 0
        self.game.online_state = {'ball': [0, 10], 'velocity': [2, -10], '_received_at': 100,
                                 'frame_id': 7, 'silent': False, 'paddles': [0, 0], 'shields': []}
        with patch.object(run_offline.time, 'monotonic', return_value=100):
            start = self.game.refresh_online_audio()
        with patch.object(run_offline.time, 'monotonic', return_value=100.05):
            end = self.game.refresh_online_audio()
        self.assertLess(end[1], start[1])
        self.assertGreater(end[0], start[0])

    def test_fast_ball_at_high_ping_does_not_skip_last_contact_position(self):
        self.game.connection = MagicMock()
        self.game.connection.supports_strike_ref = True
        self.game.connection.ping_ms = 300
        self.game.online_player = 0
        self.game.online_state = {'ball': [0, 18], 'velocity': [0, -120], '_received_at': 100,
                                 'phase': .003, 'sim_time': 0, 'frame_id': 7, 'flight_id': 3,
                                 'silent': False, 'paddles': [0, 0], 'shields': [], 'pending_goal': False}
        with patch.object(run_offline.time, 'monotonic', return_value=100):
            point = self.game.refresh_online_audio()
        self.assertGreaterEqual(point[1], 1)
        self.assertLess(point[1], 6)
        self.assertLess(self.game.presented_view['seconds'], .15)

    def test_modern_stale_state_stops_audio_and_input_before_one_second(self):
        self.game.connection = MagicMock()
        self.game.connection.supports_strike_ref = True
        self.game.connection.ping_ms = 0
        self.game.online_player = 0
        self.game.online_state = {'ball': [0, 10], 'velocity': [0, -40], '_received_at': 100,
                                 'frame_id': 7, 'silent': False, 'paddles': [0, 0], 'shields': []}
        with patch.object(run_offline.time, 'monotonic', return_value=100.3):
            self.game.refresh_online_audio()
            self.game.key_down(SimpleNamespace(keysym='Up'))
        self.game.audio.set_ball.assert_called_with(None)
        self.game.connection.send.assert_not_called()

    def test_late_packet_arrival_does_not_restart_old_contact_audio(self):
        self.game.connection = MagicMock()
        self.game.connection.supports_strike_ref = True
        self.game.connection.ping_ms = 80
        self.game.online_player = 0
        self.game.online_state = {'ball': [0, 3], 'velocity': [0, -80], '_received_at': 100.3,
                                 'server_time': 500, '_server_now_floor': 500.35,
                                 'frame_id': 7, 'silent': False, 'paddles': [0, 0], 'shields': []}
        with patch.object(run_offline.time, 'monotonic', return_value=100.3):
            self.game.refresh_online_audio()
            self.game.key_down(SimpleNamespace(keysym='Up'))
        self.game.audio.set_ball.assert_called_with(None)
        self.game.connection.send.assert_not_called()

    def test_pending_packet_plays_and_references_retained_contact(self):
        self.game.connection = MagicMock()
        self.game.connection.supports_strike_ref = True
        self.game.connection.ping_ms = 80
        self.game.online_player = 0
        frames = ContactFrames()
        source = {'ball': [0, 3], 'velocity': [0, -80], '_received_at': 100,
                  'frame_id': 7, 'flight_id': 3, 'sim_time': 0, 'pending_goal': False,
                  'silent': False, 'paddles': [0, 0], 'shields': []}
        frames.receive(source)
        self.game.online_state = frames.receive({**source, 'ball': [0, .28], 'velocity': [0, 0],
                                                'frame_id': 8, 'sim_time': .051,
                                                '_received_at': 100.05, 'pending_goal': True})
        with patch.object(run_offline.time, 'monotonic', return_value=100.05):
            point = self.game.refresh_online_audio()
            self.game.key_down(SimpleNamespace(keysym='Up'))
        self.assertTrue(1 <= point[1] < 6)
        self.game.audio.set_ball.assert_called_with(None)
        self.assertEqual(self.game.audio.play.call_args.args[0].kind, 'paddle')
        self.assertEqual(self.game.presented_view['frame'], 7)
        self.game.connection.send.assert_called_once_with('strike', view=self.game.presented_view)

    def test_local_hit_feedback_for_both_players_does_not_repeat(self):
        for player in (0, 1):
            with self.subTest(player=player):
                self.game.menu()
                self.game.connection = MagicMock()
                self.game.connection.supports_strike_ref = True
                self.game.connection.ping_ms = 0
                self.game.connection.next_press = 1
                self.game.online_player = player
                self.game.online_state = {
                    'ball': [0, 3 if player == 0 else 17],
                    'velocity': [0, -20 if player == 0 else 20],
                    '_received_at': 100, 'frame_id': 7, 'flight_id': 3,
                    'silent': False, 'paddles': [0, 0], 'shields': [],
                    'pending_goal': False, 'scores': [0, 0], 'events': [],
                }
                self.game.audio.play.reset_mock()
                with patch.object(run_offline.time, 'monotonic', return_value=100):
                    self.game.refresh_online_audio()
                    self.game.key_down(SimpleNamespace(keysym='Up'))
                    self.game.key_down(SimpleNamespace(keysym='Up'))
                self.assertEqual(self.game.audio.play.call_count, 1)
                self.assertEqual(self.game.audio.play.call_args.args[0].player, player)
                self.assertEqual(self.game.local_hit_flight, 3)

    def test_local_hit_feedback_requires_reachable_incoming_ball(self):
        self.game.connection = MagicMock()
        self.game.connection.supports_strike_ref = True
        self.game.connection.ping_ms = 0
        self.game.online_player = 0
        self.game.online_state = {
            'ball': [8, 3], 'velocity': [0, -20], '_received_at': 100,
            'frame_id': 7, 'flight_id': 3, 'silent': False,
            'paddles': [0, 0], 'shields': [], 'pending_goal': False,
        }
        with patch.object(run_offline.time, 'monotonic', return_value=100):
            self.game.refresh_online_audio()
            self.game.key_down(SimpleNamespace(keysym='Up'))
        self.game.connection.send.assert_called_once()
        self.game.audio.play.assert_not_called()

    def test_confirmed_local_hit_sound_is_not_played_again(self):
        self.game.connection = MagicMock()
        self.game.connection.supports_strike_ref = True
        self.game.connection.supports_step_ack = False
        self.game.connection.ping_ms = 0
        self.game.connection.next_press = 1
        self.game.online_player = 0
        self.game.online_state = {
            'ball': [0, 3], 'velocity': [0, -20], '_received_at': 100,
            'frame_id': 7, 'flight_id': 3, 'silent': False,
            'paddles': [0, 0], 'shields': [], 'pending_goal': False,
            'scores': [0, 0], 'events': [], 'winner': None,
        }
        self.game.online_game_screen()
        with patch.object(run_offline.time, 'monotonic', return_value=100):
            self.game.refresh_online_audio()
            self.game.key_down(SimpleNamespace(keysym='Up'))
        self.assertEqual(self.game.audio.play.call_count, 1)
        confirmed = {**self.game.online_state, 'type': 'state', 'ball': [0, 0],
                     'velocity': [0, 20], '_received_at': 100.05,
                     'frame_id': 8, 'flight_id': 4,
                     'events': [{'kind': 'paddle', 'x': 0, 'z': 0, 'player': 0}]}
        with patch.object(run_offline.time, 'monotonic', return_value=100.05):
            self.game.online_message(confirmed)
        self.assertEqual(self.game.audio.play.call_count, 1)
        self.assertIsNone(self.game.local_hit_flight)

    def test_rejected_local_hit_releases_pending_feedback(self):
        self.game.connection = MagicMock()
        self.game.connection.supports_strike_ref = True
        self.game.connection.ping_ms = 0
        self.game.connection.next_press = 1
        self.game.online_player = 0
        self.game.online_state = {
            'ball': [0, 3], 'velocity': [0, -20], '_received_at': 100,
            'frame_id': 7, 'flight_id': 3, 'silent': False,
            'paddles': [0, 0], 'shields': [], 'pending_goal': False,
        }
        self.game.online_game_screen()
        with patch.object(run_offline.time, 'monotonic', return_value=100):
            self.game.refresh_online_audio()
            self.game.key_down(SimpleNamespace(keysym='Up'))
            self.game.online_message({'type': 'strike_result', 'press': 2,
                                      'result': 'too_late'})
        self.assertEqual(self.game.local_hit_flight, 3)
        with patch.object(run_offline.time, 'monotonic', return_value=100.01):
            self.game.online_message({'type': 'strike_result', 'press': 1,
                                      'result': 'too_late'})
        self.assertIsNone(self.game.local_hit_flight)

    def test_fresh_state_recovers_after_stale_input_was_discarded(self):
        self.game.connection = MagicMock()
        self.game.connection.supports_strike_ref = True
        self.game.connection.ping_ms = 0
        self.game.online_player = 0
        self.game.online_state = {'ball': [0, 3], 'velocity': [0, -40], '_received_at': 100,
                                 'frame_id': 7, 'silent': False, 'paddles': [0, 0], 'shields': []}
        with patch.object(run_offline.time, 'monotonic', return_value=100.3):
            self.game.refresh_online_audio()
            self.game.key_down(SimpleNamespace(keysym='Up'))
        self.game.connection.send.assert_not_called()
        self.game.online_state = {**self.game.online_state, '_received_at': 100.31, 'frame_id': 8}
        with patch.object(run_offline.time, 'monotonic', return_value=100.31):
            self.game.refresh_online_audio()
            self.game.key_down(SimpleNamespace(keysym='Up'))
        self.assertIsNotNone(self.game.audio.set_ball.call_args.args[0])
        self.game.connection.send.assert_called_once_with('strike', view={'frame': 8, 'seconds': 0})

    def test_recovery_replaces_stale_window_title_once(self):
        self.game.connection = MagicMock()
        self.game.connection.supports_strike_ref = True
        self.game.connection.supports_step_ack = False
        self.game.connection.ping_ms = 120
        self.game.connection.status_text.return_value = 'Ping 120 ms'
        self.game.connection.events.get_nowait.side_effect = queue.Empty
        self.game.controller.poll.return_value = []
        self.game.online_state = {'ball': [0, 10], 'velocity': [0, -3], '_received_at': 100,
                                 'scores': [0, 0], 'silent': False, 'paddles': [0, 0], 'shields': []}
        self.game.online_game_screen()
        with patch.object(self.game.root, 'after'):
            with patch.object(run_offline.time, 'monotonic', return_value=100.3):
                self.game.key_down(SimpleNamespace(keysym='F6'))
                self.game.tick()
            for now in (100.4, 100.7):
                self.game.online_state['_received_at'] = now
                with patch.object(run_offline.time, 'monotonic', return_value=now):
                    self.game.tick()
        self.assertIn('Bağlantı düzeldi', self.game.root.last_announcement)
        self.assertNotIn('Oyun verisi gecikiyor', self.game.root.last_announcement)

    def test_unstable_recovery_does_not_repeat_live_announcements(self):
        self.game.connection = MagicMock()
        self.game.connection.supports_strike_ref = True
        self.game.online_state = {'_received_at': 100}
        with patch.object(self.game, 'announce') as announce:
            for now, received in ((100.3, 100), (100.31, 100.31), (100.6, 100.31),
                                  (100.61, 100.61), (100.9, 100.9), (101, 101)):
                self.game.online_state['_received_at'] = received
                with patch.object(run_offline.time, 'monotonic', return_value=now):
                    self.game.update_network_notice()
        self.assertEqual([call.args[0] for call in announce.call_args_list],
                         ['Oyun verisi gecikiyor. Yeni girişler bekletiliyor.',
                          'Bağlantı düzeldi. Oyun sürüyor.'])

    def test_finished_match_does_not_announce_recovered_game(self):
        self.game.connection = MagicMock()
        self.game.connection.supports_strike_ref = True
        self.game.online_state = {'_received_at': 100}
        with patch.object(self.game, 'announce') as announce:
            with patch.object(run_offline.time, 'monotonic', return_value=100.3):
                self.game.update_network_notice()
            self.game.online_state.update(_received_at=100.4, winner=1)
            with patch.object(run_offline.time, 'monotonic', return_value=101):
                self.game.update_network_notice()
        self.assertEqual(announce.call_count, 1)

    def test_explicit_status_uses_alert_without_replacing_window_title(self):
        self.game.connection = MagicMock()
        self.game.connection.status_text.return_value = 'Ping 42 ms'
        title = self.game.root.title()
        self.game.key_down(SimpleNamespace(keysym='F6'))
        self.assertEqual(self.game.root.title(), title)
        self.assertEqual(self.game.root.last_announcement, 'Ping 42 ms')

    def test_rejected_contact_has_explanation(self):
        self.start_offline()
        self.game.online_message({'type': 'strike_result', 'result': 'out_of_reach', 'press': 1})
        self.assertIn('raketin yanında', self.game.status.cget('text'))

    def test_network_state_is_applied_before_frame_is_drawn(self):
        self.game.connection = MagicMock()
        self.game.online_state = {'type': 'state', 'ball': [0, 0]}
        self.game.controller.poll.return_value = []
        incoming = {'type': 'state', 'ball': [1, 1]}
        self.game.connection.events.get_nowait.side_effect = [incoming, queue.Empty]
        drawn = []
        with (patch.object(self.game, 'online_message',
                           side_effect=lambda message: setattr(self.game, 'online_state', message)),
              patch.object(self.game, 'draw',
                           side_effect=lambda: drawn.append(self.game.online_state['ball'][:])),
              patch.object(self.game.root, 'after')):
            self.game.tick()
        self.assertEqual(drawn, [[1, 1]])

    def test_online_step_is_shown_immediately_with_server_ack_support(self):
        self.game.connection = MagicMock()
        self.game.connection.supports_step_ack = True
        self.game.online_player = 0
        self.game.online_state = {'paddles': [0, 0], 'step_ack': [0, 0]}
        with patch.object(self.game, 'draw') as draw:
            self.game.key_down(SimpleNamespace(keysym='Right'))
        self.game.connection.send.assert_called_once_with('step', direction=1, seq=1)
        self.assertEqual(self.game.predicted_paddles(), [1, 0])
        self.assertEqual(self.game.audio.listener_x, 1)
        draw.assert_called_once()

    def test_authoritative_ack_reconciles_without_double_movement(self):
        self.game.connection = MagicMock()
        self.game.connection.supports_step_ack = True
        self.game.connection.ping_ms = None
        self.game.online_player = 0
        self.game.online_state = {'paddles': [0, 0], 'step_ack': [0, 0]}
        self.game.score_label = MagicMock()
        self.game.paddle_prediction.add(1)
        self.game.paddle_prediction.add(1)
        def state(x, ack):
            return {'type': 'state', 'paddles': [x, 0], 'step_ack': [ack, 0],
                    'scores': [0, 0], 'velocity': [0, 0], 'ball': [0, 0],
                    'silent': False, 'shields': [], 'events': []}
        self.game.online_message(state(1, 1))
        self.assertEqual(self.game.predicted_paddles()[0], 2)
        self.assertEqual(self.game.audio.listener_x, 2)
        self.game.online_message(state(2, 2))
        self.assertEqual(self.game.predicted_paddles()[0], 2)

    def test_old_server_keeps_authoritative_paddle_display(self):
        self.game.connection = MagicMock()
        self.game.connection.supports_step_ack = False
        self.game.online_player = 0
        self.game.online_state = {'paddles': [0, 0]}
        self.game.key_down(SimpleNamespace(keysym='Right'))
        self.game.connection.send.assert_called_once_with('step', direction=1)
        self.assertEqual(self.game.predicted_paddles()[0], 0)

    def test_missing_ack_disables_prediction_without_changing_server_position(self):
        self.game.connection = MagicMock()
        self.game.connection.supports_step_ack = True
        self.game.connection.ping_ms = None
        self.game.online_player = 0
        self.game.online_state = {'paddles': [0, 0], 'step_ack': [0, 0]}
        self.game.score_label = MagicMock()
        self.game.paddle_prediction.add(1)
        self.game.online_message({'type': 'state', 'paddles': [0, 0],
                                  'scores': [0, 0], 'velocity': [0, 0],
                                  'ball': [0, 0], 'silent': False,
                                  'shields': [], 'events': []})
        self.assertFalse(self.game.connection.supports_step_ack)
        self.assertEqual(self.game.predicted_paddles()[0], 0)

    def test_leaving_room_discards_unacknowledged_prediction(self):
        self.game.paddle_prediction.add(1)
        self.game.menu()
        self.assertEqual(self.game.paddle_prediction.position(0, player=0), 0)

    def test_guest_immediate_display_uses_mirrored_world_direction(self):
        self.game.connection = MagicMock()
        self.game.connection.supports_step_ack = True
        self.game.online_player = 1
        self.game.online_state = {'paddles': [0, 0], 'step_ack': [0, 0]}
        with patch.object(self.game, 'draw'):
            self.game.key_down(SimpleNamespace(keysym='Right'))
        self.assertEqual(self.game.predicted_paddles(), [0, -1])
        self.assertEqual(self.game.audio.listener_x, -1)

    def test_failed_step_send_clears_visual_prediction(self):
        self.game.connection = MagicMock()
        self.game.connection.supports_step_ack = True
        self.game.connection.send.side_effect = ConnectionError('offline')
        self.game.online_player = 0
        self.game.online_state = {'paddles': [0, 0], 'step_ack': [0, 0]}
        self.game.key_down(SimpleNamespace(keysym='Right'))
        self.assertIsNone(self.game.connection)
        self.assertEqual(self.game.paddle_prediction.position(0, player=0), 0)

    def test_send_failure_on_strike_and_legacy_step_returns_to_menu(self):
        for key in ('Up', 'Right'):
            with self.subTest(key=key):
                connection = MagicMock()
                connection.supports_step_ack = False
                connection.send.side_effect = ConnectionError('test offline')
                self.game.connection = connection
                self.game.online_player = 0
                self.game.online_state = {'paddles': [0, 0]}
                self.game.key_down(SimpleNamespace(keysym=key))
                self.assertIsNone(self.game.connection)
                self.assertIn('test offline', self.game.error.cget('text'))

    def test_failed_room_send_keeps_error_menu_visible(self):
        self.game.connection = MagicMock()
        self.game.connection.send.side_effect = ConnectionError('queue full')
        self.game.enter_room('create')
        self.assertIsNone(self.game.connection)
        self.assertIn('queue full', self.game.error.cget('text'))
        self.assertTrue(self.game.name.winfo_exists())

    def test_f6_reports_connection_status_even_before_match(self):
        self.game.connection = MagicMock()
        self.game.connection.status_text.return_value = 'Ping 42 ms | Dalgalanma 7 ms'
        with patch.object(self.game, 'title_message') as announce:
            self.game.key_down(SimpleNamespace(keysym='F6'))
        announce.assert_called_once_with('Ping 42 ms | Dalgalanma 7 ms')

    def test_stalled_state_blocks_commands_until_fresh_state_arrives(self):
        self.game.connection = MagicMock()
        self.game.connection.status_text.return_value = 'Ping 42 ms'
        self.game.connection.supports_step_ack = False
        self.game.online_player = 0
        self.game.online_state = {'paddles': [0, 0], '_received_at': 100}
        with patch.object(run_offline.time, 'monotonic', return_value=102):
            for key in ('Up', 'Right', 'a', 'space'):
                self.game.key_down(SimpleNamespace(keysym=key))
            self.assertIn('Oyun verisi gecikiyor', self.game.network_text())
        self.game.connection.send.assert_not_called()
        self.game.online_state['_received_at'] = 102
        with patch.object(run_offline.time, 'monotonic', return_value=102.1):
            self.game.key_down(SimpleNamespace(keysym='Right'))
        self.game.connection.send.assert_called_once_with('step', direction=1)

    def test_stalled_ball_stops_extrapolating(self):
        self.game.connection = MagicMock()
        self.game.connection.ping_ms = 100
        state = {'ball': [0, 10], 'velocity': [10, -10], '_received_at': 100}
        with patch.object(run_offline.time, 'monotonic', return_value=102):
            self.assertEqual(self.game.online_ball(state), (0, 10))

    def test_final_score_uses_authoritative_paddle_position(self):
        self.game.connection = MagicMock()
        self.game.connection.supports_step_ack = True
        self.game.connection.ping_ms = None
        self.game.online_player = 0
        self.game.online_state = {'paddles': [0, 0], 'step_ack': [0, 0]}
        self.game.score_label = MagicMock()
        self.game.paddle_prediction.add(1)
        self.game.online_message({'type': 'state', 'paddles': [0, 0],
                                  'step_ack': [0, 0], 'scores': [3, 0],
                                  'winner': 0, 'velocity': [0, 0], 'ball': [0, 0],
                                  'silent': False, 'shields': [], 'events': []})
        self.assertEqual(self.game.predicted_paddles()[0], 0)

    def test_music_stops_before_settings_and_match(self):
        self.start_offline()
        self.game.audio.music.assert_called_with(None)
        self.game.menu()
        self.game.audio.music.assert_called_with('Music/Menu.wav')

    def test_name_and_settings_saved_before_start(self):
        self.game.name.delete(0, 'end')
        self.game.name.insert(0, 'Kalici')
        self.game.offline_character_menu()
        self.assertEqual(run_offline.load_profile()['name'], 'Kalici')
        self.game.offline_settings()
        self.game.score.delete(0, 'end')
        self.game.score.insert(0, '30')
        self.game.shield.set(False)
        self.game.difficulty.set('Ultra')
        self.game.remember_settings()
        self.game.key_down(SimpleNamespace(keysym='Escape'))
        saved = run_offline.load_profile()
        self.assertEqual((saved['score'], saved['shield'], saved['difficulty']), (30, False, 'Ultra'))

    def test_spectator_arrows_cycle_both_directions(self):
        self.game.connection = MagicMock()
        self.game.online_state = {'players': ['bir', 'iki']}
        self.game.audio.listener = 0
        for expected in (1, 0, 1):
            self.game.key_down(SimpleNamespace(keysym='Right'))
            self.game.connection.send.assert_called_with('perspective', player=expected)

    def test_room_list_has_new_room_choice_and_enter_binding(self):
        with patch.object(run_offline, 'Connection'):
            self.game.online_menu()
        self.game.online_message({'type': 'rooms', 'rooms': [
            {'room_id': 'a', 'host_name': 'ghostkiller', 'joinable': True}]})
        self.assertEqual(self.game.rooms_list.get(1), 'Yeni oda oluştur ve eş bekle')
        self.assertTrue(self.game.rooms_list.bind('<Return>'))
        self.game.rooms_list.selection_clear(0, 'end')
        self.game.rooms_list.selection_set(1)
        self.game.join_room()
        self.game.connection.send.assert_called_with('create', name='Oyuncu', room_id=None)

    def test_mouse_button_and_three_wheel_steps(self):
        self.start_offline()
        self.assertTrue(self.game.canvas.bind('<Button-1>'))
        for _ in range(3):
            self.game.mouse_wheel(SimpleNamespace(delta=120))
        self.assertEqual(self.game.match.paddles[0], 1)

    def test_spectator_settings_message_does_not_show_player_settings(self):
        self.game.online_player = None
        with patch.object(self.game, 'online_settings') as settings:
            self.game.online_message({'type': 'settings_required'})
        settings.assert_not_called()

    def test_invalid_profile_values_are_ignored(self):
        self.profile.write_text(json.dumps({'name': 3, 'score': -1, 'shield': 'off', 'difficulty': 'bad'}))
        self.assertEqual(run_offline.load_profile()['name'], 'Oyuncu')
        self.assertEqual(run_offline.load_profile()['score'], 10)
        self.assertIs(run_offline.load_profile()['shield'], True)

    def test_exit_button_and_state_labels_exist(self):
        labels = [str(widget.cget('text')) for widget in self.game.container.winfo_children()
                  if 'text' in widget.keys()]
        self.assertIn('Çık', labels)
        self.game.offline_character_menu()
        self.game.offline_settings()
        widgets = [widget for widget in self.game.container.winfo_children()
                   if widget.winfo_class() == 'CheckBox']
        self.assertEqual(len(widgets), 2)
        self.assertTrue(widgets[0].native.GetValue())
        self.game.shield.set(False)
        self.assertFalse(widgets[0].native.GetValue())
