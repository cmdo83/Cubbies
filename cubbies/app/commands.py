"""Commands from the command line, run in the copy that's already running."""

import os
import sys

from gi.repository import GLib, Gtk

from ..core import LAUNCHER, dbg
from ..layouts import apply_layout, load_layout, save_layout


class AppCommands:
    """Command-line commands. Part of App."""

    # -- commands from the command line (cubbies --help lists them)
    def run_command(self, name, arg=""):
        dbg("command from the command line:", name, arg)
        if name in ("hide", "show"):
            if self.hidden != (name == "hide"):
                self.toggle_hidden()
        elif name == "refresh":
            self.refresh_all()
        elif name == "page":
            self.go_to_page_named(arg)
        elif name == "new-cubby":
            if self.hidden:
                self.toggle_hidden()
            self.new_cubby(arg or None)
        elif name == "new-launch-bar":
            self.new_launch_bar()
        elif name == "page-bar":
            self.pager.key_toggle()
        elif name == "manage-pages":
            GLib.idle_add(lambda: self.open_page_order(toggle=True) and False)
        elif name in ("lock-all", "unlock-all"):
            self.setting_set("lock_all", name == "lock-all")
            for win in self.windows.values():
                win.update_title()
        elif name == "save-layout":
            save_layout(self.cfg, arg)
        elif name == "restore-layout":
            self.restore_layout(arg)
        elif name == "settings":
            GLib.idle_add(lambda: self.open_settings() and False)
        elif name == "restore":
            self.restore_from_file(arg, ask_first=False)
        elif name == "restart":
            self.save()
            os.execv(sys.executable, [sys.executable, LAUNCHER])
        elif name == "quit":
            Gtk.main_quit()
        else:
            print("Cubbies: unknown command", name, file=sys.stderr)

    def go_to_page_named(self, which):
        pages = self.cfg["pages"]
        which = (which or "").strip()
        dest = None
        if which.isdigit() and 1 <= int(which) <= len(pages):
            dest = int(which) - 1
        else:
            for i, page in enumerate(pages):
                if page["name"].casefold() == which.casefold():
                    dest = i
                    break
        if dest is None:
            print(f"Cubbies: there is no page {which!r}", file=sys.stderr)
            return
        if dest != self.cfg["page"]:
            self.change_page(dest - self.cfg["page"], force=True)

    def restore_layout(self, name):
        """Put every cubby back where a saved layout had it (rebuilding the windows, so
        rolled-up, docked and bottom-title cubbies come back exactly as they were)."""
        snap = load_layout(name)
        if snap is None:
            return 0
        n = apply_layout(self.cfg, snap)
        for win in list(self.windows.values()):
            win.destroy()
        self.windows = {}
        self.show_page()
        self.save()
        dbg("layout", name, "restored for", n, "cubbies")
        return n
