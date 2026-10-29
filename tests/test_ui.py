"""Real Tk widgets with audio mocked; never touches the real saved profile."""
import json
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
                        patch.object(run_offline, 'AudioOutput')]
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

    def test_music_stops_before_settings_and_match(self):
        self.start_offline()
        self.game.audio.music.assert_called_with(None)
        self.game.menu()
        self.game.audio.music.assert_called_with('Music/Menu.wav')

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
