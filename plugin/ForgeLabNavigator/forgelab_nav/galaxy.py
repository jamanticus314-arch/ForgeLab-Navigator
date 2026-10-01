"""Read-only neutron star pack: compact, cell-sorted, memory-mapped.

Standard library only (runs inside EDMC's bundled Python). Layout (little endian):

    0   8s  magic b"FLNAVPK1"
    8   I   header length H
    12  H   UTF-8 JSON header (sections, grid, counts, provenance)
    ... sections, each 16-byte aligned, located by header["sections"][name] = [offset, bytes]:
      coarse  uint32[cx*cy*cz]   block number per coarse cell, or EMPTY
      fine    uint32[blocks*(SUB**3+1)]  node start index per fine sub-cell (+ block end)
      pos     float32[N*3]       x, y, z (galactic LY, Sol at origin)
      addr    uint64[N]          exact SystemAddress (id64)
      flags   uint8[N]           FLAG_* bits below

Nodes are sorted by (coarse cell, fine sub-cell), so every fine cell is one
contiguous index range and a sphere query touches only nearby memory.
"""
from __future__ import annotations

import json
import math
import mmap
import struct
from pathlib import Path

MAGIC = b"FLNAVPK1"
EMPTY = 0xFFFFFFFF
FLAG_PREDICTED = 1       # ForgeLab prediction (not in the reported catalogue snapshot)
FLAG_CONFIRMED = 2       # seen in game by a field check (galaxy map / NavRoute / arrival)
FLAG_BLOCKED = 4         # permit-locked or inside a locked region: never routed through
FLAG_FIELD_ADDED = 8     # neutron seen in game that was missing from the corpus
FLAG_NAME_OVERRIDE = 16  # paste name comes from the names table, not derivation
FLAG_UNNAMED = 32        # no safe paste name: never offered as a waypoint


class PackError(RuntimeError):
    pass


