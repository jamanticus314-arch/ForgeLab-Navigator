# Changes

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
