"""Parent-to-child boxel scheduler, RVA 0x3c341a5..0x3c36726.

Source SHA256: e6be8bbe04e6a7ae226d4318945af7f367de13dc5a007a261964d9ba8144e988

generate_boxel(key, parent, galaxy) executes the native blocks in order. The
caller (0x3c33f60) enters with r12 = rdi = 0x1000000, r14 = 0 and a zeroed
frame tree/counters. Literal providers, ordinary/influenced constructors and
canonical adapter allocation tokens supply the complete legal scheduler path.
See evidence/scheduler-port.md for the implementation and validation ledger.
"""
from dataclasses import dataclass, field
from typing import Optional

pass  # vendored: _bootstrap path setup removed  # noqa: F401
from .formation.accepted.recovered_rng import FrontierMT
from .scheduler_constants import SchedulerGap, MASS_ENDPOINTS, SPACING, INFLUENCE_FRACTION, budget_factor
from .scheduler_fixed import U16, U32, U64, s32, tz_sar5, key_x, key_y, key_z, address_level_mask, sequence_address, minstd_seed, boxel_key_at, mass_q12, depleted_mass_q24, is_heavy_type44, massive_initialize
from .scheduler_context import interval_from_state
from .galaxy_allocator import ShadowAllocator

RECORD_SIZE = 0x60
CONTEXT_READY = 4


def _u16(record, offset):
    return int.from_bytes(record[offset:offset + 2], 'little')


def _u32(record, offset):
    return int.from_bytes(record[offset:offset + 4], 'little')


def _u64(record, offset):
    return int.from_bytes(record[offset:offset + 8], 'little')


def _put(record, offset, size, value):
    record[offset:offset + size] = (value & ((1 << (8 * size)) - 1)).to_bytes(size, 'little')


@dataclass
class InfluenceEntry:
    """One 0x50-byte element of context+0x258 (copied parent -> child)."""
    budgets: list          # +0x00..+0x38, 8 x uint64 Q24, indexed by level
    x: int                 # +0x40 absolute position dwords
    y: int                 # +0x44
    z: int                 # +0x48
    radius: int            # +0x4c

    def copy(self):
        return InfluenceEntry(list(self.budgets), self.x, self.y, self.z, self.radius)

    def to_bytes(self):
        return (b''.join((v & U64).to_bytes(8, 'little') for v in self.budgets)
                + b''.join((v & U32).to_bytes(4, 'little')
                           for v in (self.x, self.y, self.z, self.radius)))


@dataclass
class Boxel:
    key: int
    records: list = field(default_factory=list)            # context+0x30 order
    generated_records: list = field(default_factory=list)  # context+0x98
    depletion_q24: int = 0                                 # context+0xc8
    spacing: int = 0                                       # context+0xd4
    category: int = 0                                      # frame [rbp-0x48]
    constructors: list = field(default_factory=list)
    inherited_metadata: dict = field(default_factory=dict)
    state: int = 0                                         # context+0xd0
    parent: Optional['Boxel'] = field(default=None, repr=False)
    influence: list = field(default_factory=list, repr=False)   # context+0x258
    specials: list = field(default_factory=list, repr=False)    # context+0xb0
    ids: list = field(default_factory=list, repr=False)         # context+0x80
    mt_draw_sites: list = field(default_factory=list, repr=False)
    allocator: object = field(default=None, repr=False)


class _SharedMT:
    """The boxel MT at [rbp+0x1c0], seeded by 0x2013010 with the boxel key."""

    def __init__(self, key, sites):
        self._mt = FrontierMT(key)
        self._sites = sites

    def draw(self, site):
        self._sites.append(site)
        return self._mt.u32()

    def u32(self):
        return self.draw('external')

    def u64(self):
        return (self.u32() << 32) | self.u32()


