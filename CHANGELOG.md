# Changes

## 1.1.1 — 2026-10-01

- Fix the ship, location and fuel recovered when EDMC starts while the game is already running. Journals were chosen by file name, and the pre-2022 name format (`Journal.YYMMDDHHMMSS.01.log`) sorts after the current one, so commanders with old journals could see a ship from years ago (reported as a Caspian Explorer shown as a Beluga Liner). Journals are now ordered by the time in their names, in both formats.
- Cross-check the recovered ship against EDMC's current ship and use EDMC's when they differ. If EDMC's data is incomplete, wait for a fresh loadout instead of planning with another ship.
- The standalone companion now follows the newest journal in both name formats.
- Show proper ship names: the name table now uses the journal's ship symbols.

Workaround for 1.1.0: with EDMC running, relog to the main menu and back in; the fresh loadout corrects the ship.

## 1.1.0 — 2026-09-30

- Show the scooping and arrival-fuel amounts that a route depends on, and replan when the actual fuel or star class cannot support the next leg.
- Use the planner's fuel reserve when checking a galaxy-map plot, and show shortfall warnings in game.
- Keep the overlay to two guidance lines plus a brief event line; update progress after each jump and clear it promptly when hidden.
- Accept or decline route offers with `!nav yes` / `!nav no`; add offer acceptance and guidance visibility hotkeys.
- Keep tips relevant to the current route and waypoint, and show completed-route progress briefly.
- Upgrade refuel and neutron evidence labels when the game confirms or contradicts a predicted star class.
- Avoid duplicate clipboard writes and preserve text copied by the player between automatic updates.
- Fix plain panel text under EDMC's dark theme, add a fuel row, and report overlay and hotkey availability.

The release includes 41 passing automated tests. See [validation notes](docs/VALIDATION.md) for the checks performed and remaining live checks.
