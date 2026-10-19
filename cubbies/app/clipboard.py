"""Cut / copy / paste (in Nemo's format) and creating new files."""

import gi
import os
import shutil
import sys

from gi.repository import Gdk, Gio, GLib, Gtk

from ..core import DEBUG, dbg, undoable
from ..desktop_env import IS_MATE
from ..dialogs import tell
from ..files import uris_to_paths
from ..hotkeys import selection_owner_info


class AppClipboard:
    """Cut / copy / paste. Part of App."""

    # -- cut / copy / paste (shares Nemo's clipboard format, so Nemo can paste what you copy here)
    # Nemo and Thunar use the gnome name for the file list, Caja the mate one
    CLIP_TARGETS = ("x-special/gnome-copied-files", "x-special/mate-copied-files",
                    "text/uri-list", "UTF8_STRING", "text/plain;charset=utf-8", "text/plain",
                    "STRING", "TEXT")

    def _clip_owner_widget(self):
        """An invisible widget that owns the system clipboard while files are copied here.
        (Gtk.Clipboard.set_with_data cannot be used from Python, so the older selection
        calls are used: they work, and Nemo / the desktop can then paste the files.)"""
        w = getattr(self, "_clipw", None)
        if w is None:
            w = self._clipw = Gtk.Invisible()
            w.realize()
            for i, name in enumerate(self.CLIP_TARGETS):
                Gtk.selection_add_target(w, Gdk.SELECTION_CLIPBOARD,
                                         Gdk.Atom.intern(name, False), i)
            w.connect("selection-get", self._on_clip_get)
            w.connect("selection-clear-event", self._on_clip_clear)
        return w

    def _on_clip_get(self, _w, sel, info, _time):
        try:
            # what was copied when the clipboard was taken (not affected by anything since)
            clip = getattr(self, "_clip_offer", None) or self.clip or {"mode": "copy",
                                                                         "paths": []}
            uris = [Gio.File.new_for_path(p).get_uri() for p in clip["paths"]]
            if info in (0, 1):
                sel.set(sel.get_target(), 8, (clip["mode"] + "\n" + "\n".join(uris)).encode())
            elif info == 2:
                sel.set(sel.get_target(), 8, ("\r\n".join(uris) + "\r\n").encode())
            else:
                sel.set_text("\n".join(clip["paths"]), -1)
            dbg("clipboard asked for", sel.get_target().name())
        except Exception as exc:
            dbg("clipboard answer failed:", repr(exc))

    def _on_clip_clear(self, *_a):
        self._clip_owned = False
        if DEBUG:
            dbg("clipboard: another program took it over:", selection_owner_info())
        return False

    def clip_set(self, mode, paths):
        self.clip = {"mode": mode, "paths": list(paths)}
        self._clip_offer = {"mode": mode, "paths": list(paths)}
        self._clip_ignore_until = GLib.get_monotonic_time() // 1000 + 800
        self._clip_owned = False
        try:
            w = self._clip_owner_widget()
            t = Gtk.get_current_event_time()
            if not t:
                try:
                    gi.require_version("GdkX11", "3.0")
                    from gi.repository import GdkX11
                    t = GdkX11.x11_get_server_time(w.get_window())
                except Exception:
                    t = Gdk.CURRENT_TIME
            self._clip_owned = bool(Gtk.selection_owner_set(w, Gdk.SELECTION_CLIPBOARD, t))
            dbg("clipboard owned:", self._clip_owned, "- owner now:",
                selection_owner_info() if DEBUG else "")
        except Exception as exc:
            dbg("could not take the clipboard:", repr(exc))
        if not self._clip_owned:
            try:
                Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text("\n".join(paths), -1)
            except Exception:
                pass
        dbg(mode, "->", paths)

    def on_clip_owner(self, _cb, _event):
        if getattr(self, "_clip_owned", False):
            return            # still ours (this is just the notice of taking it)
        if GLib.get_monotonic_time() // 1000 >= self._clip_ignore_until:
            dbg("clipboard: something else was copied:", selection_owner_info() if DEBUG else "")
            self.clip = None  # something else was copied: our own clipboard is stale

    def clip_get(self):
        """(mode, [paths]) from the clipboard (Nemo's or ours), or None."""
        if getattr(self, "_clip_owned", False) and self.clip:
            paths = [p for p in self.clip["paths"] if os.path.lexists(p)]
            if paths:
                return self.clip["mode"], paths
        try:
            cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            sel = None
            for name in (("x-special/mate-copied-files", "x-special/gnome-copied-files")
                         if IS_MATE else ("x-special/gnome-copied-files",
                                          "x-special/mate-copied-files")):
                sel = cb.wait_for_contents(Gdk.Atom.intern(name, False))
                if sel is not None and sel.get_length() > 0:
                    break
                sel = None
            if sel is not None:
                raw = bytes(sel.get_data()).decode("utf-8", "replace")
                lines = [ln for ln in raw.replace("\r", "").split("\n") if ln]
                if lines and lines[0] in ("copy", "cut"):
                    paths = [p for p in uris_to_paths(lines[1:]) if os.path.lexists(p)]
                    if paths:
                        return lines[0], paths
        except Exception as exc:
            dbg("could not read the clipboard:", repr(exc))
        if self.clip:
            paths = [p for p in self.clip["paths"] if os.path.lexists(p)]
            if paths:
                return self.clip["mode"], paths
        return None

    def paste_into(self, fdata):
        got = self.clip_get()
        if not got:
            return
        mode, paths = got
        if fdata.get("folder"):
            self.paste_into_folder(fdata, mode, paths)
            if mode == "cut":
                self.clip = None
            return
        if mode == "cut":
            for other in self.all_cubbies():       # it may sit in a cubby on another page
                if other is not fdata:
                    gone = [p for p in paths if p in other["items"]]
                    for p in gone:
                        other["items"].remove(p)
                    if gone:
                        self.refresh_cubby(other)
            self.add_items(fdata, paths)
            self.clip = None
            try:
                self._clip_ignore_until = GLib.get_monotonic_time() // 1000 + 800
                if getattr(self, "_clip_owned", False):
                    Gtk.selection_owner_set(None, Gdk.SELECTION_CLIPBOARD,
                                            Gtk.get_current_event_time())
                    self._clip_owned = False
                else:
                    Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).clear()
            except Exception:
                pass
            return
        copies = []
        self.make_store()
        for p in paths:
            try:
                dest = self.unique_path(self.store_dir(), os.path.basename(p.rstrip("/")))
                if os.path.isdir(p) and not os.path.islink(p):
                    shutil.copytree(p, dest, symlinks=True)
                else:
                    shutil.copy2(p, dest)
                copies.append(dest)
            except Exception as exc:
                print("Cubbies: could not copy", p, "-", exc, file=sys.stderr)
        if copies:
            self.add_items(fdata, copies)

    @undoable("Create")
    def create_in_store(self, fdata, kind, template=None):
        """Create a new folder / empty file / file from a template inside ~/Cubbies and
        put it in the cubby."""
        if kind == "folder":
            name = "New Folder"
        else:
            name = os.path.basename(template) if template else "New Document.txt"
        try:
            base = self.folder_of(fdata) or self.store_dir()
            os.makedirs(base, exist_ok=True)
            dest = self.unique_path(base, name)
            if kind == "folder":
                os.mkdir(dest)
            elif template:
                shutil.copy2(template, dest)
            else:
                open(dest, "x").close()
            self.undo_note("made", dest)
        except Exception as exc:
            print("Cubbies: could not create", name, "-", exc, file=sys.stderr)
            tell(f"Could not create “{name}”", str(exc))
            return
        if fdata.get("folder"):
            self.refresh_cubby(fdata)
        else:
            self.add_items(fdata, [dest])
        # then type its name straight away, right where it sits (like the file manager)
        self.edit_new_item(fdata, dest)

    def edit_new_item(self, fdata, path, tries=12):
        win = self.find_cubby_window(fdata)
        if win is None:
            return

        state = {"left": tries, "scrolled": False}

        def go():
            ev = win.item_widgets.get(path)
            if ev is not None and ev.get_mapped() and ev.cubby_label.get_allocated_width() > 1:
                if not state["scrolled"]:
                    state["scrolled"] = True
                    sw = win.flow.get_parent()
                    while sw is not None and not isinstance(sw, Gtk.ScrolledWindow):
                        sw = sw.get_parent()
                    pos = ev.translate_coordinates(win.flow, 0, 0)
                    if sw is not None and pos:
                        adj = sw.get_vadjustment()
                        top, h = pos[1], ev.get_allocated_height()
                        if top < adj.get_value():
                            adj.set_value(top)
                            return True
                        if top + h > adj.get_value() + adj.get_page_size():
                            adj.set_value(top + h - adj.get_page_size())
                            return True
                self.clear_selection()
                win.set_selection({path})
                win.edit_item_name(path)
                return False
            state["left"] -= 1
            return state["left"] > 0
        GLib.timeout_add(60, go)
