"""Standalone exact-ID names: pinned EDTS spelling with native HA boundaries.

No game process, executable, memory, captured key, or public summary is read.
Literal catalogue/override aliases are extracted from installed game resources.
The geometric correction follows the pinned client's 0x3cee810 routine:
smallest containing sphere, strict squared-distance comparison, float32 at
every arithmetic operation in the engine's absolute coordinate frame.
"""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
import json, math, re, struct, zlib
from ._vendor.edts import pgnames, pgdata

GRID_ORIGIN=(-49985,-40985,-24105)
DATA=Path(__file__).resolve().parent.parent/'data'
PG=re.compile(r"^(.+) ([A-Z]{2})-([A-Z]) ([a-h])(?:(\d+)-)?(\d+)$",re.I)
REGION_RENAMES={'Eskimo Sector':'NGC 2392 Sector'}

class NamingError(ValueError):
    """A name cannot safely be converted using the supported naming domain."""

@lru_cache(maxsize=1)
def _exclusions():
    p=DATA/'names-exclusions.json'
    if not p.exists():raise NamingError('Validated naming exclusions are missing from this package.')
    return {int(a):reason for a,reason in json.loads(p.read_text(encoding='utf8'))['address_reasons'].items()}

def exact_address(value):
    if isinstance(value,str):
        if not re.fullmatch(r'[0-9]+',value):raise NamingError('Address must be decimal digits.')
        value=int(value)
    if isinstance(value,bool) or not isinstance(value,int) or not 0<=value<1<<55:
        raise NamingError('Address must be an exact integer in the 55-bit system layout.')
    return value

def decode_address(value):
    a=exact_address(value);m=a&7;w=10<<m
    x=(a>>(30-2*m))&((1<<(14-m))-1)
    y=(a>>(17-m))&((1<<(13-m))-1)
    z=(a>>3)&((1<<(14-m))-1)
    lower=tuple(v*w+o for v,o in zip((x,y,z),GRID_ORIGIN))
    return {'address':a,'m':m,'mass':'abcdefgh'[m],'grid':(x,y,z),
            'width':w,'n2':a>>(44-3*m),'lower':lower}

@lru_cache(maxsize=1)
def _aliases():
    p=DATA/'names-catalogue.json.zlib'
    return {int(a):name for a,name in json.loads(zlib.decompress(p.read_bytes())).items()}

@lru_cache(maxsize=1)
def _aliases_inverse():
    out={}
    for address,name in _aliases().items():out.setdefault(name.casefold(),[]).append(address)
    return out

def f32(value):return struct.unpack('<f',struct.pack('<f',value))[0]

@lru_cache(maxsize=32768)
def _nearby_regions(sx,sy,sz):
    lower=tuple(s*1280+o for s,o in zip((sx,sy,sz),GRID_ORIGIN))
    out=[]
    for region in pgdata.ha_regions.values():
        for sphere in region.spheres:
            c=tuple(sphere.centre);r=sphere.radius
            if all(lo<=v+r and v-r<=lo+1280 for v,lo in zip(c,lower)):
                out.append((region,sphere));
    return tuple(out)

def _naming_region(position):
    if len(position)!=3 or not all(math.isfinite(v) for v in position):raise NamingError('Finite XYZ position required.')
    coords=tuple(math.floor((p-o)/1280) for p,o in zip(position,GRID_ORIGIN))
    closest=None;smallest=float('inf')
    for region,sphere in _nearby_regions(*coords):
        r2=f32(sphere.radius*sphere.radius)
        if r2>=smallest:continue
        diff=[f32(f32(p-o)-f32(c-o)) for p,c,o in zip(position,sphere.centre,GRID_ORIGIN)]
        sq=[f32(d*d) for d in diff]
        d2=f32(f32(sq[0]+sq[1])+sq[2])
        if d2<r2:closest=region;smallest=r2
    return closest

@lru_cache(maxsize=32768)
def _ordinary_sector(sx,sy,sz):
    pos=tuple(s*1280+o+640 for s,o in zip((sx,sy,sz),GRID_ORIGIN))
    try:
        name=pgnames.get_sector_name(pos,allow_ha=False)
        sector=pgnames.get_sector(name,allow_ha=False)
        if sector is None or tuple(sector.index)!=(sx,sy,sz):raise ValueError('Sector inversion failed')
        return sector
    except (ValueError,IndexError,TypeError) as e:
        raise NamingError('Procedural sector lies outside the verified spelling domain.') from e

