"""ForgeLab Navigator tests (standard library unittest).

    python -m unittest discover -s tests -v

Synthetic packs test the engine exactly; the real pack (if present) is used
for integration checks.
"""
from __future__ import annotations

import json
import math
import random
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin" / "ForgeLabNavigator"
sys.path.insert(0, str(PLUGIN))

from forgelab_nav import galaxy, names, route, router, session, stars  # noqa: E402
from forgelab_nav.ship import Ship  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
REAL_PACK = PLUGIN / "data" / "neutrons.flnav"
LOADOUT = json.loads((FIXTURES / "loadout-caspian.json").read_text())


_OPEN = []


def tearDownModule():
    for item in _OPEN:
        item.close()


def make_pack(points, flags=None, addresses=None, coarse=1000.0, sub=4):
    """Build a pack file from (x, y, z) points (mirrors tools/build_datapack.py)."""
    import array
    n = len(points)
    flags = flags or [0] * n
    addresses = addresses or [1000 + i for i in range(n)]
    lo = [math.floor(min(p[k] for p in points) / coarse) * coarse - coarse for k in range(3)]
    hi = [math.ceil(max(p[k] for p in points) / coarse) * coarse + coarse for k in range(3)]
    dims = [int((h - l) / coarse) for l, h in zip(lo, hi)]
    fine_size = coarse / sub

    def keys(p):
        f = [math.floor((v - l) / fine_size) for v, l in zip(p, lo)]
        c = [v // sub for v in f]
        s = [v - cc * sub for v, cc in zip(f, c)]
        return (c[0] * dims[1] + c[1]) * dims[2] + c[2], (s[0] * sub + s[1]) * sub + s[2]

    order = sorted(range(n), key=lambda i: (*keys([float(array.array("f", [v])[0]) for v in points[i]]),
                                            addresses[i]))
    pos32 = array.array("f", [v for i in order for v in points[i]])
    sorted_keys = [keys(pos32[3 * k:3 * k + 3]) for k in range(n)]
    blocks = sorted({c for c, _ in sorted_keys})
    coarse_table = array.array("I", [galaxy.EMPTY] * (dims[0] * dims[1] * dims[2]))
    for b, c in enumerate(blocks):
        coarse_table[c] = b
    block_len = sub ** 3 + 1
    fine = array.array("I")
    for c in blocks:
        idx = [k for k, (cc, _) in enumerate(sorted_keys) if cc == c]
        start = idx[0]
        subs = [sorted_keys[k][1] for k in idx]
        for s in range(block_len):
            fine.append(start + sum(1 for x in subs if x < s))
    header = {"format": "test", "corpus_id": "test", "count": n,
              "grid": {"origin": lo, "coarse": coarse, "sub": sub, "dims": dims}}
    path = Path(tempfile.mkdtemp()) / "test.flnav"
    galaxy.write_pack(path, header, coarse_table.tobytes(), fine.tobytes(), pos32.tobytes(),
                      array.array("Q", [addresses[i] for i in order]).tobytes(),
                      bytes(flags[i] for i in order))
    pack = galaxy.NeutronPack(path)
    _OPEN.append(pack)
    return pack


def ship(**changes):
    s = Ship.from_loadout(LOADOUT)
    from dataclasses import replace
    return replace(s, **changes) if changes else s


class PackTests(unittest.TestCase):
    def test_sphere_query_matches_brute_force(self):
        rng = random.Random(7)
        pts = [(rng.uniform(-3000, 3000), rng.uniform(-500, 500), rng.uniform(-3000, 3000)) for _ in range(3000)]
        pack = make_pack(pts)
        for _ in range(40):
            c = (rng.uniform(-3000, 3000), rng.uniform(-500, 500), rng.uniform(-3000, 3000))
            r = rng.uniform(50, 900)
            got = sorted(int(pack.addr[i]) for i, *_ in pack.within(c, r, skip_flags=0))
            want = sorted(1000 + i for i, p in enumerate(pts)
                          if math.dist(p, c) <= r + 1e-3 and math.dist(p, c) <= r)
            # float32 storage: allow boundary disagreements only within 1e-3 LY of r
            boundary = {1000 + i for i, p in enumerate(pts) if abs(math.dist(p, c) - r) < 1e-2}
            self.assertEqual(set(got) - boundary, set(want) - boundary)

    def test_flags_filter(self):
        pts = [(0, 0, 0), (10, 0, 0), (20, 0, 0)]
        pack = make_pack(pts, flags=[0, galaxy.FLAG_BLOCKED, galaxy.FLAG_PREDICTED])
        got = {int(pack.addr[i]) for i, *_ in pack.within((0, 0, 0), 50)}
        self.assertEqual(got, {1000, 1002})
        got = {int(pack.addr[i]) for i, *_ in pack.within((0, 0, 0), 50, galaxy.FLAG_BLOCKED | galaxy.FLAG_PREDICTED)}
        self.assertEqual(got, {1000})

    def test_locate(self):
        pack = make_pack([(5, 5, 5), (600, 0, 0)])
        self.assertIsNotNone(pack.locate(1001, (600, 0, 0)))
        self.assertIsNone(pack.locate(1001, (5, 5, 5)))


class ShipTests(unittest.TestCase):
    def test_fuel_model_matches_real_journal_jumps(self):
        """191 real FSDJumps (normal, x6 neutron, FSD injection) with this exact loadout."""
        jumps = json.loads((FIXTURES / "caspian-jumps.json").read_text())
        s = ship()
        worst = 0.0
        for j in jumps:
            mult = j["boost"] if j["boost"] > 1 else j["injection"]
            pred = s.with_cargo(j["cargo"]).fuel_used(j["jump_dist"], j["fuel_level"] + j["fuel_used"], mult)
            worst = max(worst, abs(pred - j["fuel_used"]))
        self.assertGreater(len(jumps), 100)
        self.assertLess(worst, 0.001)

    def test_caspian_boost(self):
        s = ship()
        self.assertEqual(s.neutron_multiplier, 6.0)
        self.assertAlmostEqual(s.max_range(s.fuel_capacity), 77.24, places=1)


class RouterTests(unittest.TestCase):
    def line_pack(self, spacing, count, flags=None):
        pts = [(i * spacing, 0.0, 0.0) for i in range(1, count + 1)]
        return make_pack(pts, flags=flags)

    def test_boost_chain_uses_one_jump_per_neutron(self):
        s = ship()
        B = s.max_range(s.fuel_capacity) * 6
        pack = self.line_pack(B * 0.9, 12)
        plan = router.Planner(pack).plan((0, 0, 0), (B * 0.9 * 12 + 50, 0, 0), s)
        # first hop is ordinary (start is not a neutron), then 1 jump per boost
        self.assertEqual([h.jumps for h in plan.hops[1:-1]], [1] * (len(plan.hops) - 2))
        self.assertLess(plan.jumps, plan.direct_jumps / 3)

    def test_fuel_reserve_forces_refuel_hops(self):
        s = ship(fuel_capacity=16.0)   # 16 t tank: two full boosts, then refuel
        B = s.max_range(s.fuel_capacity) * 6
        pack = self.line_pack(B * 0.95, 10)
        plan = router.Planner(pack).plan((0, 0, 0), (B * 0.95 * 10, 0, 0), s, start_is_neutron=False)
        self.assertTrue(any(h.refuel == router.SCOOP_REQUIRED for h in plan.hops))
        fuel = s.fuel_capacity
        for h in plan.hops:
            if h.boosted and h.refuel == router.NO_SCOOP:
                fuel -= s.fuel_used(h.distance, s.fuel_capacity, 6)
                self.assertGreaterEqual(fuel, s.max_fuel_per_jump - 1e-6)
            else:
                fuel = s.fuel_capacity - s.max_fuel_per_jump

    def test_no_scoop_ship_never_assumes_refuel(self):
        s = ship(scoop_rate=0.0)
        B = s.max_range(s.fuel_capacity) * 6
        pack = self.line_pack(B * 0.9, 40)
        with self.assertRaises(router.PlanError):
            router.Planner(pack).plan((0, 0, 0), (B * 0.9 * 40, 0, 0), s, fuel=20.0)
        plan = router.Planner(pack).plan((0, 0, 0), (B * 0.9 * 3, 0, 0), s, fuel=s.fuel_capacity)
        self.assertTrue(all(h.refuel == router.NO_SCOOP for h in plan.hops))
        self.assertGreaterEqual(plan.hops[-1].fuel_after, 0.0)

    def test_reported_only_excludes_predictions(self):
        s = ship()
        B = s.max_range(s.fuel_capacity) * 6
        pack = self.line_pack(B * 0.9, 8, flags=[galaxy.FLAG_PREDICTED] * 8)
        with_pred = router.Planner(pack).plan((0, 0, 0), (B * 0.9 * 8, 0, 0), s)
        without = router.Planner(pack).plan((0, 0, 0), (B * 0.9 * 8, 0, 0), s,
                                            options=router.Options(use_predicted=False))
        self.assertLess(with_pred.jumps, without.jumps)
        self.assertTrue(all(h.to["kind"] == "destination" for h in without.hops))

    def test_avoid_list_routes_around_missing_star(self):
        s = ship()
        B = s.max_range(s.fuel_capacity) * 6
        pack = self.line_pack(B * 0.5, 10)
        first = router.Planner(pack).plan((0, 0, 0), (B * 5, 0, 0), s)
        used = {h.to["index"] for h in first.hops if h.to["kind"] == "neutron"}
        bad = sorted(used)[1]
        second = router.Planner(pack).plan((0, 0, 0), (B * 5, 0, 0), s, avoid={bad})
        self.assertNotIn(bad, {h.to.get("index") for h in second.hops})

    def test_gap_crossing(self):
        s = ship()
        R = s.max_range(s.fuel_capacity)
        B = R * 6
        pts = [(B * 0.9 * i, 0, 0) for i in range(1, 4)] + [(B * 0.9 * 3 + B + 4 * R + B * 0.9 * i, 0, 0)
                                                            for i in range(0, 3)]
        pack = make_pack(pts)
        plan = router.Planner(pack).plan((0, 0, 0), (pts[-1][0] + 100, 0, 0), s)
        gap = [h for h in plan.hops if h.distance > B]
        self.assertTrue(gap, "expected a gap-crossing hop")
        self.assertTrue(all(h.jumps >= 2 for h in gap))


@unittest.skipUnless(REAL_PACK.exists(), "real neutron pack not built")
class RealDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = galaxy.NeutronPack(REAL_PACK)
        _OPEN.append(cls.pack)
        cls.stars = stars.Stars()

    def test_sol_is_resolved_offline(self):
        sol = self.stars.by_name("Sol")
        self.assertEqual(sol.address, 10477373803)
        self.assertEqual(sol.position, (0.0, 0.0, 0.0))
        self.assertEqual(sol.star_class, "G")

    def test_names_round_trip_on_pack_sample(self):
        rng = random.Random(3)
        for _ in range(300):
            i = rng.randrange(self.pack.count)
            name = route.neutron_name(self.pack, i)
            self.assertEqual(names.address_from_name(name), int(self.pack.addr[i]), name)

    def test_long_route_is_fast_and_verified(self):
        s = ship()
        a, b = self.stars.by_name("Sol"), self.stars.by_name("Colonia")
        t = time.perf_counter()
        plan = router.Planner(self.pack).plan(a.position, b.position, s)
        self.assertLess(time.perf_counter() - t, 10.0)
        r = route.build(plan, self.pack, self.stars, {"name": a.name, "address": a.address, "position": a.position},
                        {"name": b.name, "address": b.address, "position": b.position}, s, True)
        self.assertEqual(route.verify(r, s), [])
        self.assertLess(r.total_jumps, 70)
        self.assertGreater(r.direct_jumps, 250)


class FakeHost(session.Host):
    def __init__(self, journal_dir=None):
        self.clipboard = []
        self.overlays = []
        self._jd = journal_dir

    def copy(self, text):
        self.clipboard.append(text)

    def overlay(self, lines):
        self.overlays.append(lines)

    def journal_dir(self):
        return self._jd


@unittest.skipUnless(REAL_PACK.exists(), "real neutron pack not built")
class SessionTests(unittest.TestCase):
    START = {"event": "Location", "StarSystem": "Aucownst BL-R c7-0", "SystemAddress": 72712361026,
             "StarPos": [-6661.375, -140.8125, 1818.8125], "Docked": False, "timestamp": "2026-09-30T05:00:00Z"}

    def make(self):
        host = FakeHost(Path(tempfile.mkdtemp()))
        nav = session.Navigator(host, tempfile.mkdtemp(), REAL_PACK)
        _OPEN.append(nav)
        nav.on_journal(LOADOUT)
        nav.on_journal(self.START)
        return host, nav

    def plan(self, nav, dest="Swoilt NO-I d9-0"):
        self.assertIsNone(nav.plot(dest))
        end = time.time() + 60
        while nav.planning and time.time() < end:
            time.sleep(0.05)
        self.assertIsNotNone(nav.route)

    def jump(self, nav, name, address, position, star_class="K"):
        nav.on_journal({"event": "StartJump", "JumpType": "Hyperspace", "SystemAddress": address,
                        "StarClass": star_class})
        nav.on_journal({"event": "FSDJump", "StarSystem": name, "SystemAddress": address,
                        "StarPos": list(position), "FuelLevel": 100.0, "timestamp": "2026-09-30T05:01:00Z"})

    def test_plot_copies_first_waypoint_and_advances(self):
        host, nav = self.make()
        self.plan(nav)
        self.assertEqual(host.clipboard[-1], nav.route.waypoints[0].name)
        w0 = nav.route.waypoints[0]
        self.jump(nav, w0.name, w0.address, w0.position, "N")
        self.assertEqual(nav.route.next_index, 1)
        self.assertEqual(host.clipboard[-1], nav.route.waypoints[1].name)
        self.assertIn("supercharge", nav.tip.text.lower())

    def test_skip_ahead_when_player_passes_waypoints(self):
        host, nav = self.make()
        self.plan(nav)
        w2 = nav.route.waypoints[2]
        # Arrive at an ordinary system right next to waypoint 3 (index 2).
        near = (w2.position[0] + 5, w2.position[1], w2.position[2])
        self.jump(nav, "Somewhere", 123, near)
        self.assertGreaterEqual(nav.route.next_index, 2)

    def test_leaving_route_triggers_replan(self):
        host, nav = self.make()
        self.plan(nav)
        first = nav.route.route_id
        self.jump(nav, "Far away", 124, (-6661.375 - 900, -140.8125, 1818.8125 - 900))
        end = time.time() + 60
        while (nav.planning or nav.route.route_id == first) and time.time() < end:
            time.sleep(0.05)
        self.assertNotEqual(nav.route.route_id, first)
        self.assertEqual(tuple(nav.route.start["position"]), (-6661.375 - 900, -140.8125, 1818.8125 - 900))

    def test_wrong_prediction_is_avoided_and_logged(self):
        host, nav = self.make()
        self.plan(nav)
        w0 = nav.route.waypoints[0]
        self.jump(nav, w0.name, w0.address, w0.position, "K")   # game says K, not N
        self.assertEqual(nav.field["contradicted"], 1)
        idx = nav.pack.locate(w0.address, w0.position)
        self.assertIn(idx, nav.avoid)
        log = (nav.state_dir / "field-checks.jsonl").read_text().splitlines()
        self.assertEqual(json.loads(log[-1])["kind"], "contradicted")

    def test_chat_commands(self):
        host, nav = self.make()
        nav.on_journal({"event": "SendText", "To": "local", "Message": "!nav to Swoilt NO-I d9-0"})
        end = time.time() + 60
        while nav.planning and time.time() < end:
            time.sleep(0.05)
        self.assertIsNotNone(nav.route)
        nav.on_journal({"event": "SendText", "To": "local", "Message": "!nav next"})
        self.assertEqual(nav.route.next_index, 1)
        nav.on_journal({"event": "SendText", "To": "local", "Message": "!nav clear"})
        self.assertIsNone(nav.route)

    def test_state_survives_restart(self):
        host, nav = self.make()
        self.plan(nav)
        nav.step(1)
        again = session.Navigator(FakeHost(), nav.state_dir, REAL_PACK)
        _OPEN.append(again)
        self.assertEqual(again.route.next_index, 1)
        self.assertEqual(again.route.destination["name"], "Swoilt NO-I d9-0")

    def test_unknown_destination_message(self):
        host, nav = self.make()
        msg = nav.plot("Definitely Not A System")
        self.assertIn("Unknown system", msg)

    def test_autocomplete(self):
        self.assertIn("Colonia", session.suggest("Colon"))
        self.assertEqual(session.suggest("x"), [])


class ClipHost(FakeHost):
    """FakeHost whose clipboard can be changed 'by another program'."""

    def __init__(self, journal_dir=None):
        super().__init__(journal_dir)
        self.foreign = None

    def copy(self, text):
        super().copy(text)
        self.foreign = None

    def clipboard_text(self):
        if self.foreign is not None:
            return self.foreign
        return self.clipboard[-1] if self.clipboard else ""


def wait_until(predicate, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            settle()
            return True
        time.sleep(0.05)
    return False


def settle():
    """Let planning threads finish handing their results back."""
    import threading
    for t in threading.enumerate():
        if t.name == "forgelab-plan":
            t.join(60)


@unittest.skipUnless(REAL_PACK.exists(), "real neutron pack not built")
class GuidanceTests(unittest.TestCase):
    """1.1: overlay, scoped tips, offers, clipboard rules, evidence and fuel guidance."""
    START = SessionTests.START
    HERE = tuple(START["StarPos"])

    def make(self, host=None):
        host = host or ClipHost(Path(tempfile.mkdtemp()))
        nav = session.Navigator(host, tempfile.mkdtemp(), REAL_PACK)
        _OPEN.append(nav)
        nav.on_journal(LOADOUT)
        nav.on_journal(self.START)
        return host, nav

    def plan(self, nav, dest="Swoilt NO-I d9-0"):
        self.assertIsNone(nav.plot(dest))
        self.assertTrue(wait_until(lambda: not nav.planning))
        self.assertIsNotNone(nav.route)

    # ---------------------------------------------------------------- overlay
    def test_overlay_baseline_wording(self):
        host, nav = self.make()
        self.plan(nav)
        lines = nav.overlay_lines()
        self.assertEqual(lines[0], (f"Next: {nav.route.next.name}", "target"))
        n = nav.route.jumps_left
        self.assertTrue(lines[1][0].endswith(f"~{n} jumps left"), lines[1])
        self.assertEqual(session.jumps_text(1), "~1 jump")
        self.assertTrue(all(len(text) <= 70 for text, _ in lines), lines)

    def test_overlay_resent_only_on_change(self):
        host, nav = self.make()
        self.plan(nav)
        before = len(host.overlays)
        nav.push_overlay()
        nav.push_overlay()
        self.assertEqual(len(host.overlays), before)
        nav.push_overlay(keepalive=True)
        self.assertEqual(len(host.overlays), before + 1)

    def test_hide_clears_at_once_and_stays_hidden(self):
        host, nav = self.make()
        self.plan(nav)
        self.assertIsNotNone(host.overlays[-1])
        nav.on_journal({"event": "SendText", "Message": "!nav hide"})
        self.assertIsNone(host.overlays[-1])
        w0 = nav.route.waypoints[0]
        SessionTests.jump(self, nav, w0.name, w0.address, w0.position, "N")
        nav.push_overlay(keepalive=True)
        self.assertIsNone(host.overlays[-1])
        nav.on_journal({"event": "SendText", "Message": "!nav show"})
        self.assertEqual(host.overlays[-1][0][0], f"Next: {nav.route.next.name}")

    def test_arrival_moment_then_clear(self):
        host, nav = self.make()
        self.plan(nav)
        for w in nav.route.waypoints:
            SessionTests.jump(self, nav, w.name, w.address, w.position, "N" if w.kind == "neutron" else "K")
        self.assertTrue(nav.route.done)
        self.assertEqual(host.overlays[-1][0][0], f"Arrived: {nav.route.destination['name']}")
        self.assertIn(f"{len(nav.route.waypoints)} jumps flown", host.overlays[-1][1][0])
        nav.completed["at"] -= session.ARRIVAL_SECONDS + 1
        nav.push_overlay()
        self.assertIsNone(host.overlays[-1])

    # ---------------------------------------------------------------- tips
    def test_tip_belongs_to_its_moment(self):
        host, nav = self.make()
        self.plan(nav)
        self.assertIn("Route ready", nav.snapshot()["tip"]["text"])
        w0 = nav.route.waypoints[0]
        step = [a + (b - a) * 0.2 for a, b in zip(self.HERE, w0.position)]
        SessionTests.jump(self, nav, "Ordinary star", 555, step)
        self.assertEqual(nav.route.next_index, 0)
        self.assertIsNone(nav.snapshot()["tip"])

    def test_chat_errors_reach_the_overlay_without_a_route(self):
        host, nav = self.make()
        nav.on_journal({"event": "SendText", "Message": "!nav to Definitely Not A System"})
        self.assertEqual(host.overlays[-1][0][1], "bad")
        self.assertIn("Unknown system", host.overlays[-1][0][0])

    # ---------------------------------------------------------------- offers
    def plotted(self, nav, n=23):
        dest = nav.stars.by_name("Swoilt NO-I d9-0")
        stops = [{"StarSystem": "Aucownst BL-R c7-0", "SystemAddress": 72712361026,
                  "StarPos": list(self.HERE), "StarClass": "K"}]
        for i in range(1, n):
            p = [a + (b - a) * i / n for a, b in zip(self.HERE, dest.position)]
            stops.append({"StarSystem": f"Filler {i}", "SystemAddress": 900000000 + i, "StarPos": p,
                          "StarClass": "M"})
        stops.append({"StarSystem": dest.name, "SystemAddress": dest.address, "StarPos": list(dest.position),
                      "StarClass": dest.star_class})
        return stops

    def test_offer_reaches_the_game_and_is_accepted_by_chat(self):
        host, nav = self.make()
        nav.on_journal({"event": "NavRoute", "Route": self.plotted(nav)})
        self.assertTrue(wait_until(lambda: nav.offer is not None))
        nav.push_overlay()
        self.assertIn("!nav yes", host.overlays[-1][-1][0])
        nav.on_journal({"event": "SendText", "Message": "!nav yes"})
        self.assertIsNotNone(nav.route)
        self.assertIsNone(nav.offer)
        self.assertEqual(host.clipboard[-1], nav.route.waypoints[0].name)

    def test_stale_offers_are_dropped(self):
        host, nav = self.make()
        stops = self.plotted(nav)
        nav.on_journal({"event": "NavRoute", "Route": stops})
        self.assertTrue(wait_until(lambda: nav.offer is not None))
        nav.on_journal({"event": "NavRouteClear"})
        self.assertIsNone(nav.offer)
        nav.on_journal({"event": "NavRoute", "Route": stops})
        self.assertTrue(wait_until(lambda: nav.offer is not None))
        nav.on_journal({"event": "NavRoute", "Route": stops[:3]})    # a short new plot replaces it
        time.sleep(0.2)
        self.assertIsNone(nav.offer)

    # ---------------------------------------------------------------- clipboard
    def test_automatic_copies_never_overwrite_the_players_clipboard(self):
        host, nav = self.make()
        self.plan(nav)
        name = nav.route.next.name
        count = len(host.clipboard)
        nav.on_status({"GuiFocus": 6})                 # already on the clipboard: no rewrite
        self.assertEqual(len(host.clipboard), count)
        nav.on_status({"GuiFocus": 0})
        host.foreign = "something the player copied"
        nav.on_status({"GuiFocus": 6})                 # player copied something since: leave it
        self.assertEqual(len(host.clipboard), count)
        self.assertEqual(nav.copy_kept, name)
        nav.copy_next()                                # an explicit request always copies
        self.assertEqual(host.clipboard[-1], name)
        self.assertIsNone(nav.copy_kept)

    def test_supercharge_does_not_copy_twice(self):
        host, nav = self.make()
        self.plan(nav)
        w0 = nav.route.waypoints[0]
        SessionTests.jump(self, nav, w0.name, w0.address, w0.position, "N")
        count = len(host.clipboard)
        nav.on_journal({"event": "JetConeBoost", "BoostValue": 6.0})
        self.assertEqual(len(host.clipboard), count)
        self.assertIn("Supercharged", nav.snapshot()["tip"]["text"])

    def test_replan_tip_only_claims_a_copy_that_happened(self):
        host, nav = self.make()
        self.plan(nav)
        nav.settings.auto_copy = False
        first = nav.route.route_id
        nav.replan()
        self.assertTrue(wait_until(lambda: not nav.planning and nav.route.route_id != first))
        self.assertNotIn("copied", nav.snapshot()["tip"]["text"].replace("Copy the", ""))

    # ---------------------------------------------------------------- galaxy-map leg check
    def test_leg_check_uses_the_planners_reserve(self):
        host, nav = self.make()
        s = nav.ship
        far = (self.HERE[0] + 50.0, self.HERE[1], self.HERE[2])
        used = s.fuel_used(50.0, s.fuel_capacity)
        nav.fuel = used + (router.reserve_fuel(s, 1.0) + 0.5 * s.max_fuel_per_jump) / 2   # between old and new
        nav.star_class = "T"
        leg = nav._leg_check([{"StarSystem": "Here", "SystemAddress": 1, "StarPos": list(self.HERE), "StarClass": "T"},
                              {"StarSystem": "There", "SystemAddress": 2, "StarPos": list(far), "StarClass": "T"}])
        self.assertIsNotNone(leg["warning"])
        self.assertTrue(leg["short"])

    # ---------------------------------------------------------------- evidence
    def synthetic(self, nav, legs):
        """Route along +x from here: legs = [(kind, distance, boosted, scoop)]."""
        x = self.HERE[0]
        wps = []
        for i, (kind, d, boosted, scoop) in enumerate(legs):
            x += d
            wps.append(route.Waypoint(f"WP {i}", 7000 + i, (x, self.HERE[1], self.HERE[2]), kind,
                                      max(1, math.ceil(d / 400)), d, boosted, evidence="reported",
                                      star_class="K" if kind == route.SCOOP else "N", scoop=scoop))
        dest = {"name": wps[-1].name, "address": wps[-1].address, "position": wps[-1].position, "star_class": "N"}
        r = route.Route(wps, dict(nav.system), dest, {"name": "t", "range": 77.0, "boost_range": 460.0,
                                                    "multiplier": 6.0, "tank": 128.0, "scoop": True}, 100, True)
        nav.route = r
        return r

    def test_refuel_star_evidence_is_labelled_and_upgraded(self):
        host, nav = self.make()
        r = self.synthetic(nav, [("neutron", 400, False, router.SCOOP_EN_ROUTE),
                                 ("scoop", 400, True, router.SCOOP_REQUIRED),
                                 ("neutron", 60, False, router.NO_SCOOP)])
        stop = r.waypoints[1]
        self.assertEqual(nav.evidence(stop), "generated")
        nav._see(stop.address, "K")
        self.assertEqual(nav.evidence(stop), "class confirmed")
        nav._see(stop.address, "TTS")
        self.assertEqual(nav.evidence(stop), "class contradicted")
        self.assertIn("not scoopable", nav.current_tip().text)

    # ---------------------------------------------------------------- fuel
    def test_top_up_cue_when_the_plan_counts_on_it(self):
        host, nav = self.make()
        found = None
        for n in range(4, 40):
            r = self.synthetic(nav, [("neutron", 300, False, router.SCOOP_EN_ROUTE)] +
                               [("neutron", 440, True, router.NO_SCOOP)] * n)
            literal = route.walk_fuel(r, nav.ship, nav.ship.fuel_capacity, self.HERE, False, topup=False)
            if literal.dry_at is not None:
                found = n
                break
        self.assertIsNotNone(found, "no chain long enough to need a top-up")
        nav.fuel = nav.ship.fuel_capacity
        nav.star_class = "M"
        advice = nav.fuel_advice()
        self.assertTrue(advice["short"].startswith("Top up on the way"), advice)
        self.assertGreater(advice["arrive"], 0)
        self.assertTrue(nav.overlay_lines()[1][0].startswith("Top up on the way"))
        r = self.synthetic(nav, [("neutron", 300, False, router.SCOOP_EN_ROUTE)] +
                           [("neutron", 440, True, router.NO_SCOOP)] * 3)
        self.assertIsNone(nav.fuel_advice())          # a short chain needs no top-up: stay quiet

    def test_scoop_stop_gives_a_fuel_target(self):
        host, nav = self.make()
        r = self.synthetic(nav, [("scoop", 1, False, router.SCOOP_REQUIRED)] +
                           [("neutron", 440, True, router.NO_SCOOP)] * 6)
        nav.system = {"name": "WP 0", "address": r.waypoints[0].address, "position": r.waypoints[0].position}
        r.next_index = 1
        nav.star_class = "K"
        nav.fuel = 10.0
        advice = nav.fuel_advice()
        self.assertEqual(advice["level"], "warn")
        self.assertTrue(10 < advice["target"] < nav.ship.fuel_capacity, advice)
        nav.fuel = float(advice["target"])
        self.assertEqual(nav.fuel_advice()["level"], "good")

    def test_unscoopable_refuel_star_replans_on_arrival(self):
        host, nav = self.make()
        r = self.synthetic(nav, [("scoop", 300, False, router.SCOOP_REQUIRED)] +
                           [("neutron", 440, True, router.NO_SCOOP)] * 3)
        stop = r.waypoints[0]
        nav.fuel = 20.0
        nav.settings.auto_replan = False
        nav.on_journal({"event": "StartJump", "JumpType": "Hyperspace", "SystemAddress": stop.address,
                        "StarClass": "Y"})
        nav.on_journal({"event": "FSDJump", "StarSystem": stop.name, "SystemAddress": stop.address,
                        "StarPos": list(stop.position), "FuelLevel": 20.0, "timestamp": "2026-09-30T05:01:00Z"})
        self.assertEqual(nav.evidence(stop), "class contradicted")
        self.assertEqual(nav.fuel_advice()["short"], "Refuel star not scoopable")
        self.assertIn("not scoopable", nav.current_tip().text)
        self.assertIn("Press Replan", nav.current_tip().text)

    def test_too_little_fuel_replans_on_arrival(self):
        host, nav = self.make()
        self.plan(nav)
        first = nav.route.route_id
        w0 = nav.route.waypoints[0]
        nav.on_journal({"event": "StartJump", "JumpType": "Hyperspace", "SystemAddress": w0.address,
                        "StarClass": "N"})
        nav.on_journal({"event": "FSDJump", "StarSystem": w0.name, "SystemAddress": w0.address,
                        "StarPos": list(w0.position), "FuelLevel": 0.3, "timestamp": "2026-09-30T05:01:00Z"})
        self.assertEqual(nav.fuel_advice()["level"], "bad")
        self.assertIn("Replanning", nav.tip.text)
        self.assertTrue(wait_until(lambda: not nav.planning))
        self.assertNotEqual(nav.route.route_id, first)


@unittest.skipUnless(REAL_PACK.exists(), "real neutron pack not built")
class ObedientPlayerTests(unittest.TestCase):
    """Regression for the 1.0 fuel gap: a player who only scoops when the Navigator
    says so (named refuel stops, 'top up on the way', 'scoop here') never runs dry."""

    TRIPS = [("loadout-caspian.json", "Blaa Eohn CB-U d4-28", "Prai Hypue NU-I b29-0"),
             ("loadout-caspian.json", "Sol", "Colonia"),
             ("loadout-4x-small-tank.json", "Sol", "Colonia")]

    def fly(self, loadout, a, b):
        host = FakeHost()
        nav = session.Navigator(host, tempfile.mkdtemp(), REAL_PACK)
        _OPEN.append(nav)
        nav.on_journal(json.loads((FIXTURES / loadout).read_text()))
        ship = nav.ship
        s, d = nav.stars.by_name(a), nav.stars.by_name(b)
        nav.on_journal({"event": "Location", "StarSystem": s.name, "SystemAddress": s.address,
                        "StarPos": list(s.position)})
        nav.fuel = ship.fuel_capacity
        self.assertIsNone(nav.plot(b))
        self.assertTrue(wait_until(lambda: not nav.planning))
        r = nav.route
        R = ship.max_range(ship.fuel_capacity)
        eta = router.Options().eta
        fuel, cues, lowest = ship.fuel_capacity, 0, ship.fuel_capacity
        while not r.done:
            nav.fuel = fuel
            nav._advice_cache = (None, None)
            advice = nav.fuel_advice()
            self.assertFalse(advice and advice["level"] == "bad", (a, b, r.next_index, advice))
            topup = None
            if advice and advice["level"] == "warn":
                cues += 1
                if "target" in advice:
                    fuel = max(fuel, float(advice["target"]))       # scoop to the target, no more
                else:
                    topup = advice["arrive"]                        # top up on the way
            w = r.next
            here = nav.system["position"]
            boosted = w.boosted and nav.star_class == "N"
            legs = route.hop_legs(math.dist(here, w.position), boosted, R, ship.neutron_multiplier, eta)
            for n, (dist, mult) in enumerate(legs):
                if topup is not None and n == len(legs) - 1 and mult == 1.0:
                    fuel = ship.fuel_capacity                       # scoop at the last star before it
                used = ship.fuel_used(dist, max(fuel, 1e-6), mult)
                self.assertLessEqual(used, min(fuel, ship.max_fuel_per_jump) + 1e-6,
                                     f"{a} -> {b}: ran dry on the way to waypoint {r.next_index}")
                fuel -= used
                lowest = min(lowest, fuel)
            if topup is not None:
                self.assertGreaterEqual(fuel + 1e-6, topup, f"{a} -> {b}: top-up target not reachable")
            nav.system = {"name": w.name, "address": w.address, "position": w.position}
            nav.star_class = "N" if w.kind == route.NEUTRON else (w.star_class or "K")
            r.next_index += 1
        return cues, lowest, r.total_jumps

    def test_following_the_navigator_never_runs_dry(self):
        for loadout, a, b in self.TRIPS:
            with self.subTest(trip=f"{a} -> {b}", ship=loadout):
                cues, lowest, jumps = self.fly(loadout, a, b)
                print(f"\n  {loadout}: {a} -> {b}: {jumps} jumps, {cues} fuel cues, lowest tank {lowest:.1f} t",
                      end="")
                self.assertGreaterEqual(lowest, 0.0)


CASPIAN = dict(LOADOUT, ShipID=30)      # public fixtures carry no ShipID


def other_ship_loadout(ship_id=7):
    """A different ship than CASPIAN (Beluga, own ShipID) built from the same modules."""
    return dict(LOADOUT, Ship="BelugaLiner", ShipID=ship_id, UnladenMass=LOADOUT["UnladenMass"] + 500)


def edmc_state(loadout):
    """EDMC monitor.state as it looks after a Loadout event."""
    return {"ShipID": loadout["ShipID"], "ShipType": loadout["Ship"].lower(),
            "UnladenMass": loadout["UnladenMass"], "FuelCapacity": dict(loadout["FuelCapacity"]),
            "Modules": {m["Slot"]: dict(m) for m in loadout["Modules"]}}


def write_journal(directory, name, *entries):
    (directory / name).write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")


class ShipSelectionTests(unittest.TestCase):
    """Reddit report 2026-10-01: Caspian in EDMC, Beluga Liner in the panel."""

    def test_journal_files_order_by_time_across_name_formats(self):
        d = Path(tempfile.mkdtemp())
        for name in ("Journal.2026-09-30T010000.01.log", "Journal.211105120000.01.log",
                     "Journal.211105120000.02.log", "Journal.2026-09-30T010000.02.log",
                     "Journal.171231235959.01.log", "Journal.2026-10-01T090000.01.log"):
            (d / name).write_text("", encoding="utf-8")
        self.assertEqual([p.name for p in session.journal_files(d)],
                         ["Journal.171231235959.01.log", "Journal.211105120000.01.log",
                          "Journal.211105120000.02.log", "Journal.2026-09-30T010000.01.log",
                          "Journal.2026-09-30T010000.02.log", "Journal.2026-10-01T090000.01.log"])

    def test_ship_names_use_journal_symbols(self):
        self.assertEqual(Ship.from_loadout(other_ship_loadout()).name, "Beluga Liner")
        self.assertEqual(Ship.from_loadout(CASPIAN).name, "Caspian Explorer")

    def test_loadout_from_state(self):
        built = session.loadout_from_state(edmc_state(CASPIAN))
        from dataclasses import replace
        self.assertEqual(Ship.from_loadout(built), replace(Ship.from_loadout(CASPIAN), source_timestamp=""))
        self.assertIsNone(session.loadout_from_state({"ShipID": 30, "ShipType": "explorer_nx", "Modules": {}}))
        self.assertIsNone(session.loadout_from_state(None))

    def navigator(self, journal_dir):
        nav = session.Navigator(FakeHost(journal_dir), tempfile.mkdtemp(), REAL_PACK)
        _OPEN.append(nav)
        return nav

    def veteran_journals(self):
        """Years-old journals (old name format, Beluga) plus today's (new format, Caspian)."""
        d = Path(tempfile.mkdtemp())
        for k in range(3):
            write_journal(d, f"Journal.2111051200{k:02d}.01.log", other_ship_loadout())
        write_journal(d, "Journal.2026-10-01T090000.01.log", CASPIAN)
        return d

    @unittest.skipUnless(REAL_PACK.exists(), "real neutron pack not built")
    def test_bootstrap_reads_the_newest_journals_not_the_last_names(self):
        nav = self.navigator(self.veteran_journals())
        nav.bootstrap()
        self.assertEqual(nav.ship.name, "Caspian Explorer")

    @unittest.skipUnless(REAL_PACK.exists(), "real neutron pack not built")
    def test_bootstrap_prefers_edmc_current_ship(self):
        d = Path(tempfile.mkdtemp())
        write_journal(d, "Journal.2026-10-01T090000.01.log", other_ship_loadout())
        nav = self.navigator(d)
        nav.bootstrap(state=edmc_state(CASPIAN))
        self.assertEqual(nav.ship.name, "Caspian Explorer")

    @unittest.skipUnless(REAL_PACK.exists(), "real neutron pack not built")
    def test_bootstrap_waits_rather_than_plan_with_another_ship(self):
        d = Path(tempfile.mkdtemp())
        write_journal(d, "Journal.2026-10-01T090000.01.log", other_ship_loadout())
        nav = self.navigator(d)
        nav.bootstrap(state={"ShipID": 30, "ShipType": "explorer_nx", "Modules": None})
        self.assertIsNone(nav.ship)
        self.assertIn("relog", nav.ship_error)

    @unittest.skipUnless(REAL_PACK.exists(), "real neutron pack not built")
    def test_same_ship_in_journals_and_edmc_is_kept(self):
        d = Path(tempfile.mkdtemp())
        write_journal(d, "Journal.2026-10-01T090000.01.log", CASPIAN)
        nav = self.navigator(d)
        nav.bootstrap(state={"ShipID": 30, "ShipType": "explorer_nx", "Modules": None})
        self.assertEqual(nav.loadout, CASPIAN)       # the journal's own Loadout, untouched
        self.assertEqual(nav.ship.name, "Caspian Explorer")

    @unittest.skipUnless(REAL_PACK.exists(), "real neutron pack not built")
    def test_live_events_follow_edmc_ship(self):
        nav = self.navigator(None)
        nav.on_journal(other_ship_loadout(), edmc_state(other_ship_loadout()))
        self.assertEqual(nav.ship.name, "Beluga Liner")
        nav.on_journal({"event": "Music", "MusicTrack": "Exploration"}, edmc_state(CASPIAN))
        self.assertEqual(nav.ship.name, "Caspian Explorer")


class TailerTests(unittest.TestCase):
    def test_follows_the_newest_journal_across_name_formats(self):
        from forgelab_nav.standalone import JournalTailer
        d = Path(tempfile.mkdtemp())
        for name in ("Journal.211105120000.01.log", "Journal.2026-10-01T090000.01.log"):
            (d / name).write_text("", encoding="utf-8")
        tailer = JournalTailer(d, None, None, None)
        self.assertEqual(tailer._newest().name, "Journal.2026-10-01T090000.01.log")

    def test_follows_new_lines_new_files_and_status(self):
        from forgelab_nav.standalone import JournalTailer
        d = Path(tempfile.mkdtemp())
        first = d / "Journal.2026-09-30T010000.01.log"
        first.write_text(json.dumps({"event": "Fileheader"}) + "\n", encoding="utf-8")
        got, status = [], []
        tailer = JournalTailer(d, got.append, status.append, lambda fn: fn(), interval=0.05)
        tailer.start_at_end()
        tailer.start()
        try:
            with open(first, "a", encoding="utf-8") as f:
                f.write(json.dumps({"event": "FSDJump", "n": 1}) + "\n")
                f.write('{"event": "Partial"')           # incomplete line: must wait
            time.sleep(0.3)
            with open(first, "a", encoding="utf-8") as f:
                f.write(', "n": 2}\n')
            second = d / "Journal.2026-09-30T020000.01.log"
            second.write_text(json.dumps({"event": "LoadGame", "n": 3}) + "\n", encoding="utf-8")
            (d / "Status.json").write_text(json.dumps({"event": "Status", "GuiFocus": 6}), encoding="utf-8")
            end = time.time() + 5
            while (len(got) < 3 or not status) and time.time() < end:
                time.sleep(0.05)
        finally:
            tailer.stop_event.set()
            tailer.join(2)
        self.assertEqual([e["event"] for e in got], ["FSDJump", "Partial", "LoadGame"])
        self.assertEqual(status[-1]["GuiFocus"], 6)


if __name__ == "__main__":
    unittest.main()
