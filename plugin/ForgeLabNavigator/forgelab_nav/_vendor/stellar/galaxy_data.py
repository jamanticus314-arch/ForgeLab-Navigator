"""Literal galaxy-map, category and installed-record provider, stdlib only.

The data files are emitted by galaxy_extract.py from the retained MilkyWay and
Overrides assets. Runtime does not read the game executable, run an emulator,
import a PE parser, or use measured star properties. Arithmetic ports:
4ca2660, 4ca2790, 4ca2930, 4ca2d60, 4ca2e40, 4ca3350, and 3c3cb30.

Catalogue rows contain a 72-byte core plus asset metadata (96-byte stride).
Postrelease overrides contain only a 72-byte core. The adjacent 24 bytes from
an emulated 96-byte override read are exposed solely as diagnostic evidence.
"""
from pathlib import Path
import hashlib
import json
import math
import struct
import zlib

U32 = (1 << 32) - 1
U64 = (1 << 64) - 1
HERE = Path(__file__).resolve().parent


def boxel_key(address):
    address = int(address)
    return address & ((1 << (44 - 3*(address & 7))) - 1)


def xyz(key):
    """Lower boxel corner in the engine's 10-light-year grid coordinates."""
    level = key & 7
    return (((key >> (30 - 2*level)) << level) & 16383,
            ((key >> (17 - level)) << level) & 8191,
            ((key >> 3) << level) & 16383)


