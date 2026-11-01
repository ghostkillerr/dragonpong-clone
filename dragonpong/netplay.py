"""Bounded online view prediction; offline Match remains the rules authority."""
from dataclasses import dataclass
import math

from .engine import COURT_LENGTH, HALF_WIDTH, TICK, f32

STRIKE_FEATURE = 'strike_ref_v1'
MAX_PREDICTION = .2
MAX_CONTACT_LAG = .25
MAX_VIEW_AGE = .5


@dataclass(frozen=True)
class Flight:
    x: float
    z: float
    vx: float
    vz: float


def predict_flight(ball, velocity, seconds, phase=0.0, shield_left=(0.0, 0.0), sim_time=0.0) -> Flight:
    """Use the native float32 tick and overshoot, including shield expiry.

    A speculative goal is held at its last position. Neither prediction nor
    a received view can invent a score or an opponent's next strike.
    """
    if not math.isfinite(seconds) or not 0 <= seconds <= .5:
        raise ValueError('invalid prediction time')
    x, z = ball
    vx, vz = velocity
    shield_expiry = [sim_time + value for value in shield_left]
    tick_time = sim_time
    accumulator = phase + seconds
    while vz and accumulator + 1e-12 >= TICK:
        accumulator -= TICK
        tick_time += TICK
        player = 0 if vz < 0 else 1
        depth = z if player == 0 else COURT_LENGTH - z
        if depth < 1:
            if shield_left[player] > 0 and tick_time <= shield_expiry[player]:
                vz = -vz
                continue
            break
        x = f32(f32(x + 10) + f32(vx * TICK)) - 10
        if vz < 0:
            z = f32(z - f32(-vz * TICK))
        else:
            z = COURT_LENGTH - f32((COURT_LENGTH - z) - f32(vz * TICK))
        if (x < -HALF_WIDTH and vx < 0) or (x > HALF_WIDTH and vx > 0):
            vx = -vx
    return Flight(x, z, vx, vz)


def predict_view(state: dict, seconds: float) -> Flight:
    return predict_flight(state['ball'], state['velocity'], seconds,
                          state.get('phase', 0.0), state.get('shield_left', (0.0, 0.0)),
                          state.get('sim_time', 0.0))


def view_seconds(state: dict, ping_ms, now: float, modern: bool = True) -> float:
    age = max(0.0, now - state.get('_received_at', now))
    latency = ping_ms / 1000 if isinstance(ping_ms, (int, float)) and 0 <= ping_ms < 1000 else 0.0
    # Modern contacts refer to the view at press time, so estimate the present.
    # Legacy servers still need the old input-arrival look-ahead.
    return min(MAX_PREDICTION if modern else .3, age + latency * (.5 if modern else 1))


class ContactFrames:
    """Retain one issued moving view across coalesced pending-goal packets.

    Only local metadata is attached; it never goes back over the wire. A new
    flight or confirmed goal invalidates the retained view immediately.
    """
    def __init__(self):
        self.candidate = None

    def receive(self, state: dict) -> dict:
        state.pop('_contact_candidate', None)
        flight_id = state.get('flight_id')
        if (type(flight_id) is not int or state.get('winner') is not None or
                (self.candidate and self.candidate['flight_id'] != flight_id)):
            self.candidate = None
        velocity = state.get('velocity', (0, 0))
        ball = state.get('ball', (0, 0))
        if (type(flight_id) is int and velocity[1] and not state.get('pending_goal') and
                state.get('winner') is None and
                (ball[1] if velocity[1] < 0 else COURT_LENGTH - ball[1]) >= 1):
            self.candidate = {key: list(value) if isinstance(value, list) else value for key, value in state.items()
                              if key not in ('events', '_contact_candidate')}
        if state.get('pending_goal') and self.candidate is not None:
            state['_contact_candidate'] = self.candidate
        return state


class ServerClockFloor:
    """A matched pong proves the server has reached at least its send time.

    Advancing that lower bound locally needs no shared clock origin and no
    assumption that upload/download delays are equal. It never claims an
    exact network age.
    """
    def __init__(self):
        self.server_time = None
        self.received_at = None

    def observe(self, server_time, now: float) -> None:
        if type(server_time) not in (int, float) or not math.isfinite(server_time):
            return
        previous = self.at(now)
        self.server_time = max(previous, server_time) if previous is not None else server_time
        self.received_at = now

    def at(self, now: float):
        return (self.server_time + max(0, now - self.received_at)
                if self.server_time is not None else None)

    def tag(self, state: dict, now: float) -> None:
        lower_bound = self.at(now)
        if lower_bound is not None:
            state['_server_now_floor'] = lower_bound


def view_is_stale(state: dict, now: float, limit=MAX_CONTACT_LAG) -> bool:
    local_age = max(0, now - state.get('_received_at', now))
    if local_age > limit:
        return True
    stamp, lower_bound = state.get('server_time'), state.get('_server_now_floor')
    return (type(stamp) in (int, float) and type(lower_bound) in (int, float) and
            math.isfinite(stamp) and math.isfinite(lower_bound) and
            lower_bound + local_age - stamp > limit)


@dataclass(frozen=True)
class PresentedFlight:
    source: dict
    seconds: float
    flight: Flight
    held: bool = False


def present_flight(state: dict, ping_ms, now: float, player=None, modern=True) -> PresentedFlight:
    """Keep a fast incoming ball's last legal contact visible briefly.

    This selects an earlier native tick, never a fabricated position. The
    server still validates the original frame and its unchanged lag limit.
    """
    source = state
    candidate = state.get('_contact_candidate')
    held = False
    if (modern and player in (0, 1) and state.get('pending_goal') and candidate and
            candidate.get('flight_id') == state.get('flight_id') and
            state.get('winner') is None and
            not view_is_stale(candidate, now) and
            state['sim_time'] - candidate['sim_time'] <= MAX_CONTACT_LAG):
        vz = candidate['velocity'][1]
        if (vz < 0 if player == 0 else vz > 0):
            source, held = candidate, True
    seconds = view_seconds(source, ping_ms, now, modern)
    projected = predict_view(source, seconds)
    if (modern and player in (0, 1) and source.get('winner') is None and
            not source.get('pending_goal') and not view_is_stale(source, now)):
        incoming = source['velocity'][1] < 0 if player == 0 else source['velocity'][1] > 0
        depth = projected.z if player == 0 else COURT_LENGTH - projected.z
        still_incoming = projected.vz < 0 if player == 0 else projected.vz > 0
        if incoming and still_incoming and depth < 1:
            phase = source.get('phase', 0.0)
            last = None
            for tick in range(int((phase + seconds + 1e-12) / TICK) + 1):
                elapsed = min(seconds, max(0.0, tick * TICK - phase))
                sample = predict_view(source, elapsed)
                sample_depth = sample.z if player == 0 else COURT_LENGTH - sample.z
                if 1 <= sample_depth < 6:
                    last = elapsed, sample
                if sample_depth < 1:
                    break
            if last is not None:
                seconds, projected = last
                held = True
    return PresentedFlight(source, seconds, projected, held)
