"""System places (Computer, Home, Trash, Network, drives) as icons, and the Trash."""

import os
import shutil
import sys

from gi.repository import Gio, GLib

from ..core import dbg, save_config, undoable
from ..desktop_env import FILE_MANAGER, IS_XFCE
from ..desktop_icons import DESKTOP_LINKS, drag_from_desktop, nemo_desktop_settings
from ..dialogs import confirm
from ..files import trash_has_items
from ..items import SYSTEM_PLACES, place_of
from ..cubby.cubby import Cubby


class AppPlaces:
    """System places and the Trash. Part of App."""

    # -- system places (Computer, Home, Trash, Network, drives) as icons in cubbies
    def place_launcher(self, uri, name, icon):
        """A small shortcut file in the store that opens a place like computer:///."""
        self.make_store()
        safe = "".join(c for c in name if c not in "/\\") or "Place"
        path = self.unique_path(self.store_dir(), safe + ".desktop")
        opener = FILE_MANAGER if shutil.which(FILE_MANAGER) else "xdg-open"
        target = uri
        if IS_XFCE and uri == "computer:///":
            target = "/"                   # Thunar has no Computer view: the File System
            if name == "Computer":
                name = "File System"       # (what Xfce's own desktop icon is called)
        with open(path, "w") as fh:
            fh.write("[Desktop Entry]\nType=Application\n"
                     f"Name={name}\nIcon={icon}\nExec={opener} {target}\n"
                     f"X-Cubbies-Place={uri}\nNoDisplay=true\n")
        os.chmod(path, 0o755)
        self.undo_note("made", path)
        return path

    # -- the desktop's own Computer / Home / Trash / Network icons
    def link_name_of(self, path):
        """Which of the desktop's own icons a cubby item stands for, or None."""
        place = place_of(path)
        if place:
            return next((n for n, _k, u in DESKTOP_LINKS if u == place), None)
        if os.path.normpath(path) == os.path.normpath(os.path.expanduser("~")):
            return "home"
        if IS_XFCE and os.path.normpath(path) == "/":
            return "computer"              # Xfce's File System icon
        return None

    def want_link_hidden(self, name):
        """It was taken from the desktop into a cubby: hide it there once it is in."""
        if not self.setting("hide_taken_links"):
            return
        self.__dict__.setdefault("_link_wanted", {})[name] = GLib.get_monotonic_time()
        self.sync_links_soon()

    def sync_links_soon(self):
        if getattr(self, "_links_timer", 0):
            return

        def go():
            self._links_timer = 0
            try:
                self.sync_links()
            except Exception as exc:
                dbg("desktop icons:", repr(exc))
            return False
        self._links_timer = GLib.timeout_add(300, go)

    def sync_links(self):
        """Hide the desktop icons just taken into a cubby; show again the ones Cubbies hid
        that no cubby holds any more (or all of them when the setting is off)."""
        settings = nemo_desktop_settings()
        if settings is None:
            return
        held = {self.link_name_of(p) for f in self.all_cubbies() for p in f.get("items", [])}
        hidden = list(self.cfg.get("hidden_links", []))
        wanted = self.__dict__.setdefault("_link_wanted", {})
        now = GLib.get_monotonic_time()
        on = self.setting("hide_taken_links")
        keys = {n: k for n, k, _u in DESKTOP_LINKS}
        touched = False
        for name, t in list(wanted.items()):
            if name in held and on:
                del wanted[name]
                if settings.get_boolean(keys[name]):
                    settings.set_boolean(keys[name], False)
                    touched = True
                    dbg("hid the desktop's", name, "icon (it is in a cubby now)")
                    if name not in hidden:
                        hidden.append(name)
            elif now - t > 10_000_000:      # never arrived in a cubby
                del wanted[name]
        for name in list(hidden):
            if name not in held or not on:
                hidden.remove(name)
                if not settings.get_boolean(keys[name]):
                    settings.set_boolean(keys[name], True)
                    touched = True
                    dbg("showed the desktop's", name, "icon again")
        if hidden != self.cfg.get("hidden_links", []):
            if hidden:
                self.cfg["hidden_links"] = hidden
            else:
                self.cfg.pop("hidden_links", None)
            save_config(self.cfg)
        if touched:
            Gio.Settings.sync()

    def desktop_link_dropped(self, path):
        """One of Cubbies' Trash / Computer / Network shortcuts landed on the desktop (dragged
        out of a cubby): put the desktop's own icon back instead (it shows the Trash full or
        empty, which a shortcut can't) and drop the shortcut."""
        place = place_of(path) if os.path.lexists(path) else None
        name = next((n for n, _k, u in DESKTOP_LINKS if u and u == place), None)
        if name is None or nemo_desktop_settings() is None:
            return False
        if IS_XFCE and name == "network":
            return False                 # (Xfce has no Network icon to give back)
        try:
            os.remove(path)
        except OSError:
            return False
        for f in self.all_cubbies():     # a moved one leaves its cubby (a copy stays)
            gone = [p for p in f.get("items", []) if place_of(p) == place
                    and not os.path.lexists(p)]
            if gone:
                f["items"] = [p for p in f["items"] if p not in gone]
                self.refresh_cubby(f)
        self.show_desktop_link(name)
        self.save()
        dbg("the", name, "shortcut was put on the desktop: its desktop icon is back")
        return False

    def show_desktop_link(self, name):
        settings = nemo_desktop_settings()
        key = next(k for n, k, _u in DESKTOP_LINKS if n == name)
        if settings is not None and not settings.get_boolean(key):
            settings.set_boolean(key, True)
            Gio.Settings.sync()
        hidden = [n for n in self.cfg.get("hidden_links", []) if n != name]
        if hidden:
            self.cfg["hidden_links"] = hidden
        else:
            self.cfg.pop("hidden_links", None)

    def mounted_drives(self):
        """[(name, folder)] for the drives and shares mounted right now."""
        out = []
        try:
            for mount in Gio.VolumeMonitor.get().get_mounts():
                root = mount.get_root()
                p = root.get_path() if root else None
                if p and not mount.is_shadowed():
                    out.append((mount.get_name(), p))
        except Exception as exc:
            dbg("mounts:", exc)
        return out

    def drop_paths(self, uris, make_places=True):
        """Dropped URIs as paths. Places that aren't folders (Computer, Trash, Network, a
        share, the desktop's own Computer / Home / Trash icons) become shortcut files."""
        out = []
        known = {u: (n, i) for u, n, i in SYSTEM_PLACES}
        from_desk = []                     # asked only once, and only when it matters

        def desk():
            if not from_desk:
                from_desk.append(make_places and drag_from_desktop())
            return from_desk[0]
        home = os.path.normpath(os.path.expanduser("~"))
        for u in uris or []:
            p = Gio.File.new_for_uri(u).get_path()
            if p:
                out.append(p)
                if os.path.normpath(p) == home and desk():
                    self.want_link_hidden("home")
                elif IS_XFCE and os.path.normpath(p) == "/" and desk():
                    self.want_link_hidden("computer")
                continue
            if not make_places:
                continue
            low = u.lower().rstrip("/")
            if u in known or low + "/" in known or low + "///" in known:
                key = u if u in known else next(k for k in known
                                                if k.rstrip("/") == low.rstrip("/"))
                name, icon = known[key]
                out.append(self.place_launcher(key, name, icon))
                link = next((n for n, _k, lu in DESKTOP_LINKS if lu == key), None)
                if link and desk():
                    self.want_link_hidden(link)
            elif low.startswith("x-nemo-desktop:") or low.startswith("x-caja-desktop:"):
                # the desktop's own icons: Computer, Home, Trash, Network, drives
                stem = low.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                for n, _k, _u in DESKTOP_LINKS:
                    if n in stem:
                        self.want_link_hidden(n)
                        break
                if "home" in stem:
                    out.append(os.path.expanduser("~"))
                elif "computer" in stem:
                    out.append(self.place_launcher("computer:///", "Computer", "computer"))
                elif "trash" in stem:
                    out.append(self.place_launcher("trash:///", "Trash", "user-trash"))
                elif "network" in stem:
                    out.append(self.place_launcher("network:///", "Network",
                                                   "network-workgroup"))
                else:
                    for name, folder in self.mounted_drives():
                        if name.lower() == stem or os.path.basename(folder).lower() == stem:
                            out.append(folder)
                            break
            elif "://" in u:                # a network share (smb://, sftp://...)
                name = GLib.uri_unescape_string(u.rstrip("/").rsplit("/", 1)[-1], None) or u
                out.append(self.place_launcher(u, name, "folder-remote"))
        return out

    def add_place(self, pane, what):
        """Right-click a cubby › Add System Places › ..."""
        if what == "home":
            paths = [os.path.expanduser("~")]
        elif what.startswith("/"):
            paths = [what]
        else:
            name, icon = next((n, i) for u, n, i in SYSTEM_PLACES if u == what)
            paths = [self.place_launcher(what, name, icon)]
        self.add_items(pane, paths)

    def watch_trash(self):
        """Trash icons in cubbies show full or empty as the Trash changes."""
        try:
            self._trash_mon = Gio.File.new_for_uri("trash:///").monitor_directory(
                Gio.FileMonitorFlags.NONE, None)
            self._trash_mon.connect("changed", lambda *_a: self._trash_later())
        except Exception as exc:
            dbg("the Trash can't be watched:", exc)

    def _trash_later(self):
        if getattr(self, "_trash_timer", 0):
            return

        def go():
            self._trash_timer = 0
            full = trash_has_items()
            if full == getattr(self, "_trash_full", None):
                return False
            self._trash_full = full
            for win in self.windows.values():
                if any(place_of(p) == "trash:///" for p in win.pane.get("items", [])):
                    win.refresh()
            return False
        self._trash_timer = GLib.timeout_add(500, go)

    @undoable("Move to Trash")
    def trash_dropped(self, paths):
        """Files dropped onto a Trash icon in a cubby: moved to the Trash (and out of any
        cubby that held them)."""
        for p in paths:
            if not os.path.lexists(p) or not self.trash_path(p):
                continue
            for page in self.cfg["pages"]:
                for f in page["cubbies"]:
                    if p in f.get("items", []):
                        f["items"].remove(p)
                        self.refresh_cubby(f)
        self.save()
        GLib.timeout_add(600, lambda: self.refresh_all() and False)   # the Trash icon fills

    @undoable("Empty Trash")
    def empty_trash(self):
        if not confirm("Empty the Trash?", "Everything in the Trash is deleted for good. This "
                       "can't be undone.", "Empty Trash"):
            return
        gio = shutil.which("gio")
        if gio:
            Cubby.spawn([gio, "trash", "--empty"])
        GLib.timeout_add(1500, lambda: self.refresh_all() and False)

    def trash_path(self, path):
        try:
            Gio.File.new_for_path(path).trash(None)
            self.undo_note("trash", path)
            return True
        except Exception as exc:
            print("Cubbies: could not move to the Trash:", path, "-", exc, file=sys.stderr)
            return False
