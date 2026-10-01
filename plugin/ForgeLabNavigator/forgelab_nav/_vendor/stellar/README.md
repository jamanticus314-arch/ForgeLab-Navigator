# Standalone address-to-stellar stage

The Python reference generates the full 96-byte primary record, parent/child
boxels, catalogue and postrelease overrides, massive/special branches, and the
procedural companion tree with its generated neighbouring boxels. Runtime uses
the standard library and the bundled literal tables/assets. It never opens the
game executable, imports an emulator, reads planetary keys, or uses observations.

Source: pinned executable SHA-256
`e6be8bbe04e6a7ae226d4318945af7f367de13dc5a007a261964d9ba8144e988`.
Tested with Python 3.14.7 on Windows 11, Ryzen 7 9800X3D, 16 logical CPUs.

## Run

Extract `stellar-stage-port.zip`, then run these commands in its directory:

```powershell
python -B stellar.py --address 2864609437889 --output primary.json
python -B stellar.py --address 2864609437889 --companions --output stellar-tree.json
python -B stellar.py --boxel 665586182337 --output boxel.json
python -B stellar.py --batch addresses.txt --output batch.jsonl
python -B stellar.py --batch addresses.txt --workers 4 --companions --output trees.jsonl
```

Batch defaults to every available CPU, capped by the number of input rows.
Input accepts decimal lines, address JSONL, or a JSON array. Use decimal strings
to preserve identity through other JSON tools. Text/JSONL input and file/stdout
output stream; JSON-array input is loaded by the standard JSON parser. Adjacent
addresses in one boxel stay together, with at most 256 addresses per work item
and two pending items per worker. Ordering and duplicates are preserved. Sorting
an existing survey by boxel improves reuse; no sorting or full input buffering
is imposed by the runner.

Output files must be new. An interrupted file run retains `.partial`; a finished
batch also writes `.summary.json` with exact counts, statuses, workers and time.
Bad individual identities produce `invalid_input` rows and a nonzero CLI exit.
Malformed input files fail explicitly. For the Python API, supply `output_path`
or `row_sink` for large batches; omitting both deliberately returns an in-memory
list.

```python
from api import StellarGenerator

generator = StellarGenerator()
primary = generator.predict("2864609437889")
raw96 = bytes.fromhex(primary["record_hex"])
whole_boxel = generator.boxel("665586182337")
tree = generator.predict("2864609437889", companions=True)["companion_tree"]
```

Boxel keys have zero ordinal bits. Given address `a`, its key is
`a & ((1 << (44 - 3*(a & 7))) - 1)`. Enumeration returns every entry in the native
combined vector, in its native order: address, local position, 96-byte record,
decoded words and origin/status. It also includes the engine's nonstellar
types 44/45; companion generation reports `nonstellar_record` for these.

## Output contract

| Status | Meaning |
|---|---|
| `procedural` | Generated record without a postrelease override |
| `procedural_with_override` | Generated record patched by literal postrelease fields/name |
| `catalogue_override` | Literal catalogue record with procedural provider index -1 |
| `authored_override` | Record points to an authored whole-system provider |
| `not_generated` | Valid address layout, ordinal absent from the generated boxel |
| `invalid_address` | Bits outside the engine's 55-bit address layout |
| `invalid_input` | Batch identity is not an exact uint64 integer/decimal string |
| `error` | Batch row failed; its exception is retained |

`record_hex` is the exact 96-byte primary/core record, with the same bytes also
available as `record.bytes`. Decoded fields retain native precision: `q8`,
`magnitude_q16`, temperature, `radius_q15`, age, signed `word3e`, flags/kind,
provider index and three Q5 coordinates. `local_position_ly` is the Q5 position
divided by 32; `origin_grid_10ly` and `width_ly` describe the boxel. Raw mass,
radius and age words are not a substitute for the separate journal projection,
whose conversions depend on stellar kind.

Postrelease records are 72-byte field patches; they never replace a generated
96-byte core wholesale. Name pointers are opaque integers reproducing one fresh
initialized adapter's root-to-leaf allocation history. They are deterministic
across cache order and worker count, and are not live pointers. A different
long-lived emulator heap can have different pointer bytes. Asset pointers use
the retained adapter's literal relocation convention.

`--companions` returns births, discarded births, retained stars, recursive calls,
full MT state and the final `companion_tree.root`, including binary orbits,
stellar radii, rotation and disk state. Its boundary matches the existing
`primary-machinery` companion adapter: later orientation sampling, planetary
formation and authored whole-system resource expansion are separate stages.
Authored primary records still return their full core and explicit status.

Companion constructors leave byte ranges `[42,44)`, `[72,88)`, `[89,96)` unwritten.
The port zeroes and labels these ranges. All raw padding differences are retained
in the evidence; only initialized companion bytes are claimed exact. This does
not weaken the full 96-byte primary/boxel record contract.

## Exact validation and performance

The final receipt is `evidence/stellar-validation-release.json`. It includes all
four blind addresses, all 35 TASK-008 holdouts, a frozen a-h/sector panel, explicit
catalogue/authored cases, every override kind, galaxy edges and targeted influence
children. All 84,381 records across 306 distinct boxels match in all 96 bytes.
Inherited influence entries, special-record lists, density, depletion, spacing,
category, raw MT callsites and ordinary constructor inputs also agree. Every
mismatch is an explicit row, never just a pass-rate aggregate.

Fresh companion acceptance covers eight address-only runs, including all four
blind systems: 46,375 boxel-record comparison instances, 13 births, 19 retained
stars and complete tree/MT state. There are zero initialized-byte/state mismatches;
24 raw companion padding observations are listed separately. Additional conditional
checks, historical spectral-initialization differences and every development
mismatch remain in the evidence. See `companion_notes.md` and `VALIDATION.md`.

| Measured workload | Workers | Result including startup/output |
|---|---:|---:|
| 108 dispersed requests, 105 existing records | 16 | 79.8 requests/s; 77.6 records/s |
| 8,192 distinct addresses, grouped by boxel | 1 | 2,579 records/s |
| Same 8,192 addresses | 16 | 2,847 records/s |
| Enumerate 91 requested boxels, 38,196 emitted entries | 1 | 13,241 entries/s |
| Eight mixed full companion cases, including a dense case | 4 | 3.37 systems/s |

The bulk batch includes 5,924 procedural/overridden procedural records and 2,268
catalogue/authored records; procedural throughput is 2,059/s with 16 workers.
Boxel throughput counts only explicitly emitted entries, excluding internal
parent records. Benchmarks are bounded workloads, not a whole-galaxy speed claim.
The small companion cohort is dominated by one dense case; its worker timings
do not establish parallel scaling. All worker outputs were compared exactly.

The archive contains only production modules, literal runtime data and these
usage notes. Research receipts remain beside it in this workspace. `MANIFEST.json`
pins every archived file; `evidence/package-check.json` verifies the extracted
runtime with third-party imports, external data reads and networking blocked.
