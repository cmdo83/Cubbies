"""Drawing a new cubby on the desktop, and taking in the desktop's icons."""

import os

from gi.repository import Gdk, GLib, Gtk

from ..core import dbg, undoable
from ..desktop_icons import DESKTOP_LINKS, desktop_icon_positions, desktop_link_positions
from ..files import inbox_icon_name
from ..items import SYSTEM_PLACES
from ..widgets import make_window, menu_item


class AppDrawing:
    """Drawing new cubbies. Part of App."""

    _band_win = None

    def show_new_band(self, x0, y0=None, x=None, y=None):
        """The box drawn while the right mouse button is dragged on the empty desktop."""
        win = self._band_win
        if x0 is None:
            if win is not None:
                win.hide()
            return
        if win is None:
            win = self._band_win = make_window("newband-win")
            win.set_keep_above(True)
            box = Gtk.Box()
            box.get_style_context().add_class("newband")
            lbl = Gtk.Label(label="New Cubby")
            box.pack_start(lbl, True, True, 0)
            win.add(box)
            win.lbl = lbl
        left, top = min(x0, x), min(y0, y)
        w, h = max(1, abs(x - x0)), max(1, abs(y - y0))
        n = 0
        if self.setting("box_select"):
            for cw in self.windows.values():
                if cw.get_visible():
                    cx, cy = cw.get_position()
                    ww, wh = cw.get_size()
                    if left <= cx + ww / 2 <= left + w and top <= cy + wh / 2 <= top + h:
                        n += 1
        win.lbl.set_text(f"Pick {n} {'Cubby' if n == 1 else 'Cubbies'}" if n else "New Cubby")
        win.lbl.set_visible(w >= 130 and h >= 60)
        win.set_size_request(w, h)
        win.resize(w, h)
        if not win.get_visible():
            win.show_all()
            win.lbl.set_visible(w >= 130 and h >= 60)
        win.move(left, top)
        ctx = win.get_child().get_style_context()
        if w >= 130 and h >= 90:
            ctx.add_class("big-enough")
        else:
            ctx.remove_class("big-enough")

    def new_cubby_from_band(self, x0, y0, x, y):
        """A box was drawn on the desktop. Nothing is made yet: a small menu asks what to
        make. Moving the pointer away from the menu fades the box and menu out; past about
        50 px they are gone (as is a click anywhere else)."""
        left, top = int(min(x0, x)), int(min(y0, y))
        w, h = int(abs(x - x0)), int(abs(y - y0))
        # drawn around cubbies (their middles inside the box): pick them, to move together
        if self.setting("box_select"):
            inside = []
            for fid, win in self.windows.items():
                if not win.get_visible():
                    continue
                wx, wy = win.get_position()
                ww, wh = win.get_size()
                if left <= wx + ww / 2 <= left + w and top <= wy + wh / 2 <= top + h:
                    inside.append(fid)
            if inside:
                self.show_new_band(None)
                old = self.picked_windows()
                self.picked = set(inside)
                for win in old + self.picked_windows():
                    win.outer.queue_draw()
                dbg("box drawn around", len(inside), "cubbies: picked to move together")
                return
        if not self.setting("draw_new"):
            self.show_new_band(None)
            return
        if w < 130 or h < 90:
            dbg("drawn box too small for a cubby:", w, h)
            self.show_new_band(None)
            return
        self.show_new_band(x0, y0, x, y)          # keep the outline while asking
        rect = (left, top, w, h)
        menu = Gtk.Menu()
        menu.get_style_context().add_class("cubbies-new-menu")
        state = {"done": False, "timer": 0}

        def choose(kind):
            state["done"] = True
            GLib.idle_add(lambda: self.create_drawn_cubby(kind, rect) and False)

        for label, kind, icons in (("Create Cubby Here", "regular", ("window-new", "list-add")),
                                   ("Create Folder Cubby Here", "folder", ("folder",)),
                                   ("Create Inbox Cubby Here", "inbox",
                                    (inbox_icon_name(), "mail-inbox")),
                                   ("Create Recent Files Cubby Here", "recent",
                                    ("document-open-recent", "appointment-soon"))):
            if kind == "recent" and self.page_recent(self.page()) is not None:
                continue                  # one Recent Files cubby per page
            mi = menu_item(label, *icons)
            mi.connect("activate", lambda _w, k=kind: choose(k))
            menu.append(mi)
        menu.show_all()

        def closed(*_a):
            if state.get("closed"):
                return
            state["closed"] = True
            if state["timer"]:
                GLib.source_remove(state["timer"])
                state["timer"] = 0
            self.show_new_band(None)
            if self._band_win is not None:
                self._band_win.set_opacity(1.0)
            GLib.idle_add(menu.destroy)

        menu.connect("deactivate", closed)

        def fade():
            """Fade with the pointer's distance from the menu; gone past 50 px."""
            try:
                top_win = menu.get_toplevel()
                if not top_win.get_visible():
                    return True
                mx, my = top_win.get_position()
                mw, mh = top_win.get_size()
                px, py = self.watcher.root.get_device_position(self.watcher.pointer)[1:3]
                dx = max(mx - px, 0, px - (mx + mw))
                dy = max(my - py, 0, py - (my + mh))
                dist = (dx * dx + dy * dy) ** 0.5
                if dist > 50:
                    dbg("pointer moved away from the new-cubby menu: cancelled")
                    state["timer"] = 0
                    menu.popdown()
                    closed()
                    return False
                alpha = 1.0 - (dist / 50.0) * 0.85
                top_win.set_opacity(alpha)
                if self._band_win is not None:
                    self._band_win.set_opacity(alpha)
            except Exception as exc:
                dbg("menu fade error:", repr(exc))
            return True

        # the menu opens at the corner where the button was let go
        anchor = Gdk.Rectangle()
        anchor.x, anchor.y, anchor.width, anchor.height = int(x) - left, int(y) - top, 1, 1
        gw = self._band_win.get_window()
        menu.popup_at_rect(gw, anchor, Gdk.Gravity.NORTH_WEST, Gdk.Gravity.NORTH_WEST, None)
        state["timer"] = GLib.timeout_add(30, fade)

    @undoable("New Cubby")
    def create_drawn_cubby(self, kind, rect):
        left, top, w, h = rect
        page = self.page()
        if kind == "folder":
            dlg = Gtk.FileChooserDialog(title="Choose a folder to show in the new cubby",
                                        action=Gtk.FileChooserAction.SELECT_FOLDER)
            dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Show Folder",
                            Gtk.ResponseType.OK)
            dlg.set_current_folder(os.path.expanduser("~"))
            resp = dlg.run()
            path = dlg.get_filename() if resp == Gtk.ResponseType.OK else None
            dlg.destroy()
            if not path or not os.path.isdir(path):
                return False
            path = os.path.abspath(path)
            fdata = self.new_cubby_data(page, os.path.basename(path) or path, left, top, w, h)
            fdata["folder"], fdata["sort"] = path, "name"
            page["cubbies"].append(fdata)
        else:
            title = {"inbox": "Inbox", "recent": "Recent Files"}.get(kind, "New Cubby")
            fdata = self.new_cubby_data(page, title, left, top, w, h)
            page["cubbies"].append(fdata)
            if kind == "inbox":
                self.set_collect(fdata, ["other"])
            elif kind == "recent":
                fdata["recent"] = True
        if self.hidden:
            self.toggle_hidden()
        self.show_page()
        self.save()
        dbg("new", kind, "cubby drawn at", rect)
        if kind in ("regular", "inbox") and self.setting("draw_takes_icons"):
            self.take_desktop_icons(fdata, rect)
        if kind == "regular":
            win = self.windows.get(fdata["id"])
            if win is not None:
                GLib.timeout_add(200, lambda: win.edit_title() and False)
        return False

    def take_desktop_icons(self, fdata, rect):
        """Desktop icons the new cubby was drawn around go into it straight away (instead of
        being hidden behind it)."""
        left, top, w, h = rect
        try:
            icons = desktop_icon_positions()
        except Exception as exc:
            dbg("could not read desktop icon positions:", repr(exc))
            return
        # the middle of the icon picture (Nemo stores its top-left corner)
        inside = [p for p, ix, iy in icons
                  if left <= ix + 32 <= left + w and top <= iy + 32 <= top + h
                  and os.path.lexists(p)]
        # Computer, Home, Trash, Network: not files, so shortcuts are made for them
        try:
            links = desktop_link_positions()
        except Exception as exc:
            dbg("could not read the desktop's own icons:", repr(exc))
            links = []
        for name, ix, iy in links:
            if not (left <= ix + 32 <= left + w and top <= iy + 32 <= top + h):
                continue
            uri = next(u for n, _k, u in DESKTOP_LINKS if n == name)
            if uri is None:
                path = os.path.expanduser("~")
            else:
                pname, picon = next((pn, pi) for pu, pn, pi in SYSTEM_PLACES if pu == uri)
                path = self.place_launcher(uri, pname, picon)
            icons.append((path, ix, iy))
            inside.append(path)
            self.want_link_hidden(name)
        if not inside:
            return
        dbg("drawn around", len(inside), "desktop icons; moving them in:", inside)
        inside.sort(key=lambda p: next(((iy, ix) for q, ix, iy in icons if q == p), (0, 0)))
        self.add_items(fdata, inside)
