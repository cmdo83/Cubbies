"""Adding files and apps, naming things in place, and deleting the cubby."""

import gi
import os

from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from ..constants import TITLE_ALIGNS
from ..core import dbg
from ..dialogs import ask, tell
from ..items import is_named_item
from ..style import font_css


class CubbyEditing:
    """Adding, naming and deleting. Part of Cubby."""

    def add_files(self, folders=False):
        action = (Gtk.FileChooserAction.SELECT_FOLDER if folders
                  else Gtk.FileChooserAction.OPEN)
        dlg = Gtk.FileChooserDialog(title="Add folders" if folders else "Add files", action=action)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Add", Gtk.ResponseType.OK)
        dlg.set_select_multiple(True)
        desktop = os.path.expanduser("~/Desktop")
        if os.path.isdir(desktop):
            dlg.set_current_folder(desktop)
        resp = dlg.run()
        paths = dlg.get_filenames()
        dlg.destroy()
        if resp == Gtk.ResponseType.OK and paths:
            self.app.add_items(self.pane, paths)

    def add_application(self):
        """Searchable list of every installed application (the same ones the start menu shows);
        select one or more and press Add."""
        store = Gtk.ListStore(Gio.Icon, str, str)  # icon, name, .desktop path
        apps = []
        for info in Gio.AppInfo.get_all():
            try:
                path = info.get_filename() if hasattr(info, "get_filename") else None
                if path and info.should_show():
                    apps.append((info.get_name() or "", info.get_icon(), path))
            except Exception:
                continue
        for name, icon, path in sorted(apps, key=lambda a: a[0].casefold()):
            store.append([icon, name, path])

        search = Gtk.SearchEntry()
        search.set_placeholder_text("Search applications…")
        flt = store.filter_new()
        flt.set_visible_func(
            lambda model, it, _d: search.get_text().casefold() in (model[it][1] or "").casefold())
        search.connect("search-changed", lambda _e: flt.refilter())

        view = Gtk.TreeView(model=flt)
        view.set_headers_visible(False)
        view.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        icon_cell = Gtk.CellRendererPixbuf()
        icon_cell.set_property("stock-size", Gtk.IconSize.LARGE_TOOLBAR)
        view.append_column(Gtk.TreeViewColumn("", icon_cell, gicon=0))
        view.append_column(Gtk.TreeViewColumn("Application", Gtk.CellRendererText(), text=1))

        dlg = Gtk.Dialog(title="Add applications")
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Add", Gtk.ResponseType.OK)
        dlg.set_default_size(380, 480)
        area = dlg.get_content_area()
        area.set_border_width(10)
        area.set_spacing(8)
        area.pack_start(search, False, False, 0)
        scroller = Gtk.ScrolledWindow()
        scroller.add(view)
        area.pack_start(scroller, True, True, 0)
        view.connect("row-activated", lambda *_a: dlg.response(Gtk.ResponseType.OK))
        dlg.show_all()
        resp = dlg.run()
        model, rows = view.get_selection().get_selected_rows()
        paths = [model[row][2] for row in rows] if resp == Gtk.ResponseType.OK else []
        dlg.destroy()
        if paths:
            self.app.add_items(self.pane, paths)

    # -- naming in place: the title turns into a text box
    def edit_title(self, select_all=True, pane=None):
        """Edit the name right in the title bar. Enter or clicking elsewhere keeps it,
        Escape puts the old name back. (A small window of its own holds the text box, because
        the cubby itself can't take the keyboard.) In a row of tabs, the tab's own name is
        edited right on the tab."""
        if (self.data.get("group") and self.app.cfg.get("tab_style", "rounded") != "menu"
                and getattr(self, "_tab_edit_rect", None) is None):
            self.edit_tab_title(pane or self.pane, select_all)
            return
        if pane is not None and pane is not self.pane:
            self.switch_pane(pane)
        if getattr(self, "_editor", None) is not None:
            return
        self.cancel_title_click()
        pane = self.pane
        old = pane["title"]
        wx, wy = self.get_position()
        ta = self.title_ev.get_allocation()
        na = self.name_box.get_allocation()
        btn_w = max(self.menu_btn.get_allocated_width() if self.menu_btn.get_visible() else 0,
                    self.close_btn.get_allocated_width() if self.close_btn.get_visible() else 0)
        cw = self.get_size()[0]
        align = self.title_align()
        tab_rect = getattr(self, "_tab_edit_rect", None)
        self._tab_edit_rect = None
        if tab_rect is not None:               # exactly over a tab's name
            x, w = tab_rect
            align = "center"
        elif align == "center":
            # the same space on both sides, so it sits right where the centred name is
            w = max(120, min(cw - 2 * btn_w - 12, max(na.width + 80, 220)))
            x = wx + (cw - w) // 2
        else:
            w = max(120, min(cw - 2 * btn_w - 12, max(na.width + 60, 200)))
            x = wx + (btn_w + 6 if align == "left" else cw - btn_w - 6 - w)
        ed = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        if tab_rect is not None:
            ed.set_resizable(False)
        ed.set_decorated(False)
        ed.set_skip_taskbar_hint(True)
        ed.set_skip_pager_hint(True)
        ed.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        ed.set_keep_above(True)
        ed.stick()
        entry = Gtk.Entry()
        entry.set_text(old)
        entry.set_alignment(TITLE_ALIGNS.get(align, 0.0))
        entry.set_width_chars(1)             # exactly as wide as asked, never wider
        entry.get_style_context().add_class("cubby-title-entry")
        css = Gtk.CssProvider()
        rules = font_css(self.data.get("title_font")) or "font-weight: bold;"
        try:
            css.load_from_data(f"entry {{ {rules} min-height: 0; padding: 2px 6px; }}".encode())
            entry.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        except GLib.Error:
            pass
        ed.add(entry)
        ed.set_resizable(False)
        eh = max(entry.get_preferred_height()[1], 20)
        ed.set_size_request(int(w), int(eh))
        ed.set_default_size(int(w), int(eh))
        ed.realize()
        ed.move(int(x), int(wy + ta.y + max(0, (ta.height - eh) // 2)))
        state = {"done": False}
        self._editor = ed
        self.update_title_visibility()

        def finish(keep):
            if state["done"]:
                return
            state["done"] = True
            name = entry.get_text().strip()
            self._editor = None
            ed.destroy()
            self.update_title_visibility()
            if keep and name and name != old:
                undo = self.app.undo_begin("Rename Cubby")
                pane["title"] = name
                self.app.save()
                self.app.undo_end(undo)
            if tab_rect is not None or (keep and name and name != old):
                self.update_title()          # (also puts an edited tab back to its size)
            dbg("title edit", "kept:" if keep else "cancelled:", pane["title"])

        def key(_w, event):
            if event.keyval == Gdk.KEY_Escape:
                finish(False)
                return True
            return False

        entry.connect("activate", lambda _e: finish(True))
        entry.connect("key-press-event", key)

        def watch_clicks():
            """A click anywhere outside the text box keeps the name (even where the click
            lands on something that never takes the keyboard, like the bare desktop)."""
            if state["done"]:
                return False
            try:
                _w, px, py, mask = self.app.watcher.root.get_device_position(
                    self.app.watcher.pointer)
                down = mask & (Gdk.ModifierType.BUTTON1_MASK | Gdk.ModifierType.BUTTON3_MASK)
                ex, ey = ed.get_position()
                ew, eh2 = ed.get_size()
                inside = ex <= px < ex + ew and ey <= py < ey + eh2
                if down and not inside and state.get("armed"):
                    finish(True)
                    return False
                state["armed"] = state.get("armed") or not down
            except Exception:
                pass
            return True

        GLib.timeout_add(50, watch_clicks)
        ed.connect("focus-out-event", lambda *_a: GLib.timeout_add(80, lambda: finish(True)
                                                                    and False) and False)
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
        if select_all:
            entry.select_region(0, -1)

    def edit_tab_title(self, pane, select_all=True, tries=8):
        """Rename a tab right on the tab. A tab that isn't the shown one is shown first. While
        typing, the tab grows to give the name room (the row of tabs scrolls if needed), and
        the text box sits exactly over the name, so it never covers anything else."""
        if getattr(self, "_editor", None) is not None:
            return
        self.cancel_title_click()
        if pane is not self.pane:
            self.switch_pane(pane)
            GLib.timeout_add(120, lambda: self.edit_tab_title(pane, select_all) and False)
            return
        ev = getattr(self, "_tab_widgets", {}).get(pane["id"])
        if ev is None:
            return
        lbl = ev.tab_label
        if not getattr(ev, "editing", False):
            ev.editing = True
            lbl.set_width_chars(max(12, min(28, len(pane["title"]) + 4)))
            lbl.set_ellipsize(Pango.EllipsizeMode.NONE)
            lbl.set_opacity(0.0)
            GLib.timeout_add(60, lambda: self.edit_tab_title(pane, select_all, tries) and False)
            return
        if lbl.get_allocated_width() <= 1 and tries > 0:
            GLib.timeout_add(60, lambda: self.edit_tab_title(pane, select_all, tries - 1)
                             and False)
            return
        self.show_active_tab(pane)
        pos = lbl.translate_coordinates(self, 0, 0)
        spos = self.tab_sw.translate_coordinates(self, 0, 0)
        if not pos or not spos:
            return
        wx, _wy = self.get_position()
        left = max(pos[0], spos[0])                     # only the part of the tab in view
        right = min(pos[0] + lbl.get_allocated_width(), spos[0] + self.tab_sw.get_allocated_width())
        if right - left < 24:
            right = left + 24
        self._tab_edit_rect = (wx + left, right - left)
        self.edit_title(select_all)

    def cancel_item_rename(self):
        if getattr(self, "_item_rename_timer", 0):
            GLib.source_remove(self._item_rename_timer)
            self._item_rename_timer = 0

    def edit_item_name(self, path):
        """Type a new name right over the icon's name. The name is selected without its
        extension (like the file manager); Enter or clicking elsewhere keeps it, Escape
        doesn't."""
        self.cancel_item_rename()
        ev = self.item_widgets.get(path)
        if ev is None or getattr(self, "_name_editor", None) is not None:
            return
        lbl = ev.cubby_label
        pos = lbl.translate_coordinates(self, 0, 0)
        if not pos:
            return
        wx, wy = self.get_position()
        view = self.pane.get("view", "icons")
        named = is_named_item(path)
        old = self.app.shown_name(path) if named else os.path.basename(path.rstrip("/"))
        a = lbl.get_allocation()
        ed = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        ed.set_decorated(False)
        ed.set_skip_taskbar_hint(True)
        ed.set_skip_pager_hint(True)
        ed.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        ed.set_keep_above(True)
        ed.set_resizable(False)
        entry = Gtk.Entry()
        entry.set_text(old)
        entry.set_alignment(0.5 if view == "icons" else 0.0)
        css = Gtk.CssProvider()
        try:
            css.load_from_data(b"entry { min-height: 0; padding: 1px 4px; }")
            entry.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        except GLib.Error:
            pass
        ed.add(entry)
        eh = max(entry.get_preferred_height()[1], 20)
        layout = entry.create_pango_layout(old)
        text_w = layout.get_pixel_size()[0]
        if view == "icons":
            epos = ev.translate_coordinates(self, 0, 0) or pos
            w = max(text_w + 34, ev.get_allocated_width() + 10, 130)
            x = wx + epos[0] + ev.get_allocated_width() // 2 - w // 2     # centred on the icon
        else:
            w = max(text_w + 40, 200)
            x = wx + pos[0] - 4
        entry.set_width_chars(1)             # the box is exactly as wide as asked
        cw = self.get_size()[0]
        if w < cw - 4:                       # and stays inside the cubby when it fits
            x = max(wx + 2, min(x, wx + cw - w - 2))
        lbl.set_opacity(0.0)                 # the box stands in for the name while typing
        ed.set_size_request(int(w), int(eh))
        ed.move(int(x), int(wy + pos[1] + (a.height - eh) // 2 if view != "icons"
                            else wy + pos[1] - 2))
        state = {"done": False, "armed": False}
        self._name_editor = ed

        def finish(keep):
            if state["done"]:
                return
            state["done"] = True
            name = entry.get_text()
            self._name_editor = None
            ed.destroy()
            try:
                lbl.set_opacity(1.0)
            except Exception:
                pass
            if keep:
                problem = self.app.rename_path(path, name)
                if problem:
                    tell("Could not rename it.", problem)

        def key(_w, event):
            if event.keyval == Gdk.KEY_Escape:
                finish(False)
                return True
            return False

        def watch_clicks():
            if state["done"]:
                return False
            try:
                _w, px, py, mask = self.app.watcher.root.get_device_position(
                    self.app.watcher.pointer)
                down = mask & (Gdk.ModifierType.BUTTON1_MASK | Gdk.ModifierType.BUTTON3_MASK)
                ex, ey = ed.get_position()
                ew, eh2 = ed.get_size()
                inside = ex <= px < ex + ew and ey <= py < ey + eh2
                if down and not inside and state["armed"]:
                    finish(True)
                    return False
                state["armed"] = state["armed"] or not down
            except Exception:
                pass
            return True

        entry.connect("activate", lambda _e: finish(True))
        entry.connect("key-press-event", key)
        ed.connect("focus-out-event", lambda *_a: GLib.timeout_add(80, lambda: finish(True)
                                                                    and False) and False)
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
        stem = len(old) if named or os.path.isdir(path) or old.startswith(".") else \
            len(os.path.splitext(old)[0]) or len(old)
        entry.select_region(0, stem)

    def cancel_title_click(self):
        if getattr(self, "_title_click_timer", 0):
            GLib.source_remove(self._title_click_timer)
            self._title_click_timer = 0

    def on_name(self, x_root, y_root):
        """True when the point is on the cubby's name in the title bar."""
        if not self.title_lbl.get_visible():
            return False
        wx, wy = self.get_position()
        pos = self.title_lbl.translate_coordinates(self, 0, 0)
        if not pos:
            return False
        lay_w = self.title_lbl.get_layout().get_pixel_size()[0]
        a = self.title_lbl.get_allocation()
        xa = self.title_lbl.get_xalign()
        left = pos[0] + int((a.width - lay_w) * xa)
        return (wx + left - 6 <= x_root <= wx + left + lay_w + 6
                and wy + pos[1] <= y_root <= wy + pos[1] + a.height)

    def rename(self, pane=None):
        pane = pane or self.pane
        name = ask("Rename tab" if self.data.get("group") else "Rename cubby", pane["title"])
        if name:
            pane["title"] = name
            self.update_title()
            self.app.save()

    def delete(self):
        self.app.delete_cubby(self.pane)

    def delete_whole(self):
        """The title bar's ✕: this cubby (on a "Menu only" tabbed cubby: the shown tab)."""
        self.app.delete_cubby(self.pane)
