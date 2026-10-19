"""Styling Options: a cubby's look."""

from gi.repository import Gdk, GLib, Gtk

from ..constants import (BLUR_KEYS, BUTTON_KEYS, DEFAULT_BORDER_COLOR, DEFAULT_RADIUS,
    LINE_STYLES, MAX_BORDER, MAX_RADIUS, SHARE_PARTS, TITLE_ALIGNS)
from ..core import undoable


class CubbyAppearance:
    """Styling Options. Part of Cubby."""

    @undoable("Styling Options")
    def edit_appearance(self):
        """One cubby's look, laid out like Settings: colour bars, corners and border, the
        title bar, a launch bar's line, and sharing the look. Changes show straight away."""
        app, d = self.app, self.data
        page = app.page_of(d)
        bar = bool(d.get("launchbar"))
        name = ("your launch bar" if bar else "“" + (app.group_title(d) if d.get("group")
                                                           else self.pane["title"]) + "”")
        dlg, sw, box = app.s_dialog("Styling Options", f"How {name} looks. Changes show on it "
                                    "straight away.")
        dlg.set_resizable(False)              # a fixed size; the contents scroll
        sw.set_size_request(780, 600)
        saving = {"id": 0}

        def save_later():
            if saving["id"]:
                return

            def go():
                saving["id"] = 0
                app.save()
                return False
            saving["id"] = GLib.timeout_add(400, go)

        def reopen():
            win = app.windows.get(d["id"])
            if win is not None:
                GLib.idle_add(lambda: win.edit_appearance() and False)

        sec = app.s_section(box, "Background colour")
        bg_preview = app.build_colour_bars(
            sec, fixed="cubby:" + d["id"], title="Launch Bar" if bar else self.pane["title"],
            pick=(lambda: dlg.response(Gtk.ResponseType.CLOSE), reopen),
            on_push=lambda: [p() for p in previews[1:]])

        # ---- corners and border
        sec = app.s_section(box, "Corners and border")
        grid = Gtk.Grid(row_spacing=8, column_spacing=12)
        sec.pack_start(grid, False, False, 0)
        radius = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, MAX_RADIUS, 1)
        radius.set_value(d.get("radius", DEFAULT_RADIUS))
        radius.set_size_request(300, -1)
        radius.add_mark(0, Gtk.PositionType.BOTTOM, "Square")
        radius.add_mark(DEFAULT_RADIUS, Gtk.PositionType.BOTTOM, "Default")
        radius.add_mark(MAX_RADIUS, Gtk.PositionType.BOTTOM, "Round")
        border = Gtk.SpinButton.new_with_range(0, MAX_BORDER, 1)
        border.set_value(d.get("border_width", 0))
        brow = Gtk.Box(spacing=8)
        brow.pack_start(border, False, False, 0)
        brow.pack_start(Gtk.Label(label="px   (0 = no border)"), False, False, 0)
        for r, (label, w) in enumerate((("Corner roundness:", radius), ("Border width:", brow))):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1)
            w.set_halign(Gtk.Align.START)
            grid.attach(w, 1, r, 1, 1)
        previews = [bg_preview]
        syncing = [False]

        def redraw_previews():
            for redraw in previews:
                redraw()

        def shape_changed(*_a):
            if syncing[0]:
                return
            d["radius"] = int(radius.get_value())
            bw = int(border.get_value())
            for key in ("border_width",) + BUTTON_KEYS:
                d.pop(key, None)
            if bw > 0:                       # the colour is kept even at 0, for next time
                d["border_width"] = bw
                d.setdefault("border_color", DEFAULT_BORDER_COLOR)
            self.apply_style()
            self.queue_draw()
            redraw_previews()
            save_later()
        radius.connect("value-changed", shape_changed)
        border.connect("value-changed", shape_changed)

        def border_pushed():
            """The border colour bars changed it (and may have given a 2 px border)."""
            if int(border.get_value()) != int(d.get("border_width", 0)):
                syncing[0] = True
                border.set_value(d.get("border_width", 0))
                syncing[0] = False
            redraw_previews()
            save_later()


        # ---- title bar
        if self.has_title() and not bar:
            sec = app.s_section(box, "Title bar")
            grid = Gtk.Grid(row_spacing=8, column_spacing=12)
            sec.pack_start(grid, False, False, 0)
            default_font = Gtk.Settings.get_default().get_property("gtk-font-name") or "Sans 10"
            font_btn = Gtk.FontButton()
            font_btn.set_show_size(True)
            font_btn.set_use_font(True)
            font_btn.set_font(d.get("title_font") or default_font)
            font_reset = Gtk.Button(label="Use the Usual Font")
            frow = Gtk.Box(spacing=8)
            frow.pack_start(font_btn, False, False, 0)
            frow.pack_start(font_reset, False, False, 0)
            height = Gtk.SpinButton.new_with_range(16, 100, 1)
            height.set_value(d.get("title_height") or max(16, self.title_ev.get_allocated_height()))
            hrow = Gtk.Box(spacing=8)
            hrow.pack_start(height, False, False, 0)
            hrow.pack_start(Gtk.Label(label="px"), False, False, 0)
            align = Gtk.ComboBoxText()
            for key, text in (("left", "Left"), ("center", "Centre"), ("right", "Right")):
                align.append(key, text)
            align.set_active_id(d.get("title_align") if d.get("title_align") in TITLE_ALIGNS
                                else "left")
            if d.get("group"):
                align.set_sensitive(False)
                align.set_tooltip_text("Only for a cubby that is not combined into tabs")
            elif app.setting("hover_buttons"):
                align.set_active_id("center")
                align.set_sensitive(False)
                align.set_tooltip_text("Names are centred while the ☰ and ✕ title "
                                       "bar buttons are on (Settings › Colour & "
                                       "Appearance)")
            for r, (label, w) in enumerate((("Title font:", frow), ("Title bar height:", hrow),
                                            ("Title alignment:", align))):
                grid.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1)
                w.set_halign(Gtk.Align.START)
                grid.attach(w, 1, r, 1, 1)

            def font_set(*_a):
                d["title_font"] = font_btn.get_font()
                self.apply_style()
                self.apply_title_size()
                save_later()

            def font_back(_b):
                d.pop("title_font", None)
                font_btn.set_font(default_font)
                self.apply_style()
                self.apply_title_size()
                save_later()

            def height_set(*_a):
                d["title_height"] = int(height.get_value())
                self.apply_style()
                self.apply_title_size()
                save_later()

            def align_set(*_a):
                key = align.get_active_id() or "left"
                if key == "left":
                    d.pop("title_align", None)
                else:
                    d["title_align"] = key
                self.apply_title_size()
                save_later()
            font_btn.connect("font-set", font_set)
            font_reset.connect("clicked", font_back)
            height.connect("value-changed", height_set)
            align.connect("changed", align_set)

        # ---- background blur (this cubby's own choice, else its page's, else Settings')
        sec = app.s_section(box, "Background blur")
        grid = Gtk.Grid(row_spacing=8, column_spacing=12)
        sec.pack_start(grid, False, False, 0)
        def page_blur():
            """What this cubby gets when it has no blur of its own: (on, amount, glass)."""
            own = {k: d.pop(k) for k in BLUR_KEYS if k in d}
            try:
                return app.blur_of(d)
            finally:
                d.update(own)
        p_on = page_blur()[0]
        blur_mode = Gtk.ComboBoxText()
        blur_mode.append("usual", "As on this page (" + ("on" if p_on else "off") + ")")
        blur_mode.append("on", "Blurred (frosted glass)")
        blur_mode.append("off", "Not blurred")
        blur_mode.set_active_id("usual" if d.get("blur") is None else
                                "on" if d.get("blur") else "off")
        on_now, level_now, glass_now = app.blur_of(d)
        amount = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 6, 40, 1)
        amount.set_value(level_now)
        amount.set_size_request(300, -1)
        amount.add_mark(6, Gtk.PositionType.BOTTOM, "Light")
        amount.add_mark(40, Gtk.PositionType.BOTTOM, "Heavy")
        glass = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 10, 100, 5)
        glass.set_value(round(glass_now * 100))
        glass.set_size_request(300, -1)
        glass.add_mark(10, Gtk.PositionType.BOTTOM, "Clear")
        glass.add_mark(100, Gtk.PositionType.BOTTOM, "Frosted")
        for r, (label, w) in enumerate((("Blur behind it:", blur_mode),
                                        ("Blur amount:", amount),
                                        ("Glass strength:", glass))):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1)
            w.set_halign(Gtk.Align.START)
            grid.attach(w, 1, r, 1, 1)
        back = Gtk.Button(label="Use the Page\u2019s Blur")
        back.set_halign(Gtk.Align.START)
        back.set_tooltip_text("Forget this cubby's own blur: it follows its page's again "
                              "(Manage Pages \u203a the page's gear \u203a Cubby Defaults)")
        sec.pack_start(back, False, False, 4)
        app.s_note(sec, "Moving a slider gives this cubby its own blur; otherwise it uses "
                        "its page's (Manage Pages \u203a click the page \u203a its gear).")
        busy = [False]

        def blur_changed():
            on = app.cubby_blur(d)
            amount.set_sensitive(on)
            glass.set_sensitive(on)
            back.set_sensitive(any(k in d for k in BLUR_KEYS))
            app.blurred_wallpaper(app.blur_of(d)[1])   # starts making it if newly needed
            self.queue_draw()
            save_later()

        def blur_set(*_a):
            if busy[0]:
                return
            mode = blur_mode.get_active_id()
            if mode == "usual":
                d.pop("blur", None)
            else:
                d["blur"] = mode == "on"
            blur_changed()

        def amount_set(sc):
            if not busy[0]:
                d["blur_level"] = int(sc.get_value())
                blur_changed()

        def glass_set(sc):
            if not busy[0]:
                d["blur_strength"] = round(sc.get_value() / 100.0, 2)
                blur_changed()

        def use_page(_b):
            for k in BLUR_KEYS:
                d.pop(k, None)
            _on, lv, gl = app.blur_of(d)
            busy[0] = True
            blur_mode.set_active_id("usual")
            amount.set_value(lv)
            glass.set_value(round(gl * 100))
            busy[0] = False
            blur_changed()
        blur_mode.connect("changed", blur_set)
        amount.connect("value-changed", amount_set)
        glass.connect("value-changed", glass_set)
        back.connect("clicked", use_page)
        amount.set_sensitive(on_now)
        glass.set_sensitive(on_now)
        back.set_sensitive(any(k in d for k in BLUR_KEYS))


        bsec = app.s_section(box, "Border colour")
        previews.append(app.build_colour_bars(
            bsec, fixed="cubby:" + d["id"], part="border", on_push=border_pushed,
            title="Launch Bar" if bar else self.pane["title"],
            pick=(lambda: dlg.response(Gtk.ResponseType.CLOSE), reopen)))

        # ---- a launch bar's line
        if bar:
            sec = app.s_section(box, "Line along its inner edge")
            grid = Gtk.Grid(row_spacing=8, column_spacing=12)
            sec.pack_start(grid, False, False, 0)
            lw = Gtk.SpinButton.new_with_range(0, 20, 1)
            lw.set_value(int(d.get("line_width", 0)))
            lrgba = Gdk.RGBA()
            if not lrgba.parse(d.get("line_color") or "rgba(255,255,255,0.6)"):
                lrgba.parse("rgba(255,255,255,0.6)")
            lcol = Gtk.ColorButton.new_with_rgba(lrgba)
            lcol.set_use_alpha(True)
            lstyle = Gtk.ComboBoxText()
            for k, t in LINE_STYLES:
                lstyle.append(k, t)
            lstyle.set_active_id(d.get("line_style", "solid"))
            lrow = Gtk.Box(spacing=8)
            lrow.pack_start(lw, False, False, 0)
            lrow.pack_start(Gtk.Label(label="px   (0 = no line)"), False, False, 0)
            for r, (label, w) in enumerate((("Thickness:", lrow), ("Colour:", lcol),
                                            ("Kind of line:", lstyle))):
                grid.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1)
                w.set_halign(Gtk.Align.START)
                grid.attach(w, 1, r, 1, 1)

            def line_set(*_a):
                d["line_width"] = int(lw.get_value())
                d["line_color"] = lcol.get_rgba().to_string()
                d["line_style"] = lstyle.get_active_id() or "solid"
                self.queue_draw()
                save_later()
            lw.connect("value-changed", line_set)
            lcol.connect("color-set", line_set)
            lstyle.connect("changed", line_set)
            app.s_note(sec, "Settings › Launch Bar Cubbies has the same choices (and "
                            "changes them there for every launch bar).")

        # ---- share the look
        if not bar:
            sec = app.s_section(box, "Share this look")
            app.s_note(sec, "Copy chosen parts of this look to other cubbies. Parts you "
                            "leave unticked stay as each cubby has them (so their own "
                            "colours can stay, say).")
            chosen = set(app.cfg.get("share_parts", []))
            parts_grid = Gtk.Grid(row_spacing=4, column_spacing=24)
            parts_grid.set_margin_top(4)
            sec.pack_start(parts_grid, False, False, 0)
            part_checks = {}
            for i, (key, label, _keys) in enumerate(SHARE_PARTS):
                chk = Gtk.CheckButton(label=label)
                chk.set_active(key in chosen)
                parts_grid.attach(chk, i % 3, i // 3, 1, 1)
                part_checks[key] = chk
            pages_lbl = Gtk.Label(label="To the cubbies on these pages:", xalign=0)
            pages_lbl.set_margin_top(10)
            sec.pack_start(pages_lbl, False, False, 0)
            pages_box = Gtk.FlowBox()
            pages_box.set_selection_mode(Gtk.SelectionMode.NONE)
            pages_box.set_max_children_per_line(4)
            pages_box.set_column_spacing(16)
            pages_box.set_homogeneous(False)
            sec.pack_start(pages_box, False, False, 0)
            every = Gtk.CheckButton(label="Every page")
            pages_box.add(every)
            page_checks = []
            for pg in app.cfg["pages"]:
                chk = Gtk.CheckButton(label=pg["name"] + ("  (this one)" if pg is page else ""))
                chk.set_active(pg is page)
                pages_box.add(chk)
                page_checks.append((pg, chk))
            arow = Gtk.Box(spacing=10)
            arow.set_margin_top(6)
            b_all = Gtk.Button(label="Apply to Those Cubbies")
            arow.pack_start(b_all, False, False, 0)
            sec.pack_start(arow, False, False, 0)
            note = app.s_note(sec, "")
            busy_pages = [False]

            def update_apply(*_a):
                if not busy_pages[0]:
                    busy_pages[0] = True
                    every.set_active(all(c.get_active() for _p, c in page_checks))
                    busy_pages[0] = False
                b_all.set_sensitive(any(c.get_active() for c in part_checks.values())
                                    and any(c.get_active() for _p, c in page_checks))

            def every_toggled(btn):
                if busy_pages[0]:
                    return
                busy_pages[0] = True
                for _p, c in page_checks:
                    c.set_active(btn.get_active())
                busy_pages[0] = False
                update_apply()
            every.connect("toggled", every_toggled)
            for c in part_checks.values():
                c.connect("toggled", update_apply)
            for _p, c in page_checks:
                c.connect("toggled", update_apply)
            update_apply()

            def to_all(_b):
                parts = [k for k, c in part_checks.items() if c.get_active()]
                pages = [pg for pg, c in page_checks if c.get_active()]
                app.cfg["share_parts"] = parts
                n = app.apply_look_parts(d, parts, pages)
                where = ("every page" if len(pages) == len(app.cfg["pages"]) and len(pages) > 1
                         else ", ".join(f"\u201c{pg['name']}\u201d" for pg in pages))
                note.set_text(f"Done: {n} cubb{'y' if n == 1 else 'ies'} on {where} changed."
                              if n else "There are no other cubbies there.")

            row = Gtk.Box(spacing=8)
            row.set_margin_top(10)
            b_def = Gtk.Button(label=f"Use the Whole Look as the Default for \u201c{page['name']}\u201d")
            b_copy = Gtk.Button(label="Copy Style")
            row.pack_start(b_def, False, False, 0)
            row.pack_start(b_copy, False, False, 0)
            sec.pack_start(row, False, False, 0)

            def as_default(_b):
                app.use_cubby_style_as_default(d)
                note.set_text(f"New cubbies on “{page['name']}” will look like this.")

            def copy(_b):
                app.copy_style(d)
                note.set_text("Copied. Right-click another cubby › Style › Paste.")
            b_all.connect("clicked", to_all)
            b_def.connect("clicked", as_default)
            b_copy.connect("clicked", copy)
        app.s_move_section(box, "Corners and border", "Border colour")   # (as in the page's)
        dlg.show_all()
        dlg.run()
        dlg.destroy()
        if saving["id"]:
            GLib.source_remove(saving["id"])
        app.save()
