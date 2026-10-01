"""Journal/outfitting-only hyperspace model; no game process or network access.

Units: tonnes, light years, seconds. UnladenMass excludes main tank fuel and
cargo. The reservoir is not available for jumps and is not added to jump mass.

Outfitting values are transcribed from EDCD/coriolis-data commit
0db9234b5b9ce8c939ea84133d7ce336eea88e27 (2026-09-24 retrieval). Its LICENSE.md
attributes JSON data to Frontier Developments plc, subject to Frontier terms;
it does not license the data as MIT. Formula cross-check: taleden/EDSY commit
e85bb52c0de9886075ecd08ac4271003e3dc8668, edsy.js getJumpDistance/getJumpFuelCost.
No journal-fitted constants are used. Full provenance and residual limitations
are in the release's jump-model validation report.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any, Mapping


class ShipModelError(ValueError):
    """The journal does not identify a supported, finite ship configuration."""


# Generated from the pinned outfitting JSON; tuple fields are
# (optimal mass, maximum fuel per jump, fuel multiplier, fuel power).
FSD_SPECS = {'int_hyperdrive_overcharge_size2_class1': (60, 0.6, 0.008, 2.0),
 'int_hyperdrive_overcharge_size2_class2': (90, 0.9, 0.012, 2.0),
 'int_hyperdrive_overcharge_size2_class3': (90, 0.9, 0.012, 2.0),
 'int_hyperdrive_overcharge_size2_class4': (90, 0.9, 0.012, 2.0),
 'int_hyperdrive_overcharge_size2_class5': (100, 1, 0.013, 2.0),
 'int_hyperdrive_overcharge_size3_class1': (100, 1.2, 0.008, 2.15),
 'int_hyperdrive_overcharge_size3_class2': (150, 1.8, 0.012, 2.15),
 'int_hyperdrive_overcharge_size3_class3': (150, 1.8, 0.012, 2.15),
 'int_hyperdrive_overcharge_size3_class4': (150, 1.8, 0.012, 2.15),
 'int_hyperdrive_overcharge_size3_class5': (167, 1.9, 0.013, 2.15),
 'int_hyperdrive_overcharge_size4_class1': (350, 2, 0.008, 2.3),
 'int_hyperdrive_overcharge_size4_class2': (525, 3, 0.012, 2.3),
 'int_hyperdrive_overcharge_size4_class3': (525, 3, 0.012, 2.3),
 'int_hyperdrive_overcharge_size4_class4': (525, 3, 0.012, 2.3),
 'int_hyperdrive_overcharge_size4_class5': (585, 3.2, 0.013, 2.3),
 'int_hyperdrive_overcharge_size5_class1': (700, 3.3, 0.008, 2.45),
 'int_hyperdrive_overcharge_size5_class2': (1050, 5, 0.012, 2.45),
 'int_hyperdrive_overcharge_size5_class3': (1050, 5, 0.012, 2.45),
 'int_hyperdrive_overcharge_size5_class4': (1050, 5, 0.012, 2.45),
 'int_hyperdrive_overcharge_size5_class5': (1175, 5.2, 0.013, 2.45),
 'int_hyperdrive_overcharge_size6_class1': (1200, 5.3, 0.008, 2.6),
 'int_hyperdrive_overcharge_size6_class2': (1800, 8, 0.012, 2.6),
 'int_hyperdrive_overcharge_size6_class3': (1800, 8, 0.012, 2.6),
 'int_hyperdrive_overcharge_size6_class4': (1800, 8, 0.012, 2.6),
 'int_hyperdrive_overcharge_size6_class5': (2000, 8.3, 0.013, 2.6),
 'int_hyperdrive_overcharge_size7_class1': (1800, 8.5, 0.008, 2.75),
 'int_hyperdrive_overcharge_size7_class2': (2700, 12.8, 0.012, 2.75),
 'int_hyperdrive_overcharge_size7_class3': (2700, 12.8, 0.012, 2.75),
 'int_hyperdrive_overcharge_size7_class4': (2700, 12.8, 0.012, 2.75),
 'int_hyperdrive_overcharge_size7_class5': (3000, 13.1, 0.013, 2.75),
 'int_hyperdrive_overcharge_size8_class1': (2800, 13.6, 0.008, 2.9),
 'int_hyperdrive_overcharge_size8_class2': (4200, 20.4, 0.012, 2.9),
 'int_hyperdrive_overcharge_size8_class3': (4200, 20.4, 0.012, 2.9),
 'int_hyperdrive_overcharge_size8_class4': (4200, 20.4, 0.012, 2.9),
 'int_hyperdrive_overcharge_size8_class5': (4670, 20.7, 0.013, 2.9),
 'int_hyperdrive_overcharge_size8_class5_overchargebooster_mkii': (4670, 6.8, 0.011, 2.5025),
 'int_hyperdrive_size2_class1': (48, 0.6, 0.011, 2),
 'int_hyperdrive_size2_class2': (54, 0.6, 0.01, 2),
 'int_hyperdrive_size2_class3': (60, 0.6, 0.008, 2),
 'int_hyperdrive_size2_class4': (75, 0.8, 0.01, 2),
 'int_hyperdrive_size2_class5': (90, 0.9, 0.012, 2),
 'int_hyperdrive_size3_class1': (80, 1.2, 0.011, 2.15),
 'int_hyperdrive_size3_class2': (90, 1.2, 0.01, 2.15),
 'int_hyperdrive_size3_class3': (100, 1.2, 0.008, 2.15),
 'int_hyperdrive_size3_class4': (125, 1.5, 0.01, 2.15),
 'int_hyperdrive_size3_class5': (150, 1.8, 0.012, 2.15),
 'int_hyperdrive_size4_class1': (280, 2, 0.011, 2.3),
 'int_hyperdrive_size4_class2': (315, 2, 0.01, 2.3),
 'int_hyperdrive_size4_class3': (350, 2, 0.008, 2.3),
 'int_hyperdrive_size4_class4': (437.5, 2.5, 0.01, 2.3),
 'int_hyperdrive_size4_class5': (525, 3, 0.012, 2.3),
 'int_hyperdrive_size5_class1': (560, 3.3, 0.011, 2.45),
 'int_hyperdrive_size5_class2': (630, 3.3, 0.01, 2.45),
 'int_hyperdrive_size5_class3': (700, 3.3, 0.008, 2.45),
 'int_hyperdrive_size5_class4': (875, 4.1, 0.01, 2.45),
 'int_hyperdrive_size5_class5': (1050, 5, 0.012, 2.45),
 'int_hyperdrive_size6_class1': (960, 5.3, 0.011, 2.6),
 'int_hyperdrive_size6_class2': (1080, 5.3, 0.01, 2.6),
 'int_hyperdrive_size6_class3': (1200, 5.3, 0.008, 2.6),
 'int_hyperdrive_size6_class4': (1500, 6.6, 0.01, 2.6),
 'int_hyperdrive_size6_class5': (1800, 8, 0.012, 2.6),
 'int_hyperdrive_size7_class1': (1440, 8.5, 0.011, 2.75),
 'int_hyperdrive_size7_class2': (1620, 8.5, 0.01, 2.75),
 'int_hyperdrive_size7_class3': (1800, 8.5, 0.008, 2.75),
 'int_hyperdrive_size7_class4': (2250, 10.6, 0.01, 2.75),
 'int_hyperdrive_size7_class5': (2700, 12.8, 0.012, 2.75)}
SCOOP_RATES = {'int_fuelscoop_size1_class1': 0.018,
 'int_fuelscoop_size1_class2': 0.024,
 'int_fuelscoop_size1_class3': 0.03,
 'int_fuelscoop_size1_class4': 0.036,
 'int_fuelscoop_size1_class5': 0.042,
 'int_fuelscoop_size2_class1': 0.032,
 'int_fuelscoop_size2_class2': 0.043,
 'int_fuelscoop_size2_class3': 0.054,
 'int_fuelscoop_size2_class4': 0.065,
 'int_fuelscoop_size2_class5': 0.075,
 'int_fuelscoop_size3_class1': 0.075,
 'int_fuelscoop_size3_class2': 0.1,
 'int_fuelscoop_size3_class3': 0.126,
 'int_fuelscoop_size3_class4': 0.151,
 'int_fuelscoop_size3_class5': 0.176,
 'int_fuelscoop_size4_class1': 0.147,
 'int_fuelscoop_size4_class2': 0.196,
 'int_fuelscoop_size4_class3': 0.245,
 'int_fuelscoop_size4_class4': 0.294,
 'int_fuelscoop_size4_class5': 0.342,
 'int_fuelscoop_size5_class1': 0.247,
 'int_fuelscoop_size5_class2': 0.33,
 'int_fuelscoop_size5_class3': 0.412,
 'int_fuelscoop_size5_class4': 0.494,
 'int_fuelscoop_size5_class5': 0.577,
 'int_fuelscoop_size6_class1': 0.376,
 'int_fuelscoop_size6_class2': 0.502,
 'int_fuelscoop_size6_class3': 0.627,
 'int_fuelscoop_size6_class4': 0.752,
 'int_fuelscoop_size6_class5': 0.878,
 'int_fuelscoop_size7_class1': 0.534,
 'int_fuelscoop_size7_class2': 0.712,
 'int_fuelscoop_size7_class3': 0.89,
 'int_fuelscoop_size7_class4': 1.068,
 'int_fuelscoop_size7_class5': 1.245,
 'int_fuelscoop_size8_class1': 0.72,
 'int_fuelscoop_size8_class2': 0.96,
 'int_fuelscoop_size8_class3': 1.2,
 'int_fuelscoop_size8_class4': 1.44,
 'int_fuelscoop_size8_class5': 1.68}
GUARDIAN_BOOSTS = {'int_guardianfsdbooster_size1': 4,
 'int_guardianfsdbooster_size2': 6,
 'int_guardianfsdbooster_size3': 7.75,
 'int_guardianfsdbooster_size4': 9.25,
 'int_guardianfsdbooster_size5': 10.5}
SHIP_NAMES = {'adder': 'Adder',
 'alliance_challenger': 'Alliance Challenger',
 'alliance_chieftain': 'Alliance Chieftain',
 'alliance_crusader': 'Alliance Crusader',
 'anaconda': 'Anaconda',
 'asp': 'Asp Explorer',
 'asp_scout': 'Asp Scout',
 'beluga': 'Beluga Liner',
 'cobra_mk_iii': 'Cobra Mk III',
 'cobra_mk_iv': 'Cobra Mk IV',
 'cobramkv': 'Cobra Mk V',
 'diamondback': 'Diamondback Scout',
 'diamondback_explorer': 'Diamondback Explorer',
 'dolphin': 'Dolphin',
 'eagle': 'Eagle',
 'explorer_nx': 'Caspian Explorer',
 'federal_assault_ship': 'Federal Assault Ship',
 'federal_corvette': 'Federal Corvette',
 'federal_dropship': 'Federal Dropship',
 'federal_gunship': 'Federal Gunship',
 'fer_de_lance': 'Fer-de-Lance',
 'hauler': 'Hauler',
 'imperial_clipper': 'Imperial Clipper',
 'imperial_corsair': 'Corsair',
 'imperial_courier': 'Imperial Courier',
 'imperial_cutter': 'Imperial Cutter',
 'imperial_eagle': 'Imperial Eagle',
 'keelback': 'Keelback',
 'kestrel': 'Kestrel Mk II',
 'krait_mkii': 'Krait Mk II',
 'krait_phantom': 'Krait Phantom',
 'mamba': 'Mamba',
 'mandalay': 'Mandalay',
 'orca': 'Orca',
 'panthermkii': 'Panther Clipper Mk II',
 'python': 'Python',
 'python_nx': 'Python Mk II',
 'sidewinder': 'Sidewinder',
 'type_10_defender': 'Type-10 Defender',
 'type_11_prospector': 'Type-11 Prospector',
 'type_6_transporter': 'Type-6 Transporter',
 'type_7_transport': 'Type-7 Transporter',
 'type_8_transport': 'Type-8 Transporter',
 'type_9_heavy': 'Type-9 Heavy',
 'viper': 'Viper',
 'viper_mk_iv': 'Viper Mk IV',
 'vulture': 'Vulture'}


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ShipModelError(f"{label} must be a number")
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ShipModelError(f"{label} is unavailable") from None
    if not math.isfinite(result) or result < 0 or (positive and result <= 0):
        raise ShipModelError(f"{label} must be {'positive' if positive else 'nonnegative'} and finite")
    return result


def _symbol(value: Any) -> str:
    result = str(value or "").lower().strip()
    if result.startswith("$") and result.endswith("_name;"):
        result = result[1:-6]
    return result


@dataclass(frozen=True)
class Ship:
    name: str
    unladen_mass: float
    fuel_capacity: float
    optimal_mass: float
    max_fuel_per_jump: float
    fuel_multiplier: float
    fuel_power: float
    cargo_mass: float = 0.0
    guardian_boost: float = 0.0
    scoop_rate: float = 0.0
    fuel_reserve_capacity: float = 0.0
    ship_type: str = ""
    fsd_symbol: str = ""
    neutron_multiplier: float = 4.0
    source_timestamp: str = ""
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for label in ("unladen_mass", "fuel_capacity", "optimal_mass", "max_fuel_per_jump",
                      "fuel_multiplier", "fuel_power", "neutron_multiplier"):
            object.__setattr__(self, label, _number(getattr(self, label), label, positive=True))
        for label in ("cargo_mass", "guardian_boost", "scoop_rate", "fuel_reserve_capacity"):
            object.__setattr__(self, label, _number(getattr(self, label), label))

    @property
    def dry_mass(self) -> float:
        return self.unladen_mass + self.cargo_mass

    @property
    def has_scoop(self) -> bool:
        return self.scoop_rate > 0

    def with_cargo(self, tons: float) -> "Ship":
        return replace(self, cargo_mass=_number(tons, "cargo mass"))

    def max_range(self, fuel_before: float, boost: float = 1.0) -> float:
        """Maximum range at the supplied main-tank fuel, including Guardian.

        Cone/injection boost is one multiplier on the whole range. It does not
        stack with another boost. Fuel reservoir mass is excluded.
        """
        fuel = _number(fuel_before, "main fuel")
        multiplier = _number(boost, "boost multiplier", positive=True)
        if fuel > self.fuel_capacity + 0.001:
            raise ShipModelError("Main fuel exceeds Loadout fuel capacity")
        if not fuel:
            return 0.0
        usable = min(fuel, self.max_fuel_per_jump)
        base = (usable / self.fuel_multiplier) ** (1.0 / self.fuel_power)
        return (base * self.optimal_mass / (self.dry_mass + fuel) + self.guardian_boost) * multiplier

    def fuel_used(self, distance: float, fuel_before: float, boost: float = 1.0) -> float:
        """Fuel required, including unreachable jumps (caller checks range).

        Guardian modifies the effective range/fuel curve. Subtracting its flat
        bonus from the requested distance would incorrectly produce free jumps.
        """
        distance = _number(distance, "jump distance")
        fuel = _number(fuel_before, "main fuel")
        maximum = self.max_range(fuel, boost)
        if not distance:
            return 0.0
        if not maximum:
            raise ShipModelError("No main fuel is available for a jump")
        return (distance / maximum) ** self.fuel_power * min(fuel, self.max_fuel_per_jump)

    @classmethod
    def from_loadout(cls, loadout: Mapping[str, Any], *, cargo_mass: float = 0.0) -> "Ship":
        if not isinstance(loadout, Mapping) or loadout.get("event") not in (None, "Loadout"):
            raise ShipModelError("A complete ship Loadout event is required")
        modules = loadout.get("Modules")
        if not isinstance(modules, list):
            raise ShipModelError("Loadout modules are unavailable")
        drives = [m for m in modules if m.get("Slot", "").lower() == "frameshiftdrive"]
        if len(drives) != 1:
            raise ShipModelError("Loadout must identify exactly one FrameShiftDrive")
        drive = drives[0]
        symbol = _symbol(drive.get("Item"))
        if symbol not in FSD_SPECS:
            raise ShipModelError(f"Unsupported FSD in pinned outfitting data: {symbol}")
        if not drive.get("On", False):
            raise ShipModelError("The Frame Shift Drive is not enabled in Loadout")
        if drive.get("Health") == 0:
            raise ShipModelError("The Frame Shift Drive is destroyed in Loadout")
        opt, maxfuel, fuelmul, fuelpower = FSD_SPECS[symbol]
        engineering = drive.get("Engineering") or {}
        modifiers = engineering.get("Modifiers", [])
        if engineering and not modifiers:
            raise ShipModelError("Engineered FSD is missing its journal modifier values")
        for modifier in modifiers:
            label = modifier.get("Label")
            if label == "FSDOptimalMass":
                opt = _number(modifier.get("Value"), label, positive=True)
            elif label == "MaxFuelPerJump":
                maxfuel = _number(modifier.get("Value"), label, positive=True)
        guardian = 0.0
        scoop_rate = 0.0
        for module in modules:
            item = _symbol(module.get("Item"))
            if not module.get("On", False) or module.get("Health") == 0:
                continue
            if "guardianfsdbooster" in item:
                if item not in GUARDIAN_BOOSTS:
                    raise ShipModelError(f"Unsupported Guardian booster: {item}")
                guardian += GUARDIAN_BOOSTS[item]
            if "fuelscoop" in item:
                if item not in SCOOP_RATES:
                    raise ShipModelError(f"Unsupported fuel scoop: {item}")
                scoop_rate = max(scoop_rate, SCOOP_RATES[item])
        if guardian > max(GUARDIAN_BOOSTS.values()):
            raise ShipModelError("Multiple enabled Guardian boosters in Loadout")
        capacity = loadout.get("FuelCapacity")
        if not isinstance(capacity, Mapping):
            raise ShipModelError("Loadout main fuel capacity is unavailable")
        ship_type = _symbol(loadout.get("Ship"))
        special = symbol.endswith("_overchargebooster_mkii")
        warnings = ("Module power state is the last journal Loadout snapshot.",)
        return cls(
            name=SHIP_NAMES.get(ship_type, str(loadout.get("Ship", "Unknown ship"))),
            ship_type=ship_type,
            unladen_mass=_number(loadout.get("UnladenMass"), "Loadout.UnladenMass", positive=True),
            cargo_mass=_number(cargo_mass, "cargo mass"),
            fuel_capacity=_number(capacity.get("Main"), "Loadout.FuelCapacity.Main", positive=True),
            fuel_reserve_capacity=_number(capacity.get("Reserve", 0), "Loadout.FuelCapacity.Reserve"),
            optimal_mass=opt, max_fuel_per_jump=maxfuel, fuel_multiplier=fuelmul, fuel_power=fuelpower,
            fsd_symbol=symbol, guardian_boost=guardian, scoop_rate=scoop_rate,
            neutron_multiplier=6.0 if special else 4.0,
            source_timestamp=str(loadout.get("timestamp", "")), warnings=warnings,
        )

