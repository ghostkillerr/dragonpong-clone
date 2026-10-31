"""Local paddle feedback must reconcile to the unchanged server movement rules."""
import unittest
import random

from dragonpong.client import PaddlePrediction


class PaddlePredictionTests(unittest.TestCase):
    def test_delayed_ack_does_not_move_paddle_twice(self):
        prediction = PaddlePrediction()
        self.assertEqual((prediction.add(1), prediction.add(1)), (1, 2))
        self.assertEqual(prediction.position(0, player=0), 2)
        prediction.acknowledge(1)
        self.assertEqual(prediction.position(1, player=0), 2)
        prediction.acknowledge(2)
        self.assertEqual(prediction.position(2, player=0), 2)

    def test_opposite_steps_and_old_ack_keep_current_position(self):
        prediction = PaddlePrediction()
        prediction.add(1)
        prediction.add(-1)
        self.assertEqual(prediction.position(0, player=0), 0)
        prediction.acknowledge(1)
        self.assertEqual(prediction.position(1, player=0), 0)
        prediction.acknowledge(0)
        self.assertEqual(prediction.position(1, player=0), 0)
        prediction.acknowledge(2)
        self.assertEqual(prediction.position(0, player=0), 0)

    def test_guest_direction_and_border_use_server_coordinates(self):
        prediction = PaddlePrediction()
        prediction.add(1)
        self.assertEqual(prediction.position(0, player=1), -1)
        prediction.reset()
        prediction.add(1)
        self.assertEqual(prediction.position(-9, player=1), -9)
        prediction.reset()
        self.assertEqual(prediction.position(0, player=1), 0)

    def test_random_delayed_ack_matches_all_steps_for_both_players(self):
        for player in (0, 1):
            rng = random.Random(4711 + player)
            directions = [rng.choice((-1, 1)) for _ in range(200)]
            prediction = PaddlePrediction()
            server_x = 0
            acknowledged = 0
            for end in range(1, len(directions) + 1):
                prediction.add(directions[end - 1])
                if rng.randrange(4) == 0:
                    target = rng.randrange(acknowledged, end + 1)
                    for direction in directions[acknowledged:target]:
                        server_x = max(-9, min(9, server_x + direction *
                                               (1 if player == 0 else -1)))
                    acknowledged = target
                    prediction.acknowledge(acknowledged)
                expected = 0
                for direction in directions[:end]:
                    expected = max(-9, min(9, expected + direction *
                                           (1 if player == 0 else -1)))
                self.assertEqual(prediction.position(server_x, player), expected)


if __name__ == '__main__':
    unittest.main()