def _catalogue_cell(record, spacing):
    """0x3c34b2e..0x3c34b82: 16-bit occupancy word of a catalogue record."""
    x = ((_u16(record, 0x42) << 6) // spacing) & U32
    z = ((_u16(record, 0x46) << 6) // spacing) & U32
    y = ((_u16(record, 0x44) << 6) // spacing) & U32
    cell = ((x & U16) >> 5) & 0x1F
    cell |= ((z & 0xFFE0) << 5) & U16
    return (cell | (y & 0x83E0)) & U16


def _register_authored(context, identifier):
    """0x3c34a54..0x3c34c0a: bookkeeping only (0x3c33900 fills a lookup map)."""
    if identifier in context.ids:
        return {'id': identifier, 'registered_in': context.key}
    ancestor = context.parent
    if ancestor is None:
        return {'id': identifier, 'registered_in': None}
    while True:
        if identifier in ancestor.ids:
            return {'id': identifier, 'registered_in': ancestor.key}
        if ancestor.parent is None:
            return {'id': identifier, 'registered_in': context.key}
        ancestor = ancestor.parent


def _new_influence(record):
    """0x3c34518..0x3c3479b."""
    address = _u64(record, 0)
    mass = mass_q12(_u16(record, 0x28), record[0x40] & 0x3F)
    scaled = (mass & U32) << 12
    return InfluenceEntry(
        budgets=[((scaled * f) & U64) >> 24 for f in INFLUENCE_FRACTION],
        x=(key_x(address) * 320 + _u16(record, 0x42)) & U32,
        y=(key_y(address) * 320 + _u16(record, 0x44)) & U32,
        z=(key_z(address) * 320 + _u16(record, 0x46)) & U32,
        radius=_u32(record, 0x34))


def _catalogue_mass_q24(record):
    """0x3c347a8..0x3c34a44: Q24 mass charged for a byte58 == 5 record."""
    stellar_class = _u16(record, 0x40) & 0x3F
    q8 = _u16(record, 0x28)
    if ((stellar_class - 0x2A) & U32) & 0xFFFFFFFD:
        return ((q8 << 4) & U32) << 12
    return depleted_mass_q24(mass_q12(q8, stellar_class))


def _range16(first, stop):
    """do { ... } while (++v != stop) after a first != stop pre-check."""
    first &= U16
    stop &= U16
    if first == stop:
        return
    value = first
    while True:
        yield value
        value = (value + 1) & U16
        if value == stop:
            return


def _clamped_low(value):
    t = tz_sar5(value)
    return t & U32 if t > 0 else 0


def _clamped_high(value, grid):
    t = tz_sar5(value)
    return grid if t > grid else t & U32


def _ancestor_occupancy(context, ancestor, cells, grid):
    """0x3c3537c..0x3c358a0: cells covered by an ancestor's byte58 == 5 records."""
    key = context.key
    half = context.spacing >> 1
    dx = ((key_x(key) - key_x(ancestor.key)) * 320) & U32
    dy = ((key_y(key) - key_y(ancestor.key)) * 320) & U32
    dz = ((key_z(key) - key_z(ancestor.key)) * 320) & U32
    for record in ancestor.records:
        if record[0x58] != 5:
            continue
        rx = (_u16(record, 0x42) + dx) & U32
        ry = (_u16(record, 0x44) + dy) & U32
        rz = (_u16(record, 0x46) + dz) & U32
        extent = ((ancestor.spacing << 10) & U32) >> 11

        def inside(v):
            return tz_sar5((extent + v) & U32) > 0 and s32((v - extent) & U32) < half
        if not (inside(rx) and inside(ry) and inside(rz)):
            continue
        ratio = (((ancestor.spacing << 6) & U32) // context.spacing) & U32
        width = ((((ratio & U16) >> 1) - 0x20) & U32)

        def centre(v):
            n = s32(v) << 5
            return (abs(n) // half) * (-1 if n < 0 else 1) & U32
        cx, cy, cz = centre(rx), centre(ry), centre(rz)
        x_lo = _clamped_low((cx - width) & U32)
        x_hi = _clamped_high((cx + width) & U32, grid)
        y_lo = _clamped_low((cy - width) & U32)
        y_hi = _clamped_high((cy + width) & U32, grid)
        z_lo = _clamped_low((cz - width) & U32)
        z_hi = _clamped_high((cz + width) & U32, grid)
        for x in _range16(x_lo, x_hi):
            for y in _range16(y_lo, y_hi):
                for z in _range16(z_lo, z_hi):
                    cell = ((((y << 5) & U16) | (x & 0xFC1F)) & 0x83FF) | ((z << 10) & U16)
                    cells.add(cell & U16)


def generate_boxel(key, parent, galaxy, constructor=None):
    """Execute 0x3c341a5..0x3c36726 for one boxel; parent must already be ready."""
    key &= U64
    level = key & 7
    if parent is not None and parent.state != CONTEXT_READY:
        raise ValueError('parent context has not completed (context+0xd0 != 4)')
    context = Boxel(key=key, parent=parent)
    catalogue_records = galaxy.catalogue_records(key)
    context.allocator = ShadowAllocator.for_boxel(
        key, parent.allocator if parent is not None else None, catalogue_records)
    sites = context.mt_draw_sites
    meta = context.inherited_metadata

    # 0x3c341a5..0x3c34293: parent depletion and inherited influence copies.
    remaining_scale = 0x1000000
    if parent is not None:
        remaining_scale = (remaining_scale - parent.depletion_q24) & U64
        context.influence.extend(entry.copy() for entry in parent.influence)
    meta['inherited_influence_count'] = len(context.influence)

    # 0x3c34297..0x3c343ba: density, MT seed, category, budget, spacing, grid.
    density_mass = ((galaxy.density(key) & U64) << 8) & U64
    mt = _SharedMT(key, sites)
    category = galaxy.category(key, mt) & U32
    context.category = category
    budget = (((remaining_scale << 24) & U64) >> 32)
    budget = (budget * (density_mass >> 8)) & U64
    budget = (budget >> 8) & 0xFFFFFFFFFFFF00
    budget_gap = None
    if budget:
        try:
            budget = ((budget * budget_factor(category, level)) & U64) >> 24
        except SchedulerGap as gap:
            budget, budget_gap = None, gap
    mass_lo, mass_hi = MASS_ENDPOINTS[level], MASS_ENDPOINTS[level + 1]
    spacing_index = 3 * level + category
    if spacing_index >= len(SPACING):
        raise SchedulerGap(f'spacing word 0x5e9b270[{spacing_index}] (category {category:#x}) '
                           'lies outside the captured 24-word table')
    spacing = SPACING[spacing_index]
    context.spacing = spacing
    grid = ((((((0x280 << level) & U32) << 6) // spacing) & U32) >> 6) & U16
    special_density = galaxy.special_density(key) & U32   # manager vtable +0x98

    # 0x3c343c0..0x3c34489: level-6 special count.
    special_count = 0
    if level == 6 and special_density > 0x147:
        y = key_y(key)
        distance = (y - 0xFFF) & U32 if y >= 0xFFF else (0xFFF - y) & U32
        distance = min(distance >> 6, 2)
        weight = ((0x8000 - ((((distance << 15) & U32) >> 1))) & U32)
        weight = (((weight * special_density) & U64) >> 15) & U32
        low = ((((weight >> 1) * 0xC8000) & U64) >> 15 & U32) >> 15
        high = (((weight * 0xC8000) & U64) >> 15 & U32) >> 15
        if high:
            word = mt.draw('0x3c34465')
            span = (high - low) & U32
            quotient = (word // span) & U16 if span else 0
            special_count = (low - (((span & U16) * quotient) & U32) + word) & U16
    meta['special_count'] = special_count

    # 0x3c344c1..0x3c34ee9: catalogue records of this boxel.
    cells = set()
    last_cell = 0
    consumed = 0
    registrations = []
    for raw in catalogue_records:
        record = bytearray(raw)
        if len(record) != RECORD_SIZE:
            raise SchedulerGap(f'catalogue record has {len(record)} bytes; the native '
                               'iterator (0x4c9ffb0) strides 0x60-byte sdbx records')
        if (_u64(record, 0) & address_level_mask(_u64(record, 0))) != key:
            raise ValueError('catalogue_records returned a record outside this boxel')
        record[0x5A] = 0
        if record[0x58] == 0:
            context.influence.append(_new_influence(record))
        elif record[0x58] == 5:
            consumed = (consumed + _catalogue_mass_q24(record)) & U64
        identifier = s32(_u32(record, 0x24))
        if identifier == -1:
            last_cell = _catalogue_cell(record, spacing)
            cells.add(last_cell)
        else:
            registrations.append(_register_authored(context, identifier & U32))
        context.ids.append(_u32(record, 0x20))
        context.records.append(record)
        if (record[0x40] & 0x3F) == 0x2C and is_heavy_type44(_u16(record, 0x28)) \
                and record[0x58] == 0:
            context.specials.append(record)
    catalogue_count = len(context.records)
    meta.update(catalogue_count=catalogue_count, authored_registrations=registrations,
                density_mass_q8=density_mass, catalogue_consumed_q24=consumed,
                spacing=spacing, grid=grid)

    # 0x3c34f0d..0x3c34f3c: empty boxel early return.
    if density_mass == 0 and special_count == 0:
        if parent is not None:
            context.depletion_q24 = (context.depletion_q24 + parent.depletion_q24) & U64
        context.state = CONTEXT_READY
        meta['exit'] = '0x3c34f3c'
        return context

    sequence = catalogue_count
    generated = context.generated_records

    # 0x3c34f41..0x3c35262: level-7 galactic-plane massive records.
    if level == 7:
        x_field = (key >> 9) & 0x3F80
        z_field = (key << 4) & 0x3F80
        if boxel_key_at((x_field * 320) & U32, 0x13FF60, (z_field * 320) & U32, 7) == key:
            y = key_y(key)
            top = (y * 0xFFFFFEC0) & U32
            bottom = (top + 0x13FA60) & U32
            if s32(bottom) < 0:
                bottom = 0
            top = (top + 0x140460) & U32
            if s32(top) > 0xA000:
                top = 0xA000
            word = mt.draw('0x3c35003')
            scaled = ((((word + 0x28) & U32) << 5) & U32)
            scaled = (scaled - ((((word * 0x88888889) >> 32) >> 5) * 0x780)) & U32
            metallicity = galaxy.metallicity(key) & U32   # +0x90 -> 0x4ca2660
            count = ((((scaled * metallicity) & U64) >> 15) & U32) >> 5
            meta['massive_count'] = count
            span = (mass_hi - mass_lo) & U32
            for _ in range(count):
                record = bytearray(RECORD_SIZE)   # 0x3c42400 slot, assumed zeroed
                _put(record, 0x54, 4, 0xFFFF0000)
                address = sequence_address(key, sequence)
                sequence += 1
                _put(record, 0, 8, address)
                word = mt.draw('0x3c350e7')
                quotient = (word // span) & U16 if span else 0
                _put(record, 0x28, 2, word - (((span & U16) * quotient) & U32) + mass_lo)
                massive_initialize(record, minstd_seed(address), 0x640000, 0xE10000)
                word = mt.draw('0x3c35179')
                px = ((((((word * 0xCCCCCCCD) >> 32) >> 10) & U16) * 0x300 + word) & U16) << 5
                high_y, low_y = tz_sar5(top), tz_sar5(bottom)
                word = mt.draw('0x3c351d3')
                span_y = ((high_y & U16) - (low_y & U16)) & U32
                quotient = (word // span_y) & U16 if span_y else 0
                py = ((word - (((span_y & U16) * quotient) & U32) + low_y) & U16) << 5
                word = mt.draw('0x3c35218')
                pz = ((((((word * 0xCCCCCCCD) >> 32) >> 10) & U16) * 0x300 + word) & U16) << 5
                _put(record, 0x42, 2, px)
                _put(record, 0x44, 2, py)
                _put(record, 0x46, 2, pz)
                generated.append(record)

    # 0x3c3526f..0x3c352b3
    min_mass = mass_lo << 16
    max_sequence = 1 << ((level * 3 + 11) & 63)
    hi_mass = mass_hi << 16
    if budget is None:
        raise budget_gap   # first native use of [rbp+0x48] is 0x3c352b0
    meta.update(budget_q24=budget, max_sequence=max_sequence)
    if consumed < budget:
        remaining = (budget - consumed) & U64
        _generate(context, parent, galaxy, constructor, mt, cells, last_cell, meta,
                  level, category, spacing, grid, density_mass, special_count,
                  catalogue_count, sequence, min_mass, max_sequence, hi_mass,
                  mass_lo, mass_hi, remaining, consumed)
        consumed = meta['consumed_q24']
    else:
        meta['consumed_q24'] = consumed

    # 0x3c36635..0x3c3671b: publish generated records and depletion.
    context.records.extend(generated)
    if density_mass:
        if density_mass > 0x989680000000:
            depletion = (((((consumed & ~0xF) & U64) << 16) & U64)
                         // (density_mass >> 4) << 4) & U64
        else:
            depletion = ((consumed << 24) & U64) // density_mass
        if parent is not None:
            depletion = (depletion + parent.depletion_q24) & U64
        context.depletion_q24 = min(depletion, 0x1000000)
    context.state = CONTEXT_READY
    meta['exit'] = '0x3c36726'
    return context


def _generate(context, parent, galaxy, constructor, mt, cells, last_cell, meta,
              level, category, spacing, grid, density_mass, special_count,
              catalogue_count, sequence, min_mass, max_sequence, hi_mass,
              mass_lo, mass_hi, remaining, consumed):
    key = context.key
    generated = context.generated_records

    # 0x3c352b9..0x3c358f6: inherited type-44 records and ancestor occupancy.
    ancestor = parent
    while ancestor is not None:
        context.specials.extend(ancestor.specials)
        _ancestor_occupancy(context, ancestor, cells, grid)
        ancestor = ancestor.parent

    # 0x3c35914..0x3c3602f: age and temperature intervals.
    interval = interval_from_state(key, category, mt.draw, mass_hi)
    meta['interval'] = interval
    age = (interval['age_lo'], interval['age_hi'])
    temperature = tuple(s32(v << 16) >> 16 for v in (interval['temperature_lo'],
                                                     interval['temperature_hi']))

    # 0x3c36036..0x3c36054: manager vtable +0x40 byte stored at tree+0x3c.
    tree_byte = int(galaxy.has_overrides(key))
    capacity = ((((grid * grid) & U32) & U16) * grid) & U32
    cap16 = capacity & U16
    meta['cell_capacity'] = capacity

    state = {'occupied': None, 'module': constructor}

    def occupied():
        if state['occupied'] is None:
            module = state['module']
            if module is None:
                from . import primary_constructor as module
                state['module'] = module
            occ = module.Occupied(cells=cells, last_cell=last_cell,
                                  special_records=context.specials)
            state['occupied'] = occ
        return state['occupied']

    def occupied_size():
        occ = state['occupied']
        return len(cells) if occ is None else len(occ.cells)

    def call(kind, seq, mass, allow_extra, inherit_flag, extra=None):
        occ = occupied()
        module = state['module']
        args = (key, seq, age, temperature, category, mass, spacing, grid, occ)
        override = (lambda record: context.allocator.apply_override(galaxy, record)) if tree_byte else None
        if kind == 'influence':
            builder = getattr(module, 'build_influenced', None)
            if builder is None:
                raise SchedulerGap(
                    'influence constructor 0x3c3ad80 (called at 0x3c365b7 for inherited/own '
                    'influence entries overlapping this boxel) has no port: '
                    'primary_constructor.build_influenced is not provided')
            bounds = extra['bounds']
            result = builder(*args, cell_lower=tuple(v[0] for v in bounds),
                             cell_upper=tuple(v[1] for v in bounds), override=override)
        else:
            result = module.build(*args, inherit_flag=inherit_flag, allow_extra=allow_extra,
                                  override=override)
        records = [bytearray(r) for r in result['records']]
        for record in records:
            if len(record) != RECORD_SIZE:
                raise SchedulerGap('constructor returned a record that is not 0x60 bytes')
        generated.extend(records)
        budget_word = result['budget_mass_q8'] & U16
        trace = {'kind': kind, 'sequence': seq, 'mass_interval': list(mass),
                 'age_interval': list(age), 'temperature_interval': list(temperature),
                 'category': category, 'allow_extra': allow_extra,
                 'inherit_flag': inherit_flag, 'records': len(records),
                 'budget_mass_q8': budget_word}
        if extra:
            trace['bounds'] = extra['bounds']
        context.constructors.append(trace)
        return budget_word

    # 0x3c36079..0x3c36151: level-6 special records.
    if sequence < max_sequence:
        while special_count and occupied_size() != cap16:
            call('special', sequence, (0x400, 0x1800), 0, 1)
            special_count = (special_count + 0xFFFF) & U16
            sequence = catalogue_count + len(generated)
            if sequence >= max_sequence:
                break

    if density_mass:
        # 0x3c36163..0x3c3628f: budgeted primary records.
        stop = False
        hi_word = mass_hi
        upper = hi_mass
        if sequence < max_sequence:
            while True:
                if min_mass >= remaining or occupied_size() == cap16 or stop:
                    break
                if upper > remaining:
                    if level:
                        stop = True
                    else:
                        upper = remaining
                        hi_word = (remaining >> 16) & U16
                        if hi_word <= mass_lo or hi_word < 12:
                            break
                ratio = ((((remaining << 24) & U64) // min_mass) >> 24)
                flag = (ratio & 0xFF) if ratio == 0 else 0
                allow_extra = flag & 0xFF if flag & 0xFF else 0
                used = call('main', sequence, (mass_lo, hi_word), allow_extra, 0)
                consumed = (consumed + (used << 16)) & U64
                remaining = (remaining - (used << 16)) & U64
                sequence = catalogue_count + len(generated)
                if sequence >= max_sequence:
                    break

        # 0x3c36293..0x3c3661a: influence entries overlapping this boxel.
        kx, ky, kz = (key_x(key) * 320) & U32, (key_y(key) * 320) & U32, (key_z(key) * 320) & U32
        scale32 = (grid << 5) & U32
        size = (0x140 << level) & U32

        def scale(v):
            t = ((((v & U32) * scale32) & U64) >> 5) & U32
            return (((t << 5) // size) & U32) >> 5

        for entry in list(context.influence):
            r = entry.radius
            x_max = ((((entry.x << 10) & U32) + r) & U32) >> 10
            y_max = ((((entry.y << 10) & U32) + r) & U32) >> 10
            z_max = ((((entry.z << 10) & U32) + r) & U32) >> 10
            x_min = (entry.x - (r >> 10)) & U32
            y_min = (entry.y - (r >> 10)) & U32
            z_min = (entry.z - (r >> 10)) & U32
            if x_max < kx or y_max < ky or z_max < kz:
                continue
            bx, by, bz = (size + kx) & U32, (size + ky) & U32, (size + kz) & U32
            if x_min > bx or y_min > by or z_min > bz:
                continue
            x_hi = scale(size if x_max > bx else (x_max - kx) & U32)
            y_hi = scale(size if y_max > by else (y_max - ky) & U32)
            z_hi = scale(size if z_max > bz else (z_max - kz) & U32)
            x_lo = scale(0 if x_min < kx else (x_min - kx) & U32)
            y_lo = scale(0 if y_min < ky else (y_min - ky) & U32)
            z_lo = scale(0 if z_min < kz else (z_min - kz) & U32)
            if (x_lo & U16) == (x_hi & U16) or (y_lo & U16) == (y_hi & U16) \
                    or (z_lo & U16) == (z_hi & U16):
                continue
            if sequence >= max_sequence:
                continue
            bounds = ((x_lo & U16, x_hi & U16), (y_lo & U16, y_hi & U16), (z_lo & U16, z_hi & U16))
            while True:
                if min_mass >= entry.budgets[level] or occupied_size() == cap16:
                    break
                used = call('influence', sequence, (mass_lo, mass_hi), 0, 0,
                            extra={'entry': entry, 'level': level, 'bounds': bounds})
                value = entry.budgets[level]
                left = (value - (used << 16)) & U64
                entry.budgets[level] = 0 if used > (value >> 16) else left
                sequence = catalogue_count + len(generated)
                if sequence >= max_sequence:
                    break

    occ = state['occupied']
    meta['occupied_cells'] = len(cells) if occ is None else len(occ.cells)
    meta['consumed_q24'] = consumed
