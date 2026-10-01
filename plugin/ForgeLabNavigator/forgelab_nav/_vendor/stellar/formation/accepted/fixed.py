"""Q24 decimal primitives transcribed from the pinned native arithmetic.

Pairs are (mantissa, base-10 exponent). No binary floats in the arithmetic.
The power routines use the engine's finite integer log/exp series, not math.pow.
"""
from math import isqrt

Q = 1 << 24
ZERO = (0, 0)
ONE = (Q, 0)
SCALE = (0, 0, 0, 1, 16, 167, 1677, 16777, 167772, 1677721, Q)


def trunc(a, b):
    return (abs(a) // abs(b)) * (-1 if (a < 0) != (b < 0) else 1)


def norm(m, e=0):
    if not m:
        return ZERO
    while abs(m) >= 10 * Q:
        m = trunc(m, 10)
        e += 1
    while abs(m) < Q:
        m *= 10
        e -= 1
    return m, e


def val(a):
    return a[0] / Q * 10.0 ** a[1] if a[0] and a[1] > -300 else 0.0


def cmp(a, b):
    if a[0] == 0 and b[0] == 0:
        return 0
    if a[0] < 0 <= b[0] or a[0] == 0 < b[0]:
        return -1
    if b[0] < 0 <= a[0] or b[0] == 0 < a[0]:
        return 1
    if a[1] != b[1]:
        return (1 if a[1] > b[1] else -1) * (1 if a[0] > 0 else -1)
    return (a[0] > b[0]) - (a[0] < b[0])


def add(a, b):
    if not a[0]:
        return tuple(b)
    if not b[0]:
        return tuple(a)
    e = max(a[1], b[1])
    def scaled(p):
        k = p[1] - e
        return (p[0] * (SCALE[k + 10] if k >= -10 else 0)) >> 24
    return norm(scaled(a) + scaled(b), e)


def sub(a, b):
    # Native subtraction scales positive operands before subtracting, so it
    # must not be implemented as add(a, (-b.m, b.e)).
    if not a[0]:
        return norm(-b[0], b[1])
    if not b[0]:
        return tuple(a)
    e = max(a[1], b[1])
    def scaled(p):
        k = p[1] - e
        return (p[0] * (SCALE[k + 10] if k >= -10 else 0)) >> 24
    return norm(scaled(a) - scaled(b), e)


def mul(a, b):
    return norm((a[0] * b[0]) >> 24, a[1] + b[1])


def div(a, b):
    return norm(trunc(a[0] << 24, b[0]), a[1] - b[1])


def sqrt(a):
    m, e = a
    if m <= 0:
        return ZERO
    if e % 2:
        m = trunc(m, 10)
        e += 1
    return norm(isqrt(m << 24), e // 2)


def qlog(m):
    whole = 0
    while m < Q:
        m = (m * 0xADF85459) >> 30
        whole -= 1
    while m >= 0x2B7E152:
        m = trunc(m << 30, 0xADF85459)
        whole += 1
    term = trunc((m - Q) << 24, m + Q)
    square = (term * term) >> 24
    total, denominator = 0, Q
    while True:
        quotient = trunc(term << 24, denominator)
        total += quotient
        term = (term * square) >> 24
        denominator += 2 * Q
        if abs(quotient) <= 1:
            break
    return 2 * total + whole * Q


def qexp(x):
    if not x:
        return Q
    negative = x < 0
    x = abs(x)
    whole = x // 0xB17217
    if whole >= 64:
        result = (1 << 63) - 1
    else:
        remainder = x - whole * 0xB17217
        term = result = Q
        denominator = Q
        while True:
            quotient = trunc(remainder << 24, denominator)
            denominator += Q
            term = (term * quotient) >> 24
            result += term
            if abs(term) <= 1:
                break
        result <<= whole
        result = min(result, (1 << 63) - 1)
    return trunc(Q * Q, result) if negative else result


def qpower(m, y):
    if m == Q or y == 0:
        return Q
    if m == 0:
        return 0
    return qexp((qlog(m) * y) >> 24)


def power(a, b):
    """0x39eb760 for positive bases, including its rounded recursive branch."""
    if not -3 <= b[1] <= 1:
        # 0x39ebd51..0x39ebedc: not a floating point pow shortcut. Native
        # rounds sqrt(abs(b)), then rounds BOTH power results separately.
        root = sqrt(norm(abs(b[0]), b[1]))
        result = power(power(a, root), root)
        return div(ONE, result) if b[0] < 0 else result
    y = b[0]
    for _ in range(max(b[1], 0)):
        y *= 10
    for _ in range(max(-b[1], 0)):
        y = trunc(y, 10)
    negative = y < 0
    y = abs(y)
    integral = ONE
    while y > Q:
        integral = mul(integral, a)
        y -= Q
    mantissa = qpower(a[0], y)
    decimal = a[1] * y
    exponent = trunc(decimal, Q)
    fractional = decimal - exponent * Q
    fractional_power = qpower(10 * Q, fractional)
    fractional_result = norm((mantissa * fractional_power) >> 24, exponent)
    result = mul(integral, fractional_result)
    return div(ONE, result) if negative else result
