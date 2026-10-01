# ForgeLab Navigator

Neutron-highway routing for Elite Dangerous that runs entirely on your PC. It
plans from wherever you are, in the ship you're flying, usually in a second or
two, and then flies the route with you.

- **Instant, offline routes.** It plans over 11.2 million neutron stars:
  4.98 million reported by players, plus 6.2 million ForgeLab predictions for
  space nobody has charted yet. Nothing is sent over the internet.
- **Your actual ship.** It reads range, tank, fuel scoop and the ×4 or ×6
  (SCO Mk II) neutron boost from your loadout. On 191 real jumps it matched the
  game's fuel use to within 0.001 t.
- **Fuel-safe, and it tells you what it counts on.** It never chains more
  neutron boosts than your tank can cover. When the route needs fuel it says
  so: scoop to a stated amount at a refuel stop, or top up on the way when a
  leg with ordinary jumps has to leave you nearly full for the boosts after
  it. Refuel stops are scoopable stars predicted by ForgeLab's stellar
  generator; the label changes once the game shows you the star. If you
  arrive with less fuel than the route needs, it replans with what you have.
  Ships without a fuel scoop are planned without any refuelling.
- **Hands-free waypoints.** The next system is copied to your clipboard when
  you arrive at a waypoint. Supercharging and opening the galaxy map make
  sure it is still there, but they never overwrite something you copied
  yourself since.
- **Works with the galaxy map.** Plot a long route in game as usual. If a
  neutron route is much shorter, the Navigator offers it, in game too: answer
  with `!nav yes` or `!nav no`. When you plot in the galaxy map, it reads the
  game's own route and warns you, in game, if fuel will run short before a
  scoopable star.
- **Keeps up with you.** Skipped a waypoint? It moves ahead. Flew
  elsewhere? It replans from where you are. If a predicted neutron star turns
  out to be something else, it routes around it and remembers.

## Install (EDMC)

1. In EDMC open **File → Settings → Plugins → Open** to find your plugins folder.
2. Copy the `ForgeLabNavigator` folder into it.
3. Restart EDMC. The Navigator appears in the main window.

The Navigator is built for EDMC 6.x (Python 3.11 or later). It uses
[EDMC Modern Overlay](https://github.com/SweetJonnySauce/EDMCModernOverlay)
and [EDMC Hotkeys](https://github.com/SweetJonnySauce/EDMCHotkeys) if you have
them installed. Hotkey actions are *Copy next waypoint*, *Skip waypoint*,
*Back one waypoint*, *Replan from here*, *Accept neutron route offer* and
*Show or hide in-game guidance*; bind them in the EDMC Hotkeys settings tab.
The Navigator's settings page says whether the overlay and hotkeys were found.

**Without EDMC:** double-click `ForgeLab Navigator.pyw` (needs Python 3.10+).
It opens a small window that stays on top and reads your journal itself.

## Using it

1. Type a destination and press **Plot**. You can type named systems (`Colonia`,
   `Sagittarius A*`), any procedural name (`Swoilt NO-I d9-0`), or pick a
   recent one (right-click the box). Or skip the typing: plot the destination in
   the galaxy map and accept the offer.
2. The first waypoint is already on your clipboard. Paste it into the galaxy
   map, plot and jump.
3. At a **neutron star**, fly through the jet cone to supercharge, then jump.
   The Navigator tells you when you're supercharged and has the next waypoint
   ready.
4. At a **refuel stop**, scoop to the amount shown (full is always fine).
   When it says **top up on the way**, scoop at stars on that leg so you
   arrive with the stated fuel.

**In game** the overlay keeps to two lines: the next waypoint, and what to do
now (`Next stop: neutron · ~75 jumps left`, `Supercharge here`,
`Scoop to 60 t`, `Top up on the way`). A third line appears briefly for
something that matters: a fuel warning for your in-game plot, a route offer,
or what just happened. Jump counts start with `~` because they are estimates.

In-game chat (useful in VR): `!nav copy`, `!nav next`, `!nav back`,
`!nav replan`, `!nav yes` / `!nav no` (route offer), `!nav hide` /
`!nav show` (in-game guidance), `!nav clear`, `!nav to <system>`.

**Route** opens the full list, with jumps, distance and evidence for each
stop. Double-click a system to copy it.

## What "evidence" means

| Label | Meaning |
|---|---|
| reported | Players have logged this neutron star (catalogue snapshot). |
| ForgeLab prediction | ForgeLab's generator predicts a neutron star here, but no one has logged it yet. |
| prediction confirmed in game | A ForgeLab prediction that has been checked in game. |
| seen in game | A neutron star seen in game that the catalogue was missing. |
| predicted by ForgeLab (refuel stops) | The star class of a refuel stop comes from ForgeLab's stellar generator. It becomes *confirmed in game* when a jump or galaxy-map plot shows the class, or *NOT scoopable in game* if the game disagrees (you are then told to scoop elsewhere). |

In a field check of 64 randomly drawn neutron stars (almost all of them
predictions), every one matched the game, as did 19 more predicted stars that
happened to lie on the routes. Every jump you
make adds more checks: `field-checks.jsonl` in the Navigator's data folder
records which predictions were confirmed or contradicted. The settings page
shows the totals. Turn off *Use ForgeLab-predicted neutron stars* to route
only through reported stars.

## Good to know

- Jump counts are estimates. The game's own plotter chooses the ordinary jumps
  between waypoints.
- Planning assumes the range you have on a full tank, which is the
  conservative case.
- Permit-locked systems come from community lists and are avoided on the way.
  If your destination needs a permit, the route tells you.
- Settings and your current route are stored in EDMC's data folder, in
  `forgelab-navigator`. The standalone app uses `%LOCALAPPDATA%\ForgeLabNavigator`.

## Credits and data

- Neutron map: ForgeLab corpus `8878d238…` (reported catalogue snapshot plus
  ForgeLab predictions).
- System names: EDTS (BSD licence, `forgelab_nav/_vendor/edts/LICENSE.txt`).
- Permit data: Elite Dangerous Almanac (`data/Almanac-LICENSE`).
- FSD and fuel-scoop values: EDCD coriolis-data (`data/jump-LICENSE-CORIOLIS-DATA.md`).

Elite Dangerous is © Frontier Developments plc. This is an unofficial fan tool.
