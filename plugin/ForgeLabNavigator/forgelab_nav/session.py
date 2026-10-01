"""The navigator: journal in, guidance out. Host-independent (EDMC or standalone).

The host supplies a small adapter (see ``Host``) and forwards journal entries
and Status.json updates. Everything else — ship model, planning thread, route
progress, galaxy-map integration, clipboard and overlay requests, field
confirmation of predicted neutron stars — lives here.

Threading: journal/status/commands are called on the host's UI thread.
Planning runs on a worker thread and hands results back with host.schedule().
"""
from __future__ import annotations

import bisect
import json
import math
import re
import threading
import time
import zlib
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields
from functools import lru_cache
from pathlib import Path

from . import galaxy, names, permits, route as route_mod, router, stars
from .ship import Ship, ShipModelError

PACKAGE = Path(__file__).resolve().parent.parent
DATA = PACKAGE / "data"
GUI_GALAXY_MAP = 6
DEFAULT_JUMP_SECONDS = 55.0
OVERLAY_EVENT_SECONDS = 60      # a tip stays on the in-game overlay this long
ARRIVAL_SECONDS = 30            # "Arrived" stays on the overlay this long
SEEN_LIMIT = 20000              # star classes the game has shown us, kept for evidence labels
FUEL_FLOOR = 0.25               # t left on reaching a refuel point: the planner's own minimum
STOP_WORDS = {route_mod.NEUTRON: "neutron", route_mod.SCOOP: "refuel star", route_mod.DESTINATION: "destination"}


class Host:
    """What the navigator needs from its host. Override in each host."""

    def schedule(self, fn):           # run fn() soon on the UI thread
        fn()

    def copy(self, text):             # put text on the clipboard
        pass

    def clipboard_text(self):         # current clipboard text; "" if not text; None if unknown
        return None

    def changed(self):                # state changed: refresh the UI
        pass

    def overlay(self, lines):         # show [(text, level)] in game (None = clear)
        pass

    def journal_dir(self):            # Path to the journal folder, or None
        return None

    def log(self, message):
        pass


@dataclass
class Settings:
    auto_copy: bool = True            # copy the next waypoint when you arrive at one
    copy_on_galaxy_map: bool = True   # make sure it is on the clipboard when the galaxy map opens
    use_predicted: bool = True        # include ForgeLab-predicted neutron stars
    auto_replan: bool = True          # replan automatically when you leave the route
    offer_from_galaxy_map: bool = True  # offer a neutron route for long in-game plots
    overlay: bool = True              # show guidance in game (!nav hide / !nav show)
    overlay_x: int = 40
    overlay_y: int = 140
    reserve_jumps: float = 1.0

    @classmethod
    def from_json(cls, data):
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


@dataclass
class Tip:
    text: str
    level: str = "info"               # info / good / warn / bad
    at: float = field(default_factory=time.time)
    short: str | None = None          # overlay wording; None = panel only
    scope: tuple | None = None        # (route id, next waypoint, system) the tip is about


@lru_cache(maxsize=1)
def _catalogue_names():
    raw = json.loads(zlib.decompress((DATA / "names-catalogue.json.zlib").read_bytes()))
    out = sorted({(n.casefold(), n) for n in raw.values()})
    return out


def suggest(prefix, limit=12, extra=()):
    """Autocomplete: recent/known names first, then catalogue names."""
    p = prefix.strip().casefold()
    if len(p) < 2:
        return []
    out = []
    for name in extra:
        if name.casefold().startswith(p) and name not in out:
            out.append(name)
    table = _catalogue_names()
    i = bisect.bisect_left(table, (p,))
    while i < len(table) and len(out) < limit and table[i][0].startswith(p):
        if table[i][1] not in out:
            out.append(table[i][1])
        i += 1
    return out[:limit]


_JOURNAL_NAME = re.compile(r"^Journal\.(?:(\d{4})-(\d{2})-(\d{2})T(\d{6})|(\d{12}))\.(\d{2})\.log$")


def journal_files(directory):
    """Journal.*.log files in ``directory``, oldest first, by the time in the name.

    The game named journals Journal.YYMMDDHHMMSS.NN.log until 2022 and
    Journal.YYYY-MM-DDTHHMMSS.NN.log since. Sorting by name puts the old
    2021-22 files after every new one, so a veteran's "newest" journal
    would be years old. Unrecognised names fall back to the file time.
    """
    def key(path):
        m = _JOURNAL_NAME.match(path.name)
        if m:
            stamp = "20" + m.group(5) if m.group(5) else "".join(m.group(1, 2, 3, 4))
            return stamp, int(m.group(6))
        try:
            return time.strftime("%Y%m%d%H%M%S", time.localtime(path.stat().st_mtime)), 0
        except OSError:
            return "", 0
    return sorted(Path(directory).glob("Journal.*.log"), key=lambda p: (*key(p), p.name))


def loadout_from_state(state):
    """A Loadout for the current ship from EDMC's monitor state, or None if it is incomplete.

    EDMC's monitor.ship() leaves out the fuel tank and unladen mass, but its
    state keeps them from the last Loadout event.
    """
    if not isinstance(state, Mapping):
        return None
    modules, fuel = state.get("Modules"), state.get("FuelCapacity")
    if not state.get("ShipType") or not isinstance(modules, Mapping) or not modules:
        return None
    if not isinstance(fuel, Mapping) or fuel.get("Main") is None or state.get("UnladenMass") is None:
        return None
    return {"event": "Loadout", "Ship": state["ShipType"], "ShipID": state.get("ShipID"),
            "UnladenMass": state["UnladenMass"], "FuelCapacity": dict(fuel),
            "Modules": [dict(m) for m in modules.values() if isinstance(m, Mapping)]}


def jumps_text(n):
    return f"~{n} jump{'' if n == 1 else 's'}"


