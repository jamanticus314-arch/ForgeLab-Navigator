"""Literal per-primary construction from 0x3c399e0 and 0x3c3bf60.

Pinned image e6be8bbe04e6a7ae226d4318945af7f367de13dc5a007a261964d9ba8144e988.
No executable, emulator, observation, or planetary-key access at runtime.
"""
from dataclasses import dataclass, field
import struct
import json
from pathlib import Path
from functools import lru_cache
pass  # vendored: _bootstrap path setup removed
from .formation.accepted.recovered_rng import stellar_minstd_seed, minstd_step, core_record_address
from .formation.stellar_record import ordinary, young, flag_trial, flags, setflags, tables, log_fixed, exp_fixed, lifetime_and_duration
from .formation.stellar_evolution import late_ordinary, remnant, giant

MASS_BOUNDS = (2, 51, 115, 230, 460, 1560, 3840, 7680, 30720)
MASK64 = (1 << 64) - 1


@lru_cache(None)
def engine_tables():
    return json.loads((Path(__file__).parent/'primary_tables.json').read_text())


class Minstd:
    def __init__(self, seed):
        self.state = seed or 1
        self.cursor = 0

    def word(self):
        self.state = minstd_step(self.state)
        self.cursor += 1
        return self.state


@dataclass
class Occupied:
    cells: set = field(default_factory=set)
    last_cell: int = 0
    special_records: list = field(default_factory=list)


def u16(record, offset):
    return struct.unpack_from('<H', record, offset)[0]


def put16(record, offset, value):
    struct.pack_into('<H', record, offset, value & 65535)


def put32(record, offset, value):
    struct.pack_into('<I', record, offset, value & 0xffffffff)


def sample16(rng, lower, upper):
    """Native u32 modulo followed by the final 16-bit truncation.

    Equal endpoints still consume a word and retain its low half; call sites
    that avoid this behavior explicitly bypass this function.
    """
    word = rng.word()
    width = (upper - lower) & 0xffffffff
    return ((word % width if width else word) + lower) & 65535


def mass_gate(address, mass):
    if mass <= 368:
        return False
    level = address & 7
    key = address & ((1 << (44 - 3 * level)) - 1)
    x = ((key >> (30 - 2 * level)) << level) & 0x3fff
    z = ((key >> 3) << level) & 0x3fff
    width = 0xaf00 if mass > 0x1000 else 0x3200
    return abs((5*x-0x619e)*64) < width or abs((5*z-0x2f12)*64) < width


def special(record, rng):
    """0x3c37680: type 44, logarithmic mass and shell fields."""
    setflags(record, (flags(record) & 0xffec) | 0x2c)
    radius = rng.word() % 0x31c000 + 0x4000
    put32(record, 0x34, radius)
    coefficient = 2 * (rng.word() % 0x1999 + 0x7333)
    shell = (((coefficient * radius) >> 15) & 0xffffffff) >> 11
    put16(record, 0x52, shell)
    put16(record, 0x50, ((radius * 4 - ((shell & 65535) << 11)) & 0xffffffff) >> 11)
    put16(record, 0x28, log_fixed(u16(record, 0x28), 8))
    record[0x58] = rng.word() & 1


def extra(record, rng):
    """0x3c378c0: type 45, a separately emitted compact remainder."""
    setflags(record, (flags(record) & 0xffed) | 0x2d)
    put32(record, 0x30, rng.word() % 7 + 3)
    radius = rng.word() % 0x17334 + 0xccc
    put32(record, 0x34, radius)
    coefficient = 2 * (rng.word() % 0x1999 + 0x7333)
    shell = (((coefficient * radius) >> 15) & 0xffffffff) >> 11
    put16(record, 0x52, shell)
    put16(record, 0x50, ((radius * 4 - ((shell & 65535) << 11)) & 0xffffffff) >> 11)
    put16(record, 0x28, log_fixed(u16(record, 0x28), 8))
    record[0x58] = 3


def diffuse(record, rng, lower_radius, upper_radius):
    """0x3c386a0, large type44 central-plane spatial influence constructor."""
    put32(record, 0x38, 0xf4240000)
    put32(record, 0x2c, 0x320000)
    struct.pack_into('<Q', record, 0x20, MASK64)
    setflags(record, 44)
    record[0x58] = 4
    put32(record, 0x30, rng.word() % 7 + 3)
    width = (upper_radius-lower_radius) & 0xffffffff
    word = rng.word()
    radius = ((word % width if width else word) + lower_radius) & 0xffffffff
    put32(record, 0x34, radius)
    coefficient = 2 * (rng.word() % 0x1999 + 0x7333)
    shell = (((coefficient*radius) >> 15) & 0xffffffff) >> 11
    put16(record, 0x52, shell)
    put16(record, 0x50, ((radius*4-((shell & 65535) << 11)) & 0xffffffff) >> 11)
    put16(record, 0x28, log_fixed(u16(record, 0x28), 8))


