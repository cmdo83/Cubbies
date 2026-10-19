"""Searching in a cubby, and the preview of a folder's contents."""

import gi
import os

from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from ..core import dbg
from ..files import launch
from ..items import describe
from ..widgets import hand_cursor_window


class CubbySearch:
    """Search and folder preview. Part of Cubby."""

    # -- search: a strip slides down above the icons and the icons narrow as you type
    def open_search(self):
        if getattr(self, "_search_ed", None) is not None or self.data.get("rolled"):
            return
        self.cancel_folder_preview()
        self.search_rev.set_reveal_child(True)
        GLib.timeout_add(200, self._place_search_box)

    def _place_search_box(self):
        slot = self.search_slot
        pos = slot.translate_coordinates(self, 0, 0)
        if not pos or not self.get_visible():
            return False
        wx, wy = self.get_position()
        w, h = slot.get_allocated_width(), slot.get_allocated_height()
        ed = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        ed.set_decorated(False)
        ed.set_skip_taskbar_hint(True)
        ed.set_skip_pager_hint(True)
        ed.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        ed.set_keep_above(True)
        ed.set_resizable(False)
        entry = Gtk.Entry()
        entry.set_placeholder_text("Type to search this cubby")
        entry.set_text(self._search)
        entry.set_width_chars(1)
        css = Gtk.CssProvider()
        try:
            css.load_from_data(b"entry { min-height: 0; padding: 1px 6px; }")
            entry.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        except GLib.Error:
            pass
        ed.add(entry)
        eh = max(entry.get_preferred_height()[1], 20)
        ed.set_size_request(max(60, w), eh)
        ed.move(wx + pos[0], wy + pos[1] + (h - eh) // 2)
        self._search_ed = ed
        state = {"done": False, "armed": False}

        def changed(_e):
            self._search = entry.get_text()
            self.selected = set()
            self.refresh()
            n = len(self.item_widgets)
            self.search_count.set_text(f"{n} found" if self._search.strip() else "")

        def finish(open_first=False):
            if state["done"]:
                return
            state["done"] = True
            first = next(iter(self.ordered_items()), None) if open_first else None
            self.close_search()
            if first:
                launch(first)

        def key(_w, event):
            if event.keyval == Gdk.KEY_Escape:
                finish()
                return True
            if event.keyval in (Gdk.KEY_Down, Gdk.KEY_Up):
                return True
            return False

        def watch_clicks():
            """A click anywhere outside the search box ends the search."""
            if state["done"]:
                return False
            try:
                _w, px, py, mask = self.app.watcher.root.get_device_position(
                    self.app.watcher.pointer)
                down = mask & (Gdk.ModifierType.BUTTON1_MASK | Gdk.ModifierType.BUTTON3_MASK)
                ex, ey = ed.get_position()
                ew, eh2 = ed.get_size()
                cx, cy = self.get_position()
                cw, ch = self.get_size()
                inside = (ex <= px < ex + ew and ey <= py < ey + eh2) or \
                    (cx <= px < cx + cw and cy <= py < cy + ch)   # found icons can be used
                if down and not inside and state["armed"]:
                    finish()
                    return False
                state["armed"] = state["armed"] or not down
            except Exception:
                pass
            return True

        entry.connect("changed", changed)
        entry.connect("activate", lambda _e: finish(True))
        entry.connect("key-press-event", key)
        GLib.timeout_add(50, watch_clicks)
        ed.show_all()
        t = Gtk.get_current_event_time()
        if not t:
            try:
                gi.require_version("GdkX11", "3.0")
                from gi.repository import GdkX11
                t = GdkX11.x11_get_server_time(ed.get_window())
            except Exception:
                t = 0
        ed.present_with_time(t)
        entry.grab_focus()
        return False

    def close_search(self):
        ed, self._search_ed = getattr(self, "_search_ed", None), None
        if ed is not None:
            ed.destroy()
        self.search_rev.set_reveal_child(False)
        self.search_count.set_text("")
        if self._search:
            self._search = ""
            self.refresh()

    # -- folder preview: rest the pointer on a folder to see what's inside
    def cancel_folder_preview(self, hide=True):
        if getattr(self, "_preview_timer", 0):
            GLib.source_remove(self._preview_timer)
            self._preview_timer = 0
        if hide:
            pop = getattr(self, "_preview", None)
            if pop is not None:
                self._preview = None
                pop.destroy()
            w = getattr(self, "_preview_widget", None)
            if w is not None:
                self._preview_widget = None
                try:
                    w.set_has_tooltip(True)
                except Exception:
                    pass

    PREVIEW_ROWS = 15

    def show_folder_preview(self, widget, path):
        """A small panel beside the folder listing what's inside (click one to open it).
        It goes away when the pointer leaves both the folder and the panel."""
        self._preview_timer = 0
        self.cancel_folder_preview()
        if not widget.get_mapped() or self._drag or getattr(self, "_name_editor", None):
            return False
        try:
            names = sorted((n for n in os.listdir(path) if not n.startswith(".")),
                           key=lambda n: (not os.path.isdir(os.path.join(path, n)),
                                          n.casefold()))
        except OSError as exc:
            names, problem = [], exc.strerror or str(exc)
        else:
            problem = None
        pop = Gtk.Window(type=Gtk.WindowType.POPUP)
        pop.set_keep_above(True)
        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        frame.get_style_context().add_class("cubby-preview")
        frame.set_border_width(8)
        head = Gtk.Label(xalign=0)
        head.set_text(os.path.basename(path.rstrip("/")) or path)
        head.get_style_context().add_class("head")
        head.set_ellipsize(Pango.EllipsizeMode.END)
        head.set_max_width_chars(30)
        frame.pack_start(head, False, False, 2)
        if problem or not names:
            note = Gtk.Label(label=problem or "Empty folder", xalign=0)
            note.get_style_context().add_class("dim")
            frame.pack_start(note, False, False, 2)
        for name in names[:self.PREVIEW_ROWS]:
            full = os.path.join(path, name)
            row = Gtk.EventBox()
            row.get_style_context().add_class("cubby-preview-row")
            box = Gtk.Box(spacing=6)
            box.set_border_width(2)
            try:
                gicon = describe(full, 16, load_image=False)[1]
                img = Gtk.Image.new_from_gicon(gicon, Gtk.IconSize.MENU)
            except Exception:
                img = Gtk.Image.new_from_icon_name("text-x-generic", Gtk.IconSize.MENU)
            box.pack_start(img, False, False, 0)
            lbl = Gtk.Label(label=name, xalign=0)
            lbl.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            lbl.set_max_width_chars(34)
            box.pack_start(lbl, True, True, 0)
            row.add(box)
            row.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
            row.connect("button-press-event",
                        lambda _w, e, f=full: (e.button == 1 and (launch(f),
                                                                   self.cancel_folder_preview()))
                        or True)
            hand_cursor_window(row)
            frame.pack_start(row, False, False, 0)
        if len(names) > self.PREVIEW_ROWS:
            more = Gtk.Label(label=f"and {len(names) - self.PREVIEW_ROWS} more\u2026", xalign=0)
            more.get_style_context().add_class("dim")
            frame.pack_start(more, False, False, 2)
        pop.add(frame)
        widget.set_has_tooltip(False)          # its own tooltip would cover the panel
        self._preview_widget = widget
        pop.show_all()
        # beside the folder: on its right, or its left if there is no room
        try:
            _ok, ox, oy = widget.get_window().get_origin()
            a = widget.get_allocation()
            if widget.get_has_window():
                ix, iy = ox, oy
            else:
                ix, iy = ox + a.x, oy + a.y
            pw, ph = pop.get_size()
            mon = Gdk.Display.get_default().get_monitor_at_point(ix, iy).get_workarea()
            x = ix + a.width + 6
            if x + pw > mon.x + mon.width:
                x = ix - pw - 6
            y = max(mon.y, min(iy, mon.y + mon.height - ph))
            pop.move(int(x), int(y))
            item_rect = (ix, iy, a.width, a.height)
        except Exception as exc:
            dbg("preview placement:", exc)
            item_rect = (0, 0, 0, 0)
        self._preview = pop

        def watch():
            if self._preview is not pop:
                return False
            try:
                _w, px, py, _m = self.app.watcher.root.get_device_position(self.app.watcher.pointer)
                x0, y0 = pop.get_position()
                w0, h0 = pop.get_size()
                ix, iy, iw, ih = item_rect
                over_pop = x0 - 8 <= px <= x0 + w0 + 8 and y0 - 8 <= py <= y0 + h0 + 8
                over_item = ix <= px <= ix + iw and iy <= py <= iy + ih
                gap = (min(ix + iw, x0) - 2 <= px <= max(ix, x0 + w0) + 2
                       and min(iy, y0) <= py <= max(iy + ih, y0 + h0))
                if not (over_pop or over_item or gap):
                    self.cancel_folder_preview()
                    return False
            except Exception:
                pass
            return True
        GLib.timeout_add(150, watch)
        return False

    def on_drag_data_get(self, widget, ctx, sel, info, time, path):
        paths = [p for p in self.ordered_items() if p in self.selected] \
            if path in self.selected else [path]
        sel.set_uris([Gio.File.new_for_path(p).get_uri() for p in paths])
