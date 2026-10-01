"""ForgeLab Navigator - EDMC plugin entry point.

Offline neutron-highway routing from your current system and ship, with
automatic waypoint copying, galaxy-map integration and in-game guidance.
"""
from __future__ import annotations

import logging
import os
import sys
import tkinter as tk
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

from config import appname, config  # type: ignore  # noqa: E402

from forgelab_nav import __version__, host_tk, session, ui  # noqa: E402

logger = logging.getLogger(f"{appname}.{PLUGIN_DIR.name}")
VERSION = __version__


class _State:
    nav: session.Navigator | None = None
    host: host_tk.TkHost | None = None
    panel: ui.NavigatorPanel | None = None
    apply_prefs = None
    error: str | None = None


this = _State()


def _journal_dir():
    configured = config.get_str("journaldir") or getattr(config, "default_journal_dir", None)
    return Path(configured) if configured else None


def _state_dir():
    base = getattr(config, "app_dir_path", None)
    return Path(base) / "forgelab-navigator" if base else PLUGIN_DIR / "user"


def plugin_start3(plugin_dir: str) -> str:
    try:
        this.host = host_tk.TkHost(_journal_dir)
        this.nav = session.Navigator(this.host, _state_dir())
        this.host.overlay_client = host_tk.Overlay(this.nav.settings)
        this.nav.integrations["overlay"] = this.host.overlay_client.available
    except Exception as e:  # noqa: BLE001 - show the problem in the panel, don't break EDMC
        logger.exception("ForgeLab Navigator failed to start")
        this.error = f"ForgeLab Navigator could not start: {e}"
    return "ForgeLab Navigator"


def plugin_app(parent: tk.Frame):
    if this.nav is None:
        return tk.Label(parent, text=this.error or "ForgeLab Navigator unavailable")
    try:
        from theme import theme  # type: ignore
        retheme = theme.update
    except ImportError:
        retheme = None
    this.panel = ui.NavigatorPanel(parent, this.nav, on_theme=retheme)
    this.host.attach(parent, this.panel)
    loadout = None
    try:
        from monitor import monitor  # type: ignore
        loadout = monitor.ship()
    except Exception:  # noqa: BLE001
        pass
    this.nav.bootstrap(loadout=loadout)
    registered = host_tk.register_hotkeys(this.nav)
    this.nav.integrations["hotkeys"] = None if registered is None else {"registered": registered, "bound": None}
    parent.after(15000, _tick)
    return this.panel


def _tick():
    """Keep in-game overlay text alive while a route is active."""
    if this.nav is not None:
        this.nav.push_overlay(keepalive=True)
    if this.panel is not None:
        try:
            this.panel.after(15000, _tick)
        except tk.TclError:
            pass


def journal_entry(cmdr, is_beta, system, station, entry, state):
    if this.nav is not None:
        try:
            this.nav.on_journal(entry, state)
        except Exception:  # noqa: BLE001
            logger.exception("ForgeLab Navigator journal handling failed")


def dashboard_entry(cmdr, is_beta, entry):
    if this.nav is not None:
        try:
            this.nav.on_status(entry)
        except Exception:  # noqa: BLE001
            logger.exception("ForgeLab Navigator status handling failed")


def plugin_prefs(parent, cmdr, is_beta):
    import myNotebook as nb  # type: ignore
    frame = nb.Frame(parent)
    if this.nav is None:
        nb.Label(frame, text=this.error or "Unavailable").grid(padx=10, pady=10)
        return frame
    hotkeys = this.nav.integrations.get("hotkeys")
    if hotkeys:
        hotkeys["bound"] = host_tk.bound_hotkeys()
    this.apply_prefs = ui.settings_form(frame, this.nav, nb.Checkbutton, nb.Label)
    return frame


def prefs_changed(cmdr, is_beta):
    if this.apply_prefs is not None:
        this.apply_prefs()


def plugin_stop():
    if this.nav is not None:
        this.nav.save()
        this.host.overlay(None)