def construct(record, rng, allow_special=True, inherit_flag=False, mode=False):
    """Full address-aware dispatcher 0x3c3bf60, mutating the supplied record."""
    address = struct.unpack_from('<Q', record)[0]
    mass = u16(record, 0x28)
    record[0x58] = 5
    put32(record, 0x38, 0xf4240000)
    put32(record, 0x2c, 0x320000)
    setflags(record, 0)
    struct.pack_into('<Q', record, 0x20, MASK64)
    if not mass:
        return
    if mass <= 10:
        ordinary(record, rng)
        setflags(record, (flags(record) & 0xffee) | 0x2e)
    if mass > 0x4600 and allow_special:
        cutoff = ((13 if mode else 655) if mass > 0x5a00 else
                  (9 if mode else 327))
        if rng.word() & 65535 < cutoff:
            special(record, rng)
            return
    if mass_gate(address, mass):
        mass = (rng.word() & 255) + 25
        put16(record, 0x28, mass)
        put32(record, 0x34, 0x8000)
        put32(record, 0x30, 1)
    age = u16(record, 0x3c)
    index = 0 if mass <= 0xcc else min(35, ((mass - 0xcc) * 10) >> 8)
    threshold = tables()['constants']['0x5fdbb50'][index] if mass < 1101 else 0
    if threshold and age < threshold:
        young(record, rng)
        return
    if not threshold and age < 100 and rng.word() % 100 < 10:
        put16(record, 0x3c, 1)
        young(record, rng)
        return
    if mass < 238:
        ordinary(record, rng)
        flag_trial(record, rng)
        return
    lifetime, duration = lifetime_and_duration(mass)
    if inherit_flag:
        age = rng.word() % (lifetime + 1) if age != lifetime else 0
        put16(record, 0x3c, age)
    if age < lifetime:
        if ((lifetime - age) << 18) // lifetime >= 0x3333:
            ordinary(record, rng)
        else:
            late_ordinary(record, rng)
        flag_trial(record, rng)
    elif not inherit_flag and age >= lifetime + duration:
        remnant(record, rng, lifetime)
    else:
        giant(record, rng, lifetime)
        flag_trial(record, rng)


def pack_cell(x, y, z):
    return ((((x & 0xfc1f) | ((y << 5) & 65535)) & 0x83ff) | (z << 10)) & 65535


def unpack_cell(cell):
    return cell & 31, (cell >> 5) & 31, (cell >> 10) & 31


def placement(rng, level, category, spacing, grid, occupied):
    nearby = level < 6 and rng.word() % 100 < 50 and category != 0
    near_attempts = 0
    selected = None
    if nearby:
        previous = unpack_cell(occupied.last_cell)
        limits = [(max(0, value-3), grid if value >= ((grid-3) & 65535) else value+3)
                  for value in previous]
        while True:
            near_attempts += 1
            xyz = tuple(sample16(rng, lo, hi if hi != lo else lo+1) for lo, hi in limits)
            if xyz != previous:
                break
            if near_attempts > 100000:
                raise RuntimeError('native nearby placement did not leave its preceding cell')
        cell = pack_cell(*xyz)
        if cell not in occupied.cells:
            selected = xyz
            # Literal 3c2b740 is erase, although this branch just proved absent.
            occupied.cells.discard(cell)
            occupied.last_cell = cell
    random_attempts = 0
    if selected is None:
        while True:
            random_attempts += 1
            cell = pack_cell(*(sample16(rng, 0, grid) for _ in range(3)))
            if cell not in occupied.cells or random_attempts == 5:
                break
        occupied.cells.add(cell)
        occupied.last_cell = cell
        selected = unpack_cell(cell)
    half = spacing >> 1
    xyz = []
    for cell_coord in selected:
        low = ((((cell_coord << 5) & 65535) * half) >> 5) & 65535
        high = (((((cell_coord + 1) << 5) & 65535) * half) >> 5) & 65535
        xyz.append(min(320 << level, sample16(rng, low, high)))
    return tuple(xyz), dict(cell=occupied.last_cell, near_attempts=near_attempts,
                           random_attempts=random_attempts)


def _base_position(address):
    level = address & 7
    return tuple(320 * value for value in
                 (((address >> (30-2*level)) << level) & 0x3fff,
                  ((address >> (17-level)) << level) & 0x1fff,
                  ((address >> 3) << level) & 0x3fff))


