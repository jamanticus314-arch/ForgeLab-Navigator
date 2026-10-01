# Validation of 1.1.0

- All 41 automated tests passed against the packaged application source, including route, fuel, evidence, clipboard, overlay, and journal-state checks.
- Simulated players that scoop only when instructed completed three routing regressions without running dry. These are simulations, not new live flights.
- The existing real-flight journal was replayed against 1.1.0; the progress and neutron cues followed the recorded events. The original journal is not included in this repository.
- The local EDMC lifecycle harness used an in-memory clipboard and a dark-theme stub. This checks the plugin lifecycle and colour selection without touching the user's clipboard.
- The release ZIP checksum and all 100 manifest file hashes were checked against the local 1.1.0 source. No application source bytes were changed for this publication.
- Public test loadouts omit timestamps, ship names, ship identifiers, and local ship IDs. These fixtures preserve the numerical configuration needed by the tests.

Live rendering of the new 1.1.0 overlay lines and colours, Modern Overlay's third-line behaviour, real clipboard interaction with the game, and the new bindings in EDMC Hotkeys remain unverified. Automated checks and journal replay do not establish those live behaviours.

The neutron corpus distinguishes reported stars from ForgeLab predictions. A predicted or generated star is not presented as observed until game evidence confirms it. Jump counts between waypoints are estimates.
