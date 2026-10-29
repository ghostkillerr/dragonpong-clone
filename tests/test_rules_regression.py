import math
import unittest
from dragonpong.engine import Match, Rules, Bot, TICK, f32


class FixedRolls:
    def __init__(self, values):
        self.values = iter(values)
        self.bounds = []
    def randrange(self, bound):
        self.bounds.append(bound)
        return next(self.values)


class RulesRegression(unittest.TestCase):
    def test_hit_restarts_from_paddle_like_native_received_shot(self):
        for player in (0, 1):
            match = self.incoming(player)
            match.ball_x = 2.5
            match.paddles[player] = 1
            self.assertTrue(match.strike(player))
            self.assertEqual(match.ball_x, 1)
            self.assertEqual(match.ball_z, player * 20)
            self.assertGreater(match.vx, 0)  # Direction still uses pre-hit offset.

    def test_centered_return_stays_straight_across_repeated_hits(self):
        match = self.incoming()
        match.ball_x = match.paddles[0] = match.paddles[1] = 2
        for player in (0, 1, 0, 1, 0):
            match.ball_z = 3 if player == 0 else 17
            match.vz = -abs(match.vz) if player == 0 else abs(match.vz)
            self.assertTrue(match.strike(player))
            self.assertEqual(match.vx, 0)
            for _ in range(8):
                self.assertNotIn('wall', [e.kind for e in match.step(TICK)])
                self.assertEqual(match.ball_x, 2)

    def test_mirrored_receivers_keep_identical_float32_depth(self):
        a, b = self.incoming(), self.incoming(1)
        a.ball_z, b.ball_z = 20, 0
        a.vz, b.vz = -f32(.07) / TICK, f32(.07) / TICK
        for _ in range(200):
            a.step(TICK); b.step(TICK)
            self.assertEqual(a.ball_z, 20 - b.ball_z)

    def incoming(self, player=0, rules=None):
        match = Match(rules or Rules(shield=False, silent_ball=False), seed=1)
        match.ball_z = 3 if player == 0 else 17
        match.vz = -3 if player == 0 else 3
        return match

    def test_paddle_does_not_automatically_hit(self):
        match = self.incoming()
        match.ball_z = .9
        self.assertEqual([e.kind for e in match.step(TICK)], ['goal'])
        self.assertEqual(match.scores, [0, 1])

    def test_strict_hit_edges_both_players(self):
        for player in (0, 1):
            for lateral, depth, accepted in ((3, 3, False), (-3, 3, False),
                                             (2.99, 3, True), (0, 6, False), (0, 5.99, True)):
                with self.subTest(player=player, lateral=lateral, depth=depth):
                    match = self.incoming(player)
                    match.ball_x = lateral
                    match.ball_z = depth if player == 0 else 20 - depth
                    self.assertEqual(match.strike(player), accepted)

    def test_shield_is_reusable_and_does_not_clear_silence(self):
        match = self.incoming(rules=Rules())
        match.shield_until[0] = 30
        match.silent_until = math.inf
        for _ in range(3):
            match.ball_z, match.vz = .5, -4
            events = match.step(TICK)
            self.assertEqual([e.kind for e in events], ['shield_hit'])
            self.assertEqual(match.shield_until[0], 30)
            self.assertEqual(match.silent_until, math.inf)
            self.assertEqual(match.ball_z, .5)

    def test_shield_expires_without_moving_ball(self):
        match = Match()
        match.shield_until[1] = TICK * 2
        self.assertEqual(match.step(TICK * 2), [])
        self.assertEqual([e.kind for e in match.step(TICK)], ['shield_off'])
        self.assertEqual(match.shield_until[1], 0)

    def test_silent_does_not_expire_after_eight_seconds(self):
        match = Match()
        match.silent_until = math.inf
        for _ in range(80):
            match.step(.25)
        self.assertEqual(match.silent_until, math.inf)

    def test_silent_clears_on_hit_and_goal(self):
        for hit in (False, True):
            match = self.incoming()
            match.silent_until = math.inf
            if hit:
                self.assertTrue(match.strike(0))
            else:
                match.ball_z = .5
            self.assertIn('silent_off', [e.kind for e in match.step(TICK)])
            self.assertEqual(match.silent_until, 0)

    def test_silent_wall_still_sounds(self):
        match = self.incoming()
        match.silent_until, match.ball_x, match.vx = math.inf, 9, 4
        self.assertIn('wall', [e.kind for e in match.step(TICK)])
        self.assertLess(match.vx, 0)

    def test_identical_powerup_odds_for_both_players(self):
        for player in (0, 1):
            count_shield = count_silent = 0
            for shield_roll in range(11):
                for silent_roll in range(21):
                    match = self.incoming(player, Rules())
                    match.rng = FixedRolls([0, 0, shield_roll, silent_roll])
                    self.assertTrue(match.strike(player))
                    self.assertEqual(match.rng.bounds, [6, 6, 11, 21])
                    count_shield += bool(match.shield_until[player])
                    count_silent += bool(match.silent_until)
            self.assertEqual((count_shield, count_silent), (21, 11))

    def test_disabled_powerups_never_roll(self):
        match = self.incoming()
        match.rng = FixedRolls([5, 5])
        match.strike(0)
        self.assertEqual(match.rng.bounds, [6, 6])

    def test_thirty_goal_match_ends_at_thirty(self):
        match = self.incoming(rules=Rules(score=30, shield=False, silent_ball=False))
        for goal in range(1, 31):
            match.ball_z, match.vz = .5, -3
            match.step(TICK)
            self.assertEqual(match.scores, [0, goal])
            self.assertEqual(match.winner, 1 if goal == 30 else None)
        self.assertFalse(match.strike(0))

    def test_goal_cues_have_valid_variants_and_serve_waits(self):
        match = self.incoming()
        match.ball_z = .5
        event = match.step(TICK)[0]
        self.assertIn(event.variant, range(1, 9))
        self.assertIn(event.reaction, range(1, 6))
        self.assertIn(event.opponent_reaction, range(1, 6))
        self.assertFalse(match.serve(0))
        for _ in range(30):
            match.step(.25)
        self.assertTrue(match.serve(0))

    def test_movement_bounds_and_one_step(self):
        match = Match()
        match.move_step(0, 1)
        self.assertEqual(match.paddles[0], 1)
        for _ in range(50):
            match.move_step(0, 1)
            match.move_step(1, -1)
        self.assertEqual(match.paddles, [9, -9])
        self.assertEqual(match.events[-1].kind, 'border')

    def test_tick_partition_does_not_change_physics(self):
        a, b = Match(seed=1), Match(seed=1)
        a.serve(0); b.serve(0)
        for _ in range(100):
            a.step(.017)
            b.step(.009); b.step(.008)
        self.assertEqual((a.ball_x, a.ball_z), (b.ball_x, b.ball_z))

    def test_ultra_never_moves_faster_than_63ms(self):
        match, bot = self.incoming(), Bot('Ultra', seed=1)
        match.ball_x = 9
        times, old = [], 0
        for index in range(200):
            bot.step(match, .005)
            if old != match.paddles[1]:
                self.assertEqual(abs(match.paddles[1] - old), 1)
                times.append((index + 1) * .005)
                old = match.paddles[1]
        self.assertGreater(len(times), 5)
        self.assertTrue(all(b - a >= .063 - 1e-9 for a, b in zip(times, times[1:])))

    def test_ultra_tracks_outgoing_and_incoming_and_can_concede(self):
        for velocity in (-3, 3):
            match, bot = self.incoming(), Bot('Ultra', seed=1)
            match.ball_z, match.ball_x, match.vz = 10, 8, velocity
            for _ in range(40):
                bot.step(match, .01)
            self.assertGreater(match.paddles[1], 4)
        match, bot = self.incoming(1), Bot('Ultra')
        match.ball_z, match.ball_x, match.paddles[1] = 19.9, 9, -9
        bot.step(match, TICK)
        match.step(TICK)
        self.assertEqual(match.scores, [1, 0])
