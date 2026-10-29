import hashlib
import json
import unittest
from unittest.mock import patch
from pathlib import Path
import numpy as np
from dragonpong.audio import AudioOutput
from dragonpong.engine import Event
from dragonpong.soundbank import SoundBank, decode_wav, EVENT_FILES

BASE = Path(__file__).resolve().parents[1]


class SoundbankTests(unittest.TestCase):
    def test_delayed_voice_starts_on_exact_sample(self):
        output = AudioOutput()
        with patch.object(output.bank, 'get', return_value=np.ones(6, dtype=np.float32)):
            output.play_file('test.wav', delay=3 / 48000)
        chunks = []
        for _ in range(3):
            buffer = np.zeros((4, 2), dtype=np.float32)
            output._callback(buffer, 4, None, None)
            chunks.extend(buffer[:, 0])
        self.assertEqual(chunks, [0] * 3 + [1] * 6 + [0] * 3)

    def test_goal_voices_use_selected_characters_and_perspective_score(self):
        output = AudioOutput(listener=1)
        with patch.object(output, 'play_file') as play:
            output.goal_sequence(Event('goal', 0, 0, player=0, reaction=4, opponent_reaction=2),
                                 [4, 1], [10, 3])
        self.assertEqual([c.args[0] for c in play.call_args_list],
                         ['Chars/5/score4.wav', 'Chars/2/opscore2.wav', 'announcer/scores.wav',
                          'announcer/3.wav', 'announcer/10.wav'])
        self.assertEqual([c.kwargs.get('delay', 0) for c in play.call_args_list], [0, 3, 6, 6.5, 7])

    @unittest.skipUnless((BASE / 'reference_sounds/manifest.json').exists(), 'Local reference assets absent')
    def test_all_143_files_match_and_decode(self):
        manifest = json.loads((BASE / 'reference_sounds/manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest), 143)
        for item in manifest:
            with self.subTest(file=item['file']):
                path = BASE / 'reference_sounds/Sounds' / item['file']
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item['sha256'])
                mono = decode_wav(path)
                self.assertTrue(np.isfinite(mono).all())
                self.assertGreater(len(mono), 0)
                self.assertLessEqual(abs(len(mono) / 48000 - item['seconds']), .001)

    def test_empty_bank_allows_procedural_fallback(self):
        self.assertIsNone(SoundBank(BASE / 'does-not-exist').event('paddle'))

    @unittest.skipUnless((BASE / 'reference_sounds/manifest.json').exists(), 'Local reference assets absent')
    def test_event_assets_and_mixer(self):
        output = AudioOutput()
        for kind in EVENT_FILES:
            self.assertIsNotNone(output.bank.event(kind), kind)
        output.set_ball(Event('rolling', 4, 10))
        output.set_shields([Event('shield_loop', 0, 0)])
        output.play(Event('paddle', 0, 3))
        buffer = np.zeros((512, 2), dtype=np.float32)
        for _ in range(20):
            output._callback(buffer, 512, None, None)
            self.assertTrue(np.isfinite(buffer).all())
            self.assertLessEqual(float(np.max(np.abs(buffer))), 1)
        output.reset()
        output.music(None)
        output._callback(buffer, 512, None, None)
        self.assertEqual(float(np.sum(abs(buffer))), 0)
