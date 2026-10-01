"""Literal PRNG/state-initialization ports from EliteDangerous64.exe.

Source SHA256: e6be8bbe04e6a7ae226d4318945af7f367de13dc5a007a261964d9ba8144e988
See RECOVERY-REPORT.md for call sites, validation, and unresolved chronology.
This module does not infer a body's generation order or select a radius offset.
No dependencies, executable reads, game process access, or import-time work.
"""

import math

U32 = (1 << 32) - 1
U64 = (1 << 64) - 1


def mix64to32(value):
    """Literal uint64 mixer used by the recovered stellar and terrain paths."""
    value &= U64
    value = (~value + (value << 18)) & U64
    value ^= value >> 31
    value = (value * 21) & U64
    value ^= value >> 11
    value = (value * 65) & U64
    return (value ^ (value >> 22)) & U32


def core_record_address(boxel_word, sequence):
    """Native record assembly; sequence is NOT journal BodyID."""
    shift = (44 - 3 * (boxel_word & 7)) & 63
    return (boxel_word | ((sequence & U64) << shift)) & U64


def stellar_minstd_seed(identifier_or_mt_word):
    """Primary identifier / companion paired-MT word -> one uint32 state."""
    return mix64to32(identifier_or_mt_word) or 1


def minstd_step(state):
    """Original Schrage edge behavior for any uint32, including zero and M."""
    state &= U32
    hi = state // 44488
    a = ((state - hi * 44488) * 48271) & U32
    b = (hi * 3399) & U32
    difference = (a - b) & U32
    return difference if b < a else (difference + 0x7FFFFFFF) & U32


def kiss_hash_tail(index_product):
    value = index_product & U32
    value ^= value >> 22
    value = (value * 17) & U32
    value ^= value >> 9
    value = (value * 1025) & U32
    value ^= value >> 2
    value = (value * 129) & U32
    return value ^ (value >> 12)


def kiss_expand(mixed_word):
    """The shared four-word expansion, in (z, w, jcong, jsr) order."""
    return tuple(((mixed_word + bias) & U32) or bias
                 for bias in (12345, 65435, 12345, 34221))


def kiss_indexed_seed(input_seed, ordinal):
    """Constructor 0x3c8db60; ordinal is its internal loop index."""
    return kiss_expand(kiss_hash_tail(ordinal * 4097) ^ (input_seed & U32))


def kiss_final_reseed(input_seed):
    """Separate post-category initialization at 0x3c8e11e."""
    return kiss_expand((input_seed & U32) ^ 0xBCA9EF5F)


def coordinate_object_seed(xyz):
    """0x3c76816 coordinate hash; coordinate reference frame remains unnamed.

    CVTTSD2SI is signed 32-bit, truncating toward zero; masked invalid
    conversion (NaN, infinity or out of range) gives the 0x80000000 word.
    """
    def cvtt(value):
        value = float(value)
        if not math.isfinite(value):
            return 0x80000000
        n = math.trunc(value)
        return (n & U32) if -0x80000000 <= n <= 0x7FFFFFFF else 0x80000000
    x, y, z = map(cvtt, xyz)
    return (((x + 6000) * 73856093) ^ ((y + 6000) * 19349663)
            ^ ((z + 6000) * 83492791)) & U32


def kiss_input_from_mt_word(raw):
    """Object-spawn caller's exact UINT_MAX correction, before KISS expansion."""
    raw &= U32
    return (raw + raw // U32) & U32


def kiss_step(state):
    z, w, jcong, jsr = (word & U32 for word in state)
    z = (36969 * (z & 65535) + (z >> 16)) & U32
    w = (18000 * (w & 65535) + (w >> 16)) & U32
    jcong = (69069 * jcong + 1234567) & U32
    jsr ^= (jsr << 17) & U32
    jsr ^= jsr >> 13
    jsr ^= (jsr << 5) & U32
    mwc = ((z << 16) + w) & U32
    return (z, w, jcong, jsr), ((mwc ^ jcong) + jsr) & U32


class FrontierMT:
    """624-word MT19937 core with the client's custom uint64 seed expansion.

    u64() concatenates two consecutive uint32 outputs, first word high.
    It is not the distinct standard MT19937-64 algorithm. Mixed-width draws
    share one position; an odd-boundary pair straddles a twist normally.
    """

    def __init__(self, seed):
        seed &= U64
        hi = ((seed >> 32) & U32) or 0xBAADC0DE
        lo = (seed & U32) or 0x53ABCDEF
        if hi == lo:
            lo = (lo - 0x550056) & U32
        self.words = [hi ^ lo]
        for i in range(1, 624):
            hi = (1812433253 * (hi ^ (hi >> 30)) + i) & U32
            lo = (1812433253 * (lo ^ (lo >> 30)) + i) & U32
            self.words.append(hi ^ lo)
        self._twist()

    def _twist(self):
        for i in range(624):
            value = ((self.words[i] & 0x80000000)
                     | (self.words[(i + 1) % 624] & 0x7FFFFFFF))
            self.words[i] = (self.words[(i + 397) % 624] ^ (value >> 1)
                             ^ (0x9908B0DF if value & 1 else 0))
        self.position = 0

    def u32(self):
        if self.position == 624:
            self._twist()
        value = self.words[self.position]
        self.position += 1
        value ^= value >> 11
        value ^= (value << 7) & 0x9D2C5680
        value ^= (value << 15) & 0xEFC60000
        value ^= value >> 18
        return value & U32

    def u64(self):
        return (self.u32() << 32) | self.u32()

    def companion_minstd_seed(self):
        """Consume the literal two-word leaf seed; intervening callers omitted."""
        return stellar_minstd_seed(self.u64())


class FrontierMT32(FrontierMT):
    """0x839630 one-word initializer used by the coordinate/KISS object path."""

    def __init__(self, seed):
        self.words = [(seed & U32) or 5489]
        for i in range(1, 624):
            old = self.words[-1]
            self.words.append((1812433253 * (old ^ (old >> 30)) + i) & U32)
        self._twist()
