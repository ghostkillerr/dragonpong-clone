"""Run original x86 physics/strike bytes with external I/O stubbed, then compare.

This is NOT a complete game replay. Sound, network, RNG and clock calls are
controlled boundaries; movement/hit arithmetic and branches execute natively
inside Unicorn. The original EXE is never launched or modified.
"""
import hashlib
import json
import math
import random
import struct
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / '.testdeps'))
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EIP, UC_X86_REG_ESP, UC_X86_REG_FPCW
from dragonpong.engine import Match, Rules, TICK, f32


class Native:
    def __init__(self):
        path = BASE.parent / 'analysis/original/DragonPong.exe'
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == '937ac8bb55b8265e9359e3db479d9334e5314dab981507fbc06313576fac1341'
        pe = pefile.PE(str(path))
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc.mem_map(0x400000, 0x200000)
        self.uc.mem_write(0x400000, pe.get_memory_mapped_image())
        self.uc.mem_map(0x700000, 0x20000)
        self.uc.reg_write(UC_X86_REG_FPCW, 0x37f)
        self.cleanup = {0x407516: 4, 0x404b85: 4, 0x40737f: 12, 0x40881c: 4,
                        0x40e8b0: 0, 0x406580: 12, 0x40200f: 4, 0x407672: 8,
                        0x407504: 8, 0x407150: 4, 0x40566e: 8, 0x4054db: 4,
                        0x402253: 4}
        dis = Cs(CS_ARCH_X86, CS_MODE_32)
        self.calls = {}
        for start, size in ((0x402541, 0x3fd), (0x404bfa, 0x500),
                            (0x404988, 0x88), (0x404a10, 0x88), (0x402f8d, 0x99)):
            for ins in dis.disasm(pe.get_data(start - 0x400000, size), start):
                if ins.mnemonic == 'call':
                    self.calls[ins.address] = (ins.size, ins.op_str)
                if ins.mnemonic == 'ret':
                    break
        self.uc.hook_add(UC_HOOK_CODE, self.hook)
        self.rolls = []
        self.clock_ms = 1000
        self.put(0x412e64, 0x710000)
        self.put(0x412e6c, 0x711000)
        self.put(0x412e74, 0x712000)
        self.put(0x412dd0, 8)

    def put(self, addr, value, fmt='I'):
        self.uc.mem_write(addr, struct.pack('<' + fmt, value))

    def get(self, addr, fmt='I'):
        return struct.unpack('<' + fmt, self.uc.mem_read(addr, 4))[0]

    def hook(self, uc, address, size, _data):
        if address not in self.calls:
            return
        length, operand = self.calls[address]
        target = int(operand, 16) if operand.startswith('0x') else None
        if target == 0x402281:  # Original strict lateral hit test executes too.
            return
        if target == 0x4088cd:  # GetTickCount import thunk through IAT 0x41204c.
            cleanup, result = 0, self.clock_ms
        else:
            if target not in self.cleanup:
                raise AssertionError(f'Unmodeled call {target:x} at {address:x}')
            cleanup, result = self.cleanup[target], 0
            if target == 0x40881c:
                bound = self.get(uc.reg_read(UC_X86_REG_ESP))
                result = self.rolls.pop(0)
                assert 0 <= result <= bound
        uc.reg_write(UC_X86_REG_ESP, uc.reg_read(UC_X86_REG_ESP) + cleanup)
        uc.reg_write(UC_X86_REG_EAX, result)
        uc.reg_write(UC_X86_REG_EIP, address + length)

    def setup(self, x, z, sx, sz, lateral, inbound, shield=False, silent=False, paddle=10):
        self.put(0x412e3c, x, 'f'); self.put(0x412e40, z, 'f')
        self.put(0x412e48, sx, 'f'); self.put(0x412e44, sz, 'f')
        self.put(0x412e4c, lateral); self.put(0x412e50, 1 if inbound else 2)
        self.put(0x412e18, int(shield)); self.put(0x412e38, int(silent))
        self.put(0x412e08, paddle, 'f'); self.put(0x412dcc, 20)
        self.put(0x412d9c, 1)

    def run(self, entry):
        stack = 0x71ff00
        self.put(stack, 0x700000)
        self.uc.reg_write(UC_X86_REG_ESP, stack)
        self.uc.emu_start(entry, 0x700000, count=10000)
        assert self.uc.reg_read(UC_X86_REG_EIP) == 0x700000
        assert self.uc.reg_read(UC_X86_REG_ESP) == stack + 4


class Rolls:
    def __init__(self, values):
        self.values = iter(values)
    def randrange(self, bound):
        result = next(self.values)
        assert 0 <= result < bound
        return result
    def choice(self, values):
        return values[next(self.values)]