def first_sentence(text, limit=64):
    s = text.split(". ")[0].rstrip(".")
    return s if len(s) <= limit else s[:limit - 1] + "…"


class Navigator:
    def __init__(self, host: Host, state_dir, pack_path=None):
        self.host = host
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.pack = galaxy.NeutronPack(pack_path or DATA / "neutrons.flnav")
        self.stars = stars.Stars()
        self.planner = router.Planner(self.pack)
        self.settings = Settings()
        # Game state
        self.commander = None
        self.system = None            # {name, address, position}
        self.star_class = None        # primary of the current system, when known
        self.supercharged = False
        self.loadout = None
        self.ship = None
        self.ship_error = "Waiting for your ship's loadout (switch ship or relog once)."
        self.cargo = 0.0
        self.fuel = None
        self.gui_focus = 0
        self.jump_times = []
        self._pending_class = {}      # address -> StarClass from StartJump
        # Navigation state
        self.route = None
        self.planning = None          # {"destination": name, "started": t}
        self.offer = None             # {"route": Route, "plotted_jumps": n}
        self.leg = None               # check of the route the galaxy map plotted
        self._leg_stops = None
        self.tip = None
        self.completed = None         # {"name", "flown", "planned", "at"} for the arrival moment
        self.recents = []
        self.known = {}               # casefold name -> {name, address, position}
        self.avoid = set()            # pack indices found not to be neutron stars
        self.seen = {}                # address -> star class the game showed (arrival, StartJump, plot)
        self.field = {"confirmed": 0, "contradicted": 0, "uncatalogued": 0}
        self.checked = []             # addresses already field-checked, oldest first
        self._checked = set()
        self._generation = {"route": 0, "offer": 0}
        self._lock = threading.Lock()
        self.copied = None            # last waypoint name ForgeLab put on the clipboard
        self.copy_kept = None         # name we did not re-copy because the clipboard changed
        self._overlay_sent = None     # lines last sent to the overlay
        self._fuel_replans = set()
        self._advice_cache = (None, None)
        self.integrations = {"overlay": None, "hotkeys": None}   # set by the host
        self._load()

    # ------------------------------------------------------------------ persistence
    @property
    def _state_file(self):
        return self.state_dir / "navigator.json"

    def _load(self):
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.settings = Settings.from_json(data.get("settings"))
        self.recents = data.get("recents", [])[:10]
        self.field.update(data.get("field", {}))
        self.avoid = set(data.get("avoid", []))
        self.checked = list(data.get("checked", []))
        self._checked = set(self.checked)
        self.seen = {int(k): v for k, v in (data.get("seen") or {}).items()}
        if data.get("route"):
            try:
                self.route = route_mod.Route.from_json(data["route"])
                if self.route.corpus_id and self.route.corpus_id != self.pack.corpus_id:
                    self.route.notes.append("Planned with an older neutron map; replan to refresh.")
            except (TypeError, KeyError, ValueError):
                self.route = None

    def close(self):
        self.save()
        self.pack.close()

    def save(self):
        data = {"settings": asdict(self.settings), "recents": self.recents, "field": self.field,
                "avoid": sorted(self.avoid), "checked": self.checked[-50000:],
                "seen": {str(k): v for k, v in self.seen.items()},
                "route": self.route.to_json() if self.route else None}
        tmp = self._state_file.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.replace(self._state_file)
        except OSError as e:
            self.host.log(f"Could not save navigator state: {e}")

    def _record_field(self, kind, **info):
        self.field[kind] = self.field.get(kind, 0) + 1
        info.update(kind=kind, at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    corpus=self.pack.corpus_id)
        try:
            with open(self.state_dir / "field-checks.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(info) + "\n")
        except OSError:
            pass

    # ------------------------------------------------------------------ helpers
    def _context(self):
        r = self.route
        return (r.route_id if r else None, r.next_index if r else None,
                self.system["address"] if self.system else None)

    def say(self, text, level="info", short=None):
        """Tell the player something about the current moment.

        The tip belongs to the current route, waypoint and system: it disappears
        as soon as any of them changes, so an old instruction never lingers.
        """
        self.tip = Tip(text, level, short=short, scope=self._context())

    def current_tip(self):
        t = self.tip
        return t if t is not None and t.scope == self._context() else None

    def _set_ship(self):
        if self.loadout is None:
            return
        try:
            self.ship = Ship.from_loadout(self.loadout, cargo_mass=self.cargo)
            self.ship_error = None
        except ShipModelError as e:
            self.ship = None
            self.ship_error = str(e)

    def _jump_seconds(self):
        gaps = [b - a for a, b in zip(self.jump_times, self.jump_times[1:]) if 15 < b - a < 600]
        if len(gaps) >= 3:
            gaps.sort()
            return gaps[len(gaps) // 2]
        return DEFAULT_JUMP_SECONDS

    def _pack_index(self, address, position):
        if address is None or position is None:
            return None
        return self.pack.locate(int(address), position, 1.0)

    def _remember(self, name, address, position):
        if name and address is not None and position is not None:
            self.known[name.casefold()] = {"name": name, "address": int(address), "position": tuple(position)}

    def _see(self, address, star_class):
        """Record a star class the game showed us; warn if a planned refuel star isn't scoopable."""
        if address is None or not star_class:
            return
        address = int(address)
        self.seen.pop(address, None)
        self.seen[address] = star_class
        while len(self.seen) > SEEN_LIMIT:
            self.seen.pop(next(iter(self.seen)))
        r = self.route
        if r and not r.done and not stars.journal_scoopable(star_class):
            k = r.index_of(address)
            if k is not None and k >= r.next_index and r.waypoints[k].kind == route_mod.SCOOP:
                w = r.waypoints[k]
                self.say(f"Refuel stop {w.name} is a {star_class} star in game, not scoopable. "
                         "Scoop at another star before the next boost.", "warn",
                         short="Refuel star not scoopable · scoop elsewhere")

    # ------------------------------------------------------------------ clipboard
    def _copy(self, name, implicit):
        """Put ``name`` on the clipboard.

        Explicit requests always copy. Automatic re-copies of the name ForgeLab
        already copied never overwrite something the player copied since: the
        clipboard is left alone and the panel says so. Clipboard text is only
        compared in memory, never stored or logged.
        """
        if implicit and name == self.copied:
            current = self.host.clipboard_text()
            if current == name:
                return True
            if current is not None:
                self.copy_kept = name
                return False
        self.host.copy(name)
        self.copied = name
        self.copy_kept = None
        return True

    def _copy_next(self, implicit=True):
        wp = self.route.next if self.route else None
        if wp is None:
            return False
        return self._copy(wp.name, implicit)

    def copy_text(self, name):
        """Explicit copy of any system name (e.g. from the route window)."""
        self._copy(name, implicit=False)
        self.host.changed()

    # ------------------------------------------------------------------ startup
    def bootstrap(self, journal_dir=None, loadout=None, state=None):
        """Recover ship, location and fuel from the newest journals (quietly).

        ``loadout`` (a complete Loadout) and ``state`` (EDMC's monitor state)
        describe the host's current ship and win over the journals.
        """
        directory = Path(journal_dir) if journal_dir else self.host.journal_dir()
        if directory and directory.is_dir():
            files = journal_files(directory)[-3:]
            for path in files:
                try:
                    with open(path, encoding="utf-8") as f:
                        for line in f:
                            try:
                                entry = json.loads(line)
                            except ValueError:
                                continue
                            self._apply(entry, quiet=True)
                except OSError:
                    continue
        if loadout:
            self.loadout = loadout
        elif not self._follow_host_ship(state):
            host_id = self._host_ship_id(state)
            if host_id is not None and self.loadout is not None and self.loadout.get("ShipID") != host_id:
                # The journals describe another ship than the one EDMC says you fly: don't plan with it.
                self.loadout = None
                self.ship_error = "Waiting for your current ship's loadout (relog once)."
        self._set_ship()
        if self.route and self.system:
            self._snap_to_route(quiet=True)
        self.host.changed()

    @staticmethod
    def _host_ship_id(state):
        ship_id = state.get("ShipID") if isinstance(state, Mapping) else None
        return ship_id if isinstance(ship_id, int) and not isinstance(ship_id, bool) else None

    def _follow_host_ship(self, state):
        """Switch to the host's current ship when ours is a different one. True if switched."""
        ship_id = self._host_ship_id(state)
        if ship_id is None or (self.loadout is not None and self.loadout.get("ShipID") == ship_id):
            return False
        current = loadout_from_state(state)
        if current is None:
            return False
        try:
            Ship.from_loadout(current, cargo_mass=self.cargo)
        except ShipModelError:
            return False
        self.loadout = current
        return True

    # ------------------------------------------------------------------ journal
    def on_journal(self, entry, state=None):
        self._apply(entry, quiet=False)
        if entry.get("event") not in ("Loadout", "ShipyardSwap", "ShipyardNew") and self._follow_host_ship(state):
            self._set_ship()
        self.push_overlay()
        self.host.changed()

    def _apply(self, entry, quiet):
        event = entry.get("event")
        if event in ("Commander", "LoadGame"):
            name = entry.get("Name") or entry.get("Commander")
            if name:
                self.commander = name
            if event == "LoadGame" and entry.get("FuelLevel") is not None:
                self.fuel = float(entry["FuelLevel"])
        elif event in ("Location", "FSDJump", "CarrierJump"):
            self._arrive(entry, quiet)
        elif event == "StartJump" and entry.get("JumpType") == "Hyperspace":
            if entry.get("SystemAddress") is not None:
                self._pending_class[int(entry["SystemAddress"])] = entry.get("StarClass")
                if not quiet:
                    self._see(entry["SystemAddress"], entry.get("StarClass"))
        elif event == "JetConeBoost":
            self.supercharged = True
            if not quiet:
                wp = self.route.next if self.route and not self.route.done else None
                boost = float(entry.get("BoostValue") or 0)
                if wp is not None:
                    self.say(f"Supercharged ×{boost:g}. Paste {wp.name} in the galaxy map and jump.", "good")
                    if self.settings.auto_copy:
                        self._copy_next(implicit=True)
        elif event == "Loadout":
            self.loadout = entry
            if entry.get("FuelCapacity") and self.fuel is None:
                self.fuel = float(entry["FuelCapacity"].get("Main", 0))
            if not quiet:
                self._set_ship()
        elif event == "Cargo" and entry.get("Vessel", "Ship") == "Ship":
            self.cargo = float(entry.get("Count", self.cargo))
            if not quiet:
                self._set_ship()
        elif event == "FuelScoop":
            self.fuel = float(entry.get("Total", self.fuel or 0))
            if not quiet:
                self._refresh_leg()
        elif event in ("RefuelAll", "RefuelPartial"):
            if self.fuel is not None:
                self.fuel += float(entry.get("Amount", 0))
            if not quiet:
                self._refresh_leg()
        elif event == "ReservoirReplenished":
            self.fuel = float(entry.get("FuelMain", self.fuel or 0))
        elif event == "NavRoute" and not quiet:
            self._navroute(entry)
        elif event == "NavRouteClear" and not quiet:
            self.leg = None
            self._leg_stops = None
            self._drop_offer()
        elif event == "SendText" and not quiet:
            self._chat(entry.get("Message", ""))
        elif event in ("ShipyardSwap", "ShipyardNew"):
            self.loadout = None
            self.ship = None
            self.ship_error = "Waiting for the new ship's loadout."
            self._drop_offer()
        elif event == "Shutdown" and not quiet:
            self.save()

    def _arrive(self, entry, quiet):
        address = entry.get("SystemAddress")
        position = tuple(entry["StarPos"]) if entry.get("StarPos") else None
        name = entry.get("StarSystem")
        event = entry.get("event")
        if position is None or address is None:
            return
        address = int(address)
        self.system = {"name": name, "address": address, "position": position}
        self._remember(name, address, position)
        if event == "FSDJump":
            self.supercharged = False
            if entry.get("FuelLevel") is not None:
                self.fuel = float(entry["FuelLevel"])
            try:
                t = time.mktime(time.strptime(entry.get("timestamp", ""), "%Y-%m-%dT%H:%M:%SZ"))
                self.jump_times = (self.jump_times + [t])[-25:]
            except ValueError:
                pass
            if self.route and not self.route.done and not quiet:
                self.route.flown += 1
                self.route.leg_flown += 1
        star_class = self._pending_class.pop(address, None) if event == "FSDJump" else None
        index = self._pack_index(address, position)
        if index is None:
            self.star_class = star_class
        else:
            self.star_class = star_class or "N"
        if star_class is not None and not quiet:
            self._field_check(index, address, name, position, star_class, "arrival")
        if self.route and not quiet:
            self._progress(address, position, event)
        if not quiet:
            if event == "FSDJump":
                self._refresh_leg()
            self._check_fuel()

    # ------------------------------------------------------------------ route progress
    def _progress(self, address, position, event):
        r = self.route
        if r.done:
            return
        k = r.index_of(address)
        if k is not None and k >= r.next_index:
            wp = r.waypoints[k]
            r.next_index = k + 1
            r.leg_flown = 0
            if r.done:
                self.completed = {"name": wp.name, "flown": r.flown, "planned": r.total_jumps, "at": time.time()}
                self.say(f"Arrived at {wp.name}. Route complete: {r.flown} jumps flown "
                         f"({r.total_jumps} planned).", "good")
            else:
                nxt = r.next
                if wp.kind == route_mod.NEUTRON and self.star_class == "N":
                    self.say(f"Neutron star: supercharge in the jet cone, then jump to {nxt.name}.", "good")
                elif wp.kind == route_mod.SCOOP:
                    self.say(f"Refuel stop: scoop here, then jump to {nxt.name}.", "info")
                else:
                    self.say(f"Next: {nxt.name}.", "info")
                if self.settings.auto_copy:
                    self._copy_next(implicit=True)
            self.save()
            return
        if event == "FSDJump":
            self._snap_to_route(quiet=False)

    def _snap_to_route(self, quiet):
        """Skip ahead if the player passed waypoints; replan if they left the route."""
        r = self.route
        if r is None or r.done or self.system is None:
            return
        here = self.system["position"]
        R = r.ship["range"]
        # Passed waypoints: you are clearly closer to waypoint k than the one before it is.
        for k in range(len(r.waypoints) - 1, r.next_index, -1):
            target = r.waypoints[k].position
            if math.dist(here, target) < math.dist(r.waypoints[k - 1].position, target) - 0.5 * R:
                skipped = k - r.next_index
                r.next_index = k
                r.leg_flown = 0
                if not quiet:
                    self.say(f"Skipped {skipped} waypoint{'s' if skipped != 1 else ''}; next is "
                             f"{r.waypoints[k].name}.", "info", short="Moved ahead on the route")
                    if self.settings.auto_copy:
                        self._copy_next(implicit=True)
                self.save()
                return
        # Deviation: clearly farther from the next waypoint than the leg itself.
        nxt = r.waypoints[r.next_index]
        prev = r.waypoints[r.next_index - 1].position if r.next_index else tuple(r.start["position"])
        d_now = math.dist(here, nxt.position)
        leg = math.dist(prev, nxt.position)
        if d_now > leg + R * 1.5 and not quiet:
            if self.settings.auto_replan and self.planning is None:
                self.say("You left the route. Replanning from here…", "warn", short="Off route · replanning")
                self.replan()
            else:
                self.say("You're off the route. Press Replan to route from here.", "warn",
                         short="Off route · !nav replan")

    # ------------------------------------------------------------------ fuel
    def fuel_advice(self):
        """What the route needs from the tank right now, or None when nothing needs saying.

        Returns {"level", "text", "short"}. Levels: good (at a refuel stop, enough
        fuel), warn (scoop now / top up on the way), bad (can't reach the next
        refuel point even following the plan, and no scoopable star here).
        """
        r, ship = self.route, self.ship
        if not r or r.done or ship is None or self.fuel is None or self.system is None:
            return None
        key = (r.route_id, r.next_index, self.system["address"], round(self.fuel, 1),
               self.supercharged, self.star_class, id(ship), self.settings.reserve_jumps)
        if self._advice_cache[0] == key:
            return self._advice_cache[1]
        advice = self._fuel_advice(r, ship)
        self._advice_cache = (key, advice)
        return advice

    def _fuel_advice(self, r, ship):
        here = self.system["position"]
        nxt = r.next
        boosted_now = nxt.boosted and (self.supercharged or self.star_class == "N")
        reserve = router.reserve_fuel(ship, self.settings.reserve_jumps)
        fuel, cap = self.fuel, ship.fuel_capacity
        prev = r.waypoints[r.next_index - 1] if r.next_index else None
        scoopable_here = stars.journal_scoopable(self.star_class)

        def scoop_target():
            # Conservative scoop target: reach the next refuel point with the full reserve left.
            need = route_mod.fuel_needed(r, ship, here, boosted_now, reserve)
            return int(cap) if need is None else min(int(cap), math.ceil(need))

        try:
            if prev is not None and prev.kind == route_mod.SCOOP and prev.address == self.system["address"]:
                if self.star_class and not scoopable_here:
                    return {"level": "bad",
                            "text": f"{prev.name} is a {self.star_class} star in game, not scoopable.",
                            "short": "Refuel star not scoopable"}
                target = scoop_target()
                if fuel + 0.05 < target:
                    return {"level": "warn",
                            "text": f"Refuel stop: scoop to at least {target} t (now {fuel:.0f} of {cap:g} t), "
                                    f"then jump to {nxt.name}.",
                            "short": f"Scoop to {target} t · now {fuel:.0f} t", "target": target}
                return {"level": "good",
                        "text": f"Fuel {fuel:.0f} t covers the next leg (about {target} t needed). "
                                f"Jump to {nxt.name}.",
                        "short": f"Fuel {fuel:.0f} t (need ~{target}) · jump", "target": target}
            # Alarm only when the plan's own floor is broken: the planner lets a boost
            # onto a refuel star arrive with FUEL_FLOOR t, so anything above that is on plan.
            walk = route_mod.walk_fuel(r, ship, fuel, here, boosted_now)
            if walk.dry_at is not None or walk.fuel < FUEL_FLOOR:
                if scoopable_here:
                    target = scoop_target()
                    return {"level": "warn",
                            "text": f"Fuel {fuel:.0f} t is less than the route ahead needs (about {target} t). "
                                    "Scoop here before jumping on.",
                            "short": f"Scoop here: need ~{target} t", "target": target}
                return {"level": "bad",
                        "text": f"Fuel {fuel:.0f} t is too low for the route ahead.",
                        "short": "Fuel too low for the route ahead"}
            if nxt.scoop == router.SCOOP_EN_ROUTE:
                literal = route_mod.walk_fuel(r, ship, fuel, here, boosted_now, topup=False)
                if literal.dry_at is not None or literal.fuel < FUEL_FLOOR:
                    # How full to arrive: enough for the boosts after it with the reserve left,
                    # but no more than a full scoop at the last star can give, and never
                    # less than the plan's own minimum.
                    boost_next = nxt.kind == route_mod.NEUTRON
                    after = route_mod.fuel_needed(r, ship, nxt.position, boost_next, reserve,
                                                  start=r.next_index + 1)
                    floor = route_mod.fuel_needed(r, ship, nxt.position, boost_next, FUEL_FLOOR,
                                                  start=r.next_index + 1)
                    legs = route_mod.hop_legs(math.dist(here, nxt.position), boosted_now,
                                              ship.max_range(cap), ship.neutron_multiplier, router.Options().eta)
                    best = cap - ship.fuel_used(legs[-1][0], cap) if legs else cap
                    target = max(min(cap if after is None else after, best), cap if floor is None else floor)
                    arrive = math.floor(best * 10) / 10 if target >= best - 1e-6 else math.ceil(target)
                    left = fuel                  # already enough on board for this leg? then say nothing
                    for dist, mult in legs:
                        used = ship.fuel_used(dist, max(left, 1e-6), mult)
                        left = -1.0 if used > min(left, ship.max_fuel_per_jump) + 1e-6 else left - used
                        if left < 0:
                            break
                    if left >= arrive - 1e-6:
                        return None
                    return {"level": "warn",
                            "text": f"Top up at scoopable stars on the way to {nxt.name}: arrive with at "
                                    f"least {arrive:g} t. The boosts after it count on that fuel.",
                            "short": f"Top up on the way · arrive with {arrive:g}+ t", "arrive": arrive}
        except ShipModelError:
            return None
        return None

    def _check_fuel(self):
        """On arrival: if the tank can't carry the plan onward, replan with the real fuel."""
        if self.planning is not None:
            return                                     # a replan is under way and uses today's fuel
        advice = self.fuel_advice()
        if not advice or advice["level"] != "bad":
            return
        key = self._context()
        if key in self._fuel_replans:
            return
        self._fuel_replans.add(key)
        if self.settings.auto_replan and self.planning is None:
            self.say(advice["text"] + " Replanning with your current fuel…", "warn", short="Fuel low · replanning")
            self.replan()
        else:
            self.say(advice["text"] + " Press Replan to plan with your current fuel.", "warn",
                     short="Fuel low · !nav replan")

    # ------------------------------------------------------------------ galaxy map
    def on_status(self, status):
        focus = status.get("GuiFocus", 0)
        fuel = (status.get("Fuel") or {}).get("FuelMain")
        refresh = False
        if fuel is not None:
            fuel = float(fuel)
            if self.fuel is None or abs(fuel - self.fuel) >= 0.5:
                refresh = True
            self.fuel = fuel
        if focus != self.gui_focus:
            self.gui_focus = focus
            if focus == GUI_GALAXY_MAP and self.settings.copy_on_galaxy_map and self.route and not self.route.done:
                self._copy_next(implicit=True)
                refresh = True
        if refresh:
            self._refresh_leg()
            self.host.changed()
        self.push_overlay()

    def _read_navroute(self):
        directory = self.host.journal_dir()
        if not directory:
            return None
        try:
            data = json.loads((Path(directory) / "NavRoute.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data.get("Route") or None

    def _drop_offer(self):
        with self._lock:
            self._generation["offer"] += 1
        self.offer = None

    def _navroute(self, entry):
        stops = entry.get("Route") or self._read_navroute()
        if not stops or len(stops) < 2:
            return
        self._drop_offer()                 # a new in-game plot replaces any earlier offer
        # Field checks for every catalogued neutron the game just showed us.
        for s in stops:
            if s.get("StarPos") is None:
                continue
            self._see(s.get("SystemAddress"), s.get("StarClass"))
            idx = self._pack_index(s.get("SystemAddress"), tuple(s["StarPos"]))
            self._field_check(idx, s.get("SystemAddress"), s.get("StarSystem"), tuple(s["StarPos"]),
                              s.get("StarClass"), "navroute")
            self._remember(s.get("StarSystem"), s.get("SystemAddress"), s["StarPos"])
        last = stops[-1]
        dest = {"name": last["StarSystem"], "address": int(last["SystemAddress"]),
                "position": tuple(last["StarPos"]), "star_class": last.get("StarClass", "")}
        self._leg_stops = stops
        self.leg = self._leg_check(stops)
        r = self.route
        if r and not r.done and r.index_of(dest["address"]) is not None and r.index_of(dest["address"]) >= r.next_index:
            return
        if r and not r.done and dest["address"] == r.destination.get("address"):
            return
        plotted = len(stops) - 1
        if self.settings.offer_from_galaxy_map and plotted >= 8 and self.ship and self.system:
            self._plan(dest, offer_against=plotted)

    def _refresh_leg(self):
        """Re-check the in-game plot from where you are now, with the fuel you have now."""
        stops = self._leg_stops
        if not stops or self.system is None:
            return
        here = next((i for i, s in enumerate(stops) if s.get("SystemAddress") == self.system["address"]), None)
        if here is None:
            return
        if here >= len(stops) - 1:
            self.leg = None
            self._leg_stops = None
            return
        self.leg = self._leg_check(stops[here:])

    def _leg_check(self, stops):
        """Fuel along the route the game plotted, using the stars it lists (stops[0] = here)."""
        if not self.ship:
            return None
        ship = self.ship
        fuel = self.fuel if self.fuel is not None else ship.fuel_capacity
        reserve = router.reserve_fuel(ship, self.settings.reserve_jumps)
        scoopable = [i for i, s in enumerate(stops) if stars.journal_scoopable(s.get("StarClass"))]
        neutrons = sum(1 for s in stops[1:] if s.get("StarClass") == "N")
        boosted = self.supercharged
        warn = short = None
        last_scoop = 0 if stars.journal_scoopable(self.star_class) else None
        for i in range(1, len(stops)):
            a, b = stops[i - 1].get("StarPos"), stops[i].get("StarPos")
            if not a or not b:
                continue
            d = math.dist(a, b)
            mult = ship.neutron_multiplier if boosted and i == 1 else 1.0
            try:
                used = ship.fuel_used(d, max(fuel, 0.01), mult)
            except ShipModelError:
                used = ship.max_fuel_per_jump
            fuel -= used
            if fuel < reserve and warn is None:
                where = stops[last_scoop]["StarSystem"] if last_scoop is not None else None
                if where:
                    warn = f"Fuel runs low by jump {i}. Scoop at {where} first."
                    short = f"Fuel low by jump {i} · scoop at {where}"
                else:
                    warn = (f"Not enough fuel for this plot: about {reserve - fuel:.1f} t short "
                            "and no scoopable star before then.")
                    short = "Not enough fuel for this plot"
            if i in scoopable:
                last_scoop = i
                fuel = ship.fuel_capacity
        first_scoop = next((stops[i]["StarSystem"] for i in scoopable if i > 0), None)
        return {"jumps": len(stops) - 1, "scoopable": len([i for i in scoopable if i > 0]),
                "neutrons": neutrons, "first_scoop": first_scoop, "warning": warn, "short": short,
                "destination": stops[-1].get("StarSystem")}

    # ------------------------------------------------------------------ field checks
    def _field_check(self, index, address, name, position, star_class, source):
        if star_class is None or address is None or int(address) in self._checked:
            return
        if index is None and star_class != "N":
            return
        self._checked.add(int(address))
        self.checked.append(int(address))
        if index is not None:
            flags = self.pack.flags[index]
            predicted = bool(flags & galaxy.FLAG_PREDICTED)
            if star_class == "N":
                if predicted and not flags & galaxy.FLAG_CONFIRMED:
                    self._record_field("confirmed", address=int(address), name=name, source=source)
            else:
                self._record_field("contradicted", address=int(address), name=name, star_class=star_class,
                                   source=source, predicted=predicted)
                self.avoid.add(index)
                r = self.route
                if r and not r.done and r.index_of(int(address)) is not None and r.index_of(int(address)) >= r.next_index:
                    self.say(f"{name} is a {star_class} star, not a neutron star. Rerouting around it.", "warn",
                             short="Predicted neutron missing · rerouting")
                    self.replan()
        elif star_class == "N" and position is not None:
            self._record_field("uncatalogued", address=int(address), name=name,
                               position=list(position), source=source)

    # ------------------------------------------------------------------ evidence
    def evidence(self, wp):
        """Evidence key for a waypoint, upgraded by what the game has shown this commander."""
        seen = self.seen.get(wp.address)
        if wp.kind == route_mod.NEUTRON:
            if seen == "N" and wp.evidence == "predicted":
                return "confirmed"
            return wp.evidence
        if wp.kind == route_mod.SCOOP:
            if seen is None:
                return "generated"
            return "class confirmed" if stars.journal_scoopable(seen) else "class contradicted"
        return wp.evidence

    # ------------------------------------------------------------------ planning
    def resolve(self, text):
        """Destination from typed text: known/recent systems, then the galaxy."""
        text = (text or "").strip()
        if not text:
            raise ValueError("Type a system name.")
        hit = self.known.get(text.casefold())
        if hit is None:
            hit = next((r for r in self.recents if r["name"].casefold() == text.casefold()), None)
        if hit is not None:
            return {"name": hit["name"], "address": int(hit["address"]), "position": tuple(hit["position"]),
                    "star_class": hit.get("star_class", "")}
        try:
            system = self.stars.by_name(text)
        except names.NamingError as e:
            raise ValueError(f"Unknown system '{text}'. Check the spelling (e.g. 'Colonia', "
                             "'Swoilt NO-I d9-0').") from e
        except LookupError as e:
            raise ValueError(str(e)) from e
        return {"name": system.name, "address": system.address, "position": system.position,
                "star_class": system.star_class}

    def plot(self, text):
        """User asked for a route to ``text``. Returns an error message or None."""
        if self.ship is None:
            return self.ship_error or "Ship unknown."
        if self.system is None:
            return "Current location unknown - jump once or relog."
        try:
            dest = self.resolve(text)
        except ValueError as e:
            return str(e)
        self._plan(dest)
        return None

    def replan(self):
        if self.route is None:
            return
        dest = dict(self.route.destination)
        self._plan(dest, replan=True)

    def _plan(self, dest, offer_against=None, replan=False):
        if self.ship is None or self.system is None:
            return
        slot = "offer" if offer_against is not None else "route"
        with self._lock:
            self._generation[slot] += 1
            if slot == "route":
                self._generation["offer"] += 1   # a real request supersedes offers
            generation = self._generation[slot]
        start = dict(self.system)
        ship = self.ship
        fuel = self.fuel
        boosted = self.supercharged or self.star_class == "N"
        opts = router.Options(use_predicted=self.settings.use_predicted,
                              reserve_jumps=self.settings.reserve_jumps)
        avoid = set(self.avoid)
        if offer_against is None:
            self.planning = {"destination": dest["name"], "started": time.time()}
            self.offer = None
        blocked = permits.blocked(dest.get("address"), dest.get("position"))

        def work():
            try:
                plan = self.planner.plan(start["position"], dest["position"], ship, fuel=fuel, options=opts,
                                         start_is_neutron=boosted, avoid=avoid,
                                         cancel=lambda: generation != self._generation[slot])
                built = route_mod.build(plan, self.pack, self.stars, start, dest, ship,
                                        opts.use_predicted, self.pack.corpus_id)
                problems = route_mod.verify(built, ship)
                if problems:
                    raise router.PlanError("Route failed its safety check: " + problems[0])
                if blocked:
                    built.notes.append(blocked + ". You need it to arrive.")
                result, error = built, None
            except router.PlanError as e:
                result, error = None, str(e)
            except Exception as e:  # noqa: BLE001 - never kill the host
                result, error = None, f"Planning failed: {type(e).__name__}: {e}"
            self.host.schedule(lambda: self._planned(slot, generation, dest, result, error, offer_against, replan))

        threading.Thread(target=work, name="forgelab-plan", daemon=True).start()
        self.host.changed()

    def _planned(self, slot, generation, dest, result, error, offer_against, replan):
        if generation != self._generation[slot]:
            return
        if offer_against is not None:
            if self.planning is not None:
                return
            if result is not None and result.total_jumps <= offer_against * 0.8 and offer_against - result.total_jumps >= 3:
                self.offer = {"route": result, "plotted_jumps": offer_against}
            self.push_overlay()
            self.host.changed()
            return
        self.planning = None
        if error:
            self.say(error, "bad", short=first_sentence(error))
            self.push_overlay()
            self.host.changed()
            return
        self.route = result
        self.completed = None
        self._remember(dest["name"], dest["address"], dest["position"])
        self._add_recent(dest)
        saved = result.direct_jumps - result.total_jumps
        verb = "Replanned" if replan else "Route ready"
        extra = f", {saved} fewer than without neutrons" if saved > 0 else ""
        copied = self._copy_next(implicit=replan) if (self.settings.auto_copy or not replan) else False
        then = " First waypoint copied: paste it in the galaxy map." if copied else \
            " Copy the first waypoint with the Next button or !nav copy."
        self.say(f"{verb}: {result.total_jumps} jumps{extra}.{then}", "good",
                 short=f"{verb}: {result.total_jumps} jumps" + (" · first waypoint copied" if copied else ""))
        self.save()
        self.host.changed()
        self.push_overlay()

    def _add_recent(self, dest):
        entry = {"name": dest["name"], "address": int(dest["address"]), "position": list(dest["position"]),
                 "star_class": dest.get("star_class", "")}
        self.recents = [entry] + [r for r in self.recents if r["address"] != entry["address"]]
        self.recents = self.recents[:10]

    # ------------------------------------------------------------------ commands
    def accept_offer(self):
        if not self.offer:
            return
        self.route = self.offer["route"]
        self.offer = None
        self.completed = None
        d = self.route.destination
        self._add_recent(d)
        self._copy_next(implicit=False)
        self.say(f"Neutron route to {d['name']}: {self.route.total_jumps} jumps. First waypoint copied.", "good",
                 short=f"Neutron route: {self.route.total_jumps} jumps · first waypoint copied")
        self.save()
        self.push_overlay()
        self.host.changed()

    def dismiss_offer(self):
        self._drop_offer()
        self.push_overlay()
        self.host.changed()

    def copy_next(self):
        if self._copy_next(implicit=False):
            self.say(f"Copied {self.route.next.name}.", "info", short="Copied next waypoint")
        self.push_overlay()
        self.host.changed()

    def step(self, delta):
        r = self.route
        if not r:
            return
        r.next_index = max(0, min(len(r.waypoints), r.next_index + delta))
        r.leg_flown = 0
        if not r.done:
            copied = self.settings.auto_copy and self._copy_next(implicit=False)
            self.say(f"{'Skipped' if delta > 0 else 'Back'} to {r.next.name}{' (copied)' if copied else ''}.",
                     "info", short="Skipped a waypoint" if delta > 0 else "Back one waypoint")
        self.save()
        self.push_overlay()
        self.host.changed()

    def clear(self):
        with self._lock:
            for slot in self._generation:
                self._generation[slot] += 1
        self.route = None
        self.planning = None
        self.offer = None
        self.leg = None
        self._leg_stops = None
        self.completed = None
        self.say("Route cleared.", "info", short="Route cleared")
        self.save()
        self.push_overlay()
        self.host.changed()

    def reverse(self):
        """Plan the trip back to where this route started."""
        if self.route:
            self._plan(dict(self.route.start))

    def set_overlay(self, visible):
        """Show or hide all in-game guidance (panel keeps working)."""
        self.settings.overlay = bool(visible)
        self.save()
        self.push_overlay()
        self.host.changed()

    def settings_changed(self):
        self._advice_cache = (None, None)
        self.save()
        self.push_overlay()
        self.host.changed()

    CHAT_HELP = "!nav copy | next | back | replan | yes | no | hide | show | clear | to <system>"

    def _chat(self, message):
        """In-game chat commands (see CHAT_HELP)."""
        text = message.strip()
        if not text.lower().startswith("!nav"):
            return
        arg = text[4:].strip()
        low = arg.lower()
        if low in ("", "copy"):
            self.copy_next()
        elif low in ("next", "skip"):
            self.step(1)
        elif low in ("prev", "previous", "back"):
            self.step(-1)
        elif low == "replan":
            self.replan()
        elif low == "clear":
            self.clear()
        elif low in ("yes", "accept"):
            if self.offer:
                self.accept_offer()
            else:
                self.say("There is no route offer to accept.", "info", short="No route offer to accept")
        elif low in ("no", "dismiss"):
            self.dismiss_offer()
        elif low == "hide":
            self.set_overlay(False)
        elif low == "show":
            self.set_overlay(True)
        elif low.startswith("to "):
            error = self.plot(arg[3:])
            if error:
                self.say(error, "bad", short=first_sentence(error))
        else:
            self.say(f"Unknown command '!nav {arg}'. Try {self.CHAT_HELP}.", "bad",
                     short="Unknown !nav command")

    # ------------------------------------------------------------------ view
    def snapshot(self):
        r = self.route
        tip = self.current_tip()
        view = {"ship": None, "system": self.system, "fuel": self.fuel, "planning": self.planning,
                "tip": asdict(tip) if tip else None, "leg": self.leg, "route": None,
                "offer": None, "ship_error": self.ship_error, "supercharged": self.supercharged,
                "recents": [x["name"] for x in self.recents], "field": dict(self.field),
                "copied": self.copied, "copy_kept": self.copy_kept, "fuel_advice": self.fuel_advice()}
        if self.ship:
            s = self.ship
            view["ship"] = {"name": s.name, "range": round(s.max_range(s.fuel_capacity), 1),
                            "boost": s.neutron_multiplier, "tank": s.fuel_capacity, "scoop": s.has_scoop}
        if r:
            nxt = r.next
            secs = self._jump_seconds()
            here = self.system["position"] if self.system else None
            view["route"] = {
                "destination": r.destination["name"], "total_jumps": r.total_jumps,
                "jumps_left": r.jumps_to_go, "direct_jumps": r.direct_jumps, "done": r.done,
                "waypoints": len(r.waypoints), "next_index": r.next_index, "flown": r.flown,
                "distance_left": r.distance_left(here), "eta_seconds": r.jumps_to_go * secs,
                "notes": list(r.notes),
                "next": None if nxt is None else {
                    "name": nxt.name, "kind": nxt.kind, "jumps": nxt.jumps, "evidence": self.evidence(nxt),
                    "star_class": nxt.star_class, "boosted": nxt.boosted,
                    "distance": math.dist(here, nxt.position) if here else nxt.distance},
            }
        if self.offer:
            o = self.offer["route"]
            view["offer"] = {"destination": o.destination["name"], "jumps": o.total_jumps,
                             "plotted": self.offer["plotted_jumps"]}
        return view

    # ------------------------------------------------------------------ overlay
    def _action_line(self):
        """Overlay line 2: the current action when there is one, else the next stop."""
        r = self.route
        nxt = r.next
        left = f"{jumps_text(r.jumps_to_go)} left"
        advice = self.fuel_advice()
        if advice:
            return (f"{advice['short']} · {left}", advice["level"])
        prev = r.waypoints[r.next_index - 1] if r.next_index else None
        at_prev = prev is not None and self.system is not None and prev.address == self.system["address"]
        if nxt.boosted and self.supercharged:
            return (f"Supercharged · jump now · {left}", "good")
        if nxt.boosted and at_prev and self.star_class == "N":
            return (f"Supercharge here · {left}", "info")
        return (f"Next stop: {STOP_WORDS.get(nxt.kind, nxt.kind)} · {left}", "info")

    def _event_line(self, now):
        """Overlay line 3: at most one consequential event."""
        if self.leg and self.leg.get("warning"):
            return (self.leg["short"], "warn")
        if self.offer:
            o = self.offer
            return (f"Neutron route: {o['route'].total_jumps} jumps instead of {o['plotted_jumps']} · !nav yes",
                    "info")
        tip = self.current_tip()
        if tip and tip.short and now - tip.at < OVERLAY_EVENT_SECONDS:
            return (tip.short, tip.level)
        return None

    def overlay_lines(self):
        """What the in-game overlay should show now: [(text, level)], or None for nothing."""
        if not self.settings.overlay:
            return None
        now = time.time()
        r = self.route
        event = self._event_line(now)
        if r and not r.done:
            lines = [(f"Next: {r.next.name}", "target"), self._action_line()]
            return lines + [event] if event else lines
        c = self.completed
        if c and now - c["at"] < ARRIVAL_SECONDS:
            return [(f"Arrived: {c['name']}", "target"),
                    (f"Route complete · {c['flown']} jumps flown", "good")]
        return [event] if event else None

    def push_overlay(self, keepalive=False):
        """Send the overlay when its content changes (``keepalive`` re-sends before it expires)."""
        lines = self.overlay_lines()
        if lines is None:
            if self._overlay_sent is not None:
                self.host.overlay(None)
                self._overlay_sent = None
            return
        if keepalive or lines != self._overlay_sent:
            self.host.overlay(lines)
            self._overlay_sent = lines