def _special_distance(prior, address, local):
    """0x3c31a10 with the global query coordinates passed by 0x3c399e0."""
    base = _base_position(address)
    query = tuple(a+b for a, b in zip(base, local))
    prior_local = struct.unpack_from('<3H', prior, 0x42)
    differences = [2 * abs(a-b) for a, b in zip(prior_local, query)]
    prior_address = struct.unpack_from('<Q', prior)[0]
    key_a = address & ((1 << (44-3*(address & 7))) - 1)
    key_b = prior_address & ((1 << (44-3*(prior_address & 7))) - 1)
    if key_a != key_b:
        prior_base = _base_position(prior_address)
        differences = [v + 2 * abs(a-b) for v, a, b in zip(differences, prior_base, base)]
    return (sum((d*d) >> 6 for d in differences) << 6) & 0xffffffff


def _special_age(record, rng, inherited, prior_records):
    address = struct.unpack_from('<Q', record)[0]
    local = struct.unpack_from('<3H', record, 0x42)
    for prior in prior_records:
        radius = struct.unpack_from('<I', prior, 0x34)[0] << 9
        threshold = (((radius*radius >> 24) * 9) << 20) >> 24
        if inherited or (_special_distance(prior, address, local) << 12) < threshold:
            if rng.word() % 100 < 85:
                age_table = engine_tables()['age_table']
                selected = age_table[rng.word() % 100]
                put16(record, 0x3c, sample16(rng, max(0, selected-66), (selected+66) & 65535))
            break


def build(key, sequence, age_interval, temperature_interval, category=0,
          mass_interval=None, spacing=None, grid=None, occupied=None,
          inherit_flag=0, allow_extra=0, override=None):
    """Return exact emitted bytes and original sampled mass debit.

    ``occupied`` is shared within one generated boxel and is mutated. The native
    argument historically named ``allow_extra`` is unused by this entry point.
    Extra emission is determined by the evolved record and its original mass.
    """
    if occupied is None:
        occupied = Occupied()
    if not isinstance(occupied, Occupied):
        raise TypeError('occupied must preserve cells, last_cell and special_records')
    level = key & 7
    if spacing is None:
        spacing = engine_tables()['spacing'][level*3+category]
    if grid is None:
        grid = (640 << level) // spacing
    record = bytearray(96)
    address = core_record_address(key, sequence)
    struct.pack_into('<Q', record, 0, address)
    put32(record, 0x54, 0xffff0000)
    rng = Minstd(stellar_minstd_seed(address))
    low, high = mass_interval or MASS_BOUNDS[level:level+2]
    if level == 0:
        rng.word()  # 10% preflag trial is overwritten by 3c3bf60.
    mass = sample16(rng, low, high)
    put16(record, 0x28, mass)
    age_low, age_high = age_interval
    branch = rng.word() % 100
    inherited = bool(inherit_flag)
    if branch > 50:
        second = rng.word() % 100
        age = sample16(rng, age_low, age_high) if age_low != age_high else age_low
        if second < 75:
            inherited = True
            age >>= 1
        else:
            age = ((age * 0x1666000 >> 12) & 0xffffffff) >> 12
    else:
        age = sample16(rng, age_low, age_high) if age_low != age_high else age_low
    put16(record, 0x3c, age)
    put16(record, 0x3e, sample16(rng, *temperature_interval))
    position, placement_info = placement(rng, level, category, spacing, grid, occupied)
    struct.pack_into('<3H', record, 0x42, *position)
    _special_age(record, rng, inherited, occupied.special_records)
    seed = rng.word()
    state_after_sampling = rng.state
    stellar_rng = Minstd(seed)
    construct(record, stellar_rng, True, inherited, category == 0)
    final_mass = u16(record, 0x28)
    kind = flags(record) & 63
    new_special = kind == 44 and record[0x58] == 0 and exp_fixed(final_mass << 16, 24) > 0xc8000000
    # 3c30ce0 is called here; delta was already captured before the callback.
    if override is not None:
        override(record)
    if new_special:
        occupied.special_records.append(bytes(record))
    kind = flags(record) & 63
    records = [bytes(record)]
    extra_trial = None
    delta = (mass - final_mass) & 65535
    if mass > 238 and (0x7fffe000000 & (1 << kind)) and 2 <= (mass >> 8) <= 7:
        lifetime, _ = lifetime_and_duration(mass)
        if u16(record, 0x3c) < lifetime+10 and delta and sequence+1 < 1 << (3*level+11):
            # r15 retains the pre-dispatch seed; the trial is an independent step.
            extra_trial = minstd_step(seed) % 100
            if extra_trial < (2 if category == 0 else 10):
                other = bytearray(96)
                struct.pack_into('<Q', other, 0, core_record_address(key, sequence+1))
                struct.pack_into('<Q', other, 0x20, MASK64)
                put16(other, 0x28, delta)
                put32(other, 0x2c, 0x320000)
                put32(other, 0x38, 0xf4240000)
                put32(other, 0x54, 0xffff0000)
                struct.pack_into('<3H', other, 0x42, *position)
                extra(other, stellar_rng)
                records.append(bytes(other))
    return dict(records=records, budget_mass_q8=mass, original_mass_q8=mass,
                state_after_sampling=state_after_sampling, state_after_stellar=stellar_rng.state,
                sampling_draws=rng.cursor, stellar_draws=stellar_rng.cursor,
                inherited=inherited, placement=placement_info, extra_trial=extra_trial,
                occupied_cell_count=len(occupied.cells))


