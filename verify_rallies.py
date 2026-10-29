"""Compare complete incoming flights, including the native BE receive branch.

The first oracle only checked isolated movement/hit functions. This verifier
executes the observed receive block too, and counts wall collisions over time.
"""
import argparse
import json
import random
import subprocess
import sys
import types
from pathlib import Path

from verify_native import Native, Rolls, TICK, f32, Cs, CS_ARCH_X86, CS_MODE_32
from unicorn.x86_const import UC_X86_REG_ESP, UC_X86_REG_EIP
import dragonpong.engine as current

BASE = Path(__file__).resolve().parent


class RallyNative(Native):
    def __init__(self):
        original = BASE.parent / 'top/dragonpong/DragonPong.exe'
        super().__init__(original if original.exists() else None)
        self.walls = 0
        dis = Cs(CS_ARCH_X86, CS_MODE_32)
        for ins in dis.disasm(bytes(self.uc.mem_read(0x403cfc, 0x55)), 0x403cfc):
            if ins.mnemonic == 'call':
                self.calls[ins.address] = (ins.size, ins.op_str)

    def hook(self, uc, address, size, data):
        if address in (0x4028f1, 0x402934):
            self.walls += 1
        super().hook(uc, address, size, data)

    def receive_shot(self, paddle):
        self.put(0x412e20, paddle, 'f')
        stack = 0x71ff00
        self.uc.reg_write(UC_X86_REG_ESP, stack)
        # Native BE: incoming flag, source paddle X, clear silence, depth=20.
        self.uc.emu_start(0x403cfc, 0x403d51, count=1000)
        assert self.uc.reg_read(UC_X86_REG_EIP) == 0x403d51
        assert self.uc.reg_read(UC_X86_REG_ESP) == stack


def comparison(engine, seconds=60, seed=17):
    native = RallyNative()
    native.setup(10, 20, f32(.01), f32(.05), 2, True)
    match = engine.Match(engine.Rules(shield=False, silent_ball=False), seed=seed)
    match.ball_x, match.ball_z = 0, 20
    match.vx, match.vz = f32(.01) / TICK, -f32(.05) / TICK
    match._lateral_step = f32(.01)
    native_hits = clone_hits = clone_walls = 0
    native_rng, clone_rng = random.Random(seed), random.Random(seed)
    for _ in range(round(seconds / TICK)):
        native.run(0x402541)
        if native.get(0x412e40, 'f') < 5.5:
            paddle = max(1, min(19, round(native.get(0x412e3c, 'f'))))
            native.put(0x412e08, paddle, 'f')
            native.rolls = [native_rng.randrange(6), native_rng.randrange(6), 0, 0]
            native.run(0x404bfa)
            native.receive_shot(paddle)
            native_hits += 1
        events = match.step(TICK)
        clone_walls += sum(e.kind == 'wall' for e in events)
        player = 0 if match.vz < 0 else 1
        depth = match.ball_z if player == 0 else 20 - match.ball_z
        if depth < 5.5:
            match.paddles[player] = max(-9, min(9, round(match.ball_x)))
            match.rng = Rolls([clone_rng.randrange(6), clone_rng.randrange(6)])
            if match.strike(player):
                clone_hits += 1
    return dict(seconds=seconds, seed=seed,
                original=dict(hits=native_hits, walls=native.walls),
                clone=dict(hits=clone_hits, walls=clone_walls))


def verify_flights():
    native = RallyNative()
    rng = random.Random(20261029)
    samples = 0
    for player in (0, 1):
        for _ in range(200):
            paddle = rng.randint(2, 18)
            contact = f32(paddle + rng.uniform(-2.5, 2.5))
            depth = f32(rng.uniform(1.5, 5.9))
            sx, sz = f32(rng.uniform(.01, .3)), f32(rng.uniform(.05, .5))
            rolls = [rng.randrange(6), rng.randrange(6)]
            native.setup(contact, depth, sx, sz, 1, True, paddle=paddle)
            native.rolls = rolls + [0, 0]
            native.run(0x404bfa)
            native.receive_shot(paddle)
            match = current.Match(current.Rules(shield=False, silent_ball=False))
            match.paddles[player] = paddle - 10
            match.ball_x = contact - 10
            match.ball_z = depth if player == 0 else 20 - depth
            match.vx, match.vz = -sx / TICK, (-1 if player == 0 else 1) * sz / TICK
            match._lateral_step = sx
            match.rng = Rolls(rolls)
            assert match.strike(player)
            assert match.ball_x + 10 == native.get(0x412e3c, 'f'), 'BE lateral origin missing'
            incoming_depth = 20 - match.ball_z if player == 0 else match.ball_z
            assert incoming_depth == native.get(0x412e40, 'f'), 'BE depth origin missing'
            # Stop at the opponent's hit window; includes multiple wall bounces.
            while native.get(0x412e40, 'f') >= 6:
                before = native.walls
                native.run(0x402541)
                events = match.step(TICK)
                assert match.ball_x + 10 == native.get(0x412e3c, 'f')
                incoming_depth = 20 - match.ball_z if player == 0 else match.ball_z
                assert incoming_depth == native.get(0x412e40, 'f')
                assert sum(e.kind == 'wall' for e in events) == native.walls - before
                assert (1 if match.vx < 0 else 2 if match.vx > 0 else 3) == native.get(0x412e4c)
                samples += 1
    return samples


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args()
    engine = current
    if args.baseline:
        engine = types.ModuleType('baseline_engine')
        sys.modules[engine.__name__] = engine
        code = subprocess.check_output(['git', '-c', 'safe.directory=' + BASE.as_posix(),
                                        'show', 'cc7764a:dragonpong/engine.py'], cwd=BASE).decode()
        exec(compile(code, 'baseline_engine', 'exec'), engine.__dict__)
    results = [comparison(engine, seed=seed) for seed in (3, 17, 41)]
    report = {'baseline': args.baseline, 'comparisons': results}
    if not args.baseline:
        assert all(row['original'] == row['clone'] for row in results), results
        report['flight_samples'] = verify_flights()
    path = BASE / ('rally_baseline.json' if args.baseline else 'rally_verification.json')
    path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
