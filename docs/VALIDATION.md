# Validation of 1.1.1

- All 50 automated tests pass (41 from 1.1.0 plus 9 new), against both the local source and this public repository with the neutron map present.
- New tests cover journal ordering across the old and new name formats, a veteran journal folder (old-format Beluga journals plus a current Caspian journal), preferring EDMC's current ship, refusing to plan with a mismatched ship, keeping the journal loadout when the ships agree, live ship correction, and the standalone journal follower.
- Against the developer's real journals, the installed 1.1.1 recovered the current ship (Caspian Explorer, 77.2 LY) and location, as 1.1.0 did. That folder holds only new-format journal names; the old-format case is covered by the synthetic tests above.
- EDMC 6.1.2's `monitor.ship()` was checked to omit the fuel tank and unladen mass; 1.1.1 reads EDMC's monitor state instead. That path is tested against a stand-in for EDMC's state, not inside a live EDMC session.
- The release ZIP checksum and all 100 manifest file hashes were checked against the local source and the installed copy.
- One existing test, `test_state_survives_restart`, fails intermittently (about one full run in eight, with 1.1.0 and 1.1.1 alike). The test's stand-in host runs the planner's save on the worker thread; the EDMC and standalone hosts queue it to the UI thread.

# Validation of 1.1.0

- All 41 automated tests passed against the packaged application source, including route, fuel, evidence, clipboard, overlay, and journal-state checks.
- Simulated players that scoop only when instructed completed three routing regressions without running dry. These are simulations, not new live flights.
- The existing real-flight journal was replayed against 1.1.0; the progress and neutron cues followed the recorded events. The original journal is not included in this repository.
- The local EDMC lifecycle harness used an in-memory clipboard and a dark-theme stub. This checks the plugin lifecycle and colour selection without touching the user's clipboard.
- The release ZIP checksum and all 100 manifest file hashes were checked against the local 1.1.0 source. No application source bytes were changed for this publication.
- Public test loadouts omit timestamps, ship names, ship identifiers, and local ship IDs. These fixtures preserve the numerical configuration needed by the tests.

Live rendering of the new 1.1.0 overlay lines and colours, Modern Overlay's third-line behaviour, real clipboard interaction with the game, and the new bindings in EDMC Hotkeys remain unverified. Automated checks and journal replay do not establish those live behaviours.

The neutron corpus distinguishes reported stars from ForgeLab predictions. A predicted or generated star is not presented as observed until game evidence confirms it. Jump counts between waypoints are estimates.
