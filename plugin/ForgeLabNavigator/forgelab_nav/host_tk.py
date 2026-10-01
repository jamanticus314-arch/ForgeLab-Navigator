"""Tk host plumbing shared by EDMC and standalone: thread hand-off, clipboard,
in-game overlay (EDMC Modern Overlay) and hotkeys (EDMC Hotkeys)."""
from __future__ import annotations

import logging
import queue

from . import session, ui

log = logging.getLogger("ForgeLabNavigator")

OVERLAY_PREFIX = "forgelab-nav-"
OVERLAY_LINES = 4
OVERLAY_COLOURS = {"target": "#ff8c00", "info": "#e0e0e0", "good": "#e0e0e0",
                   "warn": "#ff9d5c", "bad": "#ff5a4f"}
PLUGIN_NAME = "ForgeLab Navigator"


class TkHost(session.Host):
    """Host whose UI is a NavigatorPanel living in a Tk widget tree."""

    def __init__(self, journal_dir_fn, overlay=None):
        self._queue = queue.Queue()
        self._journal_dir_fn = journal_dir_fn
        self.widget = None
        self.panel = None
        self.overlay_client = overlay

    # thread hand-off ----------------------------------------------------
    def attach(self, widget, panel=None):
        self.widget = widget
        self.panel = panel
        widget.after(150, self._pump)

    def _pump(self):
        try:
            while True:
                fn = self._queue.get_nowait()
                try:
                    fn()
                except Exception:  # noqa: BLE001
                    log.exception("ForgeLab Navigator callback failed")
        except queue.Empty:
            pass
        if self.widget is not None:
            try:
                self.widget.after(150, self._pump)
            except Exception:  # noqa: BLE001 - widget destroyed during shutdown
                self.widget = None

    def schedule(self, fn):
        self._queue.put(fn)

    # host services ------------------------------------------------------
    def copy(self, text):
        if self.widget is not None:
            ui.copy_to_clipboard(self.widget, text)

    def clipboard_text(self):
        """Current clipboard text for an in-memory comparison ("" if it holds no text)."""
        if self.widget is None:
            return None
        try:
            return self.widget.clipboard_get()
        except Exception:  # noqa: BLE001 - empty, non-text, or owned by a busy program
            return ""

    def changed(self):
        if self.panel is not None:
            self.panel.refresh()

    def overlay(self, lines):
        if self.overlay_client is not None:
            self.overlay_client.show(lines)

    def journal_dir(self):
        return self._journal_dir_fn()

    def log(self, message):
        log.warning(message)


class Overlay:
    """EDMC Modern Overlay (legacy edmcoverlay API). Silent if not installed."""

    def __init__(self, settings):
        self.settings = settings
        self._client = None
        try:
            from EDMCOverlay import edmcoverlay  # type: ignore
            self._module = edmcoverlay
        except ImportError:
            self._module = None
        if self._module is not None:
            try:
                from overlay_plugin.overlay_api import define_plugin_group  # type: ignore
                define_plugin_group(plugin_name="ForgeLab Navigator",
                                    plugin_matching_prefixes=[OVERLAY_PREFIX],
                                    plugin_group_name="Navigator",
                                    plugin_group_prefixes=[OVERLAY_PREFIX],
                                    plugin_group_anchor="nw")
            except Exception:  # noqa: BLE001 - optional grouping API
                pass

    @property
    def available(self):
        return self._module is not None

    def show(self, lines):
        if self._module is None:
            return
        try:
            if self._client is None:
                self._client = self._module.Overlay()
            lines = [(line, "info") if isinstance(line, str) else tuple(line) for line in (lines or [])]
            lines = lines[:OVERLAY_LINES]
            x, y = self.settings.overlay_x, self.settings.overlay_y
            for i in range(OVERLAY_LINES):
                text, level = lines[i] if i < len(lines) else ("", "info")
                colour = OVERLAY_COLOURS.get(level, OVERLAY_COLOURS["info"])
                self._client.send_message(f"{OVERLAY_PREFIX}{i}", text, colour, x, y + i * 22,
                                          ttl=45 if text else 1, size="large" if level == "target" else "normal")
        except Exception:  # noqa: BLE001 - overlay not running
            self._client = None


def register_hotkeys(nav):
    """Actions for EDMC Hotkeys. Returns the number registered, or None without EDMC Hotkeys."""
    try:
        import EDMCHotkeys as hotkeys  # type: ignore
    except ImportError:
        return None
    actions = {
        "copy": ("Copy next waypoint", lambda **_: nav.copy_next()),
        "next": ("Skip waypoint", lambda **_: nav.step(1)),
        "previous": ("Back one waypoint", lambda **_: nav.step(-1)),
        "replan": ("Replan from here", lambda **_: nav.replan()),
        "accept": ("Accept neutron route offer", lambda **_: nav.accept_offer()),
        "overlay": ("Show or hide in-game guidance", lambda **_: nav.set_overlay(not nav.settings.overlay)),
    }
    count = 0
    for key, (label, callback) in actions.items():
        try:
            count += bool(hotkeys.register_action(hotkeys.Action(
                id=f"forgelab-navigator-{key}", label=label, plugin=PLUGIN_NAME,
                callback=callback, thread_policy="main", cardinality="single")))
        except Exception:  # noqa: BLE001
            log.debug("Hotkey registration failed for %s", key)
    return count


def bound_hotkeys():
    """How many ForgeLab Navigator actions have an enabled binding (None if unknown)."""
    try:
        import EDMCHotkeys as hotkeys  # type: ignore
        return sum(1 for b in hotkeys.list_bindings(PLUGIN_NAME) if getattr(b, "enabled", True))
    except Exception:  # noqa: BLE001 - optional API
        return None
