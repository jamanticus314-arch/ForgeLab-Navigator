"""Any system in the galaxy, offline: exact position, primary star and name.

Wraps ForgeLab's address-to-stellar port (vendored, output-identical to the
pinned original). Used to resolve typed destinations, to find real scoopable
refuel stars along a route, and to name waypoints.
"""
from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass
from pathlib import Path

from . import names

DATA = Path(__file__).resolve().parent.parent / "data"
ORIGIN = (-49985.0, -40985.0, -24105.0)
STAR_TYPES = json.loads((DATA / "STELLAR-JOURNAL-TABLES.json").read_text())["star_types"]
SCOOPABLE_KINDS = range(0, 7)          # O B A F G K M (giants share these kinds)
NEUTRON_KIND = 40
NONSTELLAR_KIND = 44
JOURNAL_SCOOPABLE = set("OBAFGKM")


def journal_scoopable(star_class):
    """Scoopable from a journal StarClass/StarType string (e.g. 'K', 'M_RedGiant')."""
    if not star_class:
        return False
    s = str(star_class)
    return s in JOURNAL_SCOOPABLE or ("_" in s and s[0] in JOURNAL_SCOOPABLE)


@dataclass(frozen=True)
class System:
    address: int
    name: str
    position: tuple
    star_class: str

    @property
    def scoopable(self):
        return journal_scoopable(self.star_class)

    @property
    def neutron(self):
        return self.star_class == "N"


class Stars:
    """Lazy, thread-safe access to the stellar generator."""

    def __init__(self, cache_limit=512):
        self._lock = threading.RLock()
        self._generator = None
        self._cache_limit = cache_limit

    def _gen(self):
        if self._generator is None:
            from ._vendor.stellar.api import StellarGenerator
            self._generator = StellarGenerator(cache_limit=self._cache_limit)
        return self._generator

    @staticmethod
    def _position(row):
        return tuple(o + 10 * g + p for o, g, p in zip(ORIGIN, row["origin_grid_10ly"],
                                                       row["record"]["local_position_ly"]))

    def _system(self, row, name=None):
        kind = row["record"]["stellar_kind"]
        position = self._position(row)
        address = int(row["address"])
        if name is None:
            name = names.name_from_address(address, position)
        return System(address, name, position, STAR_TYPES[kind] if kind < len(STAR_TYPES) else "ERROR")

    def by_address(self, address, name=None):
        with self._lock:
            row = self._gen().predict(str(int(address)))
        if row.get("record") is None or row["record"]["stellar_kind"] >= NONSTELLAR_KIND:
            raise LookupError("No star system exists at address " + str(address))
        return self._system(row, name)

    def by_name(self, text):
        """Exact system from a typed name (literal catalogue or procedural spelling)."""
        address = names.address_from_name(text)
        system = self.by_address(address)
        return system

    def boxel_systems(self, key):
        with self._lock:
            data = self._gen().boxel(str(key))
        out = []
        for row in data["systems"]:
            if row["record"]["stellar_kind"] < NONSTELLAR_KIND:
                out.append(row)
        return out

    def scoop_stars_near(self, centre, radius, limit_levels=range(1, 8)):
        """Real scoopable primaries within ``radius`` of ``centre`` (exact positions).

        Enumerates every boxel at the given mass levels that intersects the
        sphere. Level 0 ('a' boxels, the lightest stars) is skipped by default:
        in measured samples it held no scoopable primary yet cost ~90% of the time.
        Returns [(distance_from_centre, address, position, star_class)].
        """
        found = []
        x, y, z = centre
        for level in limit_levels:
            width = 10 << level
            lo = [math.floor((c - radius - o) / width) for c, o in zip(centre, ORIGIN)]
            hi = [math.floor((c + radius - o) / width) for c, o in zip(centre, ORIGIN)]
            limits = (1 << (14 - level), 1 << (13 - level), 1 << (14 - level))
            for gx in range(lo[0], hi[0] + 1):
                for gy in range(lo[1], hi[1] + 1):
                    for gz in range(lo[2], hi[2] + 1):
                        if not (0 <= gx < limits[0] and 0 <= gy < limits[1] and 0 <= gz < limits[2]):
                            continue
                        box = [o + g * width for o, g in zip(ORIGIN, (gx, gy, gz))]
                        d2 = sum(max(b - c, 0.0, c - b - width) ** 2 for b, c in zip(box, centre))
                        if d2 > radius * radius:
                            continue
                        key = level | (gz << 3) | (gy << (17 - level)) | (gx << (30 - 2 * level))
                        for row in self.boxel_systems(key):
                            kind = row["record"]["stellar_kind"]
                            if kind not in SCOOPABLE_KINDS:
                                continue
                            p = self._position(row)
                            d = math.dist(p, centre)
                            if d <= radius:
                                found.append((d, int(row["address"]), p, STAR_TYPES[kind]))
        found.sort()
        return found

    def name_of(self, address, position):
        return names.name_from_address(address, position)
