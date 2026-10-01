"""A concrete route: named waypoints the player pastes into the galaxy map.

Built from a router.Plan: neutron waypoints get their exact paste names,
refuel hops get a real scoopable star from the stellar generator, and every
waypoint name is checked to round-trip to its exact address before use.
"""
from __future__ import annotations

import gzip
import json
import math
import time
import uuid
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

from . import galaxy, names, router

DATA = Path(__file__).resolve().parent.parent / "data"

# Waypoint kinds
NEUTRON = "neutron"
SCOOP = "scoop"
DESTINATION = "destination"


@lru_cache(maxsize=1)
def _name_overrides():
    path = DATA / "names-overrides.json.gz"
    if not path.exists():
        return {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return {int(k): v for k, v in json.load(f).items()}


def evidence_of(flags):
    if flags & galaxy.FLAG_FIELD_ADDED:
        return "seen in game"
    if flags & galaxy.FLAG_CONFIRMED:
        return "confirmed"
    if flags & galaxy.FLAG_PREDICTED:
        return "predicted"
    return "reported"


@dataclass
class Waypoint:
    name: str
    address: int
    position: tuple
    kind: str                     # neutron / scoop / destination
    jumps: int                    # estimated jumps from the previous waypoint
    distance: float               # LY from the previous waypoint
    boosted: bool                 # leave the previous waypoint supercharged
    evidence: str = ""            # reported / predicted / confirmed / seen in game
    star_class: str = ""          # when known (scoop stars, destination)
    fuel_after: float = 0.0
    scoop: int = 0                # router.NO_SCOOP / SCOOP_EN_ROUTE / SCOOP_REQUIRED


@dataclass
class Route:
    waypoints: list
    start: dict                   # {name, address, position}
    destination: dict             # {name, address, position, star_class}
    ship: dict                    # {name, range, boost_range, multiplier, tank}
    direct_jumps: int
    use_predicted: bool
    corpus_id: str = ""
    next_index: int = 0           # index of the waypoint being flown to
    route_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created: float = field(default_factory=time.time)
    notes: list = field(default_factory=list)
    plan_seconds: float = 0.0
    flown: int = 0                # real FSD jumps made while following this route
    leg_flown: int = 0            # real FSD jumps made since the last waypoint

    # --- progress -----------------------------------------------------
    @property
    def total_jumps(self):
        return sum(w.jumps for w in self.waypoints)

    @property
    def jumps_left(self):
        return sum(w.jumps for w in self.waypoints[self.next_index:])

    @property
    def jumps_to_go(self):
        """Estimated jumps left, counting jumps already made on the current leg."""
        if self.done:
            return 0
        return self.jumps_left - min(self.leg_flown, self.waypoints[self.next_index].jumps - 1)

    @property
    def done(self):
        return self.next_index >= len(self.waypoints)

    @property
    def next(self):
        return None if self.done else self.waypoints[self.next_index]

    def distance_left(self, here=None):
        if self.done:
            return 0.0
        wps = self.waypoints[self.next_index:]
        first = math.dist(here, wps[0].position) if here is not None else wps[0].distance
        return first + sum(w.distance for w in wps[1:])

    def index_of(self, address):
        for i, w in enumerate(self.waypoints):
            if w.address == address:
                return i
        return None

    # --- persistence --------------------------------------------------
    def to_json(self):
        data = asdict(self)
        return data

    @classmethod
    def from_json(cls, data):
        data = dict(data)
        data["waypoints"] = [Waypoint(**{**w, "position": tuple(w["position"])}) for w in data["waypoints"]]
        return cls(**data)


class RouteError(RuntimeError):
    pass


def neutron_name(pack, index):
    address = int(pack.addr[index])
    override = _name_overrides().get(address)
    if override:
        return override
    return names.name_from_address(address, pack.position(index))


def build(plan, pack, stars, start, destination, ship, use_predicted, corpus_id=""):
    """Turn a router.Plan into a Route.

    ``start``/``destination``: dicts with name, address, position (and
    destination star_class when known).
    """
    waypoints = []
    prev_pos = tuple(start["position"])
    B = plan.boost_range
    step = plan.ship_range * router.Options().eta
    for hop in plan.hops:
        to = hop.to
        if to["kind"] == "destination":
            wp = Waypoint(destination["name"], int(destination["address"]), tuple(destination["position"]),
                          DESTINATION, hop.jumps, hop.distance, hop.boosted,
                          star_class=destination.get("star_class", ""), fuel_after=hop.fuel_after,
                          scoop=hop.refuel)
        else:
            index = to["index"]
            flags = to.get("flags", 0)
            wp = Waypoint(neutron_name(pack, index), int(to["address"]), tuple(to["position"]),
                          NEUTRON, hop.jumps, hop.distance, hop.boosted,
                          evidence=evidence_of(flags), star_class="N", fuel_after=hop.fuel_after,
                          scoop=hop.refuel)
        if hop.boosted and hop.refuel == router.SCOOP_REQUIRED and stars is not None:
            stop = find_scoop_stop(stars, prev_pos, wp.position, B, step)
            if stop is not None:
                s_addr, s_pos, s_class, s_name = stop
                d1 = math.dist(prev_pos, s_pos)
                d2 = math.dist(s_pos, wp.position)
                waypoints.append(Waypoint(s_name, s_addr, s_pos, SCOOP, 1, d1, True,
                                          evidence="generated", star_class=s_class,
                                          fuel_after=ship.fuel_capacity, scoop=router.SCOOP_REQUIRED))
                wp.jumps = max(1, router.ordinary_jumps(d2, step))
                wp.distance = d2
                wp.boosted = False
                wp.scoop = router.NO_SCOOP
        waypoints.append(wp)
        prev_pos = wp.position
    route = Route(waypoints, dict(start), dict(destination),
                  {"name": ship.name, "range": round(plan.ship_range, 2), "boost_range": round(B, 2),
                   "multiplier": ship.neutron_multiplier, "tank": ship.fuel_capacity,
                   "scoop": ship.has_scoop},
                  plan.direct_jumps, use_predicted, corpus_id, notes=list(plan.notes),
                  plan_seconds=round(plan.elapsed, 2))
    return route


def find_scoop_stop(stars, u, v, B, step, radii=(10.0, 20.0, 40.0, 80.0)):
    """A real scoopable star to refuel at between neutron u and waypoint v.

    Reachable with one supercharged jump from u and as close to v as possible.
    Searches a small sphere first (dense space answers at once) and widens.
    Returns (address, position, star_class, name) or None.
    """
    d = math.dist(u, v)
    if d < 1e-6:
        return None
    direction = [(b - a) / d for a, b in zip(u, v)]
    for r in radii:
        if d <= B:
            along = max(0.0, d - step * 0.5)  # land within one jump of v
        else:
            along = max(0.0, B - r)           # as far as one boost reaches
        centre = tuple(a + k * along for a, k in zip(u, direction))
        best = None
        for dist_c, address, pos, star_class in stars.scoop_stars_near(centre, r):
            if math.dist(u, pos) > B * 0.995:
                continue
            key = (router.ordinary_jumps(math.dist(pos, v), step), math.dist(pos, v))
            if best is None or key < best[0]:
                best = (key, address, pos, star_class)
        if best is not None:
            _, address, pos, star_class = best
            try:
                name = names.name_from_address(address, pos)
            except names.NamingError:
                continue
            return address, tuple(pos), star_class, name
    return None


@dataclass
class FuelWalk:
    dry_at: int | None            # waypoint index whose hop cannot be flown with the fuel left
    stop: int                     # waypoint index where the walk ended
    fuel: float                   # main-tank fuel on reaching the stop (before any refuel)


def hop_legs(distance, boosted, R, multiplier, eta):
    """Jumps of one hop as (distance, boost multiplier): boost first, then equal ordinary jumps."""
    legs = []
    if boosted and distance > 1e-6:
        first = min(distance, R * multiplier)
        legs.append((first, multiplier))
        distance -= first
    n = router.ordinary_jumps(distance, R * eta) if distance > 1e-3 else 0
    if n:
        legs += [(distance / n, 1.0)] * n
    return legs


def walk_fuel(route, ship, fuel, here, boosted_now, topup=True, start=None):
    """Follow the route from ``here`` with ``fuel`` t in the main tank.

    Starts with the hop to waypoint ``start`` (default: the next waypoint) and
    stops at the first refuel point: a named refuel stop, or, when ``topup``,
    the last star before the end of a hop the plan marks SCOOP_EN_ROUTE. The
    planner assumes you leave that star nearly full. Without ``topup`` those
    hops are flown without scooping. The first hop starts supercharged only if
    ``boosted_now``.
    """
    R = ship.max_range(ship.fuel_capacity)
    eta = router.Options().eta
    pos = tuple(here)
    first = route.next_index if start is None else start
    for k in range(first, len(route.waypoints)):
        w = route.waypoints[k]
        boosted = w.boosted and (boosted_now or k > first)
        legs = hop_legs(math.dist(pos, w.position), boosted, R, ship.neutron_multiplier, eta)
        refuel_at = len(legs) - 1 if topup and w.scoop == router.SCOOP_EN_ROUTE and legs and legs[-1][1] == 1.0 else None
        for n, (dist, mult) in enumerate(legs):
            if n == refuel_at:
                return FuelWalk(None, k, fuel)
            if fuel <= 1e-6:
                return FuelWalk(k, k, 0.0)
            used = ship.fuel_used(dist, fuel, mult)
            if used > min(fuel, ship.max_fuel_per_jump) + 1e-6:
                return FuelWalk(k, k, fuel)
            fuel -= used
        pos = w.position
        if w.kind == SCOOP:
            return FuelWalk(None, k, fuel)
    return FuelWalk(None, len(route.waypoints) - 1, fuel)


def fuel_needed(route, ship, here, boosted_now, reserve, start=None):
    """Least fuel (t) that reaches the next refuel point with ``reserve`` left, or None."""
    def enough(f):
        walk = walk_fuel(route, ship, f, here, boosted_now, start=start)
        return walk.dry_at is None and walk.fuel >= reserve - 1e-6

    lo, hi = 0.0, ship.fuel_capacity
    if not enough(hi):
        return None
    for _ in range(24):
        mid = (lo + hi) / 2
        if enough(mid):
            hi = mid
        else:
            lo = mid
    return hi


def verify(route, ship):
    """Independent re-check of a route. Returns a list of problems (empty = ok)."""
    problems = []
    R = ship.max_range(ship.fuel_capacity)
    B = R * ship.neutron_multiplier
    prev = tuple(route.start["position"])
    for n, w in enumerate(route.waypoints, 1):
        d = math.dist(prev, w.position)
        if abs(d - w.distance) > 0.5:
            problems.append(f"{n}: distance {w.distance:.1f} != {d:.1f}")
        first = B if w.boosted else R
        need = 1 if d <= first + 1e-6 else 1 + math.ceil((d - first) / R - 1e-9)
        if w.jumps < need:
            problems.append(f"{n}: {w.jumps} jumps cannot cover {d:.1f} LY")
        if w.boosted and n > 1 and route.waypoints[n - 2].kind != NEUTRON:
            problems.append(f"{n}: boosted leg does not start at a neutron star")
        if w.kind != DESTINATION:
            try:
                if names.address_from_name(w.name) != w.address:
                    problems.append(f"{n}: name {w.name!r} does not resolve to its address")
            except names.NamingError as e:
                problems.append(f"{n}: name {w.name!r} unusable ({e})")
        prev = w.position
    return problems
