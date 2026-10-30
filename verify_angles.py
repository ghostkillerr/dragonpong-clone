"""Local-only angular comparison with original x86 strike instructions."""
import json
import math
from pathlib import Path
from verify_native import Native, Rolls, TICK, f32
from dragonpong.engine import Match, Rules


def angle(vx, vz):
    return math.degrees(math.atan2(abs(vx), abs(vz)))


def main():
    root = Path(__file__).resolve().parent
    native = Native(root.parent / 'top/dragonpong/DragonPong.exe')
    count = 0
    maximum = 0.0
    for player in (0, 1):
        for lateral, forward in ((.01, .05), (.05, .1), (.3, .25), (.5, .75), (1, 1)):
            for offset in (-2, 0, 2):
                for rise_forward in range(6):
                    for rise_lateral in range(6):
                        native.setup(10 + offset, 3, f32(lateral), f32(forward), 1, True, paddle=10)
                        native.rolls = [rise_forward, rise_lateral, 0, 0]
                        native.run(0x404bfa)
                        direction = native.get(0x412e4c)
                        expected = angle(0 if direction == 3 else native.get(0x412e48, 'f'),
                                         native.get(0x412e44, 'f'))
                        match = Match(Rules(shield=False, silent_ball=False))
                        match.ball_x = offset
                        match.ball_z = 3 if player == 0 else 17
                        match._lateral_step = f32(lateral)
                        match.vx = -f32(lateral) / TICK
                        match.vz = (-1 if player == 0 else 1) * f32(forward) / TICK
                        match.rng = Rolls([rise_forward, rise_lateral])
                        assert match.strike(player)
                        actual = angle(match.vx, match.vz)
                        error = abs(actual - expected)
                        maximum = max(maximum, error)
                        assert error < 1e-10, (player, lateral, forward, offset, expected, actual)
                        count += 1
    report = {'cases': count, 'max_angle_difference_degrees': maximum,
              'serve_degrees': angle(f32(.01), f32(.05)),
              'first_hit_most_lateral_degrees': angle(f32(.01 + .05), f32(.05)),
              'first_hit_least_lateral_degrees': angle(f32(.01), f32(.05 + .05)),
              'scope': 'Identical positions and controlled random speed increases, original x86 strike vs current engine',
              'excluded': 'Different player inputs/RNG sequences, HRTF perception, real network speed serialization'}
    (root / 'angle_verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
