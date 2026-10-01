# Data sources — `data/astro/`

**Acquired:** 2026-07-24. **Upstream revision:** unavailable for every source below.

## Procedural naming and named-region origins

- **File:** `named-region-origins.jsonc`.
- **Source:** the EDTS reference implementation (`edtslib/pgdata.py`, `edtslib/pgnames.py`).
- **Derivation:** named-region origins are stored in the game's internal coordinate frame
  (32 units per light-year from the galaxy corner). Where a region is defined by a single
  sphere, its origin and extent are the sphere's axis-aligned bounds in that frame. The
  NGC 2392 record is derived from its catalogued 100 ly sphere and verified by encoding
  the EDSM system `NGC 2392 Sector UJ-Q b5-0` (id64 `674176509065`, EDSM system id 21224).

## Hand-authored named sectors

- **File:** `hand-authored-regions.jsonc`. Region names and spheres only — whether a
  region is permit-locked is recorded once, in `permit-locked-regions.jsonc`.
- **Sources:** EDSM and Spansh. These are factual system names, coordinates and region
  bounds.
- **Derivation:** sphere membership and real-system triples are cross-checked across the
  two services. Decimal id64 values remain strings in JSON so every target language can
  parse them without IEEE-754 precision loss.

## Nebulae

- **Files:** `nebulae-real.jsonc` (catalogued real-world nebulae and dark regions),
  `nebulae-procgen.jsonc` (procedurally generated nebulae) and
  `nebulae-planetary.jsonc` (planetary nebulae), split by class.
- **Source:** the EDAstro nebulae coordinates dataset (`nebulae-coordinates.csv`, columns
  `Name,System,X,Y,Z,Type,RegionID`). Original observations are community exploration
  data.
- **Obtained via:** canonn-signals, `src/assets/nebulae.json`, which converts the CSV to
  JSON verbatim. The records here were checked against both and are identical
  field-for-field.
- **Derivation:** records retain their name, catalogued system, galactic X/Y/Z in
  light-years with Sol at the origin, class and region id. They are grouped by `type`
  into one file per class and sorted by name; the class is represented by that file and
  is not repeated on every record. In the planetary file, `system` is omitted where it
  is identical to `name`; every differing system remains.
  `regionId` is the galactic codex region id from the source CSV — a column the
  canonn-signals JSON drops — and every value was verified to agree with this
  project's own codex-region lookup.
- **Caveat:** a nebula is a volume, but the dataset records a single point — the position
  of the system it is catalogued at.

## Permit-locked systems and regions

- **Files:** `permit-locked-systems.jsonc`, `permit-locked-regions.jsonc`.
- **Source:** the community-maintained "Elite Dangerous Permit Database" spreadsheet.
  Permit status appears in no game data file, journal event or API (Sol itself reports no
  permit flag), so the list is hand-maintained by the community and is best-effort.
- **Obtained via:** canonn-signals, `src/app/data/permit-locked-systems.ts`, which
  transcribes the sheet into two arrays.
- **Derivation:** the exact system names are carried over unchanged and sorted
  case-insensitively. Permit state is split by lookup domain. The region entries are
  names of regions in
  `hand-authored-regions.jsonc`, which stores their spheres and nothing about permits.
  Each name doubles as the matching prefix, because the game names every system in a
  region after it (`Col 70 Sector AA-D b17-0`). The upstream list matches 19 lower-cased
  stems instead; the two agree except for the digit-suffixed regions, which the region
  names resolve exactly.
- **System addresses:** `id64` comes from Spansh for every system but one, cross-checked
  against EDSM wherever EDSM holds the system, with no disagreement in address or
  coordinates. EDSM holds no entry at all for the rest — expected of systems no commander
  can enter to report — so their addresses rest on Spansh alone, with one exception.
  `Plaa Ain HA-Z d46` is in neither service; it is procedurally
  named, so its address is encoded by this project's own procedural system encoder, whose
  output was confirmed against Spansh on the other two procedural entries in the list
  (`Dryio Flyuae IC-B c1-377`, `Scheau Bli NB-O d6-1409`). Values are stored as decimal
  strings so every target language parses them without IEEE-754 loss.
- **`Bleia1`–`Bleia5` and `Praei1`–`Praei6` are in-game region names**, not groupings:
  EDSM holds `Bleia1 DL-Y f26`, `Bleia2 AA-A h55` and `Praei3 MJ-D b43-8`, each inside the
  same-named sphere of `hand-authored-regions.jsonc`. The bare stems `Bleia` and `Praea`
  name unrelated procedural sectors far outside the permit spheres. `Bleia Flyuae DH-U
e3-26` sits ≈6800 ly beyond every Bleia sphere, and `Praea Aec AA-A b1-1` sits ≈46 kly
  from the Praei spheres, so neither bare stem is a permit prefix.
- **Caveat:** region membership is inferred from the system name, since no per-system
  region-permit flag is published. Permit-locked _bodies_ inside otherwise-open
  systems (Diso 5 C, Lave 2, Sol's Moon and Triton) are out of scope — a system-level flag
  would misreport their systems.

## Galactic codex regions

- **Files:** `galactic-regions.jsonc` (per-region metadata),
  `galactic-region-cells.jsonc` (per-region lookup geometry + projection), split along the
  metadata-versus-geometry axis.
- **Source:** EliteDangerousRegionMap.
- **Derivation:** the 42 region ids/names and each region's run-length cell geometry
  (`cells`) are taken from the upstream `RegionMapData.json` (itself generated from
  `RegionMap.png`), re-grouped per region. The per-region footprint fields (`cellCount`,
  `areaLy2`, `bounds`, `centroid`) are computed by this project from that grid and are
  approximate (≈49.35 ly grid resolution); coordinates are quantised to 1/64 ly.
- **Grid mapping:** regions sit on a `4096 / 83` ly (≈49.3494 ly) grid over the galactic
  plane, origin corner at `(x0, y0, z0) = (-49985, -40985, -24105)` ly.
- **Manual corrections:** one. Region 31 is stored as `The Formidine Rift`. The upstream
  transcription drops the article, and the game's own codex English carries it
  (§`data/i18n/SOURCES.md`, acquired 2026-09-10 UTC). The game is taken as authoritative
  for a region name, because `RegionMap.png` reads the codex names rather than naming the
  regions itself. The Veils, The Conduit, The Abyss and The Void keep their article
  upstream, so this is a transcription slip and not an upstream naming choice. Every
  other region name matches the game's English exactly.
  - **A name lookup answers the game's spelling and not the transcription's.** Resolving
    a region by the name `Formidine Rift` misses, where it hit before the correction.
    That spelling is what the upstream catalogues carry, and it is also the game's own
    Spanish, so a caller holding either has to pass `The Formidine Rift`. A region id is
    unaffected, which is why `data/i18n/codex-region-names.jsonc` is keyed by id.
- **The game's own region raster is not a second source for the geometry.** The codex
  localisation table acquired for `data/i18n/codex-region-names.jsonc` also carries a
  region raster and per-region border polygons. The raster reproduces
  `galactic-region-cells.jsonc` cell for cell, so it confirms the upstream derivation
  and adds nothing to it. The borders are that raster's outline on cell edges, which the
  cells already state; they are not stored.
