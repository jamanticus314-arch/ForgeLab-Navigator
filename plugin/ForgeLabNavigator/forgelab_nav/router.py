"""Neutron highway planner: fewest jumps, fuel-safe, in seconds, offline.

Model (per hop between waypoints u -> v):
  * at a neutron star u the player supercharges, so the first jump reaches up
    to B = M * R (M = 4, or 6 for the SCO Mk II drive; R = laden range on a
    full tank, the conservative case);
  * any remaining distance is covered by ordinary jumps of about eta * R,
    which the in-game plotter fills in when the player plots to v;
  * a hop with at least one ordinary jump passes ordinary stars where the
    player scoops (the route names a real scoopable star for it later);
  * a direct neutron-to-neutron boost passes no scoopable star, so fuel is
    tracked on every label; a direct boost that would leave less than the
    safety reserve becomes a refuel hop (boost onto a scoopable star, 2 jumps).

Search: jump-layered beam. Labels are grouped by jumps used so far; layers
are processed in increasing order, and each keeps the ``beam`` best labels
(one per spatial cell, ranked by remaining distance with a fuel bonus). The
first layer that reaches the destination gives the route. Dense regions are
where boosts are plentiful and greedy progress is near optimal; the beam
keeps alternatives alive around gaps.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from . import galaxy


class PlanError(RuntimeError):
    pass


# Hop.refuel values.
NO_SCOOP = 0          # direct boost between neutron stars: nothing to scoop
SCOOP_EN_ROUTE = 1    # passes ordinary stars; scoop if convenient
SCOOP_REQUIRED = 2    # the plan counts on refuelling during this hop


@dataclass
class Options:
    use_predicted: bool = True       # include ForgeLab-predicted neutron stars
    eta: float = 0.95                # ordinary-jump efficiency vs. max range
    reserve_jumps: float = 1.0       # after a boost keep fuel for this many full jumps
    predicted_penalty: float = 0.02  # tie-break toward reported/confirmed stars
    beam: int = 12                   # labels kept per jump layer
    candidates: int = 24             # successors kept per expansion
    gap_jumps: int = 12              # ordinary jumps a gap crossing may use
    time_limit: float = 30.0         # seconds


@dataclass
class Hop:
    """One leg of the plan, arriving at ``to``."""
    to: dict                         # {kind, index?, address?, position, flags?}
    jumps: int
    distance: float
    boosted: bool                    # departs supercharged from a neutron star
    refuel: int                      # NO_SCOOP / SCOOP_EN_ROUTE / SCOOP_REQUIRED
    fuel_after: float                # estimated main-tank fuel on arrival (t)


@dataclass
class Plan:
    hops: list
    jumps: int
    distance: float
    direct_jumps: int                # same trip without any neutron boost
    ship_range: float
    boost_range: float
    expansions: int
    elapsed: float
    complete: bool = True
    notes: list = field(default_factory=list)

    @property
    def boosts(self):
        return sum(1 for h in self.hops if h.boosted)


def ordinary_jumps(distance, reach):
    return max(1, math.ceil(distance / reach - 1e-9)) if distance > 1e-6 else 0


def reserve_fuel(ship, reserve_jumps):
    """Fuel the plan keeps in the tank after a boost (the same rule everywhere)."""
    return min(ship.fuel_capacity, reserve_jumps * ship.max_fuel_per_jump + 0.25)


class _Label:
    __slots__ = ("g", "pen", "node", "pos", "fuel", "boosted", "parent", "hop")

    def __init__(self, g, pen, node, pos, fuel, boosted, parent, hop):
        self.g, self.pen, self.node, self.pos, self.fuel = g, pen, node, pos, fuel
        self.boosted, self.parent, self.hop = boosted, parent, hop


class Planner:
    def __init__(self, pack: galaxy.NeutronPack):
        self.pack = pack

    def plan(self, start, goal, ship, fuel=None, options=None, start_is_neutron=False,
             cancel=None, progress=None, avoid=()):
        """Plan from ``start`` to ``goal`` (x, y, z in LY).

        ``ship``: ship.Ship. ``fuel``: current main-tank fuel (default full).
        ``start_is_neutron``: first jump is boosted (neutron primary or already
        supercharged). ``avoid``: pack indices never to use (e.g. a predicted
        star the player found missing).
        """
        o = options or Options()
        t0 = time.monotonic()
        capacity = ship.fuel_capacity
        fuel = capacity if fuel is None else max(0.0, min(float(fuel), capacity))
        R = ship.max_range(capacity)
        if R <= 0:
            raise PlanError("This ship cannot jump (no usable FSD range).")
        M = ship.neutron_multiplier
        B = R * M
        step = R * o.eta
        maxjump = ship.max_fuel_per_jump
        reserve = reserve_fuel(ship, o.reserve_jumps)
        refuelled = max(0.0, capacity - maxjump)
        skip = galaxy.FLAG_BLOCKED | galaxy.FLAG_UNNAMED
        if not o.use_predicted:
            skip |= galaxy.FLAG_PREDICTED
        avoid = set(avoid)
        pack = self.pack
        flags = pack.flags
        goal = tuple(goal)
        start = tuple(start)
        total = math.dist(start, goal)
        direct = ordinary_jumps(total, step)
        cell = B / 4.0

        scoop = ship.has_scoop
        step_fuel = ship.fuel_used(step, capacity)

        def burn(distance):
            """Fuel for ordinary jumps covering ``distance`` (last jump partial)."""
            n = ordinary_jumps(distance, step)
            return (n - 1) * step_fuel + ship.fuel_used(distance - (n - 1) * step, capacity) if n else 0.0

        def hop_cost(d, boosted, fuel_in):
            """(jumps, refuel, fuel_after) for a hop of length d, or None."""
            if not scoop:
                # No fuel scoop: every jump burns fuel and nothing refills it.
                if boosted:
                    rest = max(0.0, d - B)
                    used = ship.fuel_used(min(d, B), capacity, M) + burn(rest)
                    j = 1 + ordinary_jumps(rest, step)
                else:
                    used, j = burn(d), ordinary_jumps(d, step)
                left = fuel_in - used
                return (j, NO_SCOOP, left) if left >= 0.0 else None
            if not boosted:
                j = ordinary_jumps(d, step)
                return j, SCOOP_EN_ROUTE, refuelled
            if d <= B:
                used = ship.fuel_used(d, capacity, M)
                if fuel_in - used >= reserve:
                    return 1, NO_SCOOP, fuel_in - used
                return 2, SCOOP_REQUIRED, refuelled
            if fuel_in < maxjump:
                return None
            need = SCOOP_REQUIRED if fuel_in - maxjump < reserve else SCOOP_EN_ROUTE
            return 1 + ordinary_jumps(d - B, step), need, refuelled

        def rank(label):
            spare = (label.fuel - reserve) / max(1e-9, capacity - reserve)
            return math.dist(label.pos, goal) / B - 0.5 * max(0.0, min(1.0, spare)) + label.pen

        layers = {0: [_Label(0, 0.0, -1, start, fuel, bool(start_is_neutron), None, None)]}
        best_goal = None
        expansions = 0
        seen = {}   # (cell) -> best g reached there, per boosted state

        timed_out = False
        g_level = 0
        while layers and not timed_out:
            g_level = min(layers)
            if best_goal is not None and g_level >= best_goal.g:
                break
            labels = layers.pop(g_level)
            # Beam: one label per cell (best rank), then the best `beam`.
            by_cell = {}
            for lab in labels:
                if lab.node == -2:
                    if best_goal is None or (lab.g, lab.pen) < (best_goal.g, best_goal.pen):
                        best_goal = lab
                    continue
                key = (math.floor(lab.pos[0] / cell), math.floor(lab.pos[1] / cell),
                       math.floor(lab.pos[2] / cell), lab.boosted)
                prev = seen.get(key)
                if prev is not None and prev < lab.g:
                    continue
                cur = by_cell.get(key)
                if cur is None or rank(lab) < rank(cur):
                    by_cell[key] = lab
            if best_goal is not None and best_goal.g <= g_level:
                break
            kept = sorted(by_cell.values(), key=rank)[:o.beam]
            for lab in kept:
                key = (math.floor(lab.pos[0] / cell), math.floor(lab.pos[1] / cell),
                       math.floor(lab.pos[2] / cell), lab.boosted)
                seen[key] = min(seen.get(key, lab.g), lab.g)
            for lab in kept:
                if cancel is not None and cancel():
                    raise PlanError("Planning cancelled.")
                if time.monotonic() - t0 > o.time_limit:
                    timed_out = True
                    break
                expansions += 1
                self._expand(lab, goal, B, step, hop_cost, skip, avoid, flags, o, layers)
            if progress is not None and kept:
                progress(g_level, min(math.dist(k.pos, goal) for k in kept))

        elapsed = time.monotonic() - t0
        complete = not timed_out
        if timed_out:
            # Out of time: the best finished route already found still counts.
            for pending in layers.values():
                for lab in pending:
                    if lab.node == -2 and (best_goal is None or (lab.g, lab.pen) < (best_goal.g, best_goal.pen)):
                        best_goal = lab
        if best_goal is None:
            raise PlanError(f"No route found within the planning budget ({elapsed:.1f}s). "
                            "Try a nearer intermediate destination.")
        hops = []
        lab = best_goal
        while lab.parent is not None:
            hops.append(lab.hop)
            lab = lab.parent
        hops.reverse()
        jumps = sum(h.jumps for h in hops)
        distance = sum(h.distance for h in hops)
        plan = Plan(hops, jumps, distance, direct, R, B, expansions, elapsed, complete)
        if not complete:
            plan.notes.append("Planning time ran out; this is the best route found so far.")
        if jumps >= direct and scoop:
            plan = Plan([Hop({"kind": "destination", "position": goal}, direct, total,
                             bool(start_is_neutron), SCOOP_EN_ROUTE, refuelled)],
                        direct, total, direct, R, B, expansions, elapsed, True,
                        ["Neutron boosts do not shorten this trip."])
        return plan

    def _expand(self, lab, goal, B, step, hop_cost, skip, avoid, flags, o, layers):
        pack = self.pack
        p = lab.pos
        dist_goal = math.dist(p, goal)

        def push(new):
            layers.setdefault(new.g, []).append(new)

        # Straight to the destination.
        c = hop_cost(dist_goal, lab.boosted, lab.fuel)
        if c is not None:
            j, refuel, f_after = c
            push(_Label(lab.g + j, lab.pen, -2, goal, f_after, False, lab,
                        Hop({"kind": "destination", "position": goal}, j, dist_goal,
                            lab.boosted, refuel, f_after)))
        if lab.boosted:
            reach = B
        else:
            reach = min(3 * step, dist_goal)
        if dist_goal <= reach * 0.5:
            return
        # Forward cap first (nodes that make real progress), widening if sparse.
        found = pack.within(p, reach, skip, forward=(goal, -0.4 * reach))
        if len(found) < o.candidates:
            found = pack.within(p, reach, skip, forward=(goal, 0.1 * reach))
        best_progress = max((dist_goal - math.dist((x, y, z), goal) for _, x, y, z, _ in found), default=-1)
        if best_progress < 0.5 * reach and dist_goal > reach:
            far = min(reach + o.gap_jumps * step, dist_goal)
            found = pack.within(p, far, skip, forward=(goal, 0.1 * reach))
        succ = []
        for i, x, y, z, d in found:
            if i == lab.node or d < 1e-6 or i in avoid:
                continue
            q = (x, y, z)
            c = hop_cost(d, lab.boosted, lab.fuel)
            if c is None:
                continue
            j, refuel, f_after = c
            pen = o.predicted_penalty if (flags[i] & (galaxy.FLAG_PREDICTED | galaxy.FLAG_CONFIRMED)) == galaxy.FLAG_PREDICTED else 0.0
            g = lab.g + j
            # Rank successors by estimated total jumps.
            succ.append((g + pen + math.dist(q, goal) / B, g, pen, i, q, d, j, refuel, f_after))
        succ.sort()
        for est, g, pen, i, q, d, j, refuel, f_after in succ[:o.candidates]:
            push(_Label(g, lab.pen + pen, i, q, f_after, True, lab,
                        Hop({"kind": "neutron", "index": i, "address": int(pack.addr[i]),
                             "position": q, "flags": int(flags[i])}, j, d, lab.boosted, refuel, f_after)))