class NeutronPack:
    """Spatial access to the neutron network. Thread-safe for reads."""

    def __init__(self, path):
        self.path = Path(path)
        self._file = open(self.path, "rb")
        try:
            self._mm = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
        except (OSError, ValueError):  # pragma: no cover - exotic filesystems
            self._mm = self._file.read()
        buf = self._mm
        if bytes(buf[:8]) != MAGIC:
            raise PackError("Not a ForgeLab neutron pack: " + str(self.path))
        (hlen,) = struct.unpack_from("<I", buf, 8)
        self.header = json.loads(bytes(buf[12:12 + hlen]).decode("utf-8"))
        view = memoryview(buf)

        def section(name, fmt):
            offset, length = self.header["sections"][name]
            return view[offset:offset + length].cast(fmt)

        self.coarse = section("coarse", "I")
        self.fine = section("fine", "I")
        self.pos = section("pos", "f")
        self.addr = section("addr", "Q")
        self.flags = section("flags", "B")
        grid = self.header["grid"]
        self.origin = tuple(grid["origin"])
        self.coarse_size = float(grid["coarse"])
        self.sub = int(grid["sub"])
        self.fine_size = self.coarse_size / self.sub
        self.dims = tuple(grid["dims"])
        self.count = int(self.header["count"])
        self.block_len = self.sub ** 3 + 1
        if len(self.addr) != self.count or len(self.pos) != 3 * self.count:
            raise PackError("Neutron pack is truncated or inconsistent")

    # -- identity ---------------------------------------------------------
    @property
    def corpus_id(self):
        return self.header.get("corpus_id")

    def position(self, i):
        return (self.pos[3 * i], self.pos[3 * i + 1], self.pos[3 * i + 2])

    def locate(self, address, position, radius=1.0):
        """Exact-address lookup near a known position (cheap, no global index)."""
        address = int(address)
        for start, end in self.cell_ranges(position, radius):
            for i in range(start, end):
                if self.addr[i] == address:
                    return i
        return None

    # -- spatial ----------------------------------------------------------
    def _fine_range(self, fx, fy, fz):
        s = self.sub
        cx, cy, cz = fx // s, fy // s, fz // s
        nx, ny, nz = self.dims
        if not (0 <= cx < nx and 0 <= cy < ny and 0 <= cz < nz):
            return None
        block = self.coarse[(cx * ny + cy) * nz + cz]
        if block == EMPTY:
            return None
        sub = ((fx - cx * s) * s + (fy - cy * s)) * s + (fz - cz * s)
        base = block * self.block_len + sub
        start = self.fine[base]
        end = self.fine[base + 1]
        return (start, end) if end > start else None

    def cell_ranges(self, center, radius, forward=None):
        """Index ranges of fine cells intersecting the sphere.

        ``forward`` = (goal point, slack): skip cells that cannot contain a node
        closer to the goal than ``|center-goal| + slack`` (search pruning).
        """
        ox, oy, oz = self.origin
        w = self.fine_size
        x, y, z = center
        r = float(radius)
        lo = [math.floor((c - r - o) / w) for c, o in zip(center, self.origin)]
        hi = [math.floor((c + r - o) / w) for c, o in zip(center, self.origin)]
        r2 = r * r
        if forward is not None:
            goal, slack = forward
            limit = math.dist(center, goal) + slack
            gx, gy, gz = goal
        out = []
        for fx in range(lo[0], hi[0] + 1):
            bx0 = ox + fx * w
            dx = max(bx0 - x, 0.0, x - bx0 - w)
            if dx * dx > r2:
                continue
            for fy in range(lo[1], hi[1] + 1):
                by0 = oy + fy * w
                dy = max(by0 - y, 0.0, y - by0 - w)
                dxy = dx * dx + dy * dy
                if dxy > r2:
                    continue
                for fz in range(lo[2], hi[2] + 1):
                    bz0 = oz + fz * w
                    dz = max(bz0 - z, 0.0, z - bz0 - w)
                    if dxy + dz * dz > r2:
                        continue
                    if forward is not None:
                        ex = max(bx0 - gx, 0.0, gx - bx0 - w)
                        ey = max(by0 - gy, 0.0, gy - by0 - w)
                        ez = max(bz0 - gz, 0.0, gz - bz0 - w)
                        if ex * ex + ey * ey + ez * ez > limit * limit:
                            continue
                    rng = self._fine_range(fx, fy, fz)
                    if rng:
                        out.append(rng)
        return out

    def within(self, center, radius, skip_flags=FLAG_BLOCKED | FLAG_UNNAMED, forward=None):
        """(index, x, y, z, distance) for usable nodes within ``radius``."""
        x0, y0, z0 = center
        r2 = radius * radius
        pos = self.pos
        flags = self.flags
        out = []
        append = out.append
        for start, end in self.cell_ranges(center, radius, forward):
            coords = pos[3 * start:3 * end].tolist()
            fl = flags[start:end]
            i = start
            for k in range(0, len(coords), 3):
                dx = coords[k] - x0
                dy = coords[k + 1] - y0
                dz = coords[k + 2] - z0
                d2 = dx * dx + dy * dy + dz * dz
                if d2 <= r2 and not (fl[i - start] & skip_flags):
                    append((i, coords[k], coords[k + 1], coords[k + 2], math.sqrt(d2)))
                i += 1
        return out

    def close(self):
        for attr in ("coarse", "fine", "pos", "addr", "flags"):
            view = getattr(self, attr, None)
            if isinstance(view, memoryview):
                view.release()
        if isinstance(self._mm, mmap.mmap):
            self._mm.close()
        self._file.close()


def write_pack(path, header, coarse, fine, pos, addr, flags):
    """Write a pack from bytes-like sections (used by the build tool)."""
    sections = [("coarse", bytes(coarse)), ("fine", bytes(fine)), ("pos", bytes(pos)),
                ("addr", bytes(addr)), ("flags", bytes(flags))]
    header = dict(header)
    # Two passes: header length depends on offsets, offsets on header length.
    header["sections"] = {name: [0, len(data)] for name, data in sections}
    for _ in range(3):
        blob = json.dumps(header, sort_keys=True).encode("utf-8")
        offset = _align(12 + len(blob) + 64)
        table = {}
        for name, data in sections:
            table[name] = [offset, len(data)]
            offset = _align(offset + len(data))
        header["sections"] = table
    blob = json.dumps(header, sort_keys=True).encode("utf-8")
    with open(path, "wb") as out:
        out.write(MAGIC + struct.pack("<I", len(blob)) + blob)
        for name, data in sections:
            out.seek(table[name][0])
            out.write(data)
        out.truncate(_align(out.tell()))


def _align(n, a=16):
    return (n + a - 1) // a * a
