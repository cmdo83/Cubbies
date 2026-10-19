"""Tabs in a cubby: combined cubbies as tabs, filter tabs by file kind, and Nooks."""

import os
import uuid

from gi.repository import Gdk, GLib, Gtk, Pango

from ..constants import COLLECT_CHOICES, KIND_LABELS, STYLE_KEYS
from ..core import dbg, undoable
from ..files import file_category, inbox_kind_of, is_recent, parse_exts, uris_to_paths
from ..style import colour_swatch
from ..widgets import hand_cursor_window, menu_item


class CubbyTabs:
    """Tabs, filter tabs and Nooks. Part of Cubby."""

    def even_tabs(self, *_a):
        """With "fill", tabs are all the same width when there's room for that (each as
        wide as the widest needs), else each as wide as its own name needs plus a share of
        what's left."""
        if not getattr(self, "_tab_fill", False) or not self.data.get("group"):
            return False
        kids = self.tab_box.get_children()
        if not kids:
            return False
        room = self.tab_sw.get_allocated_width()
        widest = max(k.get_preferred_width()[0] for k in kids)
        even = widest * len(kids) <= room
        if even != self.tab_box.get_homogeneous():
            self.tab_box.set_homogeneous(even)
        return False

    # -- the scrolling tab strip of combined cubbies
    def make_tab_arrow(self, text, step):
        ev = Gtk.EventBox()
        ev.set_visible_window(True)
        ev.get_style_context().add_class("cubby-kind")
        ev.get_style_context().add_class("cubby-kind-arrow")
        ev.set_valign(Gtk.Align.CENTER)
        lbl = Gtk.Label(label=text)
        lbl.set_margin_start(5)
        lbl.set_margin_end(5)
        ev.add(lbl)
        lbl.show()
        ev.set_no_show_all(True)
        ev.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        ev.connect("button-press-event",
                   lambda _w, e: (e.button == 1 and self.scroll_tabs(step * 120)) or True)
        hand_cursor_window(ev)
        return ev

    def scroll_tabs(self, dx):
        adj = self.tab_sw.get_hadjustment()
        top = max(0.0, adj.get_upper() - adj.get_page_size())
        adj.set_value(min(top, max(0.0, adj.get_value() + dx)))
        return True

    def tabs_overflow(self):
        adj = self.tab_sw.get_hadjustment()
        return adj.get_upper() - adj.get_page_size() > 0.5

    def on_tab_scroll(self, widget, event):
        """The wheel over tabs that don't all fit scrolls them; otherwise it does what the
        wheel does on any title bar (turns the page)."""
        if not self.tabs_overflow():
            return self.on_scroll(widget, event)
        d = event.direction
        if d in (Gdk.ScrollDirection.LEFT, Gdk.ScrollDirection.UP):
            self.scroll_tabs(-60)
        elif d in (Gdk.ScrollDirection.RIGHT, Gdk.ScrollDirection.DOWN):
            self.scroll_tabs(60)
        elif d == Gdk.ScrollDirection.SMOOTH:
            v = event.delta_x if abs(event.delta_x) > abs(event.delta_y) else event.delta_y
            self.scroll_tabs(v * 40)
        return True

    def queue_tab_arrows(self, *_a):
        if not getattr(self, "_tab_arrow_idle", 0):
            self._tab_arrow_idle = GLib.idle_add(self.update_tab_arrows)

    def update_tab_arrows(self):
        self._tab_arrow_idle = 0
        adj = self.tab_sw.get_hadjustment()
        top = adj.get_upper() - adj.get_page_size()
        over = top > 0.5
        for arrow, can in ((self.tab_left, adj.get_value() > 0.5),
                           (self.tab_right, adj.get_value() < top - 0.5)):
            arrow.set_visible(over)
            arrow.set_opacity(1.0 if can else 0.3)
        return False

    def show_active_tab(self, pane=None):
        """Scroll the tab strip so this tab (the shown one by default) is fully in view."""
        ev = getattr(self, "_tab_widgets", {}).get((pane or self.pane)["id"])
        if ev is None or not ev.get_mapped():
            return False
        pos = ev.translate_coordinates(self.tab_box, 0, 0)
        if not pos:
            return False
        adj = self.tab_sw.get_hadjustment()
        left, w = pos[0], ev.get_allocated_width()
        if left < adj.get_value():
            adj.set_value(left)
        elif left + w > adj.get_value() + adj.get_page_size():
            adj.set_value(left + w - adj.get_page_size())
        return False

    # -- Filter tabs: show only one kind of file in a cubby (the files all stay in the cubby)
    def inbox_kinds(self):
        """The filter tabs under the title bar (any cubby can have them): the ticked kinds,
        then the user's own tabs (by file extension), then "Other" last."""
        want = self.pane.get("inbox_tabs", [])
        kinds = [k for k, _label in COLLECT_CHOICES if k in want and k != "other"]
        kinds += ["x:" + c["id"] for c in self.pane.get("inbox_custom", [])]
        if "other" in want:
            kinds.append("other")
        return kinds

    def kind_label(self, kind):
        if kind and kind.startswith("x:"):
            for c in self.pane.get("inbox_custom", []):
                if "x:" + c["id"] == kind:
                    return c.get("name") or "Untitled"
            return "?"
        return KIND_LABELS.get(kind, "All")

    def kind_of(self, path):
        """Which filter tab a file belongs to: the user's own tabs (by extension) come first."""
        return inbox_kind_of(path, self.pane.get("inbox_custom", []))

    def active_kind(self):
        kinds = self.inbox_kinds()
        kind = self.pane.get("inbox_active")
        return kind if kind in kinds else None

    def make_kind_arrow(self, text, step):
        ev = Gtk.EventBox()
        ev.set_visible_window(True)
        ev.get_style_context().add_class("cubby-kind")
        ev.get_style_context().add_class("cubby-kind-arrow")
        lbl = Gtk.Label(label=text)
        lbl.set_margin_start(6)
        lbl.set_margin_end(6)
        ev.add(lbl)
        lbl.show()
        ev.set_no_show_all(True)
        ev.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        ev.connect("button-press-event",
                   lambda _w, e: (e.button == 1 and self.scroll_kinds(step * 120)) or True)
        return ev

    def scroll_kinds(self, dx):
        adj = self.kind_sw.get_hadjustment()
        top = max(0.0, adj.get_upper() - adj.get_page_size())
        adj.set_value(min(top, max(0.0, adj.get_value() + dx)))
        return True

    def on_kind_scroll(self, _w, event):
        d = event.direction
        if d in (Gdk.ScrollDirection.LEFT, Gdk.ScrollDirection.UP):
            self.scroll_kinds(-60)
        elif d in (Gdk.ScrollDirection.RIGHT, Gdk.ScrollDirection.DOWN):
            self.scroll_kinds(60)
        elif d == Gdk.ScrollDirection.SMOOTH:
            v = event.delta_x if abs(event.delta_x) > abs(event.delta_y) else event.delta_y
            self.scroll_kinds(v * 40)
        return True        # the wheel here scrolls the tabs; it does not change the page

    def queue_kind_arrows(self, *_a):
        if not getattr(self, "_kind_arrow_idle", 0):
            self._kind_arrow_idle = GLib.idle_add(self.update_kind_arrows)

    def update_kind_arrows(self):
        """Arrows only when the tabs do not all fit; the one that can't go further is dimmed."""
        self._kind_arrow_idle = 0
        adj = self.kind_sw.get_hadjustment()
        top = adj.get_upper() - adj.get_page_size()
        over = top > 0.5
        for arrow, can in ((self.kind_left, adj.get_value() > 0.5),
                           (self.kind_right, adj.get_value() < top - 0.5)):
            arrow.set_visible(over)
            arrow.set_opacity(1.0 if can else 0.3)
        return False

    def update_kind_tabs(self):
        for child in self.kind_box.get_children():
            self.kind_box.remove(child)
        kinds = self.inbox_kinds()
        if not kinds:
            self.kind_row.hide()
            return
        current = self.active_kind()
        for kind in [None] + kinds:
            ev = Gtk.EventBox()
            ev.set_visible_window(True)
            ctx = ev.get_style_context()
            ctx.add_class("cubby-kind")
            if kind == current:
                ctx.add_class("active")
            lbl = Gtk.Label(label=self.kind_label(kind))
            # widget margins, not CSS: an EventBox ignores CSS padding, which is what made
            # the tabs run into each other
            lbl.set_margin_start(10)
            lbl.set_margin_end(10)
            lbl.set_margin_top(2)
            lbl.set_margin_bottom(2)
            ev.add(lbl)
            nook = self.nook_entry(kind)
            if nook is not None:
                n = len(nook.get("items", []))
                ev.set_tooltip_text(f"Nook: {n} icon{'s' if n != 1 else ''}. Drag icons "
                                    "here to tuck them in.")
                ev.drag_dest_set(Gtk.DestDefaults.ALL,
                                 [Gtk.TargetEntry.new("text/uri-list", 0, 0)],
                                 Gdk.DragAction.COPY | Gdk.DragAction.MOVE | Gdk.DragAction.LINK)
                ev.connect("drag-data-received", self.on_nook_drop, nook)
            elif kind and kind.startswith("x:"):
                exts = next((c.get("exts", []) for c in self.pane.get("inbox_custom", [])
                             if "x:" + c["id"] == kind), [])
                ev.set_tooltip_text(", ".join("." + e for e in exts) or "No file types yet")
            ev.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
            ev.connect("button-press-event", self.on_kind_press, kind)
            self.kind_box.pack_start(ev, False, False, 0)
            ev.show_all()
        self.kind_row.set_visible(not self.data.get("rolled"))
        self.queue_kind_arrows()

    # -- Nooks: filter tabs that hold the icons you put in them
    def nook_entry(self, kind):
        if not kind or not kind.startswith("x:"):
            return None
        return next((c for c in self.pane.get("inbox_custom", [])
                     if c.get("nook") and "x:" + c["id"] == kind), None)

    def nooks(self):
        return [c for c in self.pane.get("inbox_custom", []) if c.get("nook")]

    @undoable("Put in Nook")
    def put_in_nook(self, nook, paths):
        """Tuck icons into a nook (taking them out of any other nook of this cubby). Icons
        from elsewhere are added to the cubby first."""
        here = set(self.ordered_items(filtered=False))
        outside = [p for p in paths if p not in here]
        if outside and not is_recent(self.pane):
            self.app.import_moved_map = {}
            self.app.add_items(self.pane, outside)
            moved = getattr(self.app, "import_moved_map", {})   # files now in the store
            paths = [moved.get(p, p) for p in paths]
        for c in self.nooks():
            c["items"] = [p for p in c.get("items", []) if p not in paths]
        nook.setdefault("items", [])
        nook["items"] += [p for p in paths if p not in nook["items"]]
        self.selected = set()
        self.refresh()
        self.app.save()

    @undoable("Take Out of Nook")
    def take_out_of_nook(self, paths):
        for c in self.nooks():
            c["items"] = [p for p in c.get("items", []) if p not in paths]
        self.refresh()
        self.app.save()

    def on_nook_drop(self, _w, _ctx, _x, _y, sel, _info, _time, nook):
        paths = uris_to_paths(sel.get_uris())
        if paths:
            dbg("dropped into the nook", nook.get("name"), paths)
            self.put_in_nook(nook, paths)

    @undoable("New Nook")
    def new_nook(self, paths=()):
        n = len(self.nooks()) + 1
        nook = {"id": uuid.uuid4().hex[:8], "name": f"Nook {n}", "nook": True, "items": []}
        self.pane.setdefault("inbox_custom", []).append(nook)
        if paths:
            self.put_in_nook(nook, list(paths))
        else:
            self.refresh()
            self.app.save()
        return nook

    def on_kind_press(self, _widget, event, kind):
        if event.button == 1:
            self.set_kind(kind)
        elif event.button == 3:
            menu = Gtk.Menu()
            mi = menu_item("Filter Tabs\u2026", "tab-new", "view-list-symbolic")
            mi.connect("activate", lambda _w: GLib.idle_add(self.edit_inbox_tabs))
            menu.append(mi)
            menu.show_all()
            menu.popup_at_pointer(event)
        return True

    def set_kind(self, kind):
        if kind == self.active_kind():
            return
        if kind:
            self.pane["inbox_active"] = kind
        else:
            self.pane.pop("inbox_active", None)
        self.selected = set()
        self.refresh()
        self.app.save()

    KIND_ICONS = {"images": ("image-x-generic",), "documents": ("x-office-document",
                                                                "text-x-generic"),
                  "music": ("audio-x-generic",), "videos": ("video-x-generic",),
                  "archives": ("package-x-generic", "application-x-archive"),
                  "folders": ("folder",), "drives": ("drive-removable-media", "drive-harddisk"),
                  "other": ("text-x-generic", "unknown")}

    def edit_inbox_tabs(self):
        """Filter tabs for this cubby, laid out like Settings: a live picture of the tabs,
        the built-in kinds (with how many files each would show), your own tabs by file
        type, and nooks."""
        app, pane = self.app, self.pane
        dlg, _sw, box = app.s_dialog(
            "Filter Tabs", f"Tabs under the title bar of “{pane['title']}”, each "
            "showing only some of its files. Every file stays in the cubby; a tab only "
            "chooses what you see.")
        theme = Gtk.IconTheme.get_default()

        def icon_for(names):
            return Gtk.Image.new_from_icon_name(
                next((n for n in names if theme.has_icon(n)), names[0]), Gtk.IconSize.MENU)

        items = list(self.ordered_items(filtered=False))
        cats = {}
        for p in items:
            cats[file_category(p)] = cats.get(file_category(p), 0) + 1

        # ---- what the tabs will look like
        sec = app.s_section(box, "Your tabs")
        strip = Gtk.Box(spacing=6)
        strip.set_halign(Gtk.Align.START)
        sec.pack_start(strip, False, False, 4)
        checks = {}
        rows = {"tab": None, "nook": None}

        def draw_strip():
            for c in strip.get_children():
                strip.remove(c)
            names = [KIND_LABELS[k] for k, _l in COLLECT_CHOICES
                     if k != "other" and checks[k].get_active()]
            names += [(c.get("name") or "…") for c in pane.get("inbox_custom", [])]
            if checks["other"].get_active():
                names.append(KIND_LABELS["other"])
            if not names:
                lbl = Gtk.Label(label="No tabs yet: the cubby shows all its files. Tick a "
                                      "kind below or add your own tab.", xalign=0)
                lbl.get_style_context().add_class("dim-label")
                strip.pack_start(lbl, False, False, 0)
            else:
                for i, n in enumerate(["All"] + names):
                    lbl = Gtk.Label(label=n)
                    lbl.get_style_context().add_class("cb-pill")
                    if i == 0:
                        lbl.get_style_context().add_class("on")
                    strip.pack_start(lbl, False, False, 0)
            strip.show_all()

        pending = [0]

        def apply_now():
            pending[0] = 0
            kinds = [k for k, c in checks.items() if c.get_active()]
            if kinds:
                pane["inbox_tabs"] = kinds
            else:
                pane.pop("inbox_tabs", None)
            if not pane.get("inbox_custom"):
                pane.pop("inbox_custom", None)
            if pane.get("inbox_active") not in self.inbox_kinds():
                pane.pop("inbox_active", None)
            self.selected = set()
            self.refresh()
            app.save()
            return False

        def changed(*_a):
            draw_strip()
            if not pending[0]:
                pending[0] = GLib.timeout_add(300, apply_now)

        # ---- built-in kinds
        sec = app.s_section(box, "Built-in tabs")
        grid = Gtk.Grid(row_spacing=6, column_spacing=28)
        sec.pack_start(grid, False, False, 0)
        have = set(pane.get("inbox_tabs", []))
        for i, (key, label) in enumerate(COLLECT_CHOICES):
            chk = Gtk.CheckButton()
            inner = Gtk.Box(spacing=6)
            inner.pack_start(icon_for(self.KIND_ICONS.get(key, ("text-x-generic",))),
                             False, False, 0)
            inner.pack_start(Gtk.Label(label=label), False, False, 0)
            n = cats.get(key, 0)
            cnt = Gtk.Label(label=f"{n} file{'s' if n != 1 else ''}" if key != "folders"
                            else f"{n} folder{'s' if n != 1 else ''}")
            cnt.get_style_context().add_class("dim-label")
            inner.pack_start(cnt, False, False, 4)
            chk.add(inner)
            chk.set_active(key in have)
            chk.connect("toggled", changed)
            checks[key] = chk
            grid.attach(chk, i % 2, i // 2, 1, 1)
        quick = Gtk.Box(spacing=6)
        for text, on in (("Tick All", True), ("Tick Kinds This Cubby Has", None),
                         ("Untick All", False)):
            b = Gtk.Button(label=text)

            def tick(_b, on=on):
                for k, c in checks.items():
                    c.set_active(bool(cats.get(k)) if on is None else on)
            b.connect("clicked", tick)
            quick.pack_start(b, False, False, 0)
        quick.set_margin_top(4)
        sec.pack_start(quick, False, False, 0)

        # ---- own tabs (by file type) and nooks
        def count_exts(exts):
            return sum(1 for p in items if not os.path.isdir(p)
                       and os.path.splitext(p)[1].lower().lstrip(".") in exts)

        def add_row(entry, holder):
            row = Gtk.Box(spacing=8)
            row.pack_start(icon_for(("emblem-favorite", "starred") if entry.get("nook")
                                    else ("text-x-script", "text-x-generic")),
                           False, False, 0)
            name = Gtk.Entry()
            name.set_text(entry.get("name", ""))
            name.set_placeholder_text("Nook name" if entry.get("nook") else "Tab name")
            name.set_width_chars(14)
            row.pack_start(name, False, False, 0)
            info = Gtk.Label(xalign=0)
            info.get_style_context().add_class("dim-label")
            exts = None
            if entry.get("nook"):
                n = len(entry.get("items", []))
                info.set_text(f"{n} icon{'s' if n != 1 else ''}")
            else:
                exts = Gtk.Entry()
                exts.set_text(", ".join(entry.get("exts", [])))
                exts.set_placeholder_text("py, sh, js")
                exts.set_width_chars(22)
                row.pack_start(exts, False, False, 0)

                def show_count():
                    n = count_exts(entry.get("exts", []))
                    info.set_text(f"{n} matching file{'s' if n != 1 else ''}")
                show_count()
            row.pack_start(info, True, True, 0)
            rm = Gtk.Button.new_from_icon_name("list-remove-symbolic", Gtk.IconSize.BUTTON)
            rm.set_relief(Gtk.ReliefStyle.NONE)
            rm.set_tooltip_text("Remove this tab (the files stay in the cubby)")
            row.pack_start(rm, False, False, 0)

            def edited(*_a):
                entry["name"] = name.get_text().strip()
                if exts is not None:
                    entry["exts"] = parse_exts(exts.get_text())
                    show_count()
                changed()

            def remove(_b):
                pane["inbox_custom"].remove(entry)
                holder.remove(row)
                changed()
            name.connect("changed", edited)
            if exts is not None:
                exts.connect("changed", edited)
            rm.connect("clicked", remove)
            holder.pack_start(row, False, False, 0)
            row.show_all()
            return name

        sec = app.s_section(box, "Your own tabs, by file type")
        app.s_note(sec, "Name a tab and list the file types it shows, like “Scripts” "
                        "for py, sh, js. Those files show under your tab instead of a "
                        "built-in one.")
        rows["tab"] = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        sec.pack_start(rows["tab"], False, False, 4)
        sec_n = None
        for entry in pane.get("inbox_custom", []):
            if not entry.get("nook"):
                add_row(entry, rows["tab"])

        def add_tab(_b):
            entry = {"id": uuid.uuid4().hex[:8], "name": "New Tab", "exts": []}
            pane.setdefault("inbox_custom", []).append(entry)
            add_row(entry, rows["tab"]).grab_focus()
            changed()
        b = Gtk.Button(label="Add a Tab")
        b.set_halign(Gtk.Align.START)
        b.connect("clicked", add_tab)
        sec.pack_start(b, False, False, 0)

        sec_n = app.s_section(box, "Nooks: tabs for icons you pick")
        app.s_note(sec_n, "A nook holds just the icons you choose, like “Taxes” or "
                          "“Daily”. Drag icons onto its tab, or right-click icons "
                          "› Put in Nook.")
        rows["nook"] = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        sec_n.pack_start(rows["nook"], False, False, 4)
        for entry in pane.get("inbox_custom", []):
            if entry.get("nook"):
                add_row(entry, rows["nook"])

        def add_nook(_b):
            entry = {"id": uuid.uuid4().hex[:8], "name": f"Nook {len(self.nooks()) + 1}",
                     "nook": True, "items": []}
            pane.setdefault("inbox_custom", []).append(entry)
            add_row(entry, rows["nook"]).grab_focus()
            changed()
        b = Gtk.Button(label="Add a Nook")
        b.set_halign(Gtk.Align.START)
        b.connect("clicked", add_nook)
        sec_n.pack_start(b, False, False, 0)
        draw_strip()
        dlg.show_all()
        dlg.run()
        if pending[0]:
            GLib.source_remove(pending[0])
        apply_now()
        dlg.destroy()

    # -- tabs
    def switch_pane(self, pane):
        if pane is self.pane:
            return
        had_colour = bool(self.pane.get("tab_color") or pane.get("tab_color"))
        self.pane = pane
        self.data["active"] = pane["id"]
        self.selected = set()
        self.refresh()
        if had_colour:
            self.apply_style()                   # the cubby takes the shown tab's colour
        self.app.save()

    def on_tab_press(self, widget, event, pane):
        if event.button == 1 and event.type != Gdk.EventType.BUTTON_PRESS:
            self.cancel_title_click()          # a double-click is not a rename
        if event.button == 1 and event.type == Gdk.EventType.BUTTON_PRESS:
            # tabs fill the title bar, so a drag on a tab moves the whole cubby; Ctrl + drag
            # moves the tab itself (along the row, or out to be a cubby). Settings › Tabbed
            # Cubbies can swap the two.
            ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
            tab_mode = ctrl != (self.app.cfg.get("tab_drag", "cubby") == "tab")
            self._tab_drag = {"sx": event.x_root, "sy": event.y_root, "moved": False,
                              "was_shown": pane is self.pane
                              and not getattr(self, "_title_click_timer", 0),
                              "cubby": not tab_mode, "ctrl": ctrl}
            self.cancel_title_click()
            if not tab_mode and not self.app.is_locked(self.data):
                self.on_title_press(widget, event)     # the title bar's own move
        elif event.button == 3:
            self.build_tab_menu(pane).popup_at_pointer(event)
        return True

    def on_tab_drop(self, _w, _ctx, _x, _y, sel, _info, _time, pane):
        paths = self.app.drop_paths(sel.get_uris(), make_places=not pane.get("folder"))
        if paths:
            dbg("dropped on the tab", pane["title"], paths)
            self.app.add_items(pane, paths)
            if pane is not self.pane:
                self.switch_pane(pane)          # show where they went

    def tab_left_strip(self, x_root, y_root):
        """Is the pointer far enough from the tab strip that the tab is being pulled out?"""
        x, y = self.get_position()
        w = self.get_size()[0]
        top = self.title_top()
        th = self.title_h()
        return not (x - 10 <= x_root <= x + w + 10 and top - 14 <= y_root <= top + th + 14)

    def on_tab_motion(self, widget, event, pane):
        d = self._tab_drag
        if d and (abs(event.x_root - d["sx"]) > 8 or abs(event.y_root - d["sy"]) > 8):
            d["moved"] = True
        if d and d.get("cubby"):                 # moving the whole cubby
            if d["moved"] and self._drag:
                self.on_motion(widget, event)
            return True
        if d and d["moved"]:
            if "float" not in d:                     # a faint copy of the tab rides along
                d["float"] = self.make_tab_float(widget, event)
            # pulled away from the tab strip: it already looks like the cubby it will become,
            # following the pointer; back over the strip, it goes back to being a tab
            out = self.tab_left_strip(event.x_root, event.y_root)
            if out and d.get("ghost") is None:
                d["ghost"] = self.make_tab_ghost(pane, widget)
            elif not out and d.get("ghost") is not None:
                d["ghost"].destroy()
                d["ghost"] = None
                widget.set_opacity(1.0)
            fl = d.get("float")
            if d.get("ghost") is not None:
                d["ghost"].move(int(event.x_root - d["offx"]), int(event.y_root - d["offy"]))
                if fl is not None:
                    fl.hide()                    # (the cubby it will become shows instead)
            else:
                if fl is not None:
                    fl.move(int(event.x_root - fl.grab_x), int(event.y_root - fl.grab_y))
                    fl.show()
                self.slide_tab(widget, event.x_root)    # along the strip: tabs make way
        return bool(d)

    def slide_tab(self, widget, x_root):
        """While a tab is dragged along the strip it takes its new place at once (the others
        move aside), as tabs do in a web browser."""
        kids = self.tab_box.get_children()
        if widget not in kids:
            return
        wx = self.get_position()[0]
        index = 0
        for child in kids:
            if child is widget:
                continue
            pos = child.translate_coordinates(self, 0, 0)
            if pos and wx + pos[0] + child.get_allocated_width() / 2 < x_root:
                index += 1
        if kids.index(widget) != index:
            self.tab_box.reorder_child(widget, index)
            self._tab_drag["slid"] = True

    TAB_FLOAT_OPACITY = 0.38

    def make_tab_float(self, tab_widget, event):
        """A barely-there copy of the tab being dragged, riding along with the pointer (a
        picture of the tab taken as the drag starts)."""
        try:
            alloc = tab_widget.get_allocation()
            pos = tab_widget.translate_coordinates(self, 0, 0)
            gw = self.get_window()
            if not pos or gw is None or alloc.width < 2:
                return None
            pb = Gdk.pixbuf_get_from_window(gw, pos[0], pos[1], alloc.width, alloc.height)
            if pb is None:
                return None
            fl = Gtk.Window(type=Gtk.WindowType.POPUP)
            fl.set_app_paintable(True)
            visual = fl.get_screen().get_rgba_visual()
            if visual:
                fl.set_visual(visual)
            fl.set_default_size(alloc.width, alloc.height)
            fl.set_size_request(alloc.width, alloc.height)

            def draw(_w, cr):
                cr.set_operator(1)                   # SOURCE: start clear
                cr.set_source_rgba(0, 0, 0, 0)
                cr.paint()
                cr.set_operator(2)                   # OVER
                Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
                cr.paint_with_alpha(self.TAB_FLOAT_OPACITY)
                return True
            fl.connect("draw", draw)
            # held where the tab was picked up
            wx, wy = self.get_position()
            fl.grab_x = int(self._tab_drag["sx"] - (wx + pos[0]))
            fl.grab_y = int(self._tab_drag["sy"] - (wy + pos[1]))
            fl.move(int(event.x_root - fl.grab_x), int(event.y_root - fl.grab_y))
            fl.show()
            return fl
        except Exception as exc:
            dbg("no picture of the dragged tab:", repr(exc))
            return None

    def make_tab_ghost(self, pane, tab_widget):
        """A real-looking cubby for the tab being dragged out (shown while dragging)."""
        d = self._tab_drag
        fake = dict(pane)
        fake["id"] = "ghost" + uuid.uuid4().hex[:8]
        for key in STYLE_KEYS + ("title_align",):
            if key in self.data:
                fake[key] = self.data[key]
            else:
                fake.pop(key, None)
        w, _h = self.get_size()
        fake.update(w=w, h=self.data.get("h", 220), rolled=False, x=0, y=0)
        fake.pop("tab_of", None)
        fake.pop("flip", None)
        try:
            from .cubby import Cubby   # (here: cubby.py imports this file)
            ghost = Cubby(self.app, fake)
        except Exception as exc:
            dbg("could not show the dragged tab:", repr(exc))
            return None
        ghost.set_keep_below(False)
        ghost.show_all()
        ghost.sync_roll()
        ghost.set_opacity(0.92)
        try:
            ghost.get_window().raise_()
        except Exception:
            pass
        # held by its title bar, where the tab was picked up
        d["offx"], d["offy"] = 60, 14
        tab_widget.set_opacity(0.35)
        dbg("tab pulled out:", pane["title"])
        return ghost

    def on_tab_release(self, widget, event, pane):
        d, self._tab_drag = self._tab_drag, None
        if d and d.get("float") is not None:
            d["float"].destroy()
        if not d or event.button != 1:
            return True
        if d.get("cubby") and self._drag:
            if d["moved"]:
                return self.on_release(widget, event)     # the cubby was moved
            self._drag = None                              # just a click on the tab
            if self._edge_poll:
                GLib.source_remove(self._edge_poll)
                self._edge_poll = 0
            self.app.show_edge_hint(None)
        ghost = d.get("ghost")
        if not d["moved"] and d.get("ctrl"):
            self.app.toggle_picked(self)                   # Ctrl + click: pick this cubby
            return True
        if not d["moved"]:
            if d.get("was_shown"):
                # a second, slower click on the shown tab: rename it (like a file name)
                dbl = Gtk.Settings.get_default().get_property("gtk-double-click-time") or 400

                def go():
                    self._title_click_timer = 0
                    self.edit_tab_title(pane)
                    return False
                self._title_click_timer = GLib.timeout_add(dbl + 40, go)
            self.switch_pane(pane)
            return True
        if ghost is not None:
            gx, gy = ghost.get_position()
            ghost.destroy()
            # let go away from the strip: the tab becomes its own cubby right where it is
            GLib.idle_add(self.app.detach_pane, pane, int(gx), int(gy))
            return True
        x, y = self.get_position()
        w, h = self.get_size()
        if not (x <= event.x_root <= x + w and y <= event.y_root <= y + h):
            # dragged out of the cubby: the tab becomes a cubby of its own where it was dropped
            GLib.idle_add(self.app.detach_pane, pane, int(event.x_root - 40), int(event.y_root - 12))
            return True
        if d.get("slid"):
            # dropped along the tab strip: keep the order the tabs now show
            ids = {id(ev): pid for pid, ev in getattr(self, "_tab_widgets", {}).items()}
            order = [ids[id(c)] for c in self.tab_box.get_children() if id(c) in ids]
            if sorted(order) == sorted(self.data.get("tabs", [])) and order != self.data["tabs"]:
                self.data["tabs"] = order
                self.app.save()
                dbg("tab order:", order)
        return True

    def reorder_pane(self, pane, x_root):
        """Move a tab to where it was dropped: before the first other tab whose middle is to
        the right of the pointer, or at the end."""
        try:
            wx, _wy = self.get_position()
            order = [p["id"] for p in self.app.group_panes(self.data)]
            index = 0
            for child, other in zip(self.tab_box.get_children(), self.app.group_panes(self.data)):
                if other is pane:
                    continue
                pos = child.translate_coordinates(self, 0, 0)
                mid = wx + (pos[0] if pos else 0) + child.get_allocated_width() / 2
                if mid < x_root:
                    index += 1
            order.remove(pane["id"])
            order.insert(index, pane["id"])
            if order != self.data.get("tabs"):
                self.data["tabs"] = order
                self.update_title()
                self.app.save()
        except Exception as exc:
            dbg("could not reorder tabs:", repr(exc))
        return False

    def build_tab_menu(self, pane):
        menu = Gtk.Menu()
        for label, cb, icons in (
                ("Rename Tab", lambda: GLib.idle_add(lambda: self.edit_title(pane=pane) and False),
                 ("edit-rename", "document-edit")),
                ("Move Tab Out to Its Own Cubby",
                 lambda: GLib.idle_add(self.app.detach_pane, pane), ("window-new", "go-up")),
                ("Delete Tab\u2026", lambda: self.app.delete_cubby(pane),
                 ("edit-delete", "user-trash"))):
            mi = menu_item(label, *icons)
            mi.connect("activate", lambda _w, c=cb: c())
            menu.append(mi)
        menu.append(Gtk.SeparatorMenuItem())
        mi = menu_item("Tab Colour\u2026", "preferences-color", "color-select-symbolic",
                       "applications-graphics")
        mi.connect("activate", lambda _w: GLib.idle_add(lambda: self.edit_tab_colour(pane)
                                                        and False))
        menu.append(mi)
        if pane.get("tab_color"):
            mi = menu_item("Use the Cubby\u2019s Colour for This Tab", "edit-undo", "edit-clear")
            mi.connect("activate", lambda _w: self.set_tab_colour(pane, None))
            menu.append(mi)
        self.add_tab_font_items(menu)
        menu.show_all()
        return menu

    def set_tab_colour(self, pane, colour, opacity=None):
        if colour:
            pane["tab_color"] = colour
            if opacity is not None:
                pane["tab_opacity"] = opacity
        else:
            pane.pop("tab_color", None)
            pane.pop("tab_opacity", None)
        self.update_title()
        self.apply_style()
        self.app.save()

    def edit_tab_colour(self, pane):
        """One tab's own colour: its tab, and the whole cubby while it's the tab shown."""
        app = self.app
        dlg, sw, box = app.s_dialog("Tab Colour", f"The colour of the tab \u201c{pane['title']}"
                                    "\u201d. While it's the tab shown, the cubby takes this "
                                    "colour too.")
        dlg.set_resizable(False)
        sw.set_size_request(780, 470)
        sec = app.s_section(box, "Colour")

        def pushed():
            self.update_title()
            self.apply_style()

        def reopen():
            win = app.windows.get(self.data["id"])
            if win is not None:
                GLib.idle_add(lambda: win.edit_tab_colour(pane) and False)
        app.build_colour_bars(sec, fixed="cubby:" + pane["id"], title=pane["title"],
                              part="tab", on_push=pushed,
                              base=(self.data.get("color", "rgb(20,24,36)"),
                                    self.data.get("opacity", 0.58)),
                              pick=(lambda: dlg.response(Gtk.ResponseType.CLOSE), reopen))
        # the colours the other tabs have: one click gives this tab the same colour
        others = [p for p in app.group_panes(self.data)
                  if p is not pane and p.get("tab_color")]
        if others:
            sec = app.s_section(box, "Colours of the other tabs")
            for p in others:
                row = Gtk.Box(spacing=10)
                row.pack_start(colour_swatch(p["tab_color"],
                                             p.get("tab_opacity", self.data.get("opacity",
                                                                                0.58))),
                               False, False, 0)
                lbl = Gtk.Label(label=p["title"], xalign=0)
                lbl.set_ellipsize(Pango.EllipsizeMode.END)
                lbl.set_width_chars(18)
                row.pack_start(lbl, False, False, 0)
                use = Gtk.Button(label="Use This Colour")

                def take(_b, p=p):
                    self.set_tab_colour(pane, p["tab_color"],
                                        p.get("tab_opacity", self.data.get("opacity", 0.58)))
                    dlg.response(Gtk.ResponseType.CLOSE)
                use.connect("clicked", take)
                row.pack_start(use, False, False, 0)
                sec.pack_start(row, False, False, 0)
        sec = app.s_section(box, "All the tabs")
        every = Gtk.Button(label="Give Every Tab This Tab\u2019s Colour")
        every.set_halign(Gtk.Align.START)
        every.set_tooltip_text("Every tab of this cubby gets the colour above")

        def to_all(_b):
            colour, op = pane.get("tab_color"), pane.get("tab_opacity")
            for p in app.group_panes(self.data):
                if p is not pane:
                    if op is None:
                        p.pop("tab_opacity", None)        # (same transparency as this tab)
                    self.set_tab_colour(p, colour, op)     # (no colour: the cubby's, for all)
            dlg.response(Gtk.ResponseType.CLOSE)
        every.connect("clicked", to_all)
        sec.pack_start(every, False, False, 0)
        sec = app.s_section(box, "Back to the usual")
        b = Gtk.Button(label="Use the Cubby\u2019s Colour for This Tab")
        b.set_halign(Gtk.Align.START)

        def back(_b):
            self.set_tab_colour(pane, None)
            dlg.response(Gtk.ResponseType.CLOSE)
        b.connect("clicked", back)
        sec.pack_start(b, False, False, 0)
        dlg.show_all()
        dlg.run()
        dlg.destroy()
        app.save()
        return False

    def add_tab_font_items(self, menu):
        mi = menu_item("Tab Font\u2026", "preferences-desktop-font", "font-x-generic")
        mi.connect("activate", lambda _w: GLib.idle_add(lambda: self.choose_tab_font() and False))
        menu.append(mi)
        if self.data.get("tab_font"):
            mi = menu_item("Use the Page\u2019s Font for Tabs", "edit-undo", "edit-clear")
            mi.connect("activate", lambda _w: self.set_tab_font(None))
            menu.append(mi)

    def set_tab_font(self, font):
        if font:
            self.data["tab_font"] = font
        else:
            self.data.pop("tab_font", None)
        self.apply_style()
        self.queue_resize()
        GLib.idle_add(self.show_active_tab)
        self.app.save()

    def choose_tab_font(self):
        """Font, size, bold and italic for this cubby's tabs (its other cubbies' tabs and the
        page's default font are left alone). A tab moved out to a cubby of its own goes back
        to the page's font."""
        dlg = Gtk.FontChooserDialog(title="Tab Font")
        dlg.set_keep_above(True)
        default = (self.data.get("tab_font") or self.data.get("title_font")
                   or Gtk.Settings.get_default().get_property("gtk-font-name") or "Sans 10")
        dlg.set_font(default)
        before = self.data.get("tab_font")
        dlg.connect("notify::font", lambda d, _p: self.set_tab_font(d.get_font()))  # live
        resp = dlg.run()
        chosen = dlg.get_font()
        dlg.destroy()
        self.set_tab_font(chosen if resp == Gtk.ResponseType.OK else before)
        return False

    def set_merge_hint(self, on):
        ctx = self.title_ev.get_style_context()
        if on:
            ctx.add_class("merge-target")
        else:
            ctx.remove_class("merge-target")
