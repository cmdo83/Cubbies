"""A cubby's main and add menus, cubby types, the view mode and icon size."""

import os

from gi.repository import Gdk, GLib, Gtk

from ..constants import COLLECT_CHOICES, DEFAULT_ICON, MAX_ICON, MIN_ICON
from ..files import is_inbox, is_recent, launch
from ..items import describe, place_of
from ..widgets import menu_item, menu_item_text, scroll_direction


class CubbyMenus:
    """The cubby menus, view mode and icon size. Part of Cubby."""

    # -- menu actions
    def show_add_menu(self, button):
        menu = Gtk.Menu()
        entries = [("Add Files\u2026", "document-open", self.add_files),
                   ("Add Folder\u2026", "folder-open", lambda: self.add_files(folders=True))]
        if not self.pane.get("folder"):
            entries.append(("Add Applications\u2026", "applications-other", self.add_application))
        for label, icon, cb in entries:
            mi = menu_item(label, icon, "application-x-executable")
            mi.connect("activate", lambda _w, c=cb: c())
            menu.append(mi)
        menu.show_all()
        menu.popup_at_widget(button, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)

    def build_main_menu(self):
        menu = Gtk.Menu()
        pane = self.pane
        is_folder = bool(pane.get("folder"))
        is_group = bool(self.data.get("group"))

        def item(label, cb, *icons):
            mi = menu_item(label, *icons)
            mi.connect("activate", lambda _w: cb())
            menu.append(mi)

        bar = bool(self.data.get("launchbar"))

        def sub_item(submenu, label, cb, *icons):
            mi = menu_item(label, *icons)
            mi.connect("activate", lambda _w: cb())
            submenu.append(mi)

        def check(submenu, label, on, cb):
            ci = Gtk.CheckMenuItem(label=label)
            ci.set_active(bool(on))
            ci.connect("toggled", lambda w: cb(w.get_active()))
            submenu.append(ci)

        undo = self.app.undo_label()
        if undo:
            item(f"Undo {undo}", self.app.undo, "edit-undo")
            menu.append(Gtk.SeparatorMenuItem())
        if not bar:
            item("Search in This Cubby",
                 lambda: GLib.idle_add(lambda: self.open_search() and False),
                 "edit-find", "system-search")
        if is_folder:
            item("Open Folder", lambda: launch(self.app.folder_of(pane)), "folder-open")
            menu.append(Gtk.SeparatorMenuItem())
        recent = is_recent(pane)
        if recent:
            item("Clear Recent Files\u2026", self.app.clear_recent, "edit-clear-all", "edit-clear")
        item("Create New Folder", self.create_folder, "folder-new", "folder")
        doc_sub = Gtk.Menu()
        empty = menu_item("Empty Document", "text-x-generic", "text-plain")
        empty.connect("activate", lambda _w: self.create_document(None))
        doc_sub.append(empty)
        templates = self.template_files()
        if templates:
            doc_sub.append(Gtk.SeparatorMenuItem())
        for tpl in templates:
            mi = menu_item(os.path.splitext(os.path.basename(tpl))[0],
                           "text-x-generic", gicon=describe(tpl)[1])
            mi.connect("activate", lambda _w, t=tpl: self.create_document(t))
            doc_sub.append(mi)
        doc_item = menu_item("Create New Document", "document-new", "text-x-generic")
        doc_item.set_submenu(doc_sub)
        menu.append(doc_item)
        menu.append(Gtk.SeparatorMenuItem())
        paste = menu_item("Paste", "edit-paste")
        paste.set_sensitive(self.app.clip_get() is not None)
        paste.connect("activate", lambda _w: self.app.paste_into(pane))
        menu.append(paste)
        menu.append(Gtk.SeparatorMenuItem())
        item("Add Files\u2026", self.add_files, "document-open")
        item("Add Folder\u2026", lambda: self.add_files(folders=True), "folder-open")
        if recent:      # a Recent Files cubby fills itself: nothing to make or add here
            drop = {"Create New Folder", "Create New Document", "Paste", "Add Files\u2026",
                    "Add Folder\u2026"}
            for child in menu.get_children():
                if isinstance(child, Gtk.MenuItem) and menu_item_text(child) in drop:
                    menu.remove(child)
            last_sep = False
            for child in menu.get_children():
                sep = isinstance(child, Gtk.SeparatorMenuItem)
                if sep and last_sep:
                    menu.remove(child)
                last_sep = sep
        if not is_folder:
            item("Add Applications\u2026", self.add_application, "applications-other",
                 "application-x-executable")
        if not is_folder and not recent:
            places = Gtk.Menu()

            def have(key):
                items = pane.get("items", [])
                if key == "home":
                    return os.path.expanduser("~") in items
                if key.startswith("/"):
                    return key in items
                return any(place_of(p) == key for p in items)

            def place_item(label, key):
                # a tick shows what's already in the cubby. A mouse click adds the place and
                # keeps the menu open, so several can be added in one go.
                ci = Gtk.CheckMenuItem(label=label)
                ci.set_active(have(key))
                busy = [False]

                def add_it(*_a):
                    if busy[0]:
                        return True
                    if not have(key):
                        self.app.add_place(pane, key)
                    busy[0] = True
                    ci.set_active(True)
                    busy[0] = False
                    return True             # (True: the menu stays open)
                ci.connect("button-release-event", add_it)
                ci.connect("activate", lambda w: busy[0] or (add_it() and None))
                places.append(ci)

            for key, label in (("computer:///", "Computer"), ("home", "Home Folder"),
                               ("trash:///", "Trash"), ("network:///", "Network"),
                               ("recent:///", "Recent")):
                place_item(label, key)
            drives = self.app.mounted_drives()
            if drives:
                places.append(Gtk.SeparatorMenuItem())
            for name, folder in drives:
                place_item(name, folder)
            places.append(Gtk.SeparatorMenuItem())
            hint_mi = Gtk.MenuItem(label="Click as many as you like")
            hint_mi.set_sensitive(False)
            places.append(hint_mi)
            pl = menu_item("Add System Places", "computer", "user-home")
            pl.set_submenu(places)
            menu.append(pl)
        menu.append(Gtk.SeparatorMenuItem())

        # sort and view submenus: only when the ☰ button (which has the same choices)
        # can't be reached, so the menu stays short
        if not self.sort_button_shown():
            sub, vsub = Gtk.Menu(), Gtk.Menu()
            self.fill_sort_view(sub, vsub)
            sort_item = menu_item("Sort By", "view-sort-ascending", "view-list-symbolic")
            sort_item.set_submenu(sub)
            menu.append(sort_item)
            view_item = menu_item("View", "view-grid-symbolic", "view-list-symbolic")
            view_item.set_submenu(vsub)
            menu.append(view_item)
        if not is_folder and not bar:
            item("Collect Certain Kinds of Files\u2026", self.edit_collect, "folder-download",
                 "document-save")
        item("Filter Tabs\u2026", self.edit_inbox_tabs, "tab-new", "view-list-symbolic")
        menu.append(Gtk.SeparatorMenuItem())

        # Style ›  (a launch bar keeps only its Styling Options)
        if bar:
            item("Styling Options\u2026", self.edit_appearance,
                 "preferences-desktop-theme", "applications-graphics")
        else:
            style = Gtk.Menu()
            sub_item(style, "Copy", lambda: self.app.copy_style(self.data), "edit-copy")
            paste_st = menu_item("Paste", "edit-paste")
            paste_st.set_sensitive(bool(self.app.style_clip))
            paste_st.connect("activate", lambda _w: self.app.paste_style(self.data))
            style.append(paste_st)
            style.append(Gtk.SeparatorMenuItem())
            sub_item(style, "Styling Options\u2026", self.edit_appearance,
                     "preferences-desktop-theme", "applications-graphics")
            if self.data.get("group") and self.app.cfg.get("tab_style", "rounded") != "menu":
                self.add_tab_font_items(style)
            pname = self.app.page_of(self.data)["name"]
            sub_item(style, f"Use as the Default for \u201c{pname}\u201d",
                     lambda: self.app.use_cubby_style_as_default(self.data),
                     "emblem-default", "object-select", "document-save")
            st_item = menu_item("Style", "preferences-desktop-theme", "applications-graphics")
            st_item.set_submenu(style)
            menu.append(st_item)

        # Options ›
        opts = Gtk.Menu()
        tsub = Gtk.Menu()
        now = self.data.get("title_pos", "auto")
        if not self.app.setting("title_pos_choice"):
            choices = (("auto", "Shown"), ("none", "None"))
            now = "none" if now == "none" else "auto"
        else:
            choices = (("auto", "Automatic (at the Bottom Near the Screen Bottom)"),
                       ("top", "Always at the Top"), ("bottom", "Always at the Bottom"),
                       ("none", "None"))
        radios, group = [], None
        for mode, label in choices:
            ri = Gtk.RadioMenuItem.new_with_label_from_widget(group, label)
            group = group or ri
            ri.set_active(mode == now)
            radios.append((ri, mode))
            tsub.append(ri)
        for ri, mode in radios:        # connected after setting the ticks (see notes)
            ri.connect("activate", lambda w, m=mode: w.get_active() and self.set_title_pos(m))
        tb = menu_item("Title Bar", "go-top", "view-restore")
        tb.set_submenu(tsub)
        opts.append(tb)
        if not bar:
            check(opts, "Show on Every Page", self.data.get("all_pages"),
                  lambda on: self.app.set_flag(self.data, "all_pages", on))
            if self.data.get("all_pages"):
                check(opts, "Same Place on Every Page", self.data.get("same_place"),
                      lambda on: self.app.set_flag(self.data, "same_place", on))
        check(opts, "Lock Position and Size", self.data.get("locked"),
              lambda on: self.app.set_flag(self.data, "locked", on))
        check(opts, "Stay Visible When Cubbies Are Hidden", self.data.get("keep_visible"),
              lambda on: self.app.set_keep_visible(self.data, on))
        if not bar:
            check(opts, "Auto-hide at the Top or Bottom Edge", self.data.get("autohide"),
                  self.set_autohide)
        opt_item = menu_item("Options", "preferences-other", "emblem-system")
        opt_item.set_submenu(opts)
        menu.append(opt_item)
        menu.append(Gtk.SeparatorMenuItem())

        if not bar:
            convert = Gtk.Menu()
            kind_now = ("folder" if is_folder else "inbox" if is_inbox(pane)
                        else "recent" if is_recent(pane) else "regular")
            rgroup, radios = None, []
            for kind, label in (("regular", "Regular Cubby"), ("inbox", "Inbox Cubby"),
                                ("folder", "Folder Cubby\u2026"), ("recent", "Recent Files")):
                ri = Gtk.RadioMenuItem.new_with_label_from_widget(rgroup, label)
                rgroup = rgroup or ri
                ri.set_active(kind == kind_now)
                radios.append((ri, kind))
                convert.append(ri)
            # connected only AFTER the current type is ticked: ticking it while the menu is
            # built also "activates" the items, which used to turn a special cubby regular
            for ri, kind in radios:
                ri.connect("activate", lambda w, k=kind: w.get_active() and self.convert_to(k))
            convert_item = menu_item("Cubby Type", "system-run", "emblem-synchronizing",
                                     "view-refresh")
            convert_item.set_submenu(convert)
            menu.append(convert_item)
        if self.data.get("rolled"):
            item("Unroll Cubby", self.toggle_roll, "go-down")
        elif self.app.setting("rollup_enabled") and self.has_title():
            item("Roll Up Cubby", self.toggle_roll, "go-up")
        if is_group:
            tabs_sub = Gtk.Menu()
            self.fill_tab_list(tabs_sub)
            tabs_item = menu_item("Show Tab", "view-paged-symbolic", "tab-new")
            tabs_item.set_submenu(tabs_sub)
            menu.append(tabs_item)
        if self.has_title():
            item("Rename Tab" if is_group else "Rename Cubby",
                 self.rename if is_group else (lambda: GLib.timeout_add(
                     150, lambda: self.edit_title() and False)),
                 "edit-rename", "document-edit")
        if is_group:
            item("Move Tab Out to Its Own Cubby",
                 lambda: GLib.idle_add(self.app.detach_pane, pane), "window-new", "go-up")
            item("Delete Tab", self.delete, "edit-delete", "user-trash")
            item("Delete All Tabs\u2026", lambda: self.app.delete_group(self.data),
                 "edit-delete", "user-trash")
        else:
            item("Delete Launch Bar Cubby" if bar else
                 "Delete Folder Cubby" if is_folder else "Delete Cubby", self.delete,
                 "edit-delete", "user-trash")
        menu.append(Gtk.SeparatorMenuItem())
        if bar:
            item("Settings\u2026", lambda: self.app.open_settings(section="bars"),
                 "preferences-system", "preferences-other")
        else:
            item("Settings\u2026",
                 lambda: self.app.open_settings(self.app.page_index_of(self.data)),
                 "preferences-system", "preferences-other")
        menu.show_all()
        return menu

    def choose_folder(self):
        dlg = Gtk.FileChooserDialog(title="Choose a folder to show in this cubby",
                                    action=Gtk.FileChooserAction.SELECT_FOLDER)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Show Folder", Gtk.ResponseType.OK)
        dlg.set_current_folder(os.path.expanduser("~"))
        resp = dlg.run()
        path = dlg.get_filename() if resp == Gtk.ResponseType.OK else None
        dlg.destroy()
        if path:
            self.app.set_pane_folder(self.pane, path)

    def stop_folder(self):
        self.app.stop_pane_folder(self.pane)

    def convert_to(self, kind):
        """"Cubby Type": a regular cubby, an Inbox Cubby or a Folder Cubby."""
        pane = self.pane
        if kind == "recent":
            self.app.make_recent(pane)
            return
        if kind == "folder":
            pane.pop("recent", None)
            self.choose_folder()          # also what picks a different folder
            return
        pane.pop("recent", None)
        if pane.get("folder"):
            self.stop_folder()            # its own icons come back
        if kind == "inbox":
            self.set_inbox(True)
        else:
            self.set_inbox(False)
        self.refresh()
        self.app.save()

    def template_files(self):
        """Files in the user's Templates folder (what the desktop's New Document menu offers)."""
        folder = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_TEMPLATES)
        out = []
        try:
            for name in sorted(os.listdir(folder), key=str.casefold):
                full = os.path.join(folder, name)
                if not name.startswith(".") and os.path.isfile(full):
                    out.append(full)
        except Exception:
            pass
        return out[:30]

    def create_folder(self):
        self.app.create_in_store(self.pane, "folder")

    def create_document(self, template):
        self.app.create_in_store(self.pane, "file", template)

    def show_main_menu(self, button):
        self.build_main_menu().popup_at_widget(
            button, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)

    def set_inbox(self, on):
        kinds = [k for k in self.pane.get("collect", []) if k != "other"]
        self.app.set_collect(self.pane, kinds + (["other"] if on else []))

    def edit_collect(self):
        dlg = Gtk.Dialog(title=f"Collect New Desktop Files - {self.pane['title']}")
        dlg.set_resizable(False)
        dlg.add_buttons("Close", Gtk.ResponseType.CLOSE)
        box = dlg.get_content_area()
        box.set_border_width(14)
        box.set_spacing(6)
        per_page = self.app.setting("collect_per_page")
        intro = Gtk.Label(label="When a new file appears on your Desktop"
                          + (" while you're on this cubby's page" if per_page else "")
                          + ", it is moved into this cubby if its kind is ticked here. A kind "
                          "can belong to one cubby " + ("per page" if per_page else "at a time")
                          + "; ticking it here takes it from another.", xalign=0)
        intro.set_line_wrap(True)
        intro.set_max_width_chars(52)
        box.pack_start(intro, False, False, 4)
        have = set(self.pane.get("collect", []))
        checks = {}
        for key, label in COLLECT_CHOICES:
            chk = Gtk.CheckButton(label=label)
            chk.set_active(key in have)
            box.pack_start(chk, False, False, 0)
            checks[key] = chk
        if not self.app.setting("move_files"):
            warn = Gtk.Label(label="This needs \u201cMove files and folders into ~/Cubbies\u201d "
                                   "turned on in Settings.", xalign=0)
            warn.set_line_wrap(True)
            warn.get_style_context().add_class("dim-label")
            box.pack_start(warn, False, False, 4)

        def changed(*_a):
            kinds = [k for k, c in checks.items() if c.get_active()]
            self.app.set_collect(self.pane, kinds)

        for chk in checks.values():
            chk.connect("toggled", changed)
        dlg.show_all()
        dlg.run()
        dlg.destroy()

    # -- view mode and icon size
    def set_view(self, view):
        if self.pane.get("view", "icons") != view:
            self.pane["view"] = view
            self.refresh()
            self.app.save()

    def set_icon_size(self, size):
        size = max(MIN_ICON, min(MAX_ICON, int(size)))
        if size == self.pane.get("icon_size", DEFAULT_ICON):
            return
        if size == DEFAULT_ICON:
            self.pane.pop("icon_size", None)
        else:
            self.pane["icon_size"] = size
        if not self._icon_timer:   # a fast wheel changes the size many times; draw once
            self._icon_timer = GLib.timeout_add(80, self._icon_redraw)

    def show_size_slider(self):
        """A small panel with a slider for the icon / thumbnail size (like the file
        manager's zoom slider). It closes when you click anywhere else."""
        if getattr(self, "_size_panel", None) is not None:
            return
        win = Gtk.Window(type=Gtk.WindowType.POPUP)
        win.set_type_hint(Gdk.WindowTypeHint.POPUP_MENU)
        frame = Gtk.Box(spacing=10)
        frame.get_style_context().add_class("cubby-size-panel")
        frame.set_border_width(10)
        frame.pack_start(Gtk.Label(label="Icon size"), False, False, 0)
        sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, MIN_ICON, MAX_ICON, 4)
        sc.set_value(self.pane.get("icon_size", DEFAULT_ICON))
        sc.set_size_request(240, -1)
        sc.set_draw_value(True)
        sc.set_value_pos(Gtk.PositionType.RIGHT)
        sc.add_mark(DEFAULT_ICON, Gtk.PositionType.BOTTOM, None)
        sc.connect("value-changed", lambda s: self.set_icon_size(int(s.get_value())))
        frame.pack_start(sc, True, True, 0)
        win.add(frame)
        win.show_all()
        x, y = self.get_position()
        w, h = self.get_size()
        pw, ph = win.get_size()
        wa = self.workarea()
        px = min(max(x + 8, wa.x if wa else 0), (wa.x + wa.width if wa else x + w) - pw)
        py = y + self.title_h() + 4 if not self._flipped else y + h - self.title_h() - ph - 4
        win.move(int(px), int(py))
        self._size_panel = win
        state = {"armed": False}

        def watch():
            if self._size_panel is not win:
                return False
            try:
                _w, mx, my, mask = self.app.watcher.root.get_device_position(
                    self.app.watcher.pointer)
                down = mask & (Gdk.ModifierType.BUTTON1_MASK | Gdk.ModifierType.BUTTON3_MASK)
                ex, ey = win.get_position()
                ew, eh = win.get_size()
                inside = ex <= mx < ex + ew and ey <= my < ey + eh
                if down and not inside and state["armed"]:
                    self._size_panel = None
                    win.destroy()
                    return False
                state["armed"] = state["armed"] or not down
            except Exception:
                pass
            return True
        GLib.timeout_add(50, watch)

    def _icon_redraw(self):
        self._icon_timer = 0
        self.refresh()
        self.app.save()
        return False

    def on_icon_scroll(self, widget, event):
        if not (event.state & Gdk.ModifierType.CONTROL_MASK):
            mode = self.scroll_mode()
            hadj = self.sw.get_hadjustment()
            if mode != "vertical" and hadj.get_upper() - hadj.get_page_size() > 1:
                if mode == "both":
                    return False           # the cubby scrolls both ways by itself
                # horizontal: the wheel (and a sideways swipe) scroll the icons sideways
                if event.direction == Gdk.ScrollDirection.SMOOTH:
                    _ok, dx, dy = event.get_scroll_deltas()
                    move = (dx + dy) * 40
                else:
                    move = {Gdk.ScrollDirection.UP: -60, Gdk.ScrollDirection.LEFT: -60,
                            Gdk.ScrollDirection.DOWN: 60,
                            Gdk.ScrollDirection.RIGHT: 60}.get(event.direction, 0)
                top = hadj.get_upper() - hadj.get_page_size()
                hadj.set_value(max(0, min(top, hadj.get_value() + move)))
                return True
            return self.app.handle_swipe(event)     # a sideways swipe turns the page
        step = scroll_direction(event)
        if step:
            delta = 4 if event.direction == Gdk.ScrollDirection.SMOOTH else 8
            self.set_icon_size(self.pane.get("icon_size", DEFAULT_ICON) - step * delta)
        return True
