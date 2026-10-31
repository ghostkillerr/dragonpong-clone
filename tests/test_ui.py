"""Real Tk widgets with audio mocked; never touches the real saved profile."""
import json
import queue
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import run_offline


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
        self.assertAlmostEqual(x, 1.5)
        self.assertAlmostEqual(z, 8.5)

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
                   if widget.winfo_class() == 'TCheckbutton']
        self.assertEqual(len(widgets), 2)
        self.assertIn('açık', self.game.root.getvar(widgets[0].cget('textvariable')))
        self.game.shield.set(False)
        self.assertIn('kapalı', self.game.root.getvar(widgets[0].cget('textvariable')))
