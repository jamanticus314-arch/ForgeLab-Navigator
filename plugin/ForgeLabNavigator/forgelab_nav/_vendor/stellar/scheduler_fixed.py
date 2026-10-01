"""Exact integer helpers inlined in, or called by, the boxel scheduler.

Every function names its RVA range. Register widths are kept explicit:
U32/U64 masks model wraparound, s32() models signed 32-bit compares.
"""
pass  # vendored: _bootstrap path setup removed  # noqa: F401  (vendor paths)
from .formation.accepted.recovered_rng import minstd_step, mix64to32
from .scheduler_constants import SchedulerGap

U16 = 0xFFFF
U32 = (1 << 32) - 1
U64 = (1 << 64) - 1


def s32(value):
    value &= U32
    return value - (1 << 32) if value & 0x80000000 else value


def s64(value):
    value &= U64
    return value - (1 << 64) if value >> 63 else value


def tz_sar5(value):
    """neg / sar 5 / neg idiom on a 32-bit register (round toward zero).

    Kept literal so that 0x80000000 follows the native register result.
    """
    value &= U32
    if value & 0x80000000:
        return s32(-(s32(-value) >> 5))
    return value >> 5


# --- boxel key coordinate fields --------------------------------------------

def key_x(key):
    level = key & 7
    return ((key >> ((level * 0xFE + 0x1E) & 0xFF & 63)) << level) & 0x3FFF


def key_y(key):
    level = key & 7
    return ((key >> ((0x11 - level) & 0xFF & 63)) << level) & 0x1FFF


def key_z(key):
    level = key & 7
    return ((key >> 3) << level) & 0x3FFF


def address_level_mask(address):
    """(1 << (44 - 3*level)) - 1, as at 0x3c34e8e and 0x4ca001f."""
    shift = (((address & 7) * 0xFD + 0x2C) & 0xFF) & 63
    return ((1 << shift) - 1) & U64


def sequence_address(key, sequence):
    """0x3c350a6..0x3c350d1 (also 0x3c39a6a in the constructor)."""
    shift = (((key & 7) * 0xFD + 0x2C) & 0xFF) & 63
    return (((sequence << shift) & U64) | key) & U64


def minstd_seed(address):
    """0x3c35120..0x3c35167: Wang mix, zero replaced by 1."""
    return mix64to32(address) or 1


# --- 0x3c570e0: boxel key containing a point --------------------------------

def boxel_key_at(x, y, z, level):
    x &= U32
    y &= U32
    z &= U32
    if s32(x) < 0 or x >= 0x500000 or s32(y) < 0 or y >= 0x280000 \
            or s32(z) < 0 or z >= 0x500000:
        return 0
    keep = ~((1 << level) - 1) & U64
    r10 = (14 - level) & U64
    shift_x = ((((r10 & 0xFF) - level) & 0xFF) + 0x10) & 63
    xq = ((x * 0xCCCCCCCD) >> 32) >> 8
    yq = ((y * 0xCCCCCCCD) >> 32) >> 8
    zq = ((z * 0xCCCCCCCD) >> 32) >> 8
    out = (((xq & keep) >> level) << shift_x) & U64
    out |= (((yq & keep) >> level) << ((r10 + 3) & 63)) & U64
    out |= ((((zq & keep) >> level) << 3) & U64)
    return (out | level) & U64


# --- Q12 mass accessor inlined at 0x3c34629..0x3c34704 ------------------------

def mass_q12(q8, stellar_class):
    """Same instructions as accessor 0x34ac880 (mass_accessor.py)."""
    x = (q8 & U16) << 4
    if stellar_class != 42:
        return x
    if not x:
        return 0x1000
    k = ((((x << 12) * 0xB8AC68F5FDA7CFAB) >> 64) >> 11) & ~0xFFF & U64
    exponent = s32(k >> 12)
    if exponent >= 64:
        return 0xFFFFFFFF
    residual = (x - (((k * 0xB17) & U64) >> 12)) & U64
    numerator = (residual << 12) & U64
    term = total = denominator = 0x1000
    while True:
        ratio = numerator // denominator
        denominator += 0x1000
        term = ((term * ratio) & U64) >> 12
        total = (total + term) & U64
        if term <= 1:
            break
    if exponent < 0:
        return total & U32
    if (((total << exponent) & U64) >> exponent) != total:
        return 0xFFFFFFFF
    return ((total << exponent) & U64) & U32


# --- Q24 exponential shared by 0x3c3499a and 0x3c34d81 ------------------------

