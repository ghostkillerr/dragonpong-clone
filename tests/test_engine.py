import unittest

import numpy as np

from dragonpong.audio import kemar, source_sound, spatialize
from dragonpong.engine import Bot, Event, Match, Rules, TICK


class EngineTests(unittest.TestCase):
    def test_miss_scores_and_target_ends_match(self):
        match = Match(Rules(score=1, shield=False, silent_ball=False), seed=2)
        match.ball_x = 8
        match.ball_z = .03
        match.vx = 0
        match.vz = -10
        events = match.step(TICK)
        self.assertEqual(match.scores, [0, 1])
        self.assertEqual(match.winner, 1)
        self.assertEqual([e.kind for e in events], ["goal", "win"])

    def test_shield_blocks_a_miss(self):
        match = Match(Rules(score=1), seed=2)
        match.shield_until[0] = 10
        match.ball_x = 8
        match.ball_z = .03
        match.vz = -10
        events = match.step(TICK)
        self.assertEqual(match.scores, [0, 0])
        self.assertGreater(match.vz, 0)
        self.assertIn("shield_hit", [e.kind for e in events])

    def test_bot_does_not_change_ball_physics(self):
        left = Match(Rules(shield=False, silent_ball=False), seed=4)
        right = Match(Rules(shield=False, silent_ball=False), seed=4)
        for match in (left, right):
            match.serve(0)
        Bot("Kolay", seed=1).step(left, .016)
        Bot("Ultra", seed=1).step(right, .016)
        left.step(.016)
        right.step(.016)
        self.assertEqual((left.ball_x, left.ball_z, left.vx, left.vz),
                         (right.ball_x, right.ball_z, right.vx, right.vz))

    def test_random_powerups_respect_rules(self):
        match = Match(Rules(shield=False, silent_ball=False), seed=1)
        match.ball_z = 19.99
        match.vz = 8
        for _ in range(100):
            match.step(.01)
            self.assertEqual(match.shield_until, [0, 0])
            self.assertEqual(match.silent_until, 0)


class AudioTests(unittest.TestCase):
    def test_measured_hrtf_is_loaded(self):
        self.assertIsNotNone(kemar())
        self.assertGreater(len(kemar().responses), 300)

    def test_perspective_reverses_left_and_right(self):
        sound = source_sound("paddle")
        event = Event("paddle", 7, 10)
        near = spatialize(sound, event, 0)
        far = spatialize(sound, event, 1)
        self.assertGreater(np.sum(near[:, 1] ** 2), np.sum(near[:, 0] ** 2))
        self.assertGreater(np.sum(far[:, 0] ** 2), np.sum(far[:, 1] ** 2))

    def test_distance_reduces_level(self):
        sound = source_sound("wall")
        near = spatialize(sound, Event("wall", 0, 1), 0)
        far = spatialize(sound, Event("wall", 0, 19), 0)
        self.assertGreater(np.sum(near ** 2), np.sum(far ** 2))


if __name__ == "__main__":
    unittest.main()
