"""One ordered uint32 tape; every consumer records its exact cursor interval."""
from pathlib import Path
import sys
pass  # vendored: sys.path edit removed; imports are package-relative
from .accepted.fixed import norm, SCALE


def i32(x):
    x &= 0xffffffff
    return x if x < 0x80000000 else x-0x100000000


def sample_decimal(lower, upper, word):
    exponent = max(lower[1] if lower[0] else -0x80000000,
                   upper[1] if upper[0] else -0x80000000)
    def aligned(pair):
        if not pair[0]:
            return 0
        delta = pair[1]-exponent
        return i32((pair[0] * (SCALE[delta+10] if delta >= -10 else 0)) >> 24)
    lo, hi = aligned(lower), aligned(upper)
    span = (hi-lo) & 0xffffffff
    value = i32(lo + (word % span if span else word))
    m, e = norm(value, exponent)
    return m, i32(e)


class WordStream:
    def __init__(self, words, *, start=0, identity='supplied_tape'):
        self.words = iter(words)
        self.cursor = start
        self.identity = identity
        self.receipts = []

    def u32(self, consumer):
        value = next(self.words)
        assert type(value) is int and 0 <= value < 2**32
        self.receipts.append(dict(stream=self.identity, index=self.cursor,
                                 consumer=consumer, word=value))
        self.cursor += 1
        return value

    def decimal(self, lower, upper, consumer):
        return sample_decimal(lower, upper, self.u32(consumer))