class GalaxyData:
    """Reusable, lazily loaded immutable resource provider.

    `mt` supplied to category/context_for needs only a u32() method. Category
    consumes exactly one word unless the native equal-weight exit is taken.
    Files are checked against their extraction hashes on first load.
    """

    def __init__(self, assets=None, *, verify=True):
        self.assets = Path(assets) if assets else HERE/'galaxy_assets'
        self.manifest = json.loads((self.assets/'manifest.json').read_text(encoding='utf-8'))
        self.header = bytes.fromhex(self.manifest['gdm_header_hex'])
        self.verify = verify
        self._maps = {}
        self._catalogue = None
        self._catalogue_literal = None
        self._catalogue_index = None
        self._overrides = None
        self._override_boxels = None
        self.sqrt_scale = struct.unpack('<d',bytes.fromhex(self.manifest['sqrt_scale_hex']))[0]

    def _load(self, name):
        data = zlib.decompress((self.assets/name).read_bytes())
        expected = self.manifest['files'][name]
        if len(data) != expected['bytes']:
            raise ValueError(f'Extracted resource length changed: {name}')
        if self.verify and hashlib.sha256(data).hexdigest() != expected['sha256']:
            raise ValueError(f'Extracted resource hash changed: {name}')
        return data

    def u32(self, offset):
        return struct.unpack_from('<I',self.header,offset)[0]

    def _map(self, offset):
        if offset not in self._maps:
            spec = self.manifest['maps'][str(offset)]
            self._maps[offset] = (spec['width'],spec['height'],
                                  4 if spec['bits'] == 32 else 2,
                                  self._load(spec['file']))
        return self._maps[offset]

    def sample(self, offset, x_q9, y_q9):
        """0x4ca3350, also the equivalent u32 sampler inside 0x4ca2790.

        Each multiplication truncates separately. Combining the two terms
        before the right shift would alter map values and generated stars.
        """
        width,height,size,data = self._map(offset)
        x_q9,y_q9 = x_q9 & U32,y_q9 & U32
        x,y = x_q9 >> 9,y_q9 >> 9
        if x+1 >= width or y+1 >= height:
            return 0
        fmt = '<I' if size == 4 else '<H'
        a,b = struct.unpack_from('<II' if size == 4 else '<HH',data,(y*width+x)*size)
        c,d = struct.unpack_from('<II' if size == 4 else '<HH',data,((y+1)*width+x)*size)
        fx,fy = (x_q9 & 511) << 6,(y_q9 & 511) << 6
        top = (((a*(32768-fx)) >> 15) + ((b*fx) >> 15)) & U32
        bottom = (((c*(32768-fx)) >> 15) + ((d*fx) >> 15)) & U32
        return (((top*(32768-fy)) >> 15) + ((bottom*fy) >> 15)) & U32

    def map_value(self, key):
        """0x4ca2d60 classifier map at the centre of this boxel, Q15."""
        x,_,z = xyz(key)
        width,height,_,_ = self._map(0x138)
        half = 5 << (key & 7)
        sx = (((width << 15) & U32) << 15) // ((self.u32(0x2c) << 15) & U32)
        sz = (((height << 15) & U32) << 15) // ((self.u32(0x34) << 15) & U32)
        return self.sample(0x138, (((10*x+half) << 9)*sx) >> 15,
                           (((10*z+half) << 9)*sz) >> 15)

    def category(self, key, mt):
        """0x3c3cb30, preserving its tie ordering and individual thresholds."""
        v = self.map_value(key)
        p = self.u32
        if v <= p(0x174):
            a = 0
        elif v > p(0x178):
            a = 32768
        else:
            a = min((((p(0x14c)*v) >> 15)+p(0x150)) & U32,32768)
        if v < p(0x184):
            b = 0 if v <= p(0x17c) else min((((p(0x15c)*v) >> 15)+p(0x164)) & U32,32768)
        else:
            b = 0 if v >= p(0x180) else min((((p(0x160)*v) >> 15)+p(0x168)) & U32,32768)
        if v >= p(0x170):
            c = 0
        elif v <= p(0x16c):
            c = 32768
        else:
            c = min((((p(0x154)*v) >> 15)+p(0x158)) & U32,32768)
        if a == b == c:
            return U32
        total = (a+b+c) & U32
        a,b,c = ((x << 15)//total for x in (a,b,c))
        weights = (a,c,b)
        if a < b and a < c:
            first,second,third = (0,2,1) if b < c else (0,1,2)
            site = '0x3c3cc9a'
        elif b < c:
            first,second,third = (2,0,1) if a < c else (2,1,0)
            site = '0x3c3ccd3'
        else:
            first,second,third = (1,2,0) if b < a else (1,0,2)
            site = '0x3c3cd16'
        draw_at = getattr(mt,'draw',None)
        draw = (draw_at(site) if callable(draw_at) else mt.u32()) & 32767
        return first if draw < weights[first] else second if draw < weights[second] else third

    def context_for(self, key, mt):
        """Map/category context; supplied MT is advanced exactly as native."""
        return {'key':str(key),'map_value_q15':self.map_value(key),'category':self.category(key,mt)}

    def vertical_density(self, key):
        """0x4ca2e40: eight literal corner samples and unsigned difference."""
        x,y,z = xyz(key)
        side = 1 << (key & 7)
        cx,cy,cz = (self.u32(o)//20 for o in (0x2c,0x30,0x34))
        xs,zs = [abs(x-cx),abs(x+side-cx)],[abs(z-cz),abs(z+side-cz)]
        ys = sorted((abs(y-cy),abs(y+side-cy)))
        sy,sr = self.u32(8),self.u32(12)
        yq = [(((((v << 24)*sy) & U64) >> 36) & U32) >> 3 for v in ys]
        total = 0
        # Each sqrt uses SSE double precision on exact integer coordinates.
        for zz in zs:
            for xx in xs:
                radius = math.trunc(math.sqrt(float(zz)*zz+float(xx)*xx)*self.sqrt_scale)
                rq = (((radius*sr) & U64) >> 37) & U32
                total += self.sample(0x140,yq[0],rq)-self.sample(0x140,yq[1],rq)
        return (total & U32) >> 3

    def density(self, key):
        """0x4ca2790 uint64 result, before the scheduler's eight-bit shift."""
        x,_,z = xyz(key)
        level = key & 7
        xq = ((((x << 9)*self.u32(4)) & U64) >> 31) & U32
        zq = ((((z << 9)*self.u32(0x10)) & U64) >> 31) & U32
        sampled = self.sample(0x38+level*8,xq >> level,zq >> level)
        scaled = ((sampled*(self.u32(0) << (2*level))) & U64) >> 15
        return ((scaled*self.vertical_density(key)) & U64) >> 15

    def _four_corner(self,key,offset,x_scale,z_scale,coordinate_shift=0):
        x,_,z = xyz(key)
        x,z = x >> coordinate_shift,z >> coordinate_shift
        def coord(value,scale):
            return (((((value << 12)*scale) & U64) >> 31) & U32) >> 3
        xs = coord(x,self.u32(x_scale)),coord(x+1,self.u32(x_scale))
        zs = coord(z,self.u32(z_scale)),coord(z+1,self.u32(z_scale))
        value = sum(self.sample(offset,xx,zz) for zz in zs for xx in xs) & U32
        return value >> 2

    def metallicity(self,key):
        """0x4ca2660, fixed base map and literal one-grid-unit corners."""
        return self._four_corner(key,0x78,0x14,0x18)

    def special_density(self,key):
        """0x4ca2930 massive/special branch map, only mass codes g and h."""
        level = key & 7
        if level < 6:
            return 0
        return self._four_corner(key,0xc8+level*8,0x24,0x28,level-6)

    def _load_catalogue(self):
        if self._catalogue is None:
            self._catalogue = self._load('catalogue-native96.bin.zlib')
            self._catalogue_index = {}
            for offset in range(0,len(self._catalogue),96):
                address = struct.unpack_from('<Q',self._catalogue,offset)[0]
                self._catalogue_index.setdefault(boxel_key(address),[]).append(offset)

    def catalogue_records(self,key,*,literal=False):
        """Immutable 96-byte bucket rows in native catalogue iteration order.

        Default bytes include only the asset's explicit pointer relocations at
        the emulator adapter's stable asset base. Pass literal=True for the
        exact pre-relocation bytes. Callers must copy before scheduler writes.
        """
        self._load_catalogue()
        if literal and self._catalogue_literal is None:
            self._catalogue_literal = self._load('catalogue-literal96.bin.zlib')
        data = self._catalogue_literal if literal else self._catalogue
        return [data[i:i+96] for i in self._catalogue_index.get(key,())]

    def catalogue_boxels(self):
        self._load_catalogue()
        return self._catalogue_index.keys()

    def _load_overrides(self):
        if self._overrides is None:
            self._overrides = {}
            for row in json.loads(self._load('overrides.json.zlib')):
                address = int(row['address'])
                self._overrides.setdefault(address,row)

    def override_info(self,address):
        """Literal source/provenance record, including diagnostic read96 tail."""
        self._load_overrides()
        return self._overrides.get(int(address))

    def has_overrides(self,key):
        """0x3ce72c0 exact outer-container membership for an already masked key.

        The scheduler's 0x3c36041 uses this boolean for its low-mass tail.
        It does not replace a selected primary with a 72-byte override row.
        Like the native lookup this method does not clear address ordinals.
        Empty resource boxel rows, if present, still create outer membership.
        """
        if self._override_boxels is None:
            self._override_boxels = frozenset(int(row['boxel']) for row in
                json.loads(self._load('override-boxels.json.zlib')))
        return int(key) in self._override_boxels

    def override_record(self,address,*,literal=False):
        """First postrelease override's actual 72 bytes, or None."""
        row = self.override_info(address)
        return bytes.fromhex(row['literal72' if literal else 'native72']) if row else None

    def apply_override_fields(self,record,*,name_pointer=None,name_allocator=None):
        """Mutate a generated core as 0x3c30ce0, never replace it with a row.

        Names in this routine are copied into an allocation, so their pointer
        is runtime state, not the literal resource pointer. Exact callers
        must supply either `name_pointer` or `name_allocator(name_bytes)`;
        the latter receives the terminating NUL too. The returned diagnostic
        includes decoded name text. Without a name policy this fails before
        mutation instead of inventing an exact native pointer value.
        """
        if not isinstance(record,bytearray) or len(record)!=96:
            raise TypeError('apply_override_fields requires a mutable 96-byte bytearray')
        address=struct.unpack_from('<Q',record)[0]
        row=self.override_info(address)
        if row is None:
            return {'applied':False}
        raw=bytes.fromhex(row['native72'])
        mask=struct.unpack_from('<I',raw,0x3c)[0]
        if mask & (1<<15):
            name=bytes.fromhex(row['name_utf8_hex'])+b'\0'
            if name_pointer is None:
                if name_allocator is None:
                    raise ValueError('A native-compatible name pointer policy is required for this override')
                name_pointer=name_allocator(name)
            if not isinstance(name_pointer,int) or not 0<=name_pointer<=U64:
                raise ValueError('name pointer must be a uint64')
            struct.pack_into('<QQQ',record,8,name_pointer,0,0)
        for bit,source,destination,length in [(4,0x20,0x3c,2),(6,0x24,0x40,2),
                (3,0x1c,0x38,4),(0,0x10,0x28,2),(5,0x22,0x3e,2),
                (10,0x34,0x50,2),(11,0x36,0x52,2),(2,0x18,0x34,4),
                (1,0x14,0x30,4),(16,0x40,0x54,2)]:
            if mask & (1<<bit):
                record[destination:destination+length]=raw[source:source+length]
        record[0x5a]=1
        return {'applied':True,'flags':mask,'name':row['name'] if mask & (1<<15) else None}

    def override_records(self,key):
        self._load_overrides()
        return [bytes.fromhex(row['native72']) for row in self._overrides.values() if int(row['boxel']) == key]
