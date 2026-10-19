"""Clicking, selecting, deleting and dropping icons, and the icon menu."""

import os
import shutil
import sys

from gi.repository import Gdk, Gio, GLib, Gtk

from ..actions import (file_mime, load_nemo_actions, nemo_action_visible, nemo_scripts,
    run_nemo_action, run_nemo_script, show_in_folder, show_properties)
from ..constants import DEFAULT_RADIUS
from ..core import dbg, undoable
from ..dialogs import confirm, tell
from ..files import (can_trash, delete_permanently, file_category, is_network_path, is_recent,
    launch, trash_has_items, uris_to_paths)
from ..items import describe, place_of
from ..widgets import menu_item, menu_label, page_key_step


class CubbyInteraction:
    """Clicks, selection, Delete, the icon menu and drops. Part of Cubby."""

    # -- icon interaction
    def on_background_press(self, widget, event):
        """Click on empty space in the cubby: deselect; right-click: cubby menu."""
        if self._ah_hidden or self._ah_anim:
            return True          # the strip of a hidden bar: auto-hide brings it out
        if self._item_clicked:
            self._item_clicked = False
            return False
        if (event.button == 1 and event.type == Gdk.EventType.DOUBLE_BUTTON_PRESS
                and self.pane.get("folder")):
            launch(self.app.folder_of(self.pane))   # double-click empty space: open the folder
            return True
        if event.button == 1:
            # Ctrl or Shift: the box adds to what is already selected
            keep = bool(event.state & (Gdk.ModifierType.CONTROL_MASK
                                       | Gdk.ModifierType.SHIFT_MASK))
            base = set(self.selected) if keep else set()
            if not keep:
                self.app.clear_selection()
            if not keep and not self.has_title():
                # no title bar: drag the empty space to move the cubby (Shift or Ctrl + drag
                # still draws a selection box)
                self.on_title_press(self.title_ev, event)
                self._press_on_name = False
                return True
            dbg("press on empty cubby space: rubber-band selection armed")
            # a drag from here draws a selection rectangle (see on_band_motion)
            self._band = {"sx": event.x_root, "sy": event.y_root,
                          "cx": event.x_root, "cy": event.y_root,
                          "active": False, "base": base}
            return True
        elif event.button == 3:
            self.app.clear_selection()
            menu = self.build_main_menu()
            self.track_menu(menu)
            menu.popup_at_pointer(event)
            return True
        return False

    # -- rubber-band selection
    def band_rect(self):
        """The selection rectangle in window coordinates, clipped to the icon area."""
        _ok, ox, oy = self.get_window().get_origin()
        b = self._band
        x0, x1 = sorted((b["sx"] - ox, b["cx"] - ox))
        y0, y1 = sorted((b["sy"] - oy, b["cy"] - oy))
        pos = self.sw.translate_coordinates(self, 0, 0) or (0, 0)
        ax, ay = pos
        aw, ah = self.sw.get_allocated_width(), self.sw.get_allocated_height()
        return (max(x0, ax), max(y0, ay), min(x1, ax + aw), min(y1, ay + ah))

    def on_band_motion(self, widget, event):
        if self._drag and self._drag[0] in ("move", "locked") and not self.has_title():
            return self.on_motion(widget, event)
        b = self._band
        if not b:
            return False
        b["cx"], b["cy"] = event.x_root, event.y_root
        if not b["active"]:
            if abs(b["cx"] - b["sx"]) < 4 and abs(b["cy"] - b["sy"]) < 4:
                return True
            b["active"] = True
            dbg("rubber-band selection started")
        x0, y0, x1, y1 = self.band_rect()
        hits = set()
        for path, w in self.item_widgets.items():
            pos = w.translate_coordinates(self, 0, 0)
            if not pos:
                continue
            ix, iy = pos
            iw, ih = w.get_allocated_width(), w.get_allocated_height()
            if ix < x1 and ix + iw > x0 and iy < y1 and iy + ih > y0:
                hits.add(path)
        self.set_selection(b["base"] | hits)
        self.outer.queue_draw()
        return True

    def on_band_release(self, widget, event):
        if self._drag and self._drag[0] in ("move", "locked") and not self.has_title():
            return self.on_release(widget, event)
        b, self._band = self._band, None
        if b is None:
            return False
        self.outer.queue_draw()
        return bool(b["active"])

    def on_picked_draw(self, widget, cr):
        """A cubby picked for moving together (Ctrl + click its title bar): a bright outline."""
        if self.data["id"] not in self.app.picked:
            return False
        import math
        a = widget.get_allocation()
        w, h = a.width, a.height
        r = max(0, min(int(self.data.get("radius", DEFAULT_RADIUS)), w / 2, h / 2))
        cr.new_path()
        cr.arc(w - r - 1.5, r + 1.5, r, -math.pi / 2, 0)
        cr.arc(w - r - 1.5, h - r - 1.5, r, 0, math.pi / 2)
        cr.arc(r + 1.5, h - r - 1.5, r, math.pi / 2, math.pi)
        cr.arc(r + 1.5, r + 1.5, r, math.pi, 1.5 * math.pi)
        cr.close_path()
        rr, g, b = [c / 255 for c in self.sel_bg]
        cr.set_source_rgba(rr, g, b, 0.95)
        cr.set_line_width(3)
        cr.stroke()
        return False

    def on_line_draw(self, widget, cr):
        """The line along the inner edge of a launch bar (Settings › Launch Bar Cubbies)."""
        try:
            lw = int(self.data.get("line_width", 0))
        except (TypeError, ValueError):
            lw = 0
        if lw <= 0:
            return False
        import math
        a = widget.get_allocation()
        w, h = a.width, a.height
        c = Gdk.RGBA()
        if not c.parse(self.data.get("line_color") or "rgba(255,255,255,0.6)"):
            c.parse("rgba(255,255,255,0.6)")
        edge = self.screen_edge()
        at_top = edge is not None and edge[0] == "bottom"     # bar at the bottom: line on top
        r = max(0, min(int(self.data.get("radius", DEFAULT_RADIUS)), w / 2, h / 2))
        cr.save()
        cr.new_path()                          # clip to the cubby's rounded shape
        cr.arc(w - r, r, r, -math.pi / 2, 0)
        cr.arc(w - r, h - r, r, 0, math.pi / 2)
        cr.arc(r, h - r, r, math.pi / 2, math.pi)
        cr.arc(r, r, r, math.pi, 1.5 * math.pi)
        cr.close_path()
        cr.clip()
        cr.set_source_rgba(c.red, c.green, c.blue, c.alpha)
        style = self.data.get("line_style", "solid")
        cr.set_line_cap(1 if style == "dotted" else 0)     # round dots
        dash = {"dashed": [lw * 4, lw * 2.5], "dotted": [0.01, lw * 2.2],
                "dashdot": [lw * 5, lw * 2, 0.01, lw * 2]}.get(style)
        if dash:
            cr.set_dash(dash)
        if style == "double" and lw >= 3:
            t = max(1.0, lw / 3)
            cr.set_line_width(t)
            for off in (t / 2, lw - t / 2):
                y = off if at_top else h - off
                cr.move_to(0, y)
                cr.line_to(w, y)
            cr.stroke()
        else:
            cr.set_line_width(lw)
            y = lw / 2 if at_top else h - lw / 2
            cr.move_to(0, y)
            cr.line_to(w, y)
            cr.stroke()
        cr.restore()
        return False

    def on_band_draw(self, widget, cr):
        if not self._band or not self._band["active"]:
            return False
        x0, y0, x1, y1 = self.band_rect()
        off = self.outer.translate_coordinates(self, 0, 0) or (0, 0)
        x, y = x0 - off[0], y0 - off[1]
        w, h = max(x1 - x0, 0), max(y1 - y0, 0)
        r, g, bl = [c / 255 for c in self.sel_bg]
        cr.rectangle(x, y, w, h)
        cr.set_source_rgba(r, g, bl, 0.28)
        cr.fill_preserve()
        cr.set_source_rgba(r, g, bl, 0.9)
        cr.set_line_width(1)
        cr.stroke()
        return False

    # -- Delete key
    def on_key_press(self, widget, event):
        dbg("key", Gdk.keyval_name(event.keyval))
        step = page_key_step(event)
        if step:
            self.app.change_page(step, force=True)
            return True
        if event.keyval not in (Gdk.KEY_Delete, Gdk.KEY_KP_Delete):
            return False
        if not self.app.setting("delete_key") or not self.selected:
            return False
        self.app.delete_selected()
        return True

    @undoable("Delete")
    def request_remove(self, targets):
        """Remove icons from this cubby. Files that Cubbies stores itself are moved to the
        Trash (after asking); shortcuts and links elsewhere are only taken out of the cubby."""
        app = self.app
        if is_recent(self.pane):
            # only forgotten from the recent list; the files themselves are not touched
            mgr = Gtk.RecentManager.get_default()
            for p in targets:
                try:
                    mgr.remove_item(Gio.File.new_for_path(p).get_uri())
                except Exception as exc:
                    dbg("could not forget", p, exc)
            self.refresh()
            return
        folder = self.pane.get("folder")
        # in a Folder Cubby every icon is a real file in that folder
        owned = list(targets) if folder else [p for p in targets if app.is_managed(p)]
        files = list(owned) if folder else [p for p in owned if not p.endswith(".desktop")]
        launchers = [] if folder else [p for p in owned if p.endswith(".desktop")]
        label = (describe(targets[0])[0] if len(targets) == 1 else f"{len(targets)} icons")
        no_trash = [p for p in files if not can_trash(p)]
        if files:
            what = (describe(files[0])[0] if len(files) == 1 else f"{len(files)} items")
            where = app.folder_of(self.pane) if folder else app.store_dir()
            if no_trash:
                net = any(is_network_path(p) for p in no_trash)
                note = (f"{what} {'is' if len(files) == 1 else 'are'} in "
                        + ("a network folder" if net else "a place") + f" ({where}) that has "
                        "no Trash, so "
                        + ("it" if len(files) == 1 else "they") + " will be deleted for good. "
                        "This can't be undone.")
                title, button = f"Permanently delete {what}?", "Delete Permanently"
            else:
                note = (f"{what} is stored in {where}, not just linked, so removing it "
                        "from the cubby moves it to the Trash.")
                title, button = f"Delete {what}?", "Move to Trash"
            if launchers:
                note += " Shortcuts are removed too; the applications stay installed."
            if len(owned) < len(targets):
                note += " Items linked from elsewhere are only taken out of the cubby."
            if not confirm(title, note, button):
                return
        elif launchers:
            if app.setting("confirm_delete") and not confirm(
                    f"Remove {label}?", "Only the shortcut is removed. The application itself "
                    "stays installed.", "Remove"):
                return
        elif app.setting("confirm_delete") and not confirm(
                f"Remove {label} from this cubby?",
                "The file or application itself is not deleted.", "Remove"):
            return
        failed, errors = [], []
        for p in targets:
            if p in no_trash:
                app.undo_forbid()           # deleted for good: nothing to bring back
                err = delete_permanently(p)
                if err:
                    errors.append(f"{os.path.basename(p)}: {err}")
                    continue
            elif p in owned and not app.trash_path(p):
                failed.append(p)    # keep it in the cubby rather than lose track of it
                continue
            app.remove_item(self.pane, p)
        if failed:
            what = (describe(failed[0])[0] if len(failed) == 1 else f"{len(failed)} files")
            if confirm(f"{what} could not be moved to the Trash",
                       "Delete permanently instead? This can't be undone.",
                       "Delete Permanently"):
                for p in failed:
                    app.undo_forbid()
                    err = delete_permanently(p)
                    if err:
                        errors.append(f"{os.path.basename(p)}: {err}")
                    else:
                        app.remove_item(self.pane, p)
        if errors:
            tell("Some items could not be deleted", "\n".join(errors[:8])
                 + ("\n…" if len(errors) > 8 else ""))
        if folder:
            self.refresh()

    def _clear_item_flag(self):
        self._item_clicked = False
        return False

    def on_item_press(self, widget, event, path):
        dbg("click on", path, "button", event.button)
        self.cancel_folder_preview()
        self._item_clicked = True
        # Reset once this event has finished propagating (handlers that return True never
        # reach the background handler, which is what normally clears the flag).
        GLib.idle_add(self._clear_item_flag)
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(event.state & Gdk.ModifierType.SHIFT_MASK)
        if event.button == 1 and event.type == Gdk.EventType.BUTTON_PRESS and shift:
            # Shift: click = select everything from the last clicked icon to this one;
            # drag = draw a selection box, even when starting on an icon (no file drag)
            self.cancel_item_rename()
            before = set(self.selected)
            order = self.ordered_items()
            anchor = getattr(self, "_anchor", None)
            if anchor in order and path in order:
                i, j = sorted((order.index(anchor), order.index(path)))
                self.set_selection(before | set(order[i:j + 1]))
            else:
                self.set_selection(before | {path})
                self._anchor = path
            self._band = {"sx": event.x_root, "sy": event.y_root,
                          "cx": event.x_root, "cy": event.y_root,
                          "active": False, "base": before}
            return True          # stops the file drag from starting
        if event.button == 1 and event.type == Gdk.EventType.BUTTON_PRESS:
            self._anchor = path
            self.cancel_item_rename()
            lbl = widget.cubby_label
            on_label = False
            try:
                la = lbl.get_allocation()
                lx, ly = lbl.translate_coordinates(widget, 0, 0)
                on_label = (lx <= event.x <= lx + la.width and ly <= event.y <= ly + la.height)
            except Exception:
                pass
            single = self.single_click()
            self._click_arm = (path, event.x_root, event.y_root) if single and not ctrl else None
            if (not ctrl and on_label and self.selected == {path} and not single
                    and self.app.can_rename(path)):
                dbl = Gtk.Settings.get_default().get_property("gtk-double-click-time") or 400

                def go():
                    self._item_rename_timer = 0
                    if self.selected == {path}:
                        self.edit_item_name(path)
                    return False
                self._item_rename_timer = GLib.timeout_add(dbl + 80, go)
            if ctrl:
                self.set_selection(self.selected ^ {path})  # Ctrl+click toggles
            elif path not in self.selected:
                self.app.clear_selection()
                self.set_selection({path})
            return False  # let a drag start
        if event.button == 1 and event.type == Gdk.EventType.DOUBLE_BUTTON_PRESS:
            self.cancel_item_rename()
            if self.single_click():
                return True               # the first click already opened it
            self.open_item(path)
            return True
        if event.button == 3:
            if path not in self.selected:
                self.app.clear_selection()
                self.set_selection({path})
            menu = self.build_item_menu(path)
            self.track_menu(menu)
            menu.popup_at_pointer(event)
            return True
        return False

    def single_click(self):
        """Open icons with one click here? (Settings › Launch Bars: always, never, or only
        in launch bars.)"""
        mode = self.app.cfg.get("click_open", "bars")
        return mode == "single" or (mode == "bars" and bool(self.data.get("launchbar")))

    def open_item(self, path):
        now = GLib.get_monotonic_time() // 1000
        last = getattr(self, "_last_open", (None, 0))
        if last[0] == path and now - last[1] < 700:
            return                        # (a double-click by habit opens it only once)
        self._last_open = (path, now)
        self.app.note_open(path)
        if (self.data.get("autohide") and not self._ah_hidden
                and self.app.cfg.get("autohide_close", "leave") == "click"):
            GLib.timeout_add(250, lambda: self.ah_set(True) and False)
        if (self.pane.get("folder") and os.path.isdir(path) and not os.path.islink(path)
                and self.app.setting("folder_navigate")):
            self.navigate(path)           # look inside it, right here in the cubby
        else:
            launch(path)

    def on_item_release(self, widget, event, path):
        arm, self._click_arm = self._click_arm, None
        if (event.button != 1 or arm is None or arm[0] != path
                or abs(event.x_root - arm[1]) + abs(event.y_root - arm[2]) > 6
                or event.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK)):
            return False
        self.open_item(path)
        return True

    def build_item_menu(self, path):
        """The right-click menu for icons, laid out like the file manager's own: the apps,
        actions and scripts come from this computer, so it matches what Nemo would offer."""
        menu = Gtk.Menu()
        targets = [p for p in self.ordered_items() if p in self.selected] or [path]
        folder_mode = bool(self.pane.get("folder"))
        owned = [p for p in targets if self.app.is_managed(p)]
        launcher = path.endswith(".desktop")

        def add(label, fn, *icons, gicon=None, to=menu, tip=None):
            mi = menu_item(label, *icons, gicon=gicon)
            mi.connect("activate", lambda _w: fn())
            if tip:
                mi.set_tooltip_text(tip)
            to.append(mi)
            return mi

        # -- open
        ctype = file_mime(path)
        default = None
        if not launcher and ctype:
            try:
                default = Gio.AppInfo.get_default_for_type(ctype, False)
            except Exception:
                default = None
        if os.path.isdir(path):
            add("Open", lambda: launch(path), "folder-open", "document-open")
        elif default is not None and not launcher:
            add(f"Open With {default.get_display_name()}",
                lambda: self.open_with(default, targets), gicon=default.get_icon())
        else:
            add("Open", lambda: [launch(p) for p in targets], "document-open")
        if place_of(path) == "trash:///":
            mi = add("Empty Trash\u2026", self.app.empty_trash, "user-trash-full", "edit-clear")
            mi.set_sensitive(trash_has_items())
        if not launcher and ctype:
            sub = Gtk.Menu()
            seen = {default.get_id()} if default is not None else set()
            try:
                apps = Gio.AppInfo.get_recommended_for_type(ctype) or []
                apps += Gio.AppInfo.get_all_for_type(ctype) or []
            except Exception:
                apps = []
            for app in apps:
                if app.get_id() in seen or not app.should_show():
                    continue
                seen.add(app.get_id())
                add(app.get_display_name(), lambda a=app: self.open_with(a, targets),
                    gicon=app.get_icon(), to=sub)
            if sub.get_children():
                sub.append(Gtk.SeparatorMenuItem())
            add("Other Application\u2026", lambda: self.open_with_other(targets),
                "application-x-executable", to=sub)
            parent = menu_item("Open With", "system-run", "document-open")
            parent.set_submenu(sub)
            menu.append(parent)
        menu.append(Gtk.SeparatorMenuItem())

        # -- cut / copy
        for label, mode, icon in (("Cut", "cut", "edit-cut"), ("Copy", "copy", "edit-copy")):
            add(label, lambda m=mode: self.app.clip_set(m, targets), icon)
        menu.append(Gtk.SeparatorMenuItem())

        # -- rename / cubby things / delete
        if len(targets) == 1 and self.app.can_rename(path):
            add("Rename\u2026", lambda: self.app.rename_item(path), "edit-rename",
                "document-edit")
        others = [(i, p["name"]) for i, p in enumerate(self.app.cfg["pages"])
                  if i != self.app.cfg["page"] and self.app.item_target(p) is not None]
        if others and not folder_mode:
            sub = Gtk.Menu()
            for idx, pname in others:
                mi = Gtk.MenuItem(label=pname)
                mi.connect("activate",
                           lambda _w, i=idx: self.app.move_item_to_page(path, self.pane, i))
                sub.append(mi)
            parent = menu_item("Move to Page", "go-jump", "go-next")
            parent.set_submenu(sub)
            menu.append(parent)
        # -- nooks (filter tabs that hold chosen icons)
        nook_sub = Gtk.Menu()
        for nook in self.nooks():
            add(nook.get("name") or "Untitled",
                lambda nk=nook: self.put_in_nook(nk, targets), "folder", to=nook_sub)
        if self.nooks():
            nook_sub.append(Gtk.SeparatorMenuItem())
        add("New Nook with These", lambda: self.new_nook(targets), "list-add", to=nook_sub)
        nook_item = menu_item("Put in Nook", "tab-new", "folder")
        nook_item.set_submenu(nook_sub)
        menu.append(nook_item)
        if any(p in c.get("items", []) for c in self.nooks() for p in targets):
            add("Take Out of Nook", lambda: self.take_out_of_nook(targets), "list-remove")
        if is_recent(self.pane):
            add("Remove from Recent Files", lambda: self.request_remove(targets),
                "list-remove", "edit-clear")
            owned = []
        elif owned and not folder_mode:
            add("Move Back to Desktop",
                lambda: [self.app.move_back_to_desktop(self.pane, p) for p in owned],
                "user-desktop", "go-home")
        if is_recent(self.pane):
            pass
        elif folder_mode or any(not p.endswith(".desktop") for p in owned):
            if any(not can_trash(p) for p in (targets if folder_mode else owned)):
                add("Delete Permanently\u2026", lambda: self.request_remove(targets),
                    "edit-delete", "user-trash")
            else:
                add("Delete (Move to Trash)\u2026", lambda: self.request_remove(targets),
                    "user-trash", "edit-delete")
        else:
            add("Remove from Cubby", lambda: self.request_remove(targets),
                "list-remove", "edit-delete")

        # -- compress / extract (what the file manager's archive add-on offers)
        extra = []
        roller = shutil.which("file-roller") or shutil.which("engrampa")
        if roller:
            extra.append(("Compress\u2026", lambda: self.spawn([roller, "--add"] + targets),
                          ("package-x-generic", "archive-insert")))
            if all(file_category(p) == "archives" for p in targets):
                extra.append(("Extract Here",
                              lambda: self.spawn([roller, "--extract-here"] + targets),
                              ("archive-extract", "extract-archive")))
                extra.append(("Extract To\u2026",
                              lambda: self.spawn([roller, "--extract"] + targets),
                              ("archive-extract", "extract-archive")))
        # -- the system's Nemo actions and the user's Nemo scripts
        try:
            actions = [a for a in load_nemo_actions() if nemo_action_visible(a, targets)]
        except Exception as exc:
            dbg("could not read Nemo actions:", repr(exc))
            actions = []
        scripts = nemo_scripts()
        if extra or actions or scripts:
            menu.append(Gtk.SeparatorMenuItem())
        for label, fn, icons in extra:
            add(label, fn, *icons)
        for act in actions:
            label = menu_label(act["name"]).replace("%N", os.path.basename(path)) \
                .replace("%f", os.path.basename(path))
            add(label, lambda a=act: run_nemo_action(a, targets),
                act["icon"] or "system-run", tip=act["comment"] or None)
        if scripts:
            def fill(sub, entries):
                for name, full, kids in entries:
                    if kids is None:
                        add(name, lambda f=full: run_nemo_script(f, targets), "text-x-script",
                            to=sub)
                    else:
                        inner = Gtk.Menu()
                        fill(inner, kids)
                        mi = menu_item(name, "folder")
                        mi.set_submenu(inner)
                        sub.append(mi)
            sub = Gtk.Menu()
            fill(sub, scripts)
            parent = menu_item("Scripts", "text-x-script", "application-x-executable")
            parent.set_submenu(sub)
            menu.append(parent)

        # -- properties
        menu.append(Gtk.SeparatorMenuItem())
        if folder_mode:
            add("Show in Folder", lambda: show_in_folder(targets), "folder-open")
        add("Properties", lambda: show_properties(targets), "document-properties")
        menu.show_all()
        return menu

    @staticmethod
    def spawn(argv):
        try:
            GLib.spawn_async(argv, flags=GLib.SpawnFlags.DEFAULT)
        except Exception as exc:
            print("Cubbies: could not start", argv[0], "-", exc, file=sys.stderr)

    @staticmethod
    def open_with(app, paths):
        try:
            app.launch([Gio.File.new_for_path(p) for p in paths], None)
        except Exception as exc:
            print("Cubbies: could not open with", app.get_display_name(), "-", exc,
                  file=sys.stderr)

    def open_with_other(self, paths):
        dlg = Gtk.AppChooserDialog.new(None, 0, Gio.File.new_for_path(paths[0]))
        resp = dlg.run()
        app = dlg.get_app_info() if resp == Gtk.ResponseType.OK else None
        dlg.destroy()
        if app is not None:
            self.open_with(app, paths)

    def drop_index(self, x, y):
        """Where in the icon list a drop at window position (x, y) should land (None = end)."""
        try:
            pos = self.translate_coordinates(self.flow, int(x), int(y))
            if not pos:
                return None
            fx, fy = pos
            child = self.flow.get_child_at_pos(fx, fy)
            if child is None:
                return None
            idx = child.get_index()
            origin = child.translate_coordinates(self.flow, 0, 0)
            if origin and (self.pane.get("view", "icons") != "icons"
                           or self.scroll_mode() == "horizontal"):
                if fy > origin[1] + child.get_allocated_height() / 2:
                    idx += 1
            elif origin and fx > origin[0] + child.get_allocated_width() / 2:
                idx += 1
            return idx
        except Exception:
            return None

    def item_at(self, x, y):
        """The path of the icon at window position (x, y), or None."""
        try:
            fx, fy = self.translate_coordinates(self.flow, int(x), int(y))
            child = self.flow.get_child_at_pos(fx, fy)
            return getattr(child.get_child(), "cubby_path", None) if child else None
        except Exception:
            return None

    def on_drop_hover(self, _w, _ctx, x, y, _time):
        """While files are dragged over the cubby, a Trash icon under the pointer lights up
        (dropping there moves them to the Trash)."""
        onto = self.item_at(x, y)
        self.light_drop_target(onto if onto and place_of(onto) == "trash:///" else None)
        return False

    def light_drop_target(self, path):
        old = getattr(self, "_drop_lit", None)
        if old == path:
            return
        self._drop_lit = path
        for p, on in ((old, False), (path, True)):
            w = self.item_widgets.get(p) if p else None
            if w is not None:
                w.cubby_hover = on
                self.paint_item(p)

    def on_drop(self, widget, ctx, x, y, sel, info, time):
        self.light_drop_target(None)
        uris = sel.get_uris()
        # dropped onto a Trash icon: into the Trash they go (like the desktop's own Trash)
        onto = self.item_at(x, y)
        if onto and place_of(onto) == "trash:///":
            self.app.trash_dropped([p for p in uris_to_paths(uris) if p != onto])
            return
        paths = self.app.drop_paths(uris, make_places=not self.pane.get("folder"))
        if not paths:
            return
        # a single folder dropped on the title bar turns the cubby into a Folder Cubby
        pos = self.title_ev.translate_coordinates(self, 0, 0) or (0, 0)
        on_title = pos[1] <= y <= pos[1] + self.title_ev.get_allocated_height()
        if (on_title and len(paths) == 1 and os.path.isdir(paths[0])
                and paths[0] not in self.pane["items"]
                and os.path.abspath(paths[0]) != os.path.abspath(self.pane.get("folder") or "")):
            self.app.set_pane_folder(self.pane, os.path.abspath(paths[0]))
            return
        if self.pane.get("folder"):
            self.app.add_items(self.pane, paths)   # moved into the real folder
            return
        index = None
        if self.pane.get("sort", "manual") != "manual":
            # re-arranging inside a sorted cubby switches it to manual mode
            if any(p in self.pane["items"] for p in paths):
                self.set_sort("manual")
                index = self.drop_index(x, y)
        else:
            index = self.drop_index(x, y)
        if index is not None and self.active_kind():
            shown = self.ordered_items()          # only part of the list is on screen
            index = (self.pane["items"].index(shown[index])
                     if index < len(shown) and shown[index] in self.pane["items"] else None)
        self.app.add_items(self.pane, paths, index)
