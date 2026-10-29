"""Shared observed rules. Units are native game units; see PARITY.md."""
from __future__ import annotations
import math
import random
import struct
from dataclasses import dataclass, field

HALF_WIDTH = 9.0
COURT_LENGTH = 20.0
PADDLE_HALF_WIDTH = 3.0  # Strict hit tolerance.
SHIELD_SECONDS = 30.0
TICK = .017  # Nominal timing assumption; native scheduler is not deterministic.
GOAL_PAUSE = 7.3  # Two 3s reactions, then 500/500/300ms score cues.


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


@dataclass(frozen=True)
class Rules:
    score: int = 10
    shield: bool = True
    silent_ball: bool = True

    def __post_init__(self):
        if type(self.score) is not int or not 1 <= self.score <= 2_147_483_647:
            raise ValueError('score must be a positive 32-bit integer')
        if type(self.shield) is not bool or type(self.silent_ball) is not bool:
            raise ValueError('powerup settings must be boolean')


@dataclass(frozen=True)
class Event:
    kind: str
    x: float
    z: float
    height: float = .35
    player: int | None = None
    variant: int = 1
    reaction: int = 1
    opponent_reaction: int = 1


@dataclass
class Match:
    rules: Rules = field(default_factory=Rules)
    seed: int | None = None
    time: float = 0.0
    ball_x: float = 0.0
    ball_z: float = 0.0
    vx: float = 0.0
    vz: float = 0.0
    paddles: list[float] = field(default_factory=lambda: [0.0, 0.0])
    scores: list[int] = field(default_factory=lambda: [0, 0])
    shield_until: list[float] = field(default_factory=lambda: [0.0, 0.0])
    silent_until: float = 0.0  # infinity while active; ends on hit/goal.
    serving: int = 0
    winner: int | None = None
    events: list[Event] = field(default_factory=list)
    _accumulator: float = 0.0
    _lateral_step: float = .01
    ready_at: float = 0.0

    def __post_init__(self):
        self.rng = random.Random(self.seed)
        self.audio_rng = random.Random(self.seed)

    def emit(self, kind, player=None):
        if kind == 'goal':
            self.events.append(Event(kind, self.ball_x, self.ball_z, player=player,
                                     variant=self.audio_rng.randrange(1, 9),
                                     reaction=self.audio_rng.randrange(1, 6),
                                     opponent_reaction=self.audio_rng.randrange(1, 6)))
        else:
            self.events.append(Event(kind, self.ball_x, self.ball_z, player=player))

    def move_step(self, player, direction):
        if player not in (0, 1) or direction not in (-1, 1):
            raise ValueError('invalid movement')
        if self.winner is not None:
            return
        old = self.paddles[player]
        self.paddles[player] = max(-HALF_WIDTH, min(HALF_WIDTH, old + direction))
        self.events.append(Event('border' if old == self.paddles[player] else 'move',
                                 self.paddles[player], player * COURT_LENGTH, player=player))

    def serve(self, player):
        if self.winner is not None or player != self.serving or self.vz or self.time < self.ready_at:
            return False
        self.ball_x = self.paddles[player]
        self.ball_z = player * COURT_LENGTH
        self._lateral_step = f32(.01)
        self.vx = self.rng.choice((-1, 1)) * self._lateral_step / TICK
        self.vz = (1 if player == 0 else -1) * f32(.05) / TICK
        self.emit('serve', player)
        return True

    def can_strike(self, player):
        if player not in (0, 1) or self.winner is not None:
            return False
        incoming = self.vz < 0 if player == 0 else self.vz > 0
        depth = self.ball_z if player == 0 else COURT_LENGTH - self.ball_z
        return incoming and depth < 6 and abs(self.ball_x - self.paddles[player]) < 3

    def strike(self, player):
        if not self.vz:
            return self.serve(player)
        if not self.can_strike(player):
            return False
        offset = self.ball_x - self.paddles[player]
        speed = f32(f32(abs(self.vz) * TICK) + self.rng.randrange(6) / 100)
        self._lateral_step = f32(self._lateral_step + self.rng.randrange(6) / 100)
        self.vz = (1 if player == 0 else -1) * speed / TICK
        self.vx = (1 if offset > 0 else -1 if offset < 0 else 0) * self._lateral_step / TICK
        # The native peer's BE receive branch starts a fresh incoming flight
        # at the hitter's paddle, at full court depth (0x403cfc..0x403d51).
        # Keeping the fractional contact position shortened rallies and kept
        # reintroducing lateral direction even after apparently centered hits.
        self.ball_x = self.paddles[player]
        self.ball_z = player * COURT_LENGTH
        self.emit('paddle', player)
        self._clear_silent()
        # Humans and bots use this same path and these same odds.
        if self.rules.shield and self.rng.randrange(11) == 7:
            self.shield_until[player] = self.time + SHIELD_SECONDS
            self.emit('shield_on', player)
        if self.rules.silent_ball and self.rng.randrange(21) == 13:
            self.silent_until = math.inf
            self.emit('silent_on', player)
        return True

    def _clear_silent(self):
        if self.silent_until:
            self.silent_until = 0
            self.emit('silent_off')

    def step(self, dt):
        if not math.isfinite(dt) or not 0 <= dt <= .25:
            raise ValueError('invalid time step')
        self._accumulator += dt
        while self._accumulator + 1e-12 >= TICK:
            self._accumulator -= TICK
            self.time += TICK
            for player in (0, 1):
                if self.shield_until[player] and self.time > self.shield_until[player]:
                    self.shield_until[player] = 0
                    self.events.append(Event('shield_off', self.paddles[player], player * COURT_LENGTH,
                                             player=player))
            if self.vz and self.winner is None:
                self._tick()
        events, self.events = self.events, []
        return events

    def _tick(self):
        defending = 0 if self.vz < 0 else 1
        depth = self.ball_z if defending == 0 else COURT_LENGTH - self.ball_z
        if depth < 1:
            if self.rules.shield and self.shield_until[defending] > 0 and self.time <= self.shield_until[defending]:
                self.vz = -self.vz
                self.emit('shield_hit', defending)
                return
            self._clear_silent()
            scorer = 1 - defending
            self.scores[scorer] += 1
            self.emit('goal', scorer)
            self.vx = self.vz = 0
            self.serving = defending
            self.ready_at = self.time + GOAL_PAUSE
            if self.scores[scorer] >= self.rules.score:
                self.winner = scorer
                self.emit('win', scorer)
            return
        # Float32 arithmetic in original lateral coordinates (1..19).
        self.ball_x = f32(f32(self.ball_x + 10) + f32(self.vx * TICK)) - 10
        # Each receiving native client subtracts from its own float32 depth.
        # Adding in world coordinates for player 1 rounds differently and can
        # shift the hit by one tick, changing the following shot's lateral sign.
        if self.vz < 0:
            self.ball_z = f32(self.ball_z - f32(-self.vz * TICK))
        else:
            self.ball_z = COURT_LENGTH - f32((COURT_LENGTH - self.ball_z) - f32(self.vz * TICK))
        if (self.ball_x < -HALF_WIDTH and self.vx < 0) or (self.ball_x > HALF_WIDTH and self.vx > 0):
            self.vx = -self.vx
            self.emit('wall')  # Silence suppresses rolling, not wall collisions.


