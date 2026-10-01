"""Exact scalar interval supplier, RVAs 0x3c35914..0x3c3602f.

Adapted from primary-machinery-2026-09-16/recovered_context.py (natively
validated there on 1,980 fixtures). Changes: tables are the literal copies
in scheduler_constants, every MT draw goes through draw(site), the age/
temperature words are returned exactly as the frame stores them, and table
reads outside the captured words fail instead of raising IndexError.
"""
from .scheduler_constants import AGE_TABLES, TEMPERATURE_TABLES, read_u16
from .scheduler_fixed import U32, U64, s32, s64, key_x, key_y, key_z

U16 = 0xFFFF


def _trunc(a, b):
    """Signed idiv quotient (truncates toward zero)."""
    return (abs(a) // abs(b)) * (-1 if (a < 0) != (b < 0) else 1)


def exp_fixed(exponent, q, ln2):
    """Shared signed fixed-point exp (0x3c35983..0x3c35a7d, 0x3c35ca2..0x3c35d99)."""
    one = 1 << q
    if not exponent:
        return one
    magnitude = abs(s32(exponent))
    n = magnitude // ln2
    if n >= 64:
        result = (1 << 63) - 1
    else:
        remainder = magnitude - n * ln2
        term = result = one
        denominator = one
        while True:
            ratio = _trunc(remainder << q, denominator)
            denominator += one
            term = s64(term * ratio) >> q
            result = s64(result + term)
            if abs(term) <= 1:
                break
        shifted = s64(result << (n & 63))
        result = shifted if shifted >> (n & 63) == result else (1 << 63) - 1
    return _trunc(1 << (2 * q), result) if s32(exponent) < 0 else result


def height_factor(key):
    """Signed Q8 value stored at [rbp-0x38]."""
    y = key_y(key)
    r = s32(-((y - 4096) ** 2) * 256)
    r = s32((r << 7) >> 8)
    high = (r * 256 * 0x2ECFB9C869536203) >> 64
    quotient = high >> 14
    quotient += int(quotient < 0)
    return s32(exp_fixed(s32(quotient), 8, 177))


def log_q18(x):
    one = 1 << 18
    k = 0
    while x < one:
        x = (x * 0xADF85459) >> 30
        k -= 1
    while x >= 0xADF86:
        x = ((((x << 30) & U64) * 0x2F16AC6C409FB6A9) >> 64) >> 29
        k += 1
    t = ((x - one) << 18) // (x + one)
    square = (t * t) >> 18
    term = t
    total = 0
    denominator = one
    while True:
        value = (term << 18) // denominator
        term = (term * square) >> 18
        total += value
        denominator += 2 * one
        if value <= 1:
            break
    return s32(2 * total + ((k << 18) & U32))


def lifetime_limit(mass_upper):
    """[rbp-0x30] after 0x3c35dc7."""
    x = ((1 << 26) // mass_upper) & U32
    if x == 1 << 18:
        power = 1 << 18
    elif not x:
        power = 0
    else:
        power = exp_fixed(s32((log_q18(x) * 5) >> 1), 18, 0x2C5C8) & U32
    return (((power * 0xABE00000) & U64) >> 18 & U32) >> 18


# 0x3c35dcb: 0x3c3f140 is called with the fixed key 0x4e1a0044b50.
_REFERENCE_X = key_x(0x4E1A0044B50)


def interval_from_state(key, category, draw, mass_upper):
    """Returns the frame words consumed by the three constructor loops.

    draw(site) must return the next shared MT uint32 and log the site.
    mass_upper is the table upper endpoint word ([rbp+0x28]).
    """
    level = key & 7
    h = height_factor(key)
    selector = draw('0x3c35a88') & 0xFF
    if category == 0:
        table, site = 0x5FDB740, '0x3c35ab1'
    elif category == 2:
        table, site = ((0x5FDB9B0, '0x3c35af6') if selector < h
                       else (0x5FDB810, '0x3c35b27'))
    else:
        table, site = 0x5FDB8E0, '0x3c35b58'
    centre = AGE_TABLES[table][draw(site) % 100] & U16
    lo = centre - 2000 if centre >= 2000 else 0
    hi = 13200 if centre > 0x2BC0 else centre + 2000
    for_index = centre
    limit = None
    if level >= 3:
        limit = lifetime_limit(mass_upper)
        x, y, z = key_x(key), key_y(key), key_z(key)
        spatial = (abs(s32((x - _REFERENCE_X) * 320)) < 32000
                   or abs(s32((5 * y - 0x500A) * 64)) < 32000
                   or abs(s32((5 * z - 0x2F12) * 64)) < 32000)
        cap = spatial or draw('0x3c35e53') % 10000 < 2000
        if cap and hi > (limit & U16):
            if not limit & U16:
                lo = hi = for_index = 0
            else:
                sample = draw('0x3c35f1e') % (limit & U16)
                lo = sample >> 1
                hi = (sample + (((limit & U16) - sample) >> 1)) & U16
                for_index = sample
    size = ((((32 - (for_index * 32) // 26400) & U16) * 3200) >> 5) & U16
    size = (size >> 5) & 0xFF
    if category == 2:
        word = draw('0x3c35ec8')
        index = word % size if size else word & 0xFF
        centre_t = (read_u16(0x5FDBDB0, index) - ((h * 36) >> 8)) & U16
    elif category == 0:
        word = draw('0x3c35fa9')
        index = word % size if size else word & 0xFF
        centre_t = read_u16(0x5FDBCE0, index)
    else:
        centre_t = read_u16(0x5FDBE80, draw('0x3c35fea') % 100)
    return {
        'age_lo': lo & U16, 'age_hi': hi & U16,
        'temperature_lo': (centre_t - 25) & U16, 'temperature_hi': (centre_t + 25) & U16,
        'height_factor_q8': h, 'age_centre': centre, 'lifetime_limit': limit,
    }


# Signed view of the TEMPERATURE_TABLES is used only by read_u16's lookup.
assert all(len(v) == 100 for v in list(AGE_TABLES.values()) + list(TEMPERATURE_TABLES.values()))
