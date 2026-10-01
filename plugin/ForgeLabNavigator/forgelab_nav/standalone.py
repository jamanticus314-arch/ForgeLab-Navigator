"""Run ForgeLab Navigator without EDMC: its own small window + journal tailer.

    python -m forgelab_nav.standalone [--journal-dir PATH] [--state-dir PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import tkinter as tk
from pathlib import Path

from . import __version__, host_tk, session, ui


def default_journal_dir():
    home = Path(os.environ.get("USERPROFILE", Path.home()))
    return home / "Saved Games" / "Frontier Developments" / "Elite Dangerous"


def default_state_dir():
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / "ForgeLabNavigator" if base else Path.home() / ".forgelab-navigator"


class JournalTailer(threading.Thread):
    """Follows the newest Journal.*.log and Status.json; hands entries to the UI thread."""

    def __init__(self, directory, on_entry, on_status, schedule, interval=0.5):
        super().__init__(name="forgelab-journal", daemon=True)
        self.directory = Path(directory)
        self.on_entry, self.on_status, self.schedule = on_entry, on_status, schedule
        self.interval = interval
        self.stop_event = threading.Event()
        self.path = None
        self.offset = 0
        self.status_mtime = None

    def _newest(self):
        files = sorted(self.directory.glob("Journal.*.log"))
        return files[-1] if files else None

    def start_at_end(self):
        self.path = self._newest()
        self.offset = self.path.stat().st_size if self.path else 0
        status = self.directory / "Status.json"
        self.status_mtime = status.stat().st_mtime_ns if status.exists() else None

    def _drain(self, partial):
        """Deliver complete lines appended to the current file; return the unfinished tail."""
        try:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                chunk = f.read()
                self.offset = f.tell()
        except OSError:
            return partial
        if not chunk:
            return partial
        lines = (partial + chunk).split(b"\n")
        partial = lines.pop()
        for line in lines:
            try:
                entry = json.loads(line.decode("utf-8-sig"))
            except ValueError:
                continue
            self.schedule(lambda e=entry: self.on_entry(e))
        return partial

    def run(self):
        partial = b""
        while not self.stop_event.wait(self.interval):
            if self.path is not None:
                partial = self._drain(partial)
            newest = self._newest()
            if newest is not None and newest != self.path:
                # The game started a new journal: finish the old one first (done above).
                self.path, self.offset, partial = newest, 0, b""
                partial = self._drain(partial)
            status = self.directory / "Status.json"
            try:
                mtime = status.stat().st_mtime_ns
                if mtime != self.status_mtime:
                    self.status_mtime = mtime
                    data = json.loads(status.read_text(encoding="utf-8"))
                    self.schedule(lambda d=data: self.on_status(d))
            except (OSError, ValueError):
                pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="ForgeLab Navigator (standalone)")
    ap.add_argument("--journal-dir", default=str(default_journal_dir()))
    ap.add_argument("--state-dir", default=str(default_state_dir()))
    args = ap.parse_args(argv)
    journal_dir = Path(args.journal_dir)

    root = tk.Tk()
    root.title(f"ForgeLab Navigator {__version__}")
    root.minsize(360, 120)
    host = host_tk.TkHost(lambda: journal_dir)
    nav = session.Navigator(host, args.state_dir)
    host.overlay_client = None
    panel = ui.NavigatorPanel(root, nav)
    panel.pack(fill="both", expand=True, padx=8, pady=6)
    host.attach(root, panel)

    ontop = tk.BooleanVar(value=True)
    root.attributes("-topmost", True)

    def toggle_top():
        root.attributes("-topmost", bool(ontop.get()))

    def open_settings():
        win = tk.Toplevel(root)
        win.title("ForgeLab Navigator settings")
        frame = tk.Frame(win)
        frame.pack(fill="both", expand=True)
        apply = ui.settings_form(frame, nav)
        tk.Button(win, text="Save", command=lambda: (apply(), win.destroy())).pack(pady=6)

    menu = tk.Menu(root)
    view = tk.Menu(menu, tearoff=0)
    view.add_checkbutton(label="Always on top", variable=ontop, command=toggle_top)
    view.add_command(label="Settings...", command=open_settings)
    menu.add_cascade(label="Navigator", menu=view)
    root.config(menu=menu)

    if not journal_dir.is_dir():
        nav.say(f"Journal folder not found: {journal_dir}. Start with --journal-dir.", "bad")
    nav.bootstrap(journal_dir)
    tailer = JournalTailer(journal_dir, nav.on_journal, nav.on_status, host.schedule)
    tailer.start_at_end()
    tailer.start()

    def tick():
        nav.push_overlay(keepalive=True)
        root.after(15000, tick)
    root.after(15000, tick)

    def on_close():
        tailer.stop_event.set()
        nav.save()
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    sys.exit(main())
