"""3c394c0 / 3c388e0 / 3c36960 integer companion stellar evolution."""
import struct
from math import isqrt
from .stellar_record import log_fixed, exp_fixed, flags, setflags, lookup, classify, absolute_magnitude, i64


def u16(record,offset):return struct.unpack_from('<H',record,offset)[0]
def put16(record,offset,value):struct.pack_into('<H',record,offset,value&0xffff)
def put32(record,offset,value):struct.pack_into('<I',record,offset,value&0xffffffff)
def metal(record):return struct.unpack_from('<h',record,0x3e)[0]
def factor(record):
    high=((metal(record)<<40)*0x6d3a06d3a06d3a07)>>64
    value=high>>29;value+=(value&((1<<64)-1))>>63;value+=1<<24
    return (1<<24) if value<0 else value
def pow_fixed(value,numerator,bits):
    return exp_fixed((log_fixed(value,bits)*numerator)>>bits,bits) if value else 0
def spectral(record,address):
    entry=lookup(address,struct.unpack_from('<I',record,0x30)[0],'types')
    value=(flags(record)&0xffc0)|(entry&0xffff)
    setflags(record,(value&0xfc3f)|(((entry>>32)&255)<<6));return entry


def late_ordinary(record,rng):
    """3c394c0, classification enabled (r8b=0)."""
    mass=(u16(record,0x28)*(rng.word()%0x33+0xb3))>>8
    if not mass:mass=rng.word()%0x1a+0x19
    put16(record,0x28,mass);put16(record,0x3e,u16(record,0x3e)+rng.word()%25)
    power=exp_fixed(((log_fixed(mass<<16,24)//2)*5)>>2,24)
    jitter=(rng.word()%0x599a+0xd999)>>8
    temperature=((((jitter*0x16920000000000)>>24)*power)>>24)*factor(record)>>48
    radius=(((rng.word()%0x1999a+0x36666)*power)>>24)&0xffffffff
    put32(record,0x30,temperature);put32(record,0x34,radius>>3)
    spectral(record,0x5fdc1f0);classify(record,absolute_magnitude(record))


def remnant(record,rng,lifetime):
    """3c388e0; white dwarf and neutron/black-hole branches."""
    original=u16(record,0x28);draw=rng.word()
    mass=(original*(draw%0x34+0x4c))>>8
    put16(record,0x28,mass)
    if original>0x170:
        mass=max(1,mass);put16(record,0x28,mass)
        root=pow_fixed(mass,0x55,8)&0xffff
        radius=((0xa0000//root)&0xffff)<<7
        schwarzschild=(mass*0xbccc80)>>15
        if radius<schwarzschild:
            radius=schwarzschild;temperature=0;setflags(record,(flags(record)&0xffe9)|0x29)
        else:
            temperature=rng.word()%0x8adae0+0xdbba0;setflags(record,(flags(record)&0xffe8)|0x28)
    else:
        base=((((original<<16)*0x6d3a06d3a06d3a07)>>64)>>18)*0x1fbd0000>>12
        base=(base+0x4e20000)&0xffffffff
        delta=(lifetime-u16(record,0x3c))<<12
        exponent=(delta+((delta*i64(0xaec33e1f671529a5))>>64))>>11
        exponent+=(exponent&((1<<64)-1))>>63
        temperature=(((base*(exp_fixed(exponent,12)&0xffffffff))>>12)&0xffffffff)>>12
        temperature+=4000
        jitter=rng.word()%0x3333+0x6666
        scaled=mass<<7
        first=pow_fixed(0x5c288000//scaled,0x5555,15)
        numerator=scaled<<15;high=(numerator*0x638fff37ff007081)>>64
        second=pow_fixed((((numerator-high)>>1)+high)>>15,0x5555,15)
        square=isqrt(((first-second)&0xffffffff)<<15)
        radius=(((jitter*0x16f)>>15)*square)>>15
        if temperature>45000:kind=34
        elif temperature>12000:
            draw=rng.word()%0x6400
            if draw<0xf00:
                kind=32 if metal(record)>51 else 33 if rng.word()%0x6400<0xa00 else 31
            elif draw<0x1400 and mass>204:kind=36
            elif draw<0x1900:kind=27
            else:kind=29 if metal(record)>51 else 30 if rng.word()%0x6400<0xa00 else 26
        elif temperature>8000:
            draw=rng.word()%0x6400
            kind=38 if draw<0xa00 else 26 if draw<0x1e00 else 27 if draw<0x3c00 else 37
        else:kind=37
        setflags(record,(flags(record)&(0xffc0|kind))|kind)
        if not mass:put16(record,0x28,1)
    put32(record,0x30,temperature);put32(record,0x34,radius)
    setflags(record,(flags(record)&0xe3ff)|0x6000)


def giant(record,rng,lifetime):
    """3c36960, including native late giant and Wolf-Rayet choices."""
    mass=u16(record,0x28);age=u16(record,0x3c)
    if mass<0xa00:
        power=exp_fixed(((log_fixed(mass<<16,24)//2)*5)>>2,24)
        temperature=(((power*0x1692000000)>>24)*(factor(record)>>9))>>39
        radius=power>>9
        entry=lookup(0x5fdc320,temperature,'types')
        rng.word() # The native result is deliberately discarded.
        coefficient=(0x3200000000//((mass+0x300)<<7)+0x50000)&0xffffffff
        temperature>>=1;radius=(coefficient*(radius>>1))>>15
        put32(record,0x30,temperature);put32(record,0x34,radius)
        setflags(record,(flags(record)&0xffc0)|min((flags(record)&63)+3,8))
        giant_spectral(record)
        kind=flags(record)&63
        if age>lifetime+900:
            draw=rng.word()%100
            if draw<5:kind=20
            elif kind<=4:
                if metal(record)<-51:kind=21
                elif metal(record)>51:kind=17
                elif ((entry>>32)&255)>7:kind=22
            else:kind=19 if kind in (5,6) else 18
            setflags(record,(flags(record)&(0xffc0|kind))|kind)
        elif kind==6:
            draw=rng.word()%100
            if draw<10:
                kind=24 if draw<5 else 23
                setflags(record,(flags(record)&(0xffc0|kind))|kind)
        return
    if mass<0x1900:
        if age<lifetime+100:return remnant(record,rng,lifetime)
        put16(record,0x28,(mass*(rng.word()%0x33+0xb3))>>8)
        return expanded_giant(record,rng)
    if mass<0x2800:
        if age<lifetime+10:return remnant(record,rng,lifetime)
        if rng.word()%256<128:
            put16(record,0x28,(mass*(rng.word()%0x33+0xb3))>>8)
            return expanded_giant(record,rng)
        return wolf_rayet(record,rng)
    if age>lifetime+10:return remnant(record,rng,lifetime)
    if rng.word()%256>=128:return wolf_rayet(record,rng)
    put16(record,0x28,(mass*(rng.word()%0x33+0xb3))>>8)
    draw=rng.word()%0xeb0000
    put32(record,0x34,draw+0xf0000)
    value=(draw*0x1388000000)&-0x40000
    high=(value*0x16e0689427378eb5)>>64
    subtract=((((value-high)>>1)+high)>>26)>>3
    temperature=(((factor(record)>>9)*0x30d400000)>>18)-subtract
    put32(record,0x30,(temperature&((1<<64)-1))>>15)
    giant_spectral(record)


def giant_spectral(record):
    """3c31c10 / 3c3e710 classify and fetch the corresponding spectrum."""
    selected=classify(record,absolute_magnitude(record),True)
    address={0:0x5fdc320,1:0x5fdc160,2:0x5fdbfc0,3:0x5fdc3a0,
             4:0x5fdc050,5:0x5fdc1f0,6:0x5fdc420,7:0x5fdc2a0}[selected]
    spectral(record,address)


def expanded_giant(record,rng):
    """3c38390 expanded red/blue giant, preserving all branch draws."""
    scale=factor(record)
    if rng.word()%256>243:
        draw=rng.word()%0x960000
        radius=draw+0x320000
        decrement=(((draw<<18)*0x6d3a06d3a06d3a07)>>64)>>26
        temperature=((((scale>>6)*0x7d000000)>>18)-(decrement<<3))&0xffffffff
        temperature>>=18
    else:
        put16(record,0x28,(u16(record,0x28)*(rng.word()%0x33+0xb3))>>8)
        low=rng.word()%256<243
        radius=rng.word()%(0x12c0000 if low else 0x15e0000)+(0x640000 if low else 0x1900000)
        temperature=(((rng.word()%0xfa00000+0x36b00000)*(scale>>6))>>18)&0xffffffff
        temperature>>=18
    put32(record,0x30,temperature);put32(record,0x34,radius);giant_spectral(record)


def wolf_rayet(record,rng):
    """3c36760, the compact high-temperature giant branch."""
    put32(record,0x34,rng.word()%0x38000+0x18000)
    temperature=((((rng.word()%0xa604000+0x1d4c000)<<14)*factor(record))&((1<<64)-1))>>48
    put32(record,0x30,temperature);setflags(record,(flags(record)&0x87ff)|0x400)
    draw=rng.word()%0x6400;mass=u16(record,0x28)
    kind=13 if draw<0xf00 else 14 if draw<0x1e00 else 16 if mass>0x3c00 else 15 if mass>0x1900 else 12
    setflags(record,(flags(record)&(0xffc0|kind))|kind)
