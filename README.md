# ForgeLab Navigator

Offline neutron-highway navigation for Elite Dangerous, with routes planned for your current ship, fuel guidance, automatic waypoint copying, and compact in-game directions.

**[Download ForgeLab Navigator 1.1.1](https://github.com/jamanticus314-arch/ForgeLab-Navigator/releases/tag/v1.1.1)**. The release ZIP includes the complete runtime and neutron map. No internet connection is needed while using the Navigator.

## Install

1. Download `ForgeLabNavigator-1.1.1.zip` from the release page and extract it.
2. In EDMC, open **File → Settings → Plugins → Open**.
3. Copy the extracted `ForgeLabNavigator` folder into that plugins folder and restart EDMC.

EDMC 6.x with Python 3.11 or later is supported. For standalone use, open `ForgeLab Navigator.pyw` in the extracted folder with Python 3.10 or later.

Optional integrations are [EDMC Modern Overlay](https://github.com/SweetJonnySauce/EDMCModernOverlay) and [EDMC Hotkeys](https://github.com/SweetJonnySauce/EDMCHotkeys).

See the [full user guide](plugin/ForgeLabNavigator/README.md), [changes](CHANGELOG.md), and [validation notes](docs/VALIDATION.md).

## Source and tests

The application source is under `plugin/ForgeLabNavigator`. The 241.8 MB neutron map is distributed in the release ZIP rather than Git. To run all integration tests or build a complete ZIP from a source checkout, copy `data/neutrons.flnav` from the extracted release into `plugin/ForgeLabNavigator/data/`.

Run tests with Python 3.11 or later:

```console
python -B -m unittest discover -s tests
```

The synthetic tests run without the neutron map; map-dependent integration tests are skipped when it is absent. With the map present, all 50 tests run. No additional Python packages are required.

To package a complete checkout after adding the neutron map:

```console
python tools/package.py
```

The package tool creates a ZIP, a SHA-256 checksum, and a file manifest. Test loadouts retain the numerical ship configuration, with timestamps and player ship identifiers removed. Original journals, player settings, captures, and development backups are excluded.

## Credits

ForgeLab Navigator was developed with assistance from AI coding tools, including Claude. These tools were used for implementation and code review.

The runtime retains the bundled third-party licenses and data provenance. EDTS provides procedural system naming; Elite Dangerous Almanac provides permit data; EDCD coriolis-data provides FSD and fuel-scoop values. The neutron map combines reported stars with separately labelled ForgeLab predictions.

Elite Dangerous is © Frontier Developments plc. This is an unofficial fan tool.
