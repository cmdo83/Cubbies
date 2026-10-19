"""The Settings window and the building blocks its sections are made from."""

from gi.repository import Gdk, GLib, Gtk

from ..constants import DEFAULT_BORDER_COLOR, DEFAULT_RADIUS, MAX_BORDER
from ..core import dbg
from ..widgets import calm_scroll, no_wheel


class AppSettingsWindow:
    """The Settings window. Part of App."""

    # -- settings
    def setting(self, key):
        return self.cfg.get(key, {"delete_key": True, "confirm_delete": True,
                                  "desktop_dblclick": True, "page_wallpapers": True,
                                  "move_files": True, "pager_autohide": True, "peek": True,
                                  "newpage_keys": False, "edge_pull": True,
                                  "draw_new": True, "hover_buttons": True,
                                  "edge_snap": True, "wheel_pages": True,
                                  "dblclick_roll": True, "snap_cubbies": True,
                                  "fade_idle": False, "pages_enabled": True,
                                  "animate_pages": True, "page_bounce": False,
                                  "swipe_pages": True, "unhide_on_switch": True,
                                  "rollup_enabled": True, "edge_rollup": False,
                                  "show_on_start": True, "folder_navigate": True,
                                  "folder_title_icon": True, "blur_bg": False,
                                  "hide_desktop_icons": False, "lock_all": False,
                                  "f5_refresh": True, "gap_screen": True,
                                  "draw_takes_icons": True, "title_pos_choice": True,
                                  "hide_taken_links": True, "tab_fill": True,
                                  "box_select": True, "folder_preview": True,
                                  "autohide_on_top": True, "collect_per_page": False,
                                  "glance_favourites": True, "glance_browse": False,
                                  "edge_snap_sides": True}[key])

    # -- settings window (sections down the side, like a control panel)
    SETTINGS_CSS = b"""
    .cb-settings-side { background-color: shade(@theme_bg_color, 0.97);
                        border-right: 1px solid alpha(@theme_fg_color, 0.10); }
    .cb-settings-side row { padding: 11px 22px; }
    .cb-settings-side row label { font-size: 108%; }
    .cb-settings-side row:selected { background-color: alpha(@theme_selected_bg_color, 0.55);
                                     color: @theme_fg_color; }
    .cb-settings-side row:selected label { color: @theme_fg_color; }
    .cb-settings-body { background-color: @theme_base_color; }
    .cb-settings-title { font-size: 165%; }
    .cb-settings-sub { font-size: 103%; }
    .cb-settings-head { font-size: 100%; }
    .cb-settings-line { min-height: 1px; background-color: alpha(@theme_fg_color, 0.18); }
    .cb-settings-preview { border-radius: 2px; }
    .cb-card { border: 1px solid alpha(@theme_fg_color, 0.14); border-radius: 6px;
               padding: 10px 12px; }
    .cb-pill { padding: 3px 12px; border-radius: 12px;
               background-color: alpha(@theme_fg_color, 0.08); }
    .cb-pill.on { background-color: alpha(@theme_selected_bg_color, 0.85);
                  color: @theme_selected_fg_color; }
    """

    def setting_set(self, key, value):
        self.cfg[key] = bool(value)
        self.save()

    def open_settings(self, page_index=None, section="home", scroll=None):
        """Cubbies settings: a list of sections down the side and the chosen one on the right
        (Home, Colour & Appearance, Desktop Pages, Folder Cubbies, Roll-up Cubbies, Quick-hide,
        Layout & Snapping, Sorting & Organising, About). Desktop Pages has a tab per page."""
        if getattr(self, "_settings_dlg", None) is not None:
            self._settings_dlg.present()
            return
        css = Gtk.CssProvider()
        try:
            css.load_from_data(self.SETTINGS_CSS)
            Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css,
                                                     Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        except GLib.Error as exc:
            dbg("settings css:", exc)
        dlg = Gtk.Dialog(title="Cubbies Settings")
        self._settings_dlg = dlg
        dlg.set_resizable(False)
        dlg.set_default_size(980, 680)
        dlg.set_size_request(980, 680)
        dlg.add_buttons("Close", Gtk.ResponseType.CLOSE)
        area = dlg.get_content_area()
        area.set_border_width(0)
        area.set_spacing(0)

        body = Gtk.Box()
        area.pack_start(body, True, True, 0)
        side = Gtk.ListBox()
        side.set_selection_mode(Gtk.SelectionMode.SINGLE)
        side.get_style_context().add_class("cb-settings-side")
        side.set_size_request(230, -1)
        body.pack_start(side, False, False, 0)
        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        stack.set_transition_duration(120)
        stack.get_style_context().add_class("cb-settings-body")
        body.pack_start(stack, True, True, 0)

        sections = [("home", "Home", self.settings_home),
                    ("look", "Colour & Appearance", self.settings_look),
                    ("pages", "Desktop Pages", lambda: self.settings_pages(page_index)),
                    ("folders", "Folder Cubbies", self.settings_folders),
                    ("tabs", "Tabbed Cubbies", self.settings_tabs),
                    ("rollup", "Roll-up Cubbies", self.settings_rollup),
                    ("bars", "Launch Bar Cubbies", self.settings_bars),
                    ("hide", "Quick-hide", self.settings_hide),
                    ("peek", "Glance", self.settings_peek),
                    ("layout", "Layout & Snapping", self.settings_layout),
                    ("sorting", "Sorting & Organising", self.settings_sorting),
                    ("cli", "Command Line", self.settings_cli),
                    ("backup", "Backup & Restore", self.settings_backup),
                    ("about", "About", self.settings_about)]
        rows = {}
        for key, label, build in sections:
            row = Gtk.ListBoxRow()
            lbl = Gtk.Label(label=label, xalign=0)
            row.add(lbl)
            row.key = key
            side.add(row)
            rows[key] = row
            try:
                stack.add_named(build(), key)
            except Exception:
                import traceback
                traceback.print_exc()
                stack.add_named(Gtk.Label(label="(could not show this section)"), key)
        side.connect("row-selected", lambda _l, row: row and stack.set_visible_child_name(row.key))
        self._settings_go = lambda key: side.select_row(rows[key])
        dlg.show_all()
        side.select_row(rows.get(section, rows["home"]))
        no_wheel(dlg)
        if scroll:
            def put_back():
                child = stack.get_child_by_name(section)
                if isinstance(child, Gtk.ScrolledWindow):
                    child.get_vadjustment().set_value(scroll)
                return False
            GLib.timeout_add(150, put_back)
        dlg.run()
        dlg.destroy()
        self._settings_dlg = None
        self._settings_go = None
        Gtk.StyleContext.remove_provider_for_screen(Gdk.Screen.get_default(), css)

    # ---- building blocks
    def s_dialog(self, title, subtitle, width=780, height=660):
        """A window laid out like Settings (title, sections), for one cubby's options."""
        css = Gtk.CssProvider()
        try:
            css.load_from_data(self.SETTINGS_CSS)
            Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css,
                                                     Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        except GLib.Error as exc:
            dbg("dialog css:", exc)
        dlg = Gtk.Dialog(title=title)
        dlg.set_default_size(width, height)
        dlg.add_buttons("Close", Gtk.ResponseType.CLOSE)
        area = dlg.get_content_area()
        area.set_border_width(0)
        sw, box = self.s_page(title, subtitle)
        sw.get_style_context().add_class("cb-settings-body")
        area.pack_start(sw, True, True, 0)
        dlg.connect("destroy", lambda *_a: Gtk.StyleContext.remove_provider_for_screen(
            Gdk.Screen.get_default(), css))
        dlg.connect("show", lambda d: no_wheel(d))
        return dlg, sw, box

    def s_page(self, title, subtitle=None, preview=None):
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_start(22)
        box.set_margin_end(24)
        box.set_margin_top(18)
        box.set_margin_bottom(22)
        sw.add(box)
        sw.connect("map", lambda w: calm_scroll(w))    # the wheel scrolls, never sets
        t = Gtk.Label(label=title, xalign=0)
        t.get_style_context().add_class("cb-settings-title")
        box.pack_start(t, False, False, 0)
        if subtitle:
            st = Gtk.Label(label=subtitle, xalign=0)
            st.set_line_wrap(True)
            st.get_style_context().add_class("cb-settings-sub")
            box.pack_start(st, False, False, 2)
        if preview is not None:
            preview.set_halign(Gtk.Align.START)
            preview.set_margin_top(8)
            preview.set_margin_bottom(6)
            box.pack_start(preview, False, False, 0)
        return sw, box

    def s_move_section(self, box, title, before):
        """Move the section `title` (its heading and contents) to just above `before`."""
        kids = box.get_children()

        def head_of(name):
            for i, w in enumerate(kids):
                if isinstance(w, Gtk.Box):
                    for c in w.get_children():
                        if (isinstance(c, Gtk.Label) and c.get_text() == name
                                and c.get_style_context().has_class("cb-settings-head")):
                            return i
            return None
        i, j = head_of(title), head_of(before)
        if i is None or j is None or i + 1 >= len(kids):
            return
        head, inner = kids[i], kids[i + 1]
        box.reorder_child(head, j - 1 if i < j else j)
        at = box.get_children().index(head)
        # (moving down, taking `inner` out first shifts the heading up one)
        box.reorder_child(inner, at if i < j else at + 1)

    def s_section(self, box, title):
        head = Gtk.Box(spacing=8)
        head.set_margin_top(14)
        lbl = Gtk.Label(label=title, xalign=0)
        lbl.get_style_context().add_class("cb-settings-head")
        line = Gtk.Box()
        line.get_style_context().add_class("cb-settings-line")
        line.set_valign(Gtk.Align.CENTER)
        head.pack_start(lbl, False, False, 0)
        head.pack_start(line, True, True, 0)
        box.pack_start(head, False, False, 0)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        inner.set_margin_start(16)
        inner.set_margin_top(4)
        box.pack_start(inner, False, False, 0)
        return inner

    def s_check(self, box, label, key, after=None):
        chk = Gtk.CheckButton(label=label)
        chk.set_active(bool(self.setting(key)))

        def toggled(b):
            self.setting_set(key, b.get_active())
            if after:
                after(b.get_active())
        chk.connect("toggled", toggled)
        box.pack_start(chk, False, False, 0)
        return chk

    def s_combo(self, box, label, key, choices, default, after=None):
        """A labelled drop-down list for a setting kept as a word (choices: (word, text))."""
        row = Gtk.Box(spacing=8)
        row.pack_start(Gtk.Label(label=label), False, False, 0)
        combo = Gtk.ComboBoxText()
        for word, text in choices:
            combo.append(word, text)
        now = self.cfg.get(key, default)
        combo.set_active_id(now if any(w == now for w, _t in choices) else default)

        def changed(c):
            self.cfg[key] = c.get_active_id()
            self.save()
            if after:
                after(c.get_active_id())
        combo.connect("changed", changed)
        row.pack_start(combo, False, False, 0)
        box.pack_start(row, False, False, 0)
        return combo

    def s_spin(self, box, label, key, lo, hi, default, unit="", step=1, after=None):
        row = Gtk.Box(spacing=8)
        row.pack_start(Gtk.Label(label=label), False, False, 0)
        spin = Gtk.SpinButton.new_with_range(lo, hi, step)
        try:
            spin.set_value(int(self.cfg.get(key, default)))
        except (TypeError, ValueError):
            spin.set_value(default)

        def changed(b):
            self.cfg[key] = int(b.get_value())
            self.save()
            if after:
                after(int(b.get_value()))
        spin.connect("value-changed", changed)
        row.pack_start(spin, False, False, 0)
        if unit:
            row.pack_start(Gtk.Label(label=unit), False, False, 0)
        box.pack_start(row, False, False, 0)
        return spin

    def s_note(self, box, text, dim=True):
        lbl = Gtk.Label(label=text, xalign=0)
        lbl.set_line_wrap(True)
        lbl.set_max_width_chars(90)
        if dim:
            lbl.get_style_context().add_class("dim-label")
        box.pack_start(lbl, False, False, 0)
        return lbl

    def s_bullets(self, box, lines):
        for text in lines:
            row = Gtk.Box(spacing=8)
            dot = Gtk.Label(label="•")
            dot.set_valign(Gtk.Align.START)
            lbl = Gtk.Label(xalign=0)
            lbl.set_markup(text)
            lbl.set_line_wrap(True)
            lbl.set_max_width_chars(95)
            row.pack_start(dot, False, False, 0)
            row.pack_start(lbl, True, True, 0)
            box.pack_start(row, False, False, 0)

    def s_link(self, box, text, action):
        lbl = Gtk.Label(xalign=0)
        lbl.set_markup(f'<a href="#">{GLib.markup_escape_text(text)}</a>')
        lbl.connect("activate-link", lambda *_a: (action(), True)[1])
        box.pack_start(lbl, False, False, 0)
        return lbl

    def s_preview(self, kind="cubby", look=None, title="General"):
        """A small drawn picture for the top of a section. Some of them play a short loop
        showing how the feature is used (turning pages, quick-hide, making tabs)."""
        import math
        import cairo
        look = dict(look or self.page().get("defaults") or {})
        area = Gtk.DrawingArea()
        wide = kind in ("folder", "pages", "hide", "tabs", "launchbar")
        area.set_size_request(340 if wide else 250, 150 if wide else 130)
        theme = Gtk.IconTheme.get_default()
        cache = {}

        def icon(names, size=30):
            key = (tuple(names), size)
            if key not in cache:
                cache[key] = None
                for n in names:
                    try:
                        if theme.has_icon(n):
                            cache[key] = theme.load_icon(n, size, Gtk.IconLookupFlags.FORCE_SIZE)
                            break
                    except GLib.Error:
                        pass
            return cache[key]

        def rounded(cr, x, y, w, h, r):
            r = max(0, min(r, w / 2, h / 2))
            cr.new_sub_path()
            cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
            cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
            cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
            cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
            cr.close_path()

        col = Gdk.RGBA()
        TH = 20
        live = {"alpha": 0.58, "rad": 6}

        def read_look():
            if not col.parse(look.get("color") or "rgb(20,24,36)"):
                col.parse("rgb(20,24,36)")
            live["alpha"] = max(float(look.get("opacity", 0.58)), 0.12)
            live["rad"] = int(look.get("radius", DEFAULT_RADIUS)) * 0.6
            live["bw"] = max(0, min(MAX_BORDER, int(look.get("border_width") or 0)))
            bc = Gdk.RGBA()
            if not bc.parse(look.get("border_color") or DEFAULT_BORDER_COLOR):
                bc.parse(DEFAULT_BORDER_COLOR)
            live["bcol"] = bc

        def text(cr, x, y, s, size=10, alpha=0.95, centre=False):
            cr.set_source_rgba(1, 1, 1, alpha)
            cr.select_font_face("Sans", 0, 0)
            cr.set_font_size(size)
            if centre:
                x -= cr.text_extents(s).width / 2
            cr.move_to(x, y)
            cr.show_text(s)

        def cubby(cr, x, y, w, h, *args, a=1.0, **kw):
            cubby_body(cr, x, y, w, h, *args, a=a, **kw)
            bw = live.get("bw", 0)
            if bw:                                   # the border, drawn inside the edge
                bc = live["bcol"]
                cr.new_path()
                cr.set_source_rgba(bc.red, bc.green, bc.blue, bc.alpha * a)
                cr.set_line_width(bw)
                rounded(cr, x + bw / 2, y + bw / 2, w - bw, h - bw,
                        max(0, live["rad"] - bw / 2))
                cr.stroke()

        def cubby_body(cr, x, y, w, h, label, icons, names, a=1.0, show_title=True, tabs=None,
                       glow=False, folder=False, pointer_on_title=False, active=0, tstyle=None):
            base_alpha, rad = live["alpha"], live["rad"]
            tstyle = tstyle or self.cfg.get("tab_style", "rounded")
            cr.set_source_rgba(col.red, col.green, col.blue, base_alpha * a)
            rounded(cr, x, y, w, h, rad)
            cr.fill()
            if show_title:
                cr.set_source_rgba(1, 1, 1, (0.35 if glow else 0.14) * a)
                rounded(cr, x, y, w, TH, min(rad, TH / 2) if h > TH else rad)
                cr.fill()
                if tabs and tstyle == "menu":
                    cr.select_font_face("Sans", 0, 0)
                    cr.set_font_size(10)
                    tw = cr.text_extents(tabs[active]).width
                    text(cr, x + w / 2 - 6, y + 14, tabs[active], 10, 0.95 * a, centre=True)
                    tx = x + w / 2 - 6 + tw / 2 + 6           # a small ▾ (drawn: fonts vary)
                    cr.move_to(tx, y + 8)
                    cr.line_to(tx + 7, y + 8)
                    cr.line_to(tx + 3.5, y + 12)
                    cr.close_path()
                    cr.set_source_rgba(1, 1, 1, 0.95 * a)
                    cr.fill()
                elif tabs:
                    tx = x + 6
                    for i, tname in enumerate(tabs):
                        cr.select_font_face("Sans", 0, 0)
                        cr.set_font_size(9)
                        tw = cr.text_extents(tname).width + 16
                        on = i == active
                        if tstyle == "rounded":
                            cr.set_source_rgba(*(0, 0, 0, 0.32 * a) if on else (0.5, 0.5, 0.5, 0.25 * a))
                            rounded(cr, tx, y + 3, tw, TH - 6, 6)
                            cr.fill()
                        elif tstyle == "segmented":
                            if on:
                                cr.set_source_rgba(col.red, col.green, col.blue, 1.0 * a)
                            else:
                                cr.set_source_rgba(0.5, 0.5, 0.5, 0.45 * a)
                            cr.rectangle(tx, y + 4, tw, TH - 4)
                            cr.fill()
                        text(cr, tx + 8, y + 14, tname, 9, (0.98 if on else 0.55) * a)
                        tx += tw + (3 if tstyle == "rounded" else 1 if tstyle == "segmented"
                                    else 4)
                else:
                    tx = x + w / 2
                    if folder:
                        pb = icon(["folder"], 13)
                        if pb is not None:
                            cr.save()
                            ext_w = 6 * len(label)
                            Gdk.cairo_set_source_pixbuf(cr, pb, tx - ext_w / 2 - 18, y + 3)
                            cr.paint_with_alpha(a)
                            cr.restore()
                    text(cr, tx, y + 14, label, 10, 0.95 * a, centre=True)
            if h <= TH + 20:
                return
            # icons sized to fit the cubby, and kept inside it
            avail = h - TH
            isz = int(max(14, min(26, avail - 26)))
            cell = isz + 26
            per_row = max(0, int((w - 8) // cell))
            cr.save()
            rounded(cr, x, y, w, h, rad)
            cr.clip()
            for j, (ic, nm) in enumerate(zip(icons, names)):
                if j >= per_row:
                    break
                ix = x + 6 + j * cell
                pb = icon([ic, "text-x-generic"], isz)
                if pb is not None:
                    Gdk.cairo_set_source_pixbuf(cr, pb, ix + (cell - isz) / 2, y + TH + 5)
                    cr.paint_with_alpha(a)
                cr.select_font_face("Sans", 0, 0)
                cr.set_font_size(8)
                nm = nm if cr.text_extents(nm).width <= cell - 2 else nm[:5] + "\u2026"
                e = cr.text_extents(nm)
                text(cr, ix + cell / 2 - e.width / 2, y + TH + 5 + isz + 11, nm, 8, 0.9 * a)
            cr.restore()

        def pointer(cr, px, py, grab=False):
            cr.save()
            cr.new_path()
            cr.translate(px, py)
            if grab:                                  # a closed hand: a small filled blob
                cr.arc(4, 6, 6, 0, 2 * math.pi)
                cr.set_source_rgba(1, 1, 1, 1)
                cr.fill_preserve()
                cr.set_source_rgba(0, 0, 0, 1)
                cr.set_line_width(1)
                cr.stroke()
            else:
                cr.move_to(0, 0)
                cr.line_to(0, 15)
                cr.line_to(4, 11)
                cr.line_to(7, 17)
                cr.line_to(9, 16)
                cr.line_to(6, 10)
                cr.line_to(11, 10)
                cr.close_path()
                cr.set_source_rgba(1, 1, 1, 1)
                cr.fill_preserve()
                cr.set_source_rgba(0, 0, 0, 1)
                cr.set_line_width(1)
                cr.stroke()
            cr.restore()

        def ripple(cr, px, py, k):
            cr.new_path()
            for i in range(2):
                r = 4 + (k * 14) + i * 5
                cr.arc(px, py, r, 0, 2 * math.pi)
                cr.set_source_rgba(1, 1, 1, max(0, 0.8 - k))
                cr.set_line_width(1.5)
                cr.stroke()

        def ease(k):
            k = max(0.0, min(1.0, k))
            return k * k * (3 - 2 * k)

        def lerp(a, b, k):
            return a + (b - a) * k

        def background(cr, W, H, pager=None):
            g = cairo.LinearGradient(0, 0, 0, H)
            g.add_color_stop_rgb(0, 0.12, 0.42, 0.75)
            g.add_color_stop_rgb(1, 0.04, 0.27, 0.55)
            cr.set_source(g)
            cr.rectangle(0, 0, W, H)
            cr.fill()
            if pager:
                cr.set_source_rgba(0.08, 0.1, 0.15, 0.75)
                rounded(cr, W / 2 - 34, 4, 68, 15, 7)
                cr.fill()
                text(cr, W / 2, 15, pager, 8, 0.95, centre=True)

        DOC = ["folder", "x-office-spreadsheet", "image-x-generic", "text-x-generic",
               "audio-x-generic"]
        DOCN = ["Documents", "Budget", "Photos", "Notes", "Music"]
        WORK = ["x-office-document", "x-office-presentation", "x-office-spreadsheet",
                "text-x-generic"]
        WORKN = ["Report", "Slides", "Schedule", "Minutes"]
        tmode = kind[7:] if kind.startswith("titles-") else None
        t0 = GLib.get_monotonic_time()

        def draw(widget, cr):
            W, H = widget.get_allocated_width(), widget.get_allocated_height()
            t = (GLib.get_monotonic_time() - t0) / 1e6
            read_look()
            if kind == "pages":
                # pull the right edge to the left (to "Work"), then the left edge back
                P = 9.0
                ph = t % P
                if ph < 4.5:
                    side, k = "right", ph
                else:
                    side, k = "left", ph - 4.5
                frm, to = ((DOC, DOCN, "General", "Main"), (WORK, WORKN, "Work", "Work")) \
                    if side == "right" else ((WORK, WORKN, "Work", "Work"),
                                             (DOC, DOCN, "General", "Main"))
                edge_x = W - 4 if side == "right" else 4
                sign = -1 if side == "right" else 1
                start_px = W * 0.5
                if k < 1.0:                                    # pointer heads to the edge
                    px, grab, off = lerp(start_px, edge_x, ease(k / 1.0)), False, 0
                elif k < 1.3:                                  # presses
                    px, grab, off = edge_x, True, 0
                elif k < 2.3:                                  # pulls in: the page follows
                    off = ease((k - 1.3) / 1.0) * W * 0.45
                    px, grab = edge_x + sign * off, True
                elif k < 2.8:                                  # lets go: it glides the rest
                    off = lerp(W * 0.45, W, ease((k - 2.3) / 0.5))
                    px, grab = edge_x + sign * W * 0.45, False
                else:                                          # and the pointer moves off
                    off, grab = W, False
                    px = lerp(edge_x + sign * W * 0.45, start_px, ease((k - 2.8) / 1.2))
                background(cr, W, H, pager=frm[3] if off < W * 0.5 else to[3])
                shift = sign * off

                def page_main(dx):
                    cubby(cr, 26 + dx, 30, 150, 82, "General", DOC, DOCN)
                    cubby(cr, 196 + dx, 52, 120, 70, "Misc", ["folder", "text-x-generic"],
                          ["Old", "Todo"])

                def page_work(dx):
                    cubby(cr, 40 + dx, 34, 210, 84, "Work", WORK, WORKN)
                (page_main if side == "right" else page_work)(shift)
                (page_work if side == "right" else page_main)(shift - sign * W)
                pointer(cr, px, H * 0.55, grab)
            elif kind == "hide":
                P = 7.0
                k = t % P
                spot = (W * 0.62, H * 0.72)
                if k < 1.2:
                    a, px, py = 1.0, lerp(W * 0.3, spot[0], ease(k / 1.2)), \
                        lerp(H * 0.4, spot[1], ease(k / 1.2))
                else:
                    px, py = spot
                    if k < 1.8:
                        a = 1.0
                    elif k < 2.3:
                        a = 1 - ease((k - 1.8) / 0.5)
                    elif k < 4.0:
                        a = 0.0
                    elif k < 4.5:
                        a = ease((k - 4.0) / 0.5)
                    else:
                        a = 1.0
                background(cr, W, H)
                cr.set_source_rgba(0, 0, 0, 0.55)
                cr.rectangle(0, H - 14, W, 14)
                cr.fill()
                if a > 0.01:
                    cubby(cr, 20, 16, 150, 80, "General", DOC, DOCN, a=a)
                    cubby(cr, 190, 16, 128, 64, "Work", WORK, WORKN, a=a)
                for click_t in (1.2, 1.45, 3.4, 3.65):
                    if click_t <= k < click_t + 0.45:
                        ripple(cr, px, py, (k - click_t) / 0.45)
                pointer(cr, px, py)
            elif kind == "tabs":
                P = 6.5
                k = t % P
                background(cr, W, H)
                ax, ay, aw, ah = 24, 22, 190, 92
                bx0, by0 = 214, 70
                if k < 0.8:
                    bx, by, merged, glow = bx0, by0, False, False
                    px, py = lerp(W * 0.9, bx0 + 50, ease(k / 0.8)), lerp(H * 0.9, by0 + 10,
                                                                        ease(k / 0.8))
                elif k < 2.4:
                    e = ease((k - 0.8) / 1.6)
                    bx, by = lerp(bx0, ax + 60, e), lerp(by0, ay + 2, e)
                    merged, glow = False, e > 0.75
                    px, py = bx + 50, by + 10
                elif k < 5.6:
                    merged, glow = True, False
                    bx = by = 0
                    px, py = ax + 120, ay + 10
                else:
                    merged, glow = True, False
                    bx = by = 0
                    px, py = lerp(ax + 120, W * 0.9, ease((k - 5.6) / 0.9)), \
                        lerp(ay + 10, H * 0.9, ease((k - 5.6) / 0.9))
                if not merged:
                    cubby(cr, ax, ay, aw, ah, "Photos", ["image-x-generic"] * 3,
                          ["Beach", "Party", "Dog"], glow=glow)
                    cubby(cr, bx, by, 110, 60, "Work", WORK[:2], WORKN[:2])
                    pointer(cr, px, py, grab=0.8 <= k < 2.4)
                else:
                    # the tabs keep their order: clicking "Work" just shows Work's icons
                    show_work = 3.6 <= k < 5.6
                    cr.select_font_face("Sans", 0, 0)
                    cr.set_font_size(9)
                    work_x = ax + 6 + cr.text_extents("Photos").width + 16 + 3 + 14
                    cubby(cr, ax, ay, aw + 30, ah,
                          "", WORK[:3] if show_work else ["image-x-generic"] * 3,
                          WORKN[:3] if show_work else ["Beach", "Party", "Dog"],
                          tabs=["Photos", "Work"], active=1 if show_work else 0)
                    if 3.2 <= k < 3.6:
                        ripple(cr, work_x, ay + 10, (k - 3.2) / 0.4)
                    pointer(cr, work_x if 3.0 <= k < 5.6 else px,
                            ay + 10 if 3.0 <= k < 5.6 else py)
            elif kind == "launchbar":
                # a window fills the screen; the pointer pushes against the top edge, the
                # launch bar slides down, an app is clicked, and the bar slides away again
                P = 7.0
                k = t % P
                background(cr, W, H)
                cr.set_source_rgba(0.93, 0.93, 0.95, 1)          # a maximised window
                cr.rectangle(0, 0, W, H)
                cr.fill()
                cr.set_source_rgba(0.80, 0.81, 0.84, 1)
                cr.rectangle(0, 0, W, 14)
                cr.fill()
                for i, c in enumerate(((0.9, 0.35, 0.3), (0.95, 0.75, 0.3), (0.4, 0.75, 0.4))):
                    cr.set_source_rgb(*c)
                    cr.arc(W - 12 - i * 12, 7, 3.5, 0, 2 * math.pi)
                    cr.fill()
                cr.set_source_rgba(0.6, 0.62, 0.66, 1)
                for j in range(5):
                    cr.rectangle(16, 30 + j * 18, W * (0.55 if j % 2 else 0.7), 6)
                    cr.fill()
                BH, strip = 52, 3
                if k < 1.2:
                    out = 0.0
                    px, py = lerp(W * 0.45, W * 0.45, 0), lerp(H * 0.7, 1, ease(k / 1.2))
                elif k < 1.6:
                    out = ease((k - 1.2) / 0.4)
                    px, py = W * 0.45, 1
                elif k < 3.6:
                    out = 1.0
                    e = ease((k - 1.6) / 0.7)
                    px, py = lerp(W * 0.45, 92, e), lerp(1, 22, e)
                elif k < 4.6:
                    out = 1.0
                    e = ease((k - 3.6) / 1.0)
                    px, py = lerp(92, W * 0.6, e), lerp(22, H * 0.8, e)
                elif k < 5.0:
                    out = 1 - ease((k - 4.6) / 0.4)
                    px, py = W * 0.6, H * 0.8
                else:
                    out, px, py = 0.0, W * 0.6, H * 0.8
                y = -BH + strip + (BH - strip) * out
                cr.set_source_rgba(col.red, col.green, col.blue, max(live["alpha"], 0.92))
                rounded(cr, 0, y, W, BH, live["rad"])
                cr.fill()
                cr.set_source_rgba(1, 1, 1, 0.55)                # the line along its edge
                cr.rectangle(0, y + BH - 2, W, 2)
                cr.fill()
                apps = (["web-browser", "internet-web-browser"], ["utilities-terminal"],
                        ["system-file-manager", "folder"], ["accessories-text-editor",
                                                             "text-x-generic"],
                        ["multimedia-audio-player", "audio-x-generic"])
                names = ["Web", "Terminal", "Files", "Editor", "Music"]
                for i, (names_i, label) in enumerate(zip(apps, names)):
                    ix = 22 + i * 62
                    pb = icon(names_i, 24)
                    if pb is not None:
                        cr.save()
                        Gdk.cairo_set_source_pixbuf(cr, pb, ix + 7, y + 6)
                        cr.paint()
                        cr.restore()
                    text(cr, ix + 19, y + 44, label, 8, 0.95, centre=True)
                if 2.5 <= k < 2.95:
                    ripple(cr, 92, 22, (k - 2.5) / 0.45)
                pointer(cr, px, py)
            else:
                background(cr, W, H)
                if kind == "rollup":
                    cubby(cr, 30, 20, 190, TH, "Rolled Up", [], [])
                    cubby(cr, 30, 56, 190, 58, "My Stuff", DOC, DOCN)
                elif kind == "folder":
                    cubby(cr, 16, 14, W - 32, H - 28, title,
                          ["folder", "folder", "folder", "text-x-generic", "font-x-generic"],
                          ["Design", "Specs", "Archive", "Tests", "Logo"], folder=True)
                elif kind.startswith("tabstyle-"):
                    cubby(cr, 8, 10, W - 16, H - 20, "", DOC, DOCN, tabs=["Files", "Work", "Music"],
                          tstyle=kind[9:])
                elif tmode:
                    cubby(cr, 10, 10, W - 20, H - 20, "General", DOC, DOCN,
                          show_title=tmode != "never")
                    if tmode == "hover":
                        pointer(cr, W * 0.62, 16)
                else:
                    cubby(cr, 30, 18, W - 60, H - 36, title, DOC, DOCN)
            return False

        area.connect("draw", draw)
        area.look = look                      # change it and queue_draw() for a live preview
        if kind in ("pages", "hide", "tabs", "launchbar"):
            def tick():
                if getattr(area, "_gone", False):
                    return False
                if area.get_mapped():
                    area.queue_draw()
                return True
            GLib.timeout_add(33, tick)
            area.connect("destroy", lambda *_a: setattr(area, "_gone", True))
        return area
