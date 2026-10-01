"""Tk panel shared by the EDMC plugin and the standalone app.

Plain tk widgets so EDMC's theme can style them. The panel never talks to the
game; it renders Navigator.snapshot() and calls Navigator commands.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tkinter as tk
from tkinter import ttk

from . import session

LEVEL_COLOURS = {"good": "#3cb371", "warn": "#e8a33d", "bad": "#e0524a"}
KIND_LABEL = {"neutron": "Neutron", "scoop": "Refuel stop", "destination": "Destination"}
EVIDENCE_LABEL = {"reported": "reported", "predicted": "ForgeLab prediction",
                  "confirmed": "prediction confirmed in game", "seen in game": "seen in game",
                  "generated": "predicted by ForgeLab", "class confirmed": "confirmed in game",
                  "class contradicted": "NOT scoopable in game"}


def copy_to_clipboard(widget, text):
    """Put text on the system clipboard (Tk natively; CLI tools on Linux)."""
    if sys.platform.startswith("linux"):
        cli = os.getenv("EDMC_CLIPBOARD_CLI")
        if not cli:
            for cmd in ("wl-copy", "xclip -selection clipboard", "xsel --clipboard --input"):
                if shutil.which(cmd.split()[0]):
                    cli = cmd
                    break
        if cli:
            try:
                subprocess.run(cli.split(), input=text.encode("utf-8"), check=True, timeout=5)
                return
            except (OSError, subprocess.SubprocessError):
                pass
    widget.clipboard_clear()
    widget.clipboard_append(text)
    widget.update_idletasks()


def fmt_ly(v):
    return f"{v:,.0f} LY"


def fmt_eta(seconds):
    m = int(round(seconds / 60.0))
    if m < 60:
        return f"~{max(m, 1)} min"
    return f"~{m // 60} h {m % 60:02d} min"


class Autocomplete:
    """Suggestion list under an Entry (recent destinations + named systems)."""

    def __init__(self, entry, source, on_pick):
        self.entry, self.source, self.on_pick = entry, source, on_pick
        self.popup = None
        self.listbox = None
        entry.bind("<KeyRelease>", self._typed, add="+")
        entry.bind("<Down>", self._down, add="+")
        entry.bind("<Escape>", lambda e: self.hide(), add="+")
        entry.bind("<FocusOut>", lambda e: entry.after(150, self.hide), add="+")

    def _typed(self, event):
        if event.keysym in ("Down", "Up", "Return", "Escape", "Tab"):
            return
        items = self.source(self.entry.get())
        if not items:
            self.hide()
            return
        if self.popup is None:
            self.popup = tk.Toplevel(self.entry)
            self.popup.wm_overrideredirect(True)
            self.popup.attributes("-topmost", True)
            self.listbox = tk.Listbox(self.popup, height=8, activestyle="dotbox", exportselection=False)
            self.listbox.pack(fill="both", expand=True)
            self.listbox.bind("<ButtonRelease-1>", self._chosen)
            self.listbox.bind("<Return>", self._chosen)
            self.listbox.bind("<Escape>", lambda e: (self.hide(), self.entry.focus_set()))
        self.listbox.delete(0, "end")
        for item in items:
            self.listbox.insert("end", item)
        self.listbox.configure(height=min(8, len(items)))
        x = self.entry.winfo_rootx()
        y = self.entry.winfo_rooty() + self.entry.winfo_height()
        self.popup.geometry(f"{max(self.entry.winfo_width(), 260)}x{min(8, len(items)) * 18 + 4}+{x}+{y}")
        self.popup.deiconify()

    def _down(self, event):
        if self.listbox is not None and self.popup is not None and self.popup.winfo_viewable():
            self.listbox.focus_set()
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(0)
            self.listbox.activate(0)
        return "break"

    def _chosen(self, event=None):
        sel = self.listbox.curselection()
        if sel:
            value = self.listbox.get(sel[0])
            self.entry.delete(0, "end")
            self.entry.insert(0, value)
            self.hide()
            self.entry.focus_set()
            self.on_pick(value)

    def hide(self):
        if self.popup is not None:
            self.popup.withdraw()


class NavigatorPanel(tk.Frame):
    def __init__(self, parent, nav: "session.Navigator", on_theme=None):
        super().__init__(parent)
        self.nav = nav
        self.on_theme = on_theme       # EDMC: re-apply theme after showing new widgets
        self.route_window = None
        self.columnconfigure(1, weight=1)

        # Destination row
        self.title = tk.Label(self, text="ForgeLab Navigator", anchor="w")
        self.title.grid(row=0, column=0, columnspan=3, sticky="we")
        tk.Label(self, text="To:").grid(row=1, column=0, sticky="w")
        self.dest = tk.Entry(self)
        self.dest.grid(row=1, column=1, sticky="we", padx=(2, 2))
        self.dest.bind("<Return>", lambda e: self._plot())
        self.plot_btn = tk.Button(self, text="Plot", command=self._plot, width=6)
        self.plot_btn.grid(row=1, column=2, sticky="e")
        self.dest.bind("<Button-3>", self._recent_menu)
        self.auto = Autocomplete(self.dest, lambda t: session.suggest(t, extra=self.nav.snapshot()["recents"]),
                                 lambda v: self._plot())

        # Next waypoint: the one thing that matters in flight.
        self.next_btn = tk.Button(self, text="", anchor="w", command=self._copy, relief="groove")
        self.next_btn.grid(row=2, column=0, columnspan=3, sticky="we", pady=(4, 0))
        self.detail = tk.Label(self, text="", anchor="w", justify="left")
        self.detail.grid(row=3, column=0, columnspan=3, sticky="we")
        self.progress = tk.Label(self, text="", anchor="w", justify="left")
        self.progress.grid(row=4, column=0, columnspan=3, sticky="we")
        self.fuel = tk.Label(self, text="", anchor="w", justify="left", wraplength=320)
        self.fuel.grid(row=5, column=0, columnspan=3, sticky="we")
        self.tip = tk.Label(self, text="", anchor="w", justify="left", wraplength=320)
        self.tip.grid(row=6, column=0, columnspan=3, sticky="we")
        self.leg = tk.Label(self, text="", anchor="w", justify="left", wraplength=320)
        self.leg.grid(row=7, column=0, columnspan=3, sticky="we")

        # Offer from a galaxy-map plot.
        self.offer = tk.Frame(self)
        self.offer_text = tk.Label(self.offer, text="", anchor="w", justify="left", wraplength=320)
        self.offer_text.grid(row=0, column=0, columnspan=2, sticky="we")
        tk.Button(self.offer, text="Use neutron route", command=self.nav.accept_offer).grid(row=1, column=0, sticky="w")
        tk.Button(self.offer, text="No thanks", command=self.nav.dismiss_offer).grid(row=1, column=1, sticky="w")
        self.offer.grid(row=8, column=0, columnspan=3, sticky="we")

        # Controls
        self.controls = tk.Frame(self)
        self.btn_route = tk.Button(self.controls, text="Route", command=self.show_route)
        self.btn_skip = tk.Button(self.controls, text="Skip", command=lambda: self.nav.step(1))
        self.btn_back = tk.Button(self.controls, text="Back", command=lambda: self.nav.step(-1))
        self.btn_replan = tk.Button(self.controls, text="Replan", command=self.nav.replan)
        self.btn_clear = tk.Button(self.controls, text="Clear", command=self.nav.clear)
        for i, b in enumerate((self.btn_route, self.btn_back, self.btn_skip, self.btn_replan, self.btn_clear)):
            b.grid(row=0, column=i, sticky="w", padx=(0, 2))
        self.controls.grid(row=9, column=0, columnspan=3, sticky="w", pady=(2, 0))
        self.refresh()
        if self.on_theme:
            self.on_theme(self)

    # ------------------------------------------------------------------ actions
    def _plot(self):
        self.auto.hide()
        text = self.dest.get().strip()
        error = self.nav.plot(text)
        if error:
            self.nav.say(error, "bad")
        self.refresh()

    def _copy(self):
        self.nav.copy_next()

    def _recent_menu(self, event):
        recents = self.nav.snapshot()["recents"]
        if not recents:
            return
        menu = tk.Menu(self, tearoff=0)
        for name in recents:
            menu.add_command(label=name, command=lambda n=name: (self.dest.delete(0, "end"),
                                                                self.dest.insert(0, n), self._plot()))
        if self.nav.route:
            menu.add_separator()
            menu.add_command(label="Route back to start", command=self.nav.reverse)
        menu.tk_popup(event.x_root, event.y_root)

    def show_route(self):
        if self.route_window is not None and self.route_window.winfo_exists():
            self.route_window.lift()
            self.route_window.refresh()
            return
        self.route_window = RouteWindow(self, self.nav)

    # ------------------------------------------------------------------ render
    def _plain_fg(self):
        # The title is never recoloured, so it carries the current EDMC theme's text
        # colour. (A colour captured before theming would be black on the dark theme.)
        return self.title.cget("fg")

    def refresh(self):
        v = self.nav.snapshot()
        plain = self._plain_fg()
        ship = v["ship"]
        if ship:
            self.title.configure(text=f"ForgeLab Navigator · {ship['name']} · {ship['range']:.0f} LY"
                                      f" · ×{ship['boost']:g} neutron")
        else:
            self.title.configure(text="ForgeLab Navigator · " + (v["ship_error"] or "no ship yet"))
        r = v["route"]
        if v["planning"]:
            self.next_btn.configure(text=f"  Planning route to {v['planning']['destination']}…", state="disabled")
            self._show(self.next_btn, True)
        elif r and not r["done"]:
            n = r["next"]
            if v.get("copy_kept") == n["name"]:
                status = "clipboard changed · click to copy"
            elif v.get("copied") == n["name"]:
                status = "✓ copied"
            else:
                status = "click to copy"
            self.next_btn.configure(text=f"  Next:  {n['name']}     ({status})", state="normal")
            self._show(self.next_btn, True)
        elif r and r["done"]:
            self.next_btn.configure(text=f"  Arrived: {r['destination']}", state="disabled")
            self._show(self.next_btn, True)
        else:
            self._show(self.next_btn, False)

        if r and not r["done"]:
            n = r["next"]
            bits = [KIND_LABEL.get(n["kind"], n["kind"])]
            if n["kind"] == "neutron" and n["evidence"]:
                bits.append(EVIDENCE_LABEL.get(n["evidence"], n["evidence"]))
            if n["kind"] == "scoop" and n["star_class"]:
                label = EVIDENCE_LABEL.get(n["evidence"], n["evidence"])
                bits.append(f"class {n['star_class']} star ({label})")
            bits.append(f"~{n['jumps']} jump{'s' if n['jumps'] != 1 else ''}")
            bits.append(fmt_ly(n["distance"]))
            self.detail.configure(text=" · ".join(bits))
            left = r["jumps_left"]
            flown = f"{r['flown']} flown · " if r["flown"] else ""
            self.progress.configure(text=f"{flown}~{left} jump{'s' if left != 1 else ''} to go · "
                                         f"{fmt_ly(r['distance_left'])} · {fmt_eta(r['eta_seconds'])} "
                                         f"to {r['destination']}")
            self._show(self.detail, True)
            self._show(self.progress, True)
        else:
            self._show(self.detail, False)
            self._show(self.progress, False)

        advice = v["fuel_advice"]
        if advice:
            self.fuel.configure(text=advice["text"], fg=LEVEL_COLOURS.get(advice["level"], plain))
        self._show(self.fuel, bool(advice))

        tip = v["tip"]
        notes = (r or {}).get("notes") or []
        text = tip["text"] if tip else ""
        if notes and not text:
            text = notes[0]
        self.tip.configure(text=text, fg=LEVEL_COLOURS.get(tip["level"], plain) if tip else plain)
        self._show(self.tip, bool(text))

        leg = v["leg"]
        if leg:
            n_scoop = leg["scoopable"]
            line = (f"In-game plot: {leg['jumps']} jump{'s' if leg['jumps'] != 1 else ''} · "
                    f"{n_scoop} scoopable star{'s' if n_scoop != 1 else ''}")
            if leg["warning"]:
                line += " · ⚠ " + leg["warning"]
            else:
                line += " · no fuel shortfall found"
            self.leg.configure(text=line, fg=LEVEL_COLOURS["warn"] if leg["warning"] else plain)
            self._show(self.leg, True)
        else:
            self._show(self.leg, False)

        o = v["offer"]
        if o:
            saved = o["plotted"] - o["jumps"]
            self.offer_text.configure(text=f"The galaxy map plotted {o['plotted']} jumps to {o['destination']}. "
                                           f"A neutron route takes {o['jumps']} ({saved} fewer). "
                                           "In game: !nav yes or !nav no.")
            self._show(self.offer, True)
        else:
            self._show(self.offer, False)
        active = bool(r)
        for b in (self.btn_route, self.btn_skip, self.btn_back, self.btn_replan, self.btn_clear):
            b.configure(state="normal" if active else "disabled")
        self._show(self.controls, active or bool(v["planning"]))
        if self.route_window is not None and self.route_window.winfo_exists():
            self.route_window.refresh()

    @staticmethod
    def _show(widget, visible):
        if visible:
            widget.grid()
        else:
            widget.grid_remove()


class RouteWindow(tk.Toplevel):
    COLUMNS = (("#", 36), ("System", 230), ("Stop", 110), ("Jumps", 50), ("LY", 70), ("Evidence", 170))

    def __init__(self, parent, nav):
        super().__init__(parent)
        self.nav = nav
        self.title("ForgeLab route")
        self.geometry("800x460")
        self.summary = tk.Label(self, anchor="w", justify="left")
        self.summary.pack(fill="x", padx=6, pady=4)
        frame = tk.Frame(self)
        frame.pack(fill="both", expand=True, padx=6)
        self.tree = ttk.Treeview(frame, columns=[c for c, _ in self.COLUMNS], show="headings", selectmode="browse")
        for name, width in self.COLUMNS:
            self.tree.heading(name, text=name)
            self.tree.column(name, width=width, anchor="w" if name in ("System", "Stop", "Evidence") else "e")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.tag_configure("done", foreground="#888888")
        self.tree.tag_configure("next", background="#ffe9b3")
        self.tree.bind("<Double-1>", self._copy_row)
        tk.Label(self, text="Double-click a system to copy its name.", anchor="w").pack(fill="x", padx=6, pady=(2, 6))
        self.refresh()

    def _copy_row(self, event):
        item = self.tree.focus()
        if item:
            name = self.tree.item(item, "values")[1]
            self.nav.copy_text(name)

    def refresh(self):
        r = self.nav.route
        self.tree.delete(*self.tree.get_children())
        if not r:
            self.summary.configure(text="No route.")
            return
        s = r.ship
        self.summary.configure(
            text=f"{r.start['name']} → {r.destination['name']}: {r.total_jumps} jumps "
                 f"(without neutrons: {r.direct_jumps}) · {s['name']}, {s['range']:.1f} LY, "
                 f"boosted {s['boost_range']:.0f} LY")
        stop_names = {"neutron": "Neutron", "scoop": "Refuel", "destination": "Destination"}
        for i, w in enumerate(r.waypoints):
            tags = ("done",) if i < r.next_index else ("next",) if i == r.next_index else ()
            stop = stop_names.get(w.kind, w.kind) + (f" ({w.star_class})" if w.kind == "scoop" else "")
            evidence = EVIDENCE_LABEL.get(self.nav.evidence(w), w.evidence)
            self.tree.insert("", "end", values=(i + 1, w.name, stop, w.jumps, f"{w.distance:,.0f}", evidence),
                             tags=tags)
        children = self.tree.get_children()
        if children and r.next_index < len(children):
            self.tree.see(children[r.next_index])


def integration_status(nav):
    """Plain-language lines about the optional in-game helpers."""
    out = []
    overlay = nav.integrations.get("overlay")
    if overlay is True:
        hidden = "" if nav.settings.overlay else " Guidance is hidden (!nav show)."
        out.append("In-game overlay: EDMC Modern Overlay detected." + hidden)
    elif overlay is False:
        out.append("In-game overlay: EDMC Modern Overlay not found, so guidance shows only here.")
    hotkeys = nav.integrations.get("hotkeys")
    if hotkeys:
        bound = hotkeys.get("bound")
        counts = f"{hotkeys['registered']} ForgeLab actions registered"
        if bound is not None:
            counts += f", {bound} bound"
        hint = " Bind them in the EDMC Hotkeys settings tab." if not bound else ""
        out.append(f"Hotkeys: {counts}.{hint}")
    elif hotkeys is not None:
        out.append("Hotkeys: EDMC Hotkeys not found; use the panel or !nav chat commands.")
    return out


def settings_form(parent, nav, check_factory=None, label_factory=None, frame_factory=None):
    """Build a settings form; returns a function that applies it to nav.settings."""
    check_factory = check_factory or tk.Checkbutton
    label_factory = label_factory or tk.Label
    s = nav.settings
    rows = [
        ("auto_copy", "Copy the next waypoint automatically when you arrive or supercharge"),
        ("copy_on_galaxy_map", "Make sure it is on the clipboard when you open the galaxy map "
                               "(never over something you copied since)"),
        ("use_predicted", "Use ForgeLab-predicted neutron stars (more boosts where the map is sparse)"),
        ("auto_replan", "Replan automatically if you leave the route"),
        ("offer_from_galaxy_map", "Offer a neutron route when you plot a long route in the galaxy map"),
        ("overlay", "Show guidance in game (needs EDMC Modern Overlay)"),
    ]
    variables = {}
    label_factory(parent, text="ForgeLab Navigator").grid(row=0, column=0, sticky="w", padx=10, pady=(8, 4))
    for i, (key, text) in enumerate(rows, 1):
        var = tk.BooleanVar(value=getattr(s, key))
        check_factory(parent, text=text, variable=var).grid(row=i, column=0, sticky="w", padx=10)
        variables[key] = var
    field = nav.field
    label_factory(parent, text=f"Field checks so far: {field.get('confirmed', 0)} predicted neutron stars confirmed, "
                               f"{field.get('contradicted', 0)} contradicted, "
                               f"{field.get('uncatalogued', 0)} new neutron stars seen."
                  ).grid(row=len(rows) + 1, column=0, sticky="w", padx=10, pady=(8, 0))
    label_factory(parent, text="In-game chat: " + nav.CHAT_HELP
                  ).grid(row=len(rows) + 2, column=0, sticky="w", padx=10, pady=(4, 0))
    for i, line in enumerate(integration_status(nav)):
        label_factory(parent, text=line).grid(row=len(rows) + 3 + i, column=0, sticky="w", padx=10,
                                              pady=(4 if i == 0 else 0, 0))

    def apply():
        for key, var in variables.items():
            setattr(s, key, bool(var.get()))
        nav.settings_changed()
    return apply
