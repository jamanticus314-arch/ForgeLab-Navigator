"""Permit-locked systems and regions (community-maintained, best effort).

Sources (pinned, see data/permit-provenance.json): Elite Dangerous Almanac
permit lists and hand-authored region spheres, plus systems flagged
needsPermit in a retained Spansh summary. The game publishes no permit data,
so a missing entry is not proof that a system is open.
"""
from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


def read_jsonc(path):
    text = Path(path).read_text(encoding="utf-8-sig")
    return json.loads(re.sub(r"/\*.*?\*/", "", text, flags=re.S))


@lru_cache(maxsize=1)
def load():
    """(locked addresses -> name, locked region spheres [(name, centre, radius)])."""
    systems = {}
    for row in read_jsonc(DATA / "Almanac-permit-locked-systems.jsonc"):
        systems[int(row["id64"])] = row["name"]
    summary = DATA / "summary-permits.json"
    if summary.exists():
        for row in json.loads(summary.read_text(encoding="utf-8"))["systems"]:
            systems.setdefault(int(row["address"]), row["name"])
    locked = {name.casefold() for name in read_jsonc(DATA / "Almanac-permit-locked-regions.jsonc")}
    spheres = []
    for region in read_jsonc(DATA / "Almanac-hand-authored-regions.jsonc"):
        if region["name"].casefold() in locked:
            for s in region["spheres"]:
                spheres.append((region["name"], (s["cx"], s["cy"], s["cz"]), float(s["r"])))
    return systems, spheres


def blocked(address, position, held=()):
    """Reason text if routing to this system needs a permit the player lacks."""
    systems, spheres = load()
    held = {str(h).casefold() for h in held}
    name = systems.get(int(address)) if address is not None else None
    if name and name.casefold() not in held:
        return "Permit required: " + name
    if position is not None:
        for region, centre, radius in spheres:
            if region.casefold() not in held and math.dist(position, centre) <= radius:
                return "Permit-locked region: " + region
    return None