def exp_q24(x):
    """Returns (saturated, value) for the unsigned Q24 exp of x (x != 0).

    saturated is True on the exponent >= 64 path or the shift-overflow path;
    the two callers map it differently.
    """
    x &= U64
    rdx = ((((x << 24) & U64) * 0x2E2A8F0AD0C075EF) >> 64) >> 21
    rdx &= 0xFFFFFFFFFF000000
    exponent = s32(rdx >> 24)
    if exponent >= 64:
        return True, None
    residual = ((x - (((rdx * 0xB17217) & U64) >> 24)) & U64)
    residual = (residual << 24) & U64
    divisor = term = total = 0x1000000
    while True:
        ratio = residual // divisor
        divisor += 0x1000000
        term = ((term * ratio) & U64) >> 24
        total = (total + term) & U64
        if term <= 1:
            break
    if exponent < 0:
        return False, total
    shift = exponent & 63
    if (((total << shift) & U64) >> shift) != total:
        return True, None
    return False, (total << shift) & U64


def depleted_mass_q24(mass32):
    """0x3c3499a..0x3c34a44: exp of (Q12 mass << 12), capped at 0x78000000."""
    x = ((mass32 & U32) << 12) & U64
    if not x:
        return 0x1000000
    saturated, value = exp_q24(x)
    if saturated or value > 0x78000000:
        return 0x78000000
    return value


def is_heavy_type44(q8):
    """0x3c34d81..0x3c34e21: exp(q8 << 16) > 0xc8000000."""
    x = (q8 & U16) << 16
    if not x:
        return False
    saturated, value = exp_q24(x)
    return saturated or value > 0xC8000000


# --- 0x3c386a0: plane massive-record initializer ------------------------------

def _put(record, offset, size, value):
    record[offset:offset + size] = (value & ((1 << (8 * size)) - 1)).to_bytes(size, 'little')


def _get(record, offset, size):
    return int.from_bytes(record[offset:offset + size], 'little')


def massive_initialize(record, seed, radius_lo=0x640000, radius_hi=0xE10000):
    """Mutates record (bytearray 0x60) and returns the final MINSTD state."""
    _put(record, 0x38, 4, 0xF4240000)
    _put(record, 0x2C, 4, 0x320000)
    _put(record, 0x20, 8, U64)
    _put(record, 0x40, 2, 0x2C)
    state = minstd_step(seed)
    quotient7 = ((((state - ((state * 0x24924925) >> 32)) & U32) >> 1)
                 + ((state * 0x24924925) >> 32)) >> 2
    record[0x58] = 4
    _put(record, 0x30, 4, (state - quotient7 * 7 + 3) & U32)
    state = minstd_step(state)
    span = (radius_hi - radius_lo) & U32
    value = state % span if span else state
    _put(record, 0x34, 4, (value + radius_lo) & U32)
    state = minstd_step(state)
    quotient = ((state * 0xA003C017) >> 32) >> 12
    residue = (state - quotient * 0x1999) & U32
    factor = ((((residue + 0x7333) & U32) << 16) >> 15) & U32
    radius = _get(record, 0x34, 4)
    product = ((factor * radius) & U64) >> 15
    high = (product & U32) >> 11
    word52 = high & U16
    _put(record, 0x52, 2, word52)
    scaled = ((((radius << 17) & U64) >> 15) & U32)
    _put(record, 0x50, 2, (((scaled - ((word52 << 11) & U32)) & U32) >> 11) & U16)
    # Q8 natural-log of the sampled Q8 mass, 0x3c3880a..0x3c388d3.
    value = _get(record, 0x28, 2)
    if value == 0:
        raise SchedulerGap('0x3c38826: zero Q8 mass never leaves the native log loop')
    exponent = 0
    while value < 0x100:
        value = ((value & U32) * 0xADF85459) >> 30
        exponent -= 1
        value &= U32
    while value >= 0x2B8:
        value = (((((value & U32) << 30) * 0x2F16AC6C409FB6A9) >> 64) >> 29) & U32
        exponent += 1
    ratio = ((((value - 0x100) & U32) << 8) // ((value + 0x100) & U32))
    square = (((ratio & U32) * (ratio & U32)) & U64) >> 8 & U32
    term = ratio
    total = 0
    denominator = 0x100
    while True:
        term32 = term & U32
        step = ((term32 << 8) // denominator)
        denominator = (denominator + 0x200) & U32
        term = ((square * term32) & U64) >> 8
        total = (step + total) & U32
        if (step & U32) <= 1:
            break
    word = ((((exponent & U16) * 0x80) & U32) + total) & U16
    _put(record, 0x28, 2, (word + word) & U16)
    return state
