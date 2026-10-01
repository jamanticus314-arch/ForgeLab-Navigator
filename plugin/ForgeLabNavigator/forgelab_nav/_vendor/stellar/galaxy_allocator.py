"""Opaque allocation tokens for the retained BoxelNative adapter's raw bytes.

These integers are not live pointers and no memory is allocated at them.
Canonical output follows one fresh root-to-leaf chain: 0x50033420 after the
literal override-container mount and stellar-table initialization, seven fixed
adapter context allocations per boxel, catalogue links, then native name copies.
Each child clones its parent's relationship state. Querying a sibling cannot
change the canonical pointer bytes of a later result.

Relationship routing: 0x3c34a47..0x3c34d38; registration: 0x3c33900;
node allocation: 0x3c25780; vector growth: 0x503720 (adapter refuses in-place
growth); name copies: 0x3c30ce0. There are no fixture-derived pointer tables.
"""
from copy import deepcopy
from dataclasses import dataclass,field
import struct

# The retained adapter aligns every request up to 16 bytes. Mounting the
# literal Overrides resource creates a 0x90 database, 17-pointer outer
# buckets, 107 outer nodes of 0x30 with 17-pointer buckets each, and 198
# inner nodes of 0x18. The counts come from the pinned literal resource.
ADAPTER_OVERRIDE_MOUNT_BYTES = 0x90 + 0x90 + 107*(0x30+0x90) + 198*0x20
# Native 0x3c44dc0 creates 100 base nodes (0x3c25930), then 560 + 240 nodes
# through 0x3c41be0/0x3c41b60 -> 0x3c25860. Its eight 0x3c43100 calls each
# allocate 1000 and 563 entries, with 8-byte and 2-byte arrays per entry.
# These fixed initializer requests follow the literal native control flow;
# they are not per-address or fixture-derived pointer lookup values.
STELLAR_INIT_ALLOCATION_GROUPS = ((56,100),(56,800),(8000,8),(2000,8),
                                  (4504,8),(1126,8))
STELLAR_INIT_BYTES = sum(((size+15)&-16)*count
                         for size,count in STELLAR_INIT_ALLOCATION_GROUPS)
ADAPTER_HEAP_START = 0x50000000 + ADAPTER_OVERRIDE_MOUNT_BYTES + STELLAR_INIT_BYTES
ADAPTER_BOXEL_BYTES = 0x92d700


@dataclass
class _RelationshipVector:
    records: set = field(default_factory=set)
    capacity: int = 0


@dataclass
class RelationshipState:
    key: int
    parent: object = None
    identifiers: set = field(default_factory=set)
    vectors: dict = field(default_factory=dict)


class ShadowAllocator:
    """A canonical fresh-chain allocation cursor and catalogue link state.

    Usage: `allocator = ShadowAllocator.for_boxel(key, parent_allocator,
    catalogue_records)`, before any generated record. Supply
    `allocator.allocate_name` to GalaxyData.apply_override_fields. Save this
    allocator on the completed Boxel; the child constructor clones its state.
    `.heap_end` excludes the API's later 0x80 select_record wrapper.
    """
    def __init__(self, heap_end=ADAPTER_HEAP_START, relationships=None):
        self.heap_end=int(heap_end)
        self.relationships=relationships
        self.events=[]
        self.boxel_start=self.heap_end

    @classmethod
    def for_boxel(cls,key,parent=None,catalogue_records=()):
        if parent is None:
            allocator=cls()
            parent_state=None
        else:
            allocator=cls(parent.heap_end)
            parent_state=deepcopy(parent.relationships)
        allocator.relationships=RelationshipState(int(key),parent_state)
        allocator.allocate(ADAPTER_BOXEL_BYTES,'adapter-context-and-nodepool')
        allocator.register_catalogue(catalogue_records)
        return allocator

    def allocate(self,size,reason,**details):
        if not isinstance(size,int) or size<0:
            raise ValueError('allocation size must be a nonnegative integer')
        address=self.heap_end
        aligned=(size+15)&-16
        self.heap_end+=aligned
        self.events.append({'address':address,'size':size,'aligned_size':aligned,
                            'reason':reason,**details})
        return address

    def _register(self,owner,provider,address):
        vector=owner.vectors.get(provider)
        if vector is None:
            self.allocate(0x48,'catalogue-relationship-node',owner_key=str(owner.key),provider_index=provider)
            vector=owner.vectors[provider]=_RelationshipVector()
        # Original container compares asset record pointers. Extraction proves
        # every catalogue system address is unique, so addresses identify those
        # pointers without retaining the emulator arena itself.
        if address in vector.records:
            return
        size=len(vector.records)
        if size>=vector.capacity:
            vector.capacity=max(size+1,vector.capacity+(vector.capacity>>1))
            self.allocate(8*vector.capacity,'catalogue-relationship-vector',
                          owner_key=str(owner.key),provider_index=provider,capacity=vector.capacity)
        vector.records.add(address)

    def register_catalogue(self,records):
        current=self.relationships
        if current is None:
            raise ValueError('begin a boxel before registering catalogue records')
        for record in records:
            if len(record)!=96:
                raise ValueError('catalogue relationship rows require the literal 96-byte stride')
            address=struct.unpack_from('<Q',record)[0]
            identifier,provider=struct.unpack_from('<II',record,0x20)
            if provider!=0xffffffff:
                if provider in current.identifiers:
                    owner=current
                elif current.parent is not None:
                    owner=current.parent
                    while provider not in owner.identifiers:
                        if owner.parent is None:
                            owner=current
                            break
                        owner=owner.parent
                else:
                    # Native root/no-parent exit at 0x3c34c0a does not register.
                    owner=None
                if owner is not None:
                    self._register(owner,provider,address)
            current.identifiers.add(identifier)

    def allocate_name(self,nul_terminated_bytes):
        name=bytes(nul_terminated_bytes)
        if not name or name[-1]!=0 or b'\0' in name[:-1]:
            raise ValueError('name allocator requires one NUL-terminated string')
        length=len(name)-1
        if length:
            self.allocate(length+0x15,'override-name-temporary')
            return self.allocate(length+1,'override-name-copy')
        return self.allocate(1,'override-empty-name')

    def apply_override(self,galaxy,record):
        return galaxy.apply_override_fields(record,name_allocator=self.allocate_name)
