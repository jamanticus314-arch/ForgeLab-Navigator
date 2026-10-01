import logging, numbers
from . import vector3
is_str = lambda value: isinstance(value,str)
class _BraceString(str):

    def __mod__(self, other):
        return self.format(*other)

    def __str__(self):
        return self

class _StyleAdapter(logging.LoggerAdapter):

    def process(self, msg, kwargs):
        return (_BraceString(msg), kwargs)

def get_logger(name):
    return _StyleAdapter(logging.getLogger(name), None)

def jenkins32(key):
    key += key << 12
    key &= 4294967295
    key ^= key >> 22
    key += key << 4
    key &= 4294967295
    key ^= key >> 9
    key += key << 10
    key &= 4294967295
    key ^= key >> 2
    key += key << 7
    key &= 4294967295
    key ^= key >> 12
    return key

def interleave(val1, val2, maxbits):
    output = 0
    for i in range(0, maxbits // 2 + 1):
        output |= (val1 >> i & 1) << i * 2
    for i in range(0, maxbits // 2 + 1):
        output |= (val2 >> i & 1) << i * 2 + 1
    return output & 2 ** maxbits - 1

def deinterleave(val, maxbits):
    out1 = 0
    out2 = 0
    for i in range(0, maxbits, 2):
        out1 |= (val >> i & 1) << i // 2
    for i in range(1, maxbits, 2):
        out2 |= (val >> i & 1) << i // 2
    return (out1, out2)

def get_as_position(v):
    if v is None:
        return None
    if isinstance(v, vector3.Vector3):
        return v
    if hasattr(v, 'position'):
        return v.position
    if hasattr(v, 'centre'):
        return v.centre
    if hasattr(v, 'system'):
        return get_as_position(v.system)
    try:
        if len(v) == 3 and all([isinstance(i, numbers.Number) for i in v]):
            return vector3.Vector3(v[0], v[1], v[2])
    except:
        pass
    return None
