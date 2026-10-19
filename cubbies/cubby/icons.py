"""The icons in a cubby: drawing them, hover buttons, sorting, dragging them out."""

import os
import sys

from gi.repository import Gdk, GLib, Gtk, Pango

from ..constants import DEFAULT_ICON, DEFAULT_RADIUS, MAX_ICON, MIN_ICON, TITLE_ALIGNS, VIEWS
from ..core import dbg
from ..files import is_recent, recent_files
from ..items import SORT_MODES, describe, detail_columns, sort_key
from ..style import selection_colors, style_css
from ..wallpapers import make_thumbnail, thumb_pool
from ..widgets import hand_cursor, hand_cursor_window


class CubbyIcons:
    """Drawing, sorting and dragging icons. Part of Cubby."""

    def set_selection(self, paths):
        """Highlight exactly these icons (desktop-style selection)."""
        self.selected = set(paths)
        self.repaint_all()

    def repaint_all(self):
        for path in list(self.item_widgets):
            self.paint_item(path)

    def paint_item(self, path):
        """Draw one icon's state directly on its widgets (no stylesheet matching involved):
        mouse-over = soft glow in the system selection colour; selected = stronger glow and
        the name turns the system selection colour."""
        widget = self.item_widgets.get(path)
        if widget is None:
            return
        label = widget.cubby_label
        normal = Gtk.StateFlags.NORMAL

        def rgba(rgb, alpha):
            c = Gdk.RGBA()
            c.red, c.green, c.blue, c.alpha = rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, alpha
            return c

        for col in getattr(widget, "cubby_extra", ()):
            col.override_color(normal, rgba(self.sel_fg, 1.0) if path in self.selected else None)
        if path in self.selected:
            widget.override_background_color(normal, rgba(self.sel_bg, 0.45))
            label.override_background_color(normal, rgba(self.sel_bg, 1.0))
            label.override_color(normal, rgba(self.sel_fg, 1.0))
        elif widget.cubby_hover:
            widget.override_background_color(normal, rgba(self.sel_bg, 0.30))
            label.override_background_color(normal, None)
            label.override_color(normal, None)
        else:
            widget.override_background_color(normal, None)
            label.override_background_color(normal, None)
            label.override_color(normal, None)

    def apply_style(self):
        sel_bg, sel_fg = selection_colors(self.outer.get_style_context())
        self.sel_bg, self.sel_fg = sel_bg, sel_fg
        group = bool(self.data.get("group"))
        colour = self.data.get("color", "rgb(20,24,36)")
        opacity = self.data.get("opacity", 0.58)
        tabs = []
        if group:                       # tabs with their own colour; the shown one colours
            for p in self.app.group_panes(self.data):         # the whole cubby
                if p.get("tab_color"):
                    op = p.get("tab_opacity", opacity)
                    tabs.append((p["id"], p["tab_color"], op))
                    if p is self.pane:
                        colour, opacity = p["tab_color"], op
        try:
            self._provider.load_from_data(
                style_css(self.css_class, colour, opacity, sel_bg, sel_fg,
                          self.data.get("title_font"), self.data.get("radius", DEFAULT_RADIUS),
                          self.data.get("border_width", 0), self.data.get("border_color"),
                          self.data.get("tab_font") if group else None, tabs))
        except GLib.Error as exc:
            print("Could not apply cubby style:", exc, file=sys.stderr)
        if hasattr(self, "flow"):  # more rounded corners need a little more room below the icons
            self.flow.set_margin_bottom(max(4, int(self.data.get("radius", DEFAULT_RADIUS) * 0.6)))
        if hasattr(self, "title_ev"):
            self.apply_title_size()
        self.repaint_all()

    def hover_button(self, text, tip, action):
        btn = Gtk.Button(label=text)
        btn.set_relief(Gtk.ReliefStyle.NONE)
        btn.set_tooltip_text(tip)
        btn.get_style_context().add_class("cubby-hover-btn")
        btn.set_no_show_all(True)
        btn.connect("clicked", lambda b: action(b) if action == self.show_sort_menu else action())
        btn.set_opacity(0.0)
        hand_cursor(btn)
        return btn

    def on_title_hover(self, _w, event, inside):
        if not inside:
            if event.detail == Gdk.NotifyType.INFERIOR:
                return False          # only moved onto one of the title bar's own buttons
            x, y = self.get_position()
            w = self.get_size()[0]
            ta = self.title_ev.get_allocation()
            if (x <= event.x_root < x + w and y + ta.y <= event.y_root < y + ta.y + ta.height):
                return False
        self.show_hover_buttons(inside)
        return False

    def show_hover_buttons(self, on):
        on = on and bool(self.app.setting("hover_buttons"))
        for btn in (self.menu_btn, self.close_btn):
            btn.set_opacity(1.0 if on else 0.0)

    def fill_sort_view(self, sort_menu, view_menu=None):
        """Sort choices, then view choices (in one menu, or two when `view_menu` is given)."""
        pane = self.pane
        is_folder = bool(pane.get("folder"))
        one = view_menu is None
        if one:
            view_menu = sort_menu
            hdr = Gtk.MenuItem(label="Sort By")
            hdr.set_sensitive(False)
            sort_menu.append(hdr)
        current = pane.get("sort", "manual")
        if is_folder and current == "manual":
            current = "name"
        group = None
        for mode, label in SORT_MODES:
            if is_folder and mode == "manual":
                continue
            ri = Gtk.RadioMenuItem.new_with_label_from_widget(group, label)
            group = group or ri
            ri.set_active(mode == current)
            ri.connect("toggled", lambda w, m=mode: w.get_active() and self.set_sort(mode=m))
            sort_menu.append(ri)
        sort_menu.append(Gtk.SeparatorMenuItem())
        rev = Gtk.CheckMenuItem(label="Reverse Order")
        rev.set_active(bool(pane.get("sort_rev")))
        rev.set_sensitive(current != "manual")
        rev.connect("toggled", lambda w: self.set_sort(rev=w.get_active()))
        sort_menu.append(rev)
        if one:
            view_menu.append(Gtk.SeparatorMenuItem())
            hdr = Gtk.MenuItem(label="View")
            hdr.set_sensitive(False)
            view_menu.append(hdr)
        # Scroll Bars first, as its own choice
        sb = Gtk.Menu()
        now, group, radios = self.scroll_mode(), None, []
        if pane is not self.pane:
            now = pane.get("scroll", "vertical")
        for mode, label in (("vertical", "Vertical"), ("horizontal", "Horizontal"),
                            ("both", "Both")):
            ri = Gtk.RadioMenuItem.new_with_label_from_widget(group, label)
            group = group or ri
            ri.set_active(mode == now)
            radios.append((ri, mode))
            sb.append(ri)
        for ri, mode in radios:            # connected after the tick is set (see notes)
            ri.connect("activate", lambda w, m=mode: w.get_active() and self.set_scroll_mode(m))
        sbi = Gtk.MenuItem(label="Scroll Bars")
        sbi.set_submenu(sb)
        view_menu.append(sbi)
        view_menu.append(Gtk.SeparatorMenuItem())
        group = None
        for view, label in VIEWS:
            vi = Gtk.RadioMenuItem.new_with_label_from_widget(group, label)
            group = group or vi
            vi.set_active(view == pane.get("view", "icons"))
            vi.connect("toggled", lambda w, v=view: w.get_active() and self.set_view(v))
            view_menu.append(vi)
        view_menu.append(Gtk.SeparatorMenuItem())
        for label, delta in (("Larger Icons", 8), ("Smaller Icons", -8)):
            vi = Gtk.MenuItem(label=label)
            vi.connect("activate", lambda _w, d=delta: self.set_icon_size(
                self.pane.get("icon_size", DEFAULT_ICON) + d))
            view_menu.append(vi)
        vi = Gtk.MenuItem(label="Default Icon Size")
        vi.connect("activate", lambda _w: self.set_icon_size(DEFAULT_ICON))
        view_menu.append(vi)
        vi = Gtk.MenuItem(label="Icon Size\u2026")
        vi.connect("activate", lambda _w: GLib.idle_add(lambda: self.show_size_slider()
                                                         and False))
        view_menu.append(vi)
        th = Gtk.CheckMenuItem(label="Show Thumbnails")
        th.set_active(pane.get("thumbs", True))

        def thumbs(w):
            if w.get_active():
                self.pane.pop("thumbs", None)
            else:
                self.pane["thumbs"] = False
            self.refresh()
            self.app.save()
        th.connect("toggled", thumbs)
        view_menu.append(th)
        if pane.get("view", "icons") == "icons":
            nm = Gtk.CheckMenuItem(label="Show Icon Names")
            nm.set_active(pane.get("names", True) is not False)

            def names(w):
                if w.get_active():
                    self.pane.pop("names", None)
                else:
                    self.pane["names"] = False
                self.refresh()
                self.app.save()
            nm.connect("toggled", names)
            view_menu.append(nm)
        if pane.get("view", "icons") == "details":
            view_menu.append(Gtk.SeparatorMenuItem())
            hd = Gtk.CheckMenuItem(label="Show Column Headings")
            hd.set_active(pane.get("details_head", True))

            def heads(w):
                if w.get_active():
                    self.pane.pop("details_head", None)
                else:
                    self.pane["details_head"] = False
                self.update_headings()
                self.app.save()
            hd.connect("toggled", heads)
            view_menu.append(hd)

    def tab_button(self, text, tip, cb):
        btn = Gtk.Button(label=text)
        btn.set_relief(Gtk.ReliefStyle.NONE)
        btn.set_tooltip_text(tip)
        btn.get_style_context().add_class("cubby-tab-btn")
        btn.set_opacity(0.0)
        btn.set_focus_on_click(False)
        btn.connect("clicked", cb)
        hand_cursor(btn)
        return btn

    def on_tab_hover(self, ev, event, inside):
        if not inside and event.detail == Gdk.NotifyType.INFERIOR:
            return False                   # only moved onto the tab's own ☰ / ✕
        for btn in getattr(ev, "tab_buttons", ()):
            btn.set_opacity(1.0 if inside else 0.0)
        return False

    def tab_sort_menu(self, pane):
        """A tab's ☰: show that tab, then its sort and view choices under its ☰."""
        if pane is not self.pane:
            self.switch_pane(pane)          # rebuilds the tabs: use the new tab's ☰ to anchor

        def pop():
            btn = self._tab_menu_btns.get(pane["id"])
            menu = Gtk.Menu()
            self.fill_sort_view(menu)
            menu.show_all()
            if btn is not None and btn.get_mapped():
                btn.set_opacity(1.0)
                menu.popup_at_widget(btn, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)
            else:
                menu.popup_at_widget(self.title_ev, Gdk.Gravity.SOUTH_WEST,
                                     Gdk.Gravity.NORTH_WEST, None)
            return False
        GLib.idle_add(pop)

    def fill_tab_list(self, menu):
        """The tabs of a tabbed cubby as a list to choose from."""
        group = None
        for pane in self.app.group_panes(self.data):
            ri = Gtk.RadioMenuItem.new_with_label_from_widget(group, pane["title"])
            group = group or ri
            ri.set_active(pane is self.pane)
            ri.connect("toggled", lambda w, p=pane: w.get_active() and self.switch_pane(p))
            menu.append(ri)

    def show_tab_menu(self, event=None):
        menu = Gtk.Menu()
        self.fill_tab_list(menu)
        menu.show_all()
        if event is not None:
            menu.popup_at_pointer(event)
        else:
            menu.popup_at_widget(self.name_box, Gdk.Gravity.SOUTH, Gdk.Gravity.NORTH, None)

    def show_sort_menu(self, button):
        """☰: the sorting and view choices (the same as in the right-click menu); a tabbed
        cubby lists its tabs first."""
        menu = Gtk.Menu()
        if self.data.get("group"):
            hdr = Gtk.MenuItem(label="Tabs")
            hdr.set_sensitive(False)
            menu.append(hdr)
            self.fill_tab_list(menu)
            menu.append(Gtk.SeparatorMenuItem())
        self.fill_sort_view(menu)
        menu.show_all()
        menu.popup_at_widget(button, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)

    def sort_button_shown(self):
        """Is there a ☰ (sort and view) on this cubby's title bar or tabs to click? Only with
        "show the ☰ and ✕ buttons" on, a title bar, titles not hidden for good, and not on a
        launch bar."""
        return bool(self.app.setting("hover_buttons") and self.has_title()
                    and not self.data.get("launchbar")
                    and self.app.cfg.get("show_titles", "always") != "never")

    def title_align(self):
        """Where the name sits. With the ☰ and ✕ buttons on, names are always centred
        (between the two buttons); otherwise each cubby's own choice: left, centre or right."""
        if self.app.setting("hover_buttons"):
            return "center"
        return self.data.get("title_align") if self.data.get("title_align") in TITLE_ALIGNS \
            else "left"

    def place_name(self):
        """Left / right: the name fills the space beside the buttons. Centre: the name sits in
        the exact middle of the title bar, whatever buttons are on either side."""
        # a row of tabs needs the whole title bar: the (hidden) name must not hold the middle
        tab_row = bool(self.data.get("group")) and self.app.cfg.get("tab_style",
                                                                     "rounded") != "menu"
        centred = self.title_align() == "center" and not tab_row
        if centred == self._name_centred:
            return
        parent = self.name_box.get_parent()
        if parent is not None:
            if self.title_row.get_center_widget() is self.name_box:
                self.title_row.set_center_widget(None)
            elif parent is self.title_row:
                self.title_row.remove(self.name_box)
        if centred:
            self.title_row.set_center_widget(self.name_box)
        else:
            self.title_row.pack_start(self.name_box, True, True, 0)
            self.title_row.reorder_child(self.name_box, 1)
        self._name_centred = centred

    def apply_title_size(self):
        """Title bar height, the + and gear buttons, and where the name sits."""
        height = self.data.get("title_height")
        self.title_ev.set_size_request(-1, int(height) if height else -1)
        self.title_lbl.set_xalign(TITLE_ALIGNS.get(self.title_align(), 0.0))
        self.place_name()
        self.name_box.set_halign({"right": Gtk.Align.END}.get(self.title_align(),
                                                               Gtk.Align.FILL))
        hover = bool(self.app.setting("hover_buttons"))
        tab_row = bool(self.data.get("group")) and self.app.cfg.get("tab_style",
                                                                     "rounded") != "menu"
        for btn in (self.menu_btn, self.close_btn):
            btn.set_visible(hover and not tab_row)
            child = btn.get_child()
            if child is not None:
                child.show()

    def ordered_items(self, filtered=True):
        """Items in the order they are shown (sorted unless the cubby is in manual mode).
        `filtered=False` ignores the filter tab that is selected (all the cubby's items)."""
        folder = self.app.folder_of(self.pane)
        if is_recent(self.pane):            # what you opened lately, newest first
            items = recent_files(self.app.recent_count())
        else:
            items = self.folder_items(folder) if folder else list(self.pane["items"])
        mode = self.pane.get("sort", "manual")
        if folder and mode == "manual":
            mode = "name"           # a folder has no hand-made order
        if mode != "manual":
            items.sort(key=lambda p: sort_key(p, mode))
            if self.pane.get("sort_rev"):
                items.reverse()
        kind = self.active_kind() if filtered else None
        if kind:
            items = [p for p in items if self.kind_of(p) == kind]
        query = getattr(self, "_search", "").strip().casefold() if filtered else ""
        if query:
            items = [p for p in items if query in describe(p, 16, False)[0].casefold()
                     or query in os.path.basename(p).casefold()]
        return items

    def set_sort(self, mode=None, rev=None):
        old = self.pane.get("sort", "manual")
        if mode is not None:
            if mode == "manual" and old != "manual":
                self.pane["items"] = self.ordered_items(filtered=False)  # keep the order you saw
            self.pane["sort"] = mode
        if rev is not None:
            self.pane["sort_rev"] = rev
        self.refresh()
        self.app.save()

    def make_item(self, path):
        view = self.pane.get("view", "icons")
        size = max(MIN_ICON, min(MAX_ICON, int(self.pane.get("icon_size", DEFAULT_ICON))))
        small = max(16, min(32, size // 2))   # List and Details use a smaller picture
        px = size if view == "icons" else small
        thumbs = self.pane.get("thumbs", True) and not path.endswith(".desktop") \
            and not os.path.isdir(path)
        name, gicon, pix = describe(path, px, load_image=not thumbs)
        ev = Gtk.EventBox()
        ev.set_visible_window(True)
        ev.get_style_context().add_class("cubby-item")
        extra = []
        if view == "icons":
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            box.set_size_request(max(78, size + 30), -1)
        else:
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        if pix:
            img = Gtk.Image.new_from_pixbuf(pix)
        else:
            img = Gtk.Image.new_from_gicon(gicon, Gtk.IconSize.DIALOG)
            img.set_pixel_size(size if view == "icons" else small)
        if thumbs:
            # the file's icon first; its preview picture replaces it when it is ready
            gen = self._refresh_gen

            def got(fut, img=img):
                try:
                    pb = fut.result()
                except Exception:
                    pb = None
                if pb is not None:
                    GLib.idle_add(lambda: (gen == self._refresh_gen
                                           and img.set_from_pixbuf(pb)) and False)
            try:
                thumb_pool().submit(make_thumbnail, path, px).add_done_callback(got)
            except Exception as exc:
                dbg("thumbnail queue:", exc)
        lbl = Gtk.Label(label=name)
        if view == "icons":
            lbl.set_line_wrap(True)
            lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            lbl.set_max_width_chars(max(10, int(size / 4.8)))
            lbl.set_lines(2)
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
            lbl.set_justify(Gtk.Justification.CENTER)
            lbl.set_halign(Gtk.Align.CENTER)  # so the selection colour hugs the name
            box.pack_start(img, False, False, 0)
            box.pack_start(lbl, False, False, 0)
            if self.pane.get("names") is False:     # View › Show Icon Names turned off
                lbl.set_no_show_all(True)
                box.set_size_request(size + 18, -1)
        else:
            lbl.set_xalign(0)
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
            lbl.set_halign(Gtk.Align.START)
            box.set_margin_start(4)
            box.pack_start(img, False, False, 0)
            box.pack_start(lbl, True, True, 0)
            if view == "details":
                lbl.set_width_chars(22)
                lbl.set_max_width_chars(34)
                for text, chars in detail_columns(path):
                    col = Gtk.Label(label=text, xalign=1)
                    col.set_width_chars(chars)
                    box.pack_end(col, False, False, 6)
                    extra.append(col)
        ev.cubby_extra = extra
        ev.add(box)
        ev.set_tooltip_text(name if (view == "icons" and self.pane.get("names") is False)
                            else path)
        # enter/leave events drive the mouse-over glow
        ev.cubby_path = path
        ev.cubby_label = lbl
        ev.cubby_hover = False
        ev.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK
                      | Gdk.EventMask.POINTER_MOTION_MASK)
        ev.connect("enter-notify-event", self.on_item_enter)
        ev.connect("motion-notify-event", self.on_item_enter)  # in case enter was missed
        ev.connect("leave-notify-event", self.on_item_leave)
        ev.connect("drag-begin", self.on_drag_begin)
        ev.connect("drag-end", lambda w, _ctx: self.set_hover(w, False))
        ev.connect("button-press-event", self.on_item_press, path)
        ev.connect("button-release-event", self.on_item_release, path)
        ev.add_events(Gdk.EventMask.BUTTON_RELEASE_MASK)
        if self.single_click():
            hand_cursor_window(ev)

        # let icons be dragged to other cubbies (all selected icons go together)
        target = Gtk.TargetEntry.new("text/uri-list", 0, 0)
        ev.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, [target], Gdk.DragAction.MOVE)
        ev.connect("drag-data-get", self.on_drag_data_get, path)
        return ev

    def drag_pixbuf(self, path):
        """The icon picture to show under the pointer while dragging."""
        name, gicon, pix = describe(path)
        if pix:
            return pix
        try:
            info = Gtk.IconTheme.get_default().lookup_by_gicon(
                gicon, 48, Gtk.IconLookupFlags.FORCE_SIZE)
            return info.load_icon() if info else None
        except GLib.Error:
            return None

    def on_drag_begin(self, widget, ctx):
        self._click_arm = None            # dragged, not clicked
        self.cancel_item_rename()
        pix = self.drag_pixbuf(widget.cubby_path)
        if pix:
            Gtk.drag_set_icon_pixbuf(ctx, pix, pix.get_width() // 2, pix.get_height() // 2)

    def set_hover(self, widget, hover):
        if widget.cubby_hover != hover:
            widget.cubby_hover = hover
            self.paint_item(widget.cubby_path)

    def on_item_enter(self, widget, event):
        dbg("pointer over", widget.cubby_path)
        self.set_hover(widget, True)
        path = widget.cubby_path
        self.cancel_folder_preview(hide=False)
        if (self.app.setting("folder_preview") and os.path.isdir(path)
                and not (event.state & Gdk.ModifierType.BUTTON1_MASK)):
            self._preview_timer = GLib.timeout_add(
                700, lambda: self.show_folder_preview(widget, path) and False)
        return False

    def on_item_leave(self, widget, event):
        if event.detail != Gdk.NotifyType.INFERIOR:
            self.set_hover(widget, False)
            if getattr(self, "_preview_timer", 0):
                GLib.source_remove(self._preview_timer)
                self._preview_timer = 0
        return False
