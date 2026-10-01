"""Integer stellar-record helpers read from 3c31320 and 3c371e0."""
import struct
import json
from pathlib import Path
from functools import lru_cache
from .stream import i32
from .accepted.fixed import trunc

MASK64=(1<<64)-1

def i64(value):
    value&=MASK64
    return value if value<1<<63 else value-(1<<64)


def log_fixed(value,bits):
    unit=1<<bits;whole=0
    if value<=0:raise ValueError('nonpositive native log input')
    while value<unit:value=(value*0xadf85459)>>30;whole-=1
    threshold=((0xadf85459*unit)+(1<<30)-1)>>30
    while value>=threshold:value=trunc(value<<30,0xadf85459);whole+=1
    term=trunc((value-unit)<<bits,value+unit);square=(term*term)>>bits
    total=0;denominator=unit
    while True:
        quotient=trunc(term<<bits,denominator);total+=quotient
        term=(term*square)>>bits;denominator+=2*unit
        if abs(quotient)<=1:break
    return whole*unit+2*total


def absolute_magnitude(record):
    """3c31320 caches ordinary Q16 magnitude in the mutable record."""
    magnitude=struct.unpack_from('<i',record,0x2c)[0]
    if magnitude<0x280000:return magnitude
    temperature,radius=struct.unpack_from('<II',record,0x30)
    if not temperature or not radius:return 0x140000
    kind=record[0x40]&63
    if kind in (44,45):return 0x60000
    if kind==40:raise NotImplementedError('3c31320 neutron magnitude cache')
    # Native signed-high multiply division, then a separate precision drop.
    ratio=((temperature<<32)*0x2d5e8c89e1571b07>>64)>>10
    ratio=(ratio+((ratio&MASK64)>>63))>>8
    log_t=log_fixed(ratio,24)
    log_r=log_fixed(radius<<3,18)
    combined=i64((log_r//2<<16)+(log_t//2<<11))
    product=(i64(combined*0x1160418)>>24)&-256
    result=i32((0x4d47ae147-product)>>16)
    struct.pack_into('<i',record,0x2c,result)
    return result


def exp_fixed(value,bits):
    unit=1<<bits
    if not value:return unit
    ln2={8:0xb1,12:0xb17,15:0x58b9,18:0x2c5c8,24:0xb17217}[bits]
    width=32 if bits==8 else 64;maximum=(1<<(width-1))-1
    whole=abs(value)//ln2
    if whole>=width:result=maximum
    else:
        remainder=abs(value)-whole*ln2;term=result=unit;denominator=unit
        while True:
            ratio=trunc(remainder<<bits,denominator);denominator+=unit
            term=(term*ratio)>>bits;result+=term
            if abs(term)<=1:break
        result=min(result<<whole,maximum)
    return trunc(unit*unit,result) if value<0 else result


@lru_cache(None)
def tables():
    return json.loads((Path(__file__).parent/'STELLAR-SPECTRAL-TABLES.json').read_text())


def lookup(address,temperature,field):
    table=tables()['tables'][hex(address)]
    for i,bound in enumerate(table['bounds']):
        if temperature<bound:
            row=table['rows'][i];index=temperature//table['divisors'][i]-row['begin']
            return row[field][index]
    return table['default_type' if field=='types' else 'default_magnitude']


def flags(record):return struct.unpack_from('<H',record,0x40)[0]
def setflags(record,value):struct.pack_into('<H',record,0x40,value&0xffff)


def classify(record,magnitude,giant=False):
    """3c3da60: ordered comparisons to initialized magnitude tables."""
    temperature=struct.unpack_from('<I',record,0x30)[0]
    refs={i:lookup(a,temperature,'magnitudes') for i,a in
          ((6,0x5fdc420),(0,0x5fdc320),(5,0x5fdc1f0),(4,0x5fdc050),
           (7,0x5fdc2a0),(3,0x5fdc3a0),(2,0x5fdbfc0),(1,0x5fdc160))}
    def distance(i):return abs(magnitude-(refs[i]<<8))
    selected=4;best=0x5a0000
    if not giant:
        if distance(6)<best:selected=6;best=distance(6)
        if distance(0)>=best:
            setflags(record,(flags(record)&0xdfff)|0x5c00);return selected
        selected=0;best=distance(0)
        if distance(5)>=best:order=[]
        else:selected=5;best=distance(5);order=[4,7,3,2,1]
    else:
        if distance(5)<best:selected=5;best=distance(5)
        order=[4,7,3,2,1]
    for candidate in order:
        if distance(candidate)>=best:break
        selected=candidate;best=distance(candidate)
    scaled=magnitude>>8;reference=refs[selected]
    if selected in (0,5,4,7):
        row={0:((0xd7ff,0x5400),(0xcfff,0x4c00),(0xd3ff,0x5000)),
             5:((0xc7ff,0x4400),(0xbfff,0x3c00),(0xc3ff,0x4000)),
             4:((0xb7ff,0x3400),(0xafff,0x2c00),(0xb3ff,0x3000)),
             7:((0xa7ff,0x2400),(0x9fff,0x1c00),(0xa3ff,0x2000))}[selected]
        mask,bits=row[0 if scaled>=reference+0x55 else 1 if scaled<reference-0x55 else 2]
    else:
        row={3:((0x97ff,0x1400),(0x93ff,0x1000)),
             2:((0x8fff,0xc00),(0x97ff,0x1400)),
             1:((0x83ff,0),(0x8bff,0x800))}[selected]
        mask,bits=row[0 if scaled>=reference else 1]
    setflags(record,(flags(record)&mask)|bits)
    return selected


def ordinary(record,rng):
    from .accepted.stellar_radius import forward
    q8=struct.unpack_from('<H',record,0x28)[0];metal=struct.unpack_from('<h',record,0x3e)[0]
    out=forward(q8,rng.state,metal);rng.state=out['state_radius'];rng.cursor+=2
    temperature=out['temperature'];struct.pack_into('<II',record,0x30,temperature,out['qR15'])
    entry=lookup(0x5fdc320,temperature,'types');value=(flags(record)&0xffc0)|(entry&0xffff)
    if struct.unpack_from('<H',record,0x3c)[0]<120:
        setflags(record,(value&0xdbff)|0x5800);return
    value=(value&0xfc3f)|(((entry>>32)&255)<<6);setflags(record,value)
    magnitude=absolute_magnitude(record)
    if magnitude and record[0x40]&63<=6:classify(record,magnitude)
    else:setflags(record,(flags(record)&0xcbff)|0x4800)


def young(record,rng):
    """3c37b00, both native mass branches with distinct temperature rules."""
    q8=struct.unpack_from('<H',record,0x28)[0]
    lower,upper=(204,230) if q8>0x300 else (230,243)
    selected=rng.word()%(upper-lower)+lower
    mass=((selected if q8>0x300 else selected<<7)*(q8<<7))>>15
    radius_power=(1<<15) if mass==1<<15 else exp_fixed((log_fixed(mass,15)*5)>>3,15) if mass else 0
    radius=(radius_power*0x90a3)>>15
    from .accepted.stellar_radius import factor_from_word3e
    factor=factor_from_word3e(struct.unpack_from('<h',record,0x3e)[0])
    if q8>0x300:
        jitter=rng.word()%0x27100000+0x36b00000
        temperature=(((jitter*factor)>>18)&0xffffffff)>>18
    else:
        temperature_power=(1<<24) if mass<<9==1<<24 else exp_fixed(((log_fixed(mass<<9,24)//2)*5)>>2,24) if mass else 0
        jitter=rng.word()%0x6667+0xcccc
        temperature=((((jitter*0x169200000000)>>24)*temperature_power)>>24)*(factor>>3)>>39
    struct.pack_into('<II',record,0x30,temperature&0xffffffff,radius&0xffffffff)
    entry=lookup(0x5fdc320,temperature,'types')
    value=(flags(record)&0xffc0)|(entry&0xffff);value=(value&0xfc3f)|(((entry>>32)&255)<<6)
    setflags(record,(value&(0xffca if q8>0x300 else 0xffc9))|(10 if q8>0x300 else 9))
    classify(record,absolute_magnitude(record))


def flag_trial(record,rng):
    """3c31750 one MINSTD draw and the metallicity-dependent bit 15."""
    draw=rng.word()%0x64000
    metal=struct.unpack_from('<h',record,0x3e)[0]
    mass=struct.unpack_from('<H',record,0x28)[0]
    factor=exp_fixed(((metal<<4)*0x999)>>12,12)&0xffffffff
    threshold=((factor*0x65)&-4096)//((mass*0x3330)>>12)
    setflags(record,flags(record)|0x8000 if draw<threshold else flags(record)&0x7fff)


def construct_low_mass(mass,age,metal,seed):
    """Compatibility entry for the zero-address, zero-flags constructor."""
    return construct_zero_address(mass,age,metal,seed)


def lifetime_and_duration(mass):
    inverse=(1<<26)//mass
    factor=exp_fixed((log_fixed(inverse,18)*5)>>1,18) if inverse else 0
    lifetime=(((factor&0xffffffff)*0xabe00000>>18)&0xffffffff)>>18
    q12=mass<<4
    first=(i32(exp_fixed(i32((q12*-0xcc9>>12)+0x3ca8),12))*0xbf7c)>>12
    second=(i32(exp_fixed(i32((i32(q12*-0x5b05>>12)*q12>>12)+0xa796),12))*0x4ee6)>>12
    duration=trunc(i32(first+second+4096),4096)&0xffffffff
    return lifetime,max(1,min(4000,duration))


def construct_zero_address(mass,age,metal,seed):
    """3c3bf60 generated companion/converted-body record; no authored flags."""
    from .belt_detail import Minstd
    rng=Minstd(seed);record=bytearray(0x60)
    struct.pack_into('<Q',record,0x20,MASK64);struct.pack_into('<H',record,0x28,mass)
    struct.pack_into('<I',record,0x2c,0x320000);struct.pack_into('<I',record,0x38,0xf4240000)
    struct.pack_into('<Hh',record,0x3c,age,metal);record[0x58]=5
    if not mass:return record,rng
    if mass<=10:ordinary(record,rng);setflags(record,(flags(record)&0xffee)|0x2e)
    index=0 if mass<=0xcc else min(35,((mass-0xcc)*10)>>8)
    threshold=tables()['constants']['0x5fdbb50'][index] if mass<1101 else 0
    if threshold and age<threshold:young(record,rng);return record,rng
    if not threshold and age<100 and rng.word()%100<10:
        struct.pack_into('<H',record,0x3c,1);young(record,rng);return record,rng
    if mass<238:ordinary(record,rng);flag_trial(record,rng);return record,rng
    from .stellar_evolution import late_ordinary, remnant, giant
    lifetime,duration=lifetime_and_duration(mass)
    if age<lifetime:
        if ((lifetime-age)<<18)//lifetime>=0x3333:ordinary(record,rng)
        else:late_ordinary(record,rng)
        flag_trial(record,rng)
    elif age>=lifetime+duration:remnant(record,rng,lifetime)
    else:giant(record,rng,lifetime);flag_trial(record,rng)
    return record,rng
