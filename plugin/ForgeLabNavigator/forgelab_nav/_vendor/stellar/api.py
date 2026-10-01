"""Address and boxel public APIs for the independent stellar stage."""
from __future__ import annotations
from collections import OrderedDict
import struct
pass  # vendored: _bootstrap path setup removed
from .batch_runner import exact_address
from .galaxy_data import GalaxyData, boxel_key, xyz

PINNED_BINARY_SHA256='e6be8bbe04e6a7ae226d4318945af7f367de13dc5a007a261964d9ba8144e988'

def parent_key(key):
    level=key&7
    if level==7:raise ValueError('Mass-code h boxel has no parent')
    x,y,z=xyz(key);level+=1
    return level|((z>>level)<<3)|((y>>level)<<(17-level))|((x>>level)<<(30-2*level))

def boxel_identity(key):
    level=key&7
    return {'boxel_key':str(key),'mass_code':'abcdefgh'[level],
            'mass_code_index':level,'origin_grid_10ly':list(xyz(key)),
            'width_ly':10<<level}

def decode_record(record):
    data=bytes(record)
    if len(data)!=96:raise ValueError('Expected a literal 96-byte record')
    address=struct.unpack_from('<Q',data)[0]
    position=struct.unpack_from('<3H',data,0x42)
    flags=struct.unpack_from('<H',data,0x40)[0]
    return {'address':str(address),'bytes':data.hex(),'byte_length':len(data),
        'provider_index':struct.unpack_from('<i',data,0x24)[0],
        'q8':struct.unpack_from('<H',data,0x28)[0],
        'magnitude_q16':struct.unpack_from('<i',data,0x2c)[0],
        'temperature':struct.unpack_from('<I',data,0x30)[0],
        'radius_q15':struct.unpack_from('<I',data,0x34)[0],
        'age':struct.unpack_from('<H',data,0x3c)[0],
        'word3e':struct.unpack_from('<h',data,0x3e)[0],
        'flags':flags,'stellar_kind':flags&63,
        'position_q5':list(position),'local_position_ly':[p/32 for p in position]}

class StellarGenerator:
    """Cache complete generated boxels; no executable or emulator is opened."""
    def __init__(self,assets=None,*,cache_limit=256):
        if isinstance(cache_limit,bool) or not isinstance(cache_limit,int) or cache_limit<8:
            raise ValueError('cache_limit must be an integer >=8')
        self.galaxy=GalaxyData(assets)
        self.cache_limit=cache_limit
        self.boxels=OrderedDict()
        self._generated_addresses={}

    def ensure(self,key):
        key=exact_address(key)
        if boxel_key(key)!=key:raise ValueError('Boxel key must have zero system-sequence bits')
        if key in self.boxels:
            self.boxels.move_to_end(key);return self.boxels[key]
        from .boxel_scheduler import generate_boxel
        parent=self.ensure(parent_key(key)) if key&7<7 else None
        boxel=generate_boxel(key,parent,self.galaxy)
        self.boxels[key]=boxel
        self._generated_addresses[key]={struct.unpack_from('<Q',r)[0] for r in boxel.generated_records}
        while len(self.boxels)>self.cache_limit:
            removed,_=self.boxels.popitem(last=False);self._generated_addresses.pop(removed,None)
        return boxel

    def _result(self,address,boxel,record,ordinal):
        override=self.galaxy.override_info(address)
        data=bytes(record)
        origin='generated' if address in self._generated_addresses[boxel.key] else 'catalogue'
        decoded=decode_record(data)
        status=('authored_override' if decoded['provider_index']!=-1 else
                'procedural_with_override' if origin=='generated' and override is not None else
                'procedural' if origin=='generated' else 'catalogue_override')
        result={'address':str(address),'status':status,'record_origin':origin,'record':decoded,
            'record_hex':data.hex(),'record_length':len(data),'sequence':ordinal,
            **boxel_identity(boxel.key)}
        if override is not None:
            result['override_metadata']={'byte_length':72,'resource_pool':override['resource_pool'],
                'resource_offset':override['resource_offset'],'literal_hex':override['literal72']}
        return result

    def predict(self,address,*,companions=False):
        address=exact_address(address)
        if address>=1<<55:
            return {'address':str(address),'status':'invalid_address','record':None,
                    'reason':'Bits above the 55-bit system-address layout are nonzero'}
        key=boxel_key(address);boxel=self.ensure(key)
        ordinal=address>>(44-3*(key&7))
        if ordinal>=len(boxel.records):
            return {'address':str(address),'status':'not_generated','record':None,
                    'sequence':ordinal,'combined_record_count':len(boxel.records),**boxel_identity(key)}
        record=boxel.records[ordinal]
        actual=struct.unpack_from('<Q',record)[0]
        if actual!=address:
            return {'address':str(address),'status':'address_index_mismatch','record':None,
                'sequence':ordinal,'indexed_address':str(actual),**boxel_identity(key)}
        result=self._result(address,boxel,record,ordinal)
        if companions:
            from .companion_stage import generate_companions
            if result['record']['provider_index']!=-1:
                result['companion_tree']={'status':'authored_system_definition','reason':'The original procedural adapter does not generate authored whole-system definitions.'}
            else:result['companion_tree']=generate_companions(bytes.fromhex(result['record_hex']),self,include_tree=True)
        return result

    def boxel(self,key,*,companions=False):
        key=exact_address(key);boxel=self.ensure(key)
        rows=[]
        for i,record in enumerate(boxel.records):
            address=struct.unpack_from('<Q',record)[0]
            rows.append(self.predict(address,companions=True) if companions else self._result(address,boxel,record,i))
        return {**boxel_identity(key),'status':'complete','system_count':len(rows),
            'generated_count':len(boxel.generated_records),'category':boxel.category,
            'spacing_q5':boxel.spacing,'depletion_q24':boxel.depletion_q24,'systems':rows}