def influenced_placement(rng, level, category, spacing, grid, occupied,
                         cell_lower, cell_upper):
    """0x3c3b179..0x3c3b8d7, clipped placement with 100 collision attempts."""
    nearby = rng.word() % 100 < 50 and category != 0
    selected = None
    if nearby:
        previous = unpack_cell(occupied.last_cell)
        previous = tuple(max(lo, min(hi, value))
                         for lo, hi, value in zip(cell_lower, cell_upper, previous))
        limits = [(max(lo, max(0, value-3)),
                   min(hi, grid-1 if value >= ((grid-3) & 65535) else value+3))
                  for lo, hi, value in zip(cell_lower, cell_upper, previous)]
        xyz = tuple(sample16(rng, lo, hi if lo != hi else lo+1) for lo, hi in limits)
        cell = pack_cell(*xyz)
        if cell not in occupied.cells:
            selected = xyz
            occupied.last_cell = cell
            occupied.cells.discard(cell)
    attempts = 0
    if selected is None:
        while True:
            attempts += 1
            cell = pack_cell(*(sample16(rng, lo, hi) for lo, hi in zip(cell_lower, cell_upper)))
            if cell not in occupied.cells or attempts == 100:
                break
        occupied.cells.add(cell)
        occupied.last_cell = cell
        selected = unpack_cell(cell)
    half = spacing >> 1
    position = []
    for coord in selected:
        low = ((((coord << 5) & 65535) * half) >> 5) & 65535
        high = (((((coord+1) << 5) & 65535) * half) >> 5) & 65535
        position.append(min(320 << level, sample16(rng, low, high)))
    return tuple(position), dict(cell=occupied.last_cell, nearby=nearby, random_attempts=attempts)


def build_influenced(key, sequence, age_interval, temperature_interval, category,
                     mass_interval, spacing, grid, occupied, cell_lower, cell_upper,
                     override=None):
    """0x3c3ad80, the constructor used inside an inherited spatial influence.

    Bounds are integer placement-cell coordinates, upper-exclusive for random
    sampling. The native MT/influence pointers are unused by this function.
    """
    level = key & 7
    record = bytearray(96)
    address = core_record_address(key, sequence)
    struct.pack_into('<Q', record, 0, address)
    put32(record, 0x54, 0xffff0000)
    rng = Minstd(stellar_minstd_seed(address))
    mass = sample16(rng, *mass_interval)
    put16(record, 0x28, mass)
    inherited = rng.word() % 100 < 85
    if rng.word() % 100 < 85:
        selected = engine_tables()['age_table'][rng.word() % 100]
        age = sample16(rng, max(0, selected-66), (selected+66) & 65535)
    else:
        age = sample16(rng, *age_interval) if age_interval[0] != age_interval[1] else age_interval[0]
    put16(record, 0x3c, age)
    put16(record, 0x3e, sample16(rng, *temperature_interval))
    position, placement_info = influenced_placement(rng, level, category, spacing, grid, occupied,
                                                   cell_lower, cell_upper)
    struct.pack_into('<3H', record, 0x42, *position)
    seed = rng.word()
    stellar_rng = Minstd(seed)
    construct(record, stellar_rng, False, inherited, False)
    if override is not None:
        override(record)
    records = [bytes(record)]
    kind = flags(record) & 63
    delta = (mass-u16(record, 0x28)) & 65535
    if mass > 238 and (0x7fffe000000 & (1 << kind)) and 2 <= (mass >> 8) <= 7:
        lifetime, _ = lifetime_and_duration(mass)
        if u16(record, 0x3c) < lifetime+10 and delta and sequence+1 < 1 << (3*level+11):
            other = bytearray(96)
            struct.pack_into('<Q', other, 0, core_record_address(key, sequence+1))
            struct.pack_into('<Q', other, 0x20, MASK64)
            put16(other, 0x28, delta)
            put32(other, 0x2c, 0x320000)
            put32(other, 0x38, 0xf4240000)
            put32(other, 0x54, 0xffff0000)
            struct.pack_into('<3H', other, 0x42, *position)
            extra(other, stellar_rng)
            records.append(bytes(other))
    return dict(records=records, budget_mass_q8=mass, original_mass_q8=mass,
                state_after_sampling=seed, state_after_stellar=stellar_rng.state,
                sampling_draws=rng.cursor, stellar_draws=stellar_rng.cursor,
                inherited=inherited, placement=placement_info,
                occupied_cell_count=len(occupied.cells))