@lru_cache(maxsize=32768)
def _region_by_name(name):
    for old,new in REGION_RENAMES.items():
        if name.casefold()==new.casefold():name=old
    region=pgnames.get_sector(name)
    if region is None:raise NamingError('Unknown naming sector.')
    return region

def name_from_address(address,position=None,*,use_aliases=True):
    """Return a paste name. Pass exact stellar-port XYZ for HA boundary choice.

    Without XYZ a numeric ordinary spelling is returned only if the boxel has
    no intersecting HA sphere; uncertain naming is rejected, never guessed.
    """
    d=decode_address(address);a=d['address']
    if a in _exclusions():
        raise NamingError('Waypoint excluded by naming validation: '+_exclusions()[a])
    if use_aliases and a in _aliases():
        alias=_aliases()[a]
        if len(_aliases_inverse()[alias.casefold()])!=1:
            raise NamingError('Literal name is ambiguous; this waypoint is excluded.')
        return alias
    sector_indices=tuple(v>>(7-d['m']) for v in d['grid'])
    region=None
    if position is not None:
        if any(not lo<=p<lo+d['width'] for p,lo in zip(position,d['lower'])):
            raise NamingError('Position is outside the address boxel.')
        region=_naming_region(position)
    elif _nearby_regions(*sector_indices):
        # Check true boxel intersection before requiring exact position.
        for _,sphere in _nearby_regions(*sector_indices):
            distance=sum(max(lo-c,0,c-(lo+d['width']))**2 for c,lo in zip(sphere.centre,d['lower']))
            if distance<=sphere.radius**2:raise NamingError('Exact stellar position is needed at an authored naming region.')
    region=region or _ordinary_sector(*sector_indices)
    origin=tuple(int(v) for v in region.get_origin(d['mass']))
    local=tuple((lo-o)//d['width'] for lo,o in zip(d['lower'],origin))
    if any(not 0<=v<128 for v in local):raise NamingError('Naming suffix exceeds the representable local cube.')
    code=local[0]+128*local[1]+16384*local[2]
    prefix=REGION_RENAMES.get(region.name,region.name)
    name=f"{prefix} {chr(65+code%26)}{chr(65+(code//26)%26)}-{chr(65+(code//676)%26)} {d['mass']}"
    if code//17576:name+=str(code//17576)+'-'
    return name+str(d['n2'])

def address_from_name(name):
    """Decode exact name identity; aliases are literal data, never fuzzy matched."""
    if not isinstance(name,str):raise NamingError('Name must be text.')
    name=name.strip()
    aliases=_aliases_inverse().get(name.casefold())
    if aliases:
        if len(aliases)!=1:raise NamingError('Literal name is ambiguous; enter its exact address.')
        return aliases[0]
    match=PG.fullmatch(name)
    if not match:raise NamingError('Unknown literal name or malformed procedural spelling.')
    prefix,l12,l3,mass,n1,n2=match.groups();mass=mass.lower();m=ord(mass)-97;w=10<<m
    n1=int(n1 or 0);n2=int(n2)
    if n2>=1<<(11+3*m):raise NamingError('System number exceeds address layout.')
    code=n1*17576+(ord(l3.upper())-65)*676+(ord(l12[1].upper())-65)*26+ord(l12[0].upper())-65
    local=(code%128,(code//128)%128,code//16384)
    if local[2]>=128:raise NamingError('Suffix exceeds local cube.')
    region=_region_by_name(prefix)
    origin=tuple(int(v) for v in region.get_origin(mass))
    if region.sector_class!='ha' and any(v>=(128>>m) for v in local):raise NamingError('Suffix spills outside ordinary sector.')
    lower=tuple(o+v*w for o,v in zip(origin,local))
    if region.sector_class=='ha':
        intersects=any(sum(max(lo-c,0,c-(lo+w))**2 for c,lo in zip(sphere.centre,lower))<=sphere.radius**2 for sphere in region.spheres)
        if not intersects:raise NamingError('Named region does not intersect this boxel.')
    g=tuple((p-o)//w for p,o in zip(lower,GRID_ORIGIN))
    if any((p-o)%w for p,o in zip(lower,GRID_ORIGIN)):raise NamingError('Misaligned naming origin.')
    if not(0<=g[0]<1<<(14-m) and 0<=g[1]<1<<(13-m) and 0<=g[2]<1<<(14-m)):
        raise NamingError('Name is outside the address layout.')
    return m|(g[2]<<3)|(g[1]<<(17-m))|(g[0]<<(30-2*m))|(n2<<(44-3*m))