def main():
    native, rng = Native(), random.Random(20261028)
    motion_count = hit_count = 0
    for _ in range(5000):
        x, z = f32(rng.uniform(.8, 19.2)), f32(rng.uniform(1, 19))
        sx, sz = f32(rng.uniform(0, 1)), f32(rng.uniform(.01, .6))
        lateral, inbound = rng.choice((1, 2, 3)), rng.choice((True, False))
        shield = rng.random() < .1
        if shield:
            inbound, z = True, f32(.5)
        native.setup(x, z, sx, sz, lateral, inbound, shield, silent=True)
        native.run(0x402541)
        match = Match()
        match.ball_x, match.ball_z = x - 10, z
        match.vx = (-1 if lateral == 1 else 1 if lateral == 2 else 0) * sx / TICK
        match.vz = (-1 if inbound else 1) * sz / TICK
        match.silent_until = math.inf
        match.shield_until[0] = 30 if shield else 0
        match.step(TICK)
        actual = (match.ball_x + 10, match.ball_z, 1 if match.vz < 0 else 2,
                  1 if match.vx < 0 else 2 if match.vx > 0 else 3)
        expected = (native.get(0x412e3c, 'f'), native.get(0x412e40, 'f'),
                    native.get(0x412e50), native.get(0x412e4c))
        assert actual == expected, ('motion', actual, expected)
        motion_count += 1
    # Include exact hit boundaries and centered strokes, plus randomized inputs.
    cases = [(10 + dx, z, 10) for dx in (-3, -2.999, 0, 2.999, 3) for z in (.5, 5.999, 6, 8)]
    cases += [(rng.uniform(1, 19), rng.uniform(0, 10), rng.uniform(1, 19)) for _ in range(2000)]
    for x, z, paddle in cases:
        x, z, paddle = map(f32, (x, z, paddle))
        sx, sz = f32(.07), f32(.15)
        rolls = [rng.randrange(6), rng.randrange(6), rng.randrange(11), rng.randrange(21)]
        native.setup(x, z, sx, sz, 1, True, silent=True, paddle=paddle)
        native.rolls = rolls.copy()
        native.run(0x404bfa)
        match = Match()
        match.ball_x, match.ball_z, match.paddles[0] = x - 10, z, paddle - 10
        match.vx, match.vz, match._lateral_step = -sx / TICK, -sz / TICK, sx
        match.silent_until = math.inf
        match.rng = Rolls(rolls)
        match.strike(0)
        actual = (f32(abs(match.vz) * TICK), match._lateral_step,
                  1 if match.vz < 0 else 2, 1 if match.vx < 0 else 2 if match.vx > 0 else 3,
                  bool(match.shield_until[0]), bool(match.silent_until))
        expected = (native.get(0x412e44, 'f'), native.get(0x412e48, 'f'),
                    native.get(0x412e50), native.get(0x412e4c),
                    bool(native.get(0x412e18)), bool(native.get(0x412e38)))
        assert actual == expected, ('strike', x, z, paddle, actual, expected)
        hit_count += 1
    extra_count = 0
    for position in range(1, 20):
        for direction, address in ((-1, 0x404988), (1, 0x404a10)):
            native.setup(10, 3, .01, .05, 1, True, paddle=position)
            native.run(address)
            match = Match()
            match.paddles[0] = position - 10
            match.move_step(0, direction)
            assert match.paddles[0] + 10 == native.get(0x412e08, 'f')
            extra_count += 1
        for roll in (0, 1):
            native.setup(10, 3, .01, .05, 1, False, paddle=position)
            native.put(0x412e50, 0)
            native.rolls = [roll]
            native.run(0x404bfa)
            match = Match()
            match.paddles[0] = position - 10
            match.rng = Rolls([roll])
            match.serve(0)
            assert (match.ball_x + 10, match.ball_z, f32(abs(match.vx) * TICK), f32(match.vz * TICK)) == (
                native.get(0x412e3c, 'f'), native.get(0x412e40, 'f'), native.get(0x412e48, 'f'), native.get(0x412e44, 'f'))
            extra_count += 1
    for elapsed in (0, 8000, 29999, 30000, 30001, 40000):
        native.setup(10, 3, .01, .05, 1, True, shield=True)
        native.put(0x412e1c, 1000)
        native.put(0x412e30, 0)
        native.clock_ms = 1000 + elapsed
        native.run(0x402f8d)
        match = Match()
        match.shield_until[0] = 30
        match.time = elapsed / 1000 - TICK
        match.step(TICK)
        assert bool(match.shield_until[0]) == bool(native.get(0x412e18))
        extra_count += 1
    for score in (0, 1, 20, 29, 30, 1000):
        native.setup(10, .5, .01, .05, 1, True, silent=True)
        native.put(0x412e24, score)
        native.rolls = [0] * 4
        native.run(0x402541)
        match = Match(Rules(score=2000))
        match.scores[1] = score
        match.ball_z, match.vz, match.silent_until = .5, -3, math.inf
        match.step(TICK)
        assert match.scores[1] == native.get(0x412e24)
        assert bool(match.silent_until) == bool(native.get(0x412e38))
        assert native.get(0x412e50) == 0 and match.vz == 0
        extra_count += 1
    report = dict(motion_cases=motion_count, strike_cases=hit_count, additional_cases=extra_count, mismatches=0,
                  binary_sha256='937ac8bb55b8265e9359e3db479d9334e5314dab981507fbc06313576fac1341',
                  scope='Original x86 motion, walls, shield reflection/expiry, hit window/arithmetic, powerup branches, serve, movement bounds, goal scoring',
                  excluded='Goal sequencing, native timing, UI, audio rendering, network and RNG sequence')
    (BASE / 'native_verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