class Bot:
    """Observes the current ball and uses normal controls; never predicts landing."""
    # Minimum one-unit movement interval, observation interval, observation error.
    LEVELS = {'Kolay': (.20, .14, .55), 'Orta': (.111, .08, .35),
              'Zor': (.074, .04, .22), 'Ultra': (.063, .01, .12)}

    def __init__(self, level, seed=None):
        if level not in self.LEVELS:
            raise ValueError('unknown difficulty')
        self.level = level
        self.rng = random.Random(seed)
        self.observation = 0.0
        self.target = 0.0
        self.elapsed = 0.0
        self.last_move = -math.inf

    def step(self, match, dt, player=1):
        if match.winner is not None:
            return
        interval, reaction, error = self.LEVELS[self.level]
        self.elapsed += dt
        self.observation -= dt
        if self.observation <= 0:
            self.target = max(-HALF_WIDTH, min(HALF_WIDTH, match.ball_x + self.rng.uniform(-error, error)))
            self.observation = reaction
        delta = self.target - match.paddles[player]
        if abs(delta) >= .75 and self.elapsed - self.last_move + 1e-12 >= interval:
            match.move_step(player, 1 if delta > 0 else -1)
            self.last_move = self.elapsed
        if not match.vz and match.serving == player:
            match.serve(player)
        elif match.can_strike(player):
            match.strike(player)
