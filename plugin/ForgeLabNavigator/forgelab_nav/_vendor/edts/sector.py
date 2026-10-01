# coding=utf-8

import math
import numbers

from . import util
from . import vector3

sector_size = 1280.0
galaxy_size = [128, 128, 128]
internal_origin_offset = vector3.Vector3(-49985, -40985, -24105)
# Sector at (0,0,0) is Wregoe, the sector containing Sol
base_sector_index = [39, 32, 18]
base_coords = internal_origin_offset + (vector3.Vector3(base_sector_index) * sector_size)

# If I add enough of these I will be able to remember what this variable is called
internal_galaxy_offset = internal_origin_offset
internal_galaxy_origin = internal_origin_offset
galaxy_offset = internal_origin_offset
galaxy_origin = internal_origin_offset


def get_mcode_cube_width(mcode):
  if util.is_str(mcode):
    return sector_size / pow(2, ord('h') - ord(mcode.lower()))
  elif isinstance(mcode, numbers.Number):
    return mcode
  else:
    raise ValueError("First argument to get_mcode_cube_width must be string or numeric")


def get_mcode(mc):
  if util.is_str(mc) and len(mc) == 1:
    return mc.lower()
  elif isinstance(mc, numbers.Number) and (int(mc) % 10) == 0:
    return chr(int(math.log(mc / 10, 2)) + ord('a'))
  else:
    raise ValueError("First argument to get_mcode must be string or numeric and multiple of 10")


class Sector(object):
  def __init__(self, name):
    self._name = name

  @property
  def name(self):
    return self._name

  @property
  def needs_permit(self):
    return False

  @property
  def centre(self):
    raise NotImplementedError("Invalid call to base Sector centre property")

  @property
  def size(self):
    raise NotImplementedError("Invalid call to base Sector size property")

  @property
  def sector_class(self):
    raise NotImplementedError("Invalid call to base Sector sector_class property")

  def contains(self, other):
    raise NotImplementedError("Invalid call to base Sector contains method")

  def get_origin(self, cube_width):
    raise NotImplementedError("Invalid call to base Sector get_origin method")


class HASphere(object):
  def __init__(self, centre, radius):
    self._centre = centre
    self._radius = radius
    self._origin = vector3.Vector3(centre.x - radius, centre.y - radius, centre.z - radius)

  @property
  def centre(self):
    return self._centre

  @property
  def radius(self):
    return self._radius

  @property
  def origin(self):
    return self._origin

  def contains(self, other):
    pos = util.get_as_position(other)
    return ((self.centre - pos).length <= self.radius)
  
  def __str__(self):
    return "HASphere({} ± {}LY)".format(self.centre, self.radius)

  def __repr__(self):
    return self.__str__()

  def __eq__(self, rhs):
    return (self.centre == rhs.centre and self.radius == rhs.radius)

  def __ne__(self, rhs):
    return not self.__eq__(rhs)


class HARegion(Sector):
  def __init__(self, name, size, spheres, needs_permit = False):
    super(HARegion, self).__init__(name)
    self._centre = vector3.mean([s.centre for s in spheres])
    self._size = size
    self._spheres = list(spheres)
    self._needs_permit = needs_permit
    o = [float('inf'), float('inf'), float('inf')]
    for s in self.spheres:
      o[0] = min(o[0], s.origin.x)
      o[1] = min(o[1], s.origin.y)
      o[2] = min(o[2], s.origin.z)
    self._origin = vector3.Vector3(o)

  def get_origin(self, cube_width):
    cube_width = get_mcode_cube_width(cube_width)
    o = self._origin
    o = [int(math.floor(v)) for v in o]
    o[0] -= (o[0] - int(base_coords.x)) % cube_width
    o[1] -= (o[1] - int(base_coords.y)) % cube_width
    o[2] -= (o[2] - int(base_coords.z)) % cube_width
    o = [float(v) for v in o]
    return vector3.Vector3(o)

  @property
  def centre(self):
    return self._centre

  @property
  def radius(self):
    return self._size

  @property
  def size(self):
    return self._size

  @property
  def sector_class(self):
    return 'ha'

  @property
  def spheres(self):
    return self._spheres

  @property
  def needs_permit(self):
    return self._needs_permit

  def contains(self, other):
    pos = util.get_as_position(other)
    return any([s.contains(pos) for s in self.spheres])

  def __str__(self):
    return "HARegion({})".format(self.name)

  def __repr__(self):
    return self.__str__()


class PGSector(Sector):
  def __init__(self, x, y, z, name = None, sc = None):
    super(PGSector, self).__init__(name)
    self._v = [int(x), int(y), int(z)]
    self._class = 'c{}'.format(sc)

  @property
  def x(self):
    return self._v[0]

  @property
  def y(self):
    return self._v[1]

  @property
  def z(self):
    return self._v[2]

  def __str__(self):
    x, y, z = self._v
    if self.name is not None:
      return "PGSector({} @ {}, {}, {})".format(self.name, x, y, z)
    else:
      return "PGSector({}, {}, {})".format(x, y, z)

  def __repr__(self):
    return self.__str__()

  def __len__(self):
    return 3

  def __iter__(self):
    return iter(self._v)

  def __getitem__(self, index):
    try:
      return self._v[index]
    except IndexError:
      raise IndexError("There are 3 values in this object, index should be 0, 1 or 2!")
    
  def __eq__(self, rhs):
    x, y, z = self._v
    xx, yy, zz = rhs
    return (x == xx and y == yy and z == zz)

  def __ne__(self, rhs):
    return not self.__eq__(rhs)

  @property
  def origin(self):
    return self.get_origin()

  def get_origin(self, cube_width = None):
    ox = base_coords.x + (sector_size * self.x)
    oy = base_coords.y + (sector_size * self.y)
    oz = base_coords.z + (sector_size * self.z)
    return vector3.Vector3(ox, oy, oz)
  
  @property
  def centre(self):
    return self.origin + vector3.Vector3(sector_size / 2, sector_size / 2, sector_size / 2)

  @property
  def size(self):
    return sector_size

  @property
  def index(self):
    return [self.x + base_sector_index[0], self.y + base_sector_index[1], self.z + base_sector_index[2]]

  @property
  def offset(self):
    ix, iy, iz = self.index
    return (iz * galaxy_size[1] * galaxy_size[0]) + (iy * galaxy_size[0]) + (ix)

  @property
  def sector_class(self):
    return self._class

  def contains(self, other):
    o = self.origin
    pos = util.get_as_position(other)
    return (pos.x >= o.x and pos.x < (o.x + sector_size)
        and pos.y >= o.y and pos.y < (o.y + sector_size)
        and pos.z >= o.z and pos.z < (o.z + sector_size))

