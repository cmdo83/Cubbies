"""A page's own settings: its background and its default cubby look."""

import os

from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from ..constants import DEFAULT_RADIUS, MAX_BORDER, MAX_RADIUS
from ..desktop_env import BACKGROUNDS_PLACE
from ..wallpapers import PICTURE_ASPECTS, SHADINGS, make_thumbnail, wallpaper_collections


class AppPageSettings:
    """A page's own settings. Part of App."""

    def build_page_settings(self, page, tab_label=None, host=None):
        """One page's settings: its name, wallpaper, and the default look for NEW cubbies on
        it. With host (Manage Pages › the gear) it returns two boxes instead, (background,
        cubby defaults), without the name, for the two tabs there; host is a dict with
        "parent" (the window dialogs belong to), "pick" ((leave, come back) for Pick from
        Screen), "reopen" (build these again) and "changed" (the page's look changed)."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(14)

        # ---- name
        row = Gtk.Box(spacing=10)
        row.pack_start(Gtk.Label(label="Page name"), False, False, 0)
        name = Gtk.Entry()
        name.set_text(page["name"])
        name.set_width_chars(24)

        def renamed(e):
            text = e.get_text().strip()
            if text:
                page["name"] = text
                page.pop("auto", None)
                if tab_label is not None:
                    tab_label.set_text(text)
                self.pager.update()
                self.save()
        name.connect("changed", renamed)
        row.pack_start(name, False, False, 0)
        if host is None:                 # (Manage Pages has its own Rename)
            box.pack_start(row, False, False, 0)

        # ---- wallpaper
        box.pack_start(Gtk.Label(label="<b>Wallpaper</b>", use_markup=True, xalign=0),
                       False, False, 4)
        row = Gtk.Box(spacing=10)
        thumb = Gtk.Image()
        thumb.set_size_request(128, 72)
        pick = Gtk.Button()
        pick.add(thumb)
        pick.set_tooltip_text("Click to choose a wallpaper for this page")
        state = Gtk.Label(xalign=0)
        state.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        state.get_style_context().add_class("dim-label")
        clear = Gtk.Button(label="Clear")
        clear.set_halign(Gtk.Align.START)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        texts.set_valign(Gtk.Align.CENTER)
        texts.set_hexpand(True)
        texts.pack_start(state, False, False, 0)
        texts.pack_start(clear, False, False, 0)
        row.pack_start(pick, False, False, 0)
        row.pack_start(texts, True, True, 0)
        box.pack_start(row, False, False, 0)

        def show_wallpaper():
            path = page.get("wallpaper")
            if path and os.path.exists(path):
                pb = make_thumbnail(path, 128)
                if pb is not None:
                    thumb.set_from_pixbuf(pb)
                else:
                    thumb.set_from_icon_name("image-missing", Gtk.IconSize.DIALOG)
            else:
                thumb.set_from_icon_name("image-x-generic", Gtk.IconSize.DIALOG)
            title = next((t for _n, _i, pics in wallpaper_collections() for p, t in pics
                          if p == path), None) if path else None
            state.set_text((title or os.path.splitext(os.path.basename(path))[0]) if path
                           else "(the wallpaper is not changed on this page)")
            clear.set_sensitive(bool(path))

        def wall_changed():
            show_wallpaper()
            if host is not None:
                host["changed"]()
        pick.connect("clicked", lambda _b: self.choose_wallpaper(
            page, wall_changed, parent=host["parent"] if host else None))
        clear.connect("clicked", lambda _b: (self.set_wallpaper_for(page, None),
                                             wall_changed()))
        show_wallpaper()

        # the background settings for this page, right with its wallpaper
        bgrid = Gtk.Grid(row_spacing=8, column_spacing=12)
        bgrid.set_margin_top(6)
        box.pack_start(bgrid, False, False, 0)
        aspect = Gtk.ComboBoxText()
        aspect.append("desktop", "As the desktop has it")
        for k, text in PICTURE_ASPECTS:
            aspect.append(k, text)
        aspect.set_active_id(page.get("wallpaper_aspect") or "desktop")
        aspect.connect("changed", lambda c: self.set_page_bg(
            page, "wallpaper_aspect", None if c.get_active_id() in (None, "desktop")
            else c.get_active_id()))
        shading = Gtk.ComboBoxText()
        shading.append("desktop", "As the desktop has it")
        for k, text in SHADINGS:
            shading.append(k, text)
        shading.set_active_id(page.get("wallpaper_shading") or "desktop")
        bgs = self.bg_settings()

        def colour_button(key, gkey):
            rgba = Gdk.RGBA()
            now = page.get(key) or (bgs.get_string(gkey) if bgs is not None else "#000000")
            if not rgba.parse(now or "#000000"):
                rgba.parse("#000000")
            btn = Gtk.ColorButton.new_with_rgba(rgba)
            btn.set_use_alpha(False)

            def chosen(b):
                c = b.get_rgba()
                self.set_page_bg(page, key, "#{:02x}{:02x}{:02x}".format(
                    round(c.red * 255), round(c.green * 255), round(c.blue * 255)))
                if host is not None:
                    host["changed"]()
            btn.connect("color-set", chosen)
            return btn
        c1 = colour_button("wallpaper_color1", "primary-color")
        c2 = colour_button("wallpaper_color2", "secondary-color")
        crow = Gtk.Box(spacing=8)
        crow.pack_start(shading, False, False, 0)
        crow.pack_start(c1, False, False, 0)
        crow.pack_start(c2, False, False, 0)

        def shading_set(c):
            mode = c.get_active_id()
            self.set_page_bg(page, "wallpaper_shading", None if mode in (None, "desktop")
                             else mode)
            c2.set_visible(mode in ("horizontal", "vertical") or (
                mode == "desktop" and bgs is not None
                and bgs.get_string("color-shading-type") != "solid"))
        shading.connect("changed", shading_set)
        for r, (label, w) in enumerate((("Picture aspect:", aspect),
                                        ("Background colour:", crow))):
            bgrid.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1)
            w.set_halign(Gtk.Align.START)
            bgrid.attach(w, 1, r, 1, 1)
        c2.set_no_show_all(True)
        c2.set_visible(shading.get_active_id() in ("horizontal", "vertical") or (
            shading.get_active_id() == "desktop" and bgs is not None
            and bgs.get_string("color-shading-type") != "solid"))
        note = Gtk.Label(label="The colour shows around a picture that doesn't fill the "
                               "screen, or on its own with \u201cNo picture\u201d. "
                               "\u201cAs the desktop has it\u201d keeps "
                               f"{BACKGROUNDS_PLACE}' choice.", xalign=0)
        note.set_line_wrap(True)
        note.get_style_context().add_class("dim-label")
        box.pack_start(note, False, False, 0)
        try:
            src = Gio.SettingsSchemaSource.get_default()
            if src.lookup("org.cinnamon.desktop.background.slideshow", True) and Gio.Settings.new(
                    "org.cinnamon.desktop.background.slideshow").get_boolean("slideshow-enabled"):
                warn = Gtk.Label(label="Backgrounds is playing a slideshow, which changes the "
                                       "wallpaper by itself and overrides page wallpapers. Turn "
                                       "it off in System Settings \u203a Backgrounds \u203a "
                                       "Settings.", xalign=0)
                warn.set_line_wrap(True)
                box.pack_start(warn, False, False, 0)
        except Exception:
            pass

        # ---- default look for new cubbies
        if host is not None:             # (its own tab in Manage Pages)
            bg_box, box = box, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            box.set_border_width(14)
        box.pack_start(Gtk.Label(label="<b>Default look for new cubbies on this page</b>",
                                 use_markup=True, xalign=0), False, False, 6)
        hint = Gtk.Label(label="New cubbies start with this look. Existing cubbies keep theirs "
                               "unless you use the button below.", xalign=0)
        hint.set_line_wrap(True)
        hint.get_style_context().add_class("dim-label")
        box.pack_start(hint, False, False, 0)

        defaults = page.get("defaults", {})
        default_font = Gtk.Settings.get_default().get_property("gtk-font-name") or "Sans 10"
        target = "defaults:" + self.page_id(page)
        busy = [False]
        previews = []

        def put(key, value):
            if not busy[0]:
                self.set_page_default(page, key, value)
                for redraw in previews:
                    redraw()

        def labelled_grid(sec, rows):
            grid = Gtk.Grid(row_spacing=8, column_spacing=12)
            sec.pack_start(grid, False, False, 0)
            for r, (label, w) in enumerate(rows):
                grid.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1)
                w.set_halign(Gtk.Align.START)
                grid.attach(w, 1, r, 1, 1)

        def reopen_here():
            GLib.idle_add(lambda: self.open_settings(section="pages",
                                                     page_index=self.cfg["pages"].index(page)
                                                     if page in self.cfg["pages"] else None)
                          and False)
        pick = (lambda: self._settings_dlg and self._settings_dlg.response(
            Gtk.ResponseType.CLOSE), reopen_here)
        if host is not None:
            reopen_here, pick = host["reopen"], host["pick"]

        # background colour
        sec = self.s_section(box, "Background colour")
        previews.append(self.build_colour_bars(sec, fixed=target, pick=pick, title="New Cubby",
                                               on_push=lambda: [p() for p in previews[1:]]))
        # title bar
        sec = self.s_section(box, "Title bar")
        font_btn = Gtk.FontButton()
        font_btn.set_show_size(True)
        font_btn.set_use_font(True)
        font_btn.set_font(defaults.get("title_font") or default_font)
        font_reset = Gtk.Button(label="Use the Usual Font")
        frow = Gtk.Box(spacing=8)
        frow.pack_start(font_btn, False, False, 0)
        frow.pack_start(font_reset, False, False, 0)
        height_spin = Gtk.SpinButton.new_with_range(16, 100, 1)
        height_spin.set_value(defaults.get("title_height") or 28)
        hrow = Gtk.Box(spacing=8)
        hrow.pack_start(height_spin, False, False, 0)
        hrow.pack_start(Gtk.Label(label="px"), False, False, 0)
        labelled_grid(sec, (("Title font:", frow), ("Title bar height:", hrow)))
        font_btn.connect("font-set", lambda b: put("title_font", b.get_font()))

        def font_back(_b):
            busy[0] = True
            font_btn.set_font(default_font)
            busy[0] = False
            put("title_font", None)
        font_reset.connect("clicked", font_back)
        height_spin.connect("value-changed", lambda sp: put("title_height", int(sp.get_value())))
        # background blur
        sec = self.s_section(box, "Background blur")
        blur_mode = Gtk.ComboBoxText()
        blur_mode.append("usual", "As in Settings (" + ("on" if self.setting("blur_bg")
                                                         else "off") + ")")
        blur_mode.append("on", "Blurred (frosted glass)")
        blur_mode.append("off", "Not blurred")
        blur_mode.set_active_id("usual" if defaults.get("blur") is None else
                                "on" if defaults.get("blur") else "off")
        amount = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 6, 40, 1)
        amount.set_value(int(defaults.get("blur_level", self.cfg.get("blur_level", 18))))
        amount.set_size_request(300, -1)
        amount.add_mark(6, Gtk.PositionType.BOTTOM, "Light")
        amount.add_mark(40, Gtk.PositionType.BOTTOM, "Heavy")
        glass = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 10, 100, 5)
        glass.set_value(round(float(defaults.get("blur_strength",
                                                 self.cfg.get("blur_strength", 1.0))) * 100))
        glass.set_size_request(300, -1)
        glass.add_mark(10, Gtk.PositionType.BOTTOM, "Clear")
        glass.add_mark(100, Gtk.PositionType.BOTTOM, "Frosted")
        labelled_grid(sec, (("Blur behind it:", blur_mode), ("Blur amount:", amount),
                            ("Glass strength:", glass)))
        bnote = Gtk.Label(label="Every cubby on this page uses this, unless it has its own "
                                "blur (right-click it \u203a Style \u203a Styling Options).",
                          xalign=0)
        bnote.set_line_wrap(True)
        bnote.get_style_context().add_class("dim-label")
        sec.pack_start(bnote, False, False, 0)

        def page_blur_on():
            b = (page.get("defaults") or {}).get("blur")
            return bool(self.setting("blur_bg") if b is None else b)

        def blur_put(key, value):
            put(key, value)
            on = page_blur_on()
            amount.set_sensitive(on)
            glass.set_sensitive(on)
            self.blurred_wallpaper()           # (starts making it if it's newly needed)
            if not getattr(self, "_page_blur_redraw", 0):
                def redraw():                  # the page's cubbies follow it straight away
                    self._page_blur_redraw = 0
                    for win in self.windows.values():
                        win.queue_draw()
                    return False
                self._page_blur_redraw = GLib.timeout_add(120, redraw)
        amount.set_sensitive(page_blur_on())
        glass.set_sensitive(page_blur_on())
        blur_mode.connect("changed", lambda c: blur_put(
            "blur", None if c.get_active_id() == "usual" else c.get_active_id() == "on"))
        amount.connect("value-changed", lambda sc: blur_put("blur_level", int(sc.get_value())))
        glass.connect("value-changed", lambda sc: blur_put("blur_strength",
                                                           round(sc.get_value() / 100.0, 2)))
        # corners and border
        sec = self.s_section(box, "Corners and border")
        radius_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, MAX_RADIUS, 1)
        radius_scale.set_value(defaults.get("radius", DEFAULT_RADIUS))
        radius_scale.set_size_request(300, -1)
        radius_scale.add_mark(0, Gtk.PositionType.BOTTOM, "Square")
        radius_scale.add_mark(DEFAULT_RADIUS, Gtk.PositionType.BOTTOM, "Default")
        radius_scale.add_mark(MAX_RADIUS, Gtk.PositionType.BOTTOM, "Round")
        border_spin = Gtk.SpinButton.new_with_range(0, MAX_BORDER, 1)
        border_spin.set_value(defaults.get("border_width", 0))
        brow = Gtk.Box(spacing=8)
        brow.pack_start(border_spin, False, False, 0)
        brow.pack_start(Gtk.Label(label="px   (0 = no border)"), False, False, 0)
        labelled_grid(sec, (("Corner roundness:", radius_scale), ("Border width:", brow)))
        radius_scale.connect("value-changed", lambda sc: put("radius", int(sc.get_value())))
        border_spin.connect("value-changed", lambda sp: put("border_width",
                                                            int(sp.get_value()) or None))
        # border colour
        sec = self.s_section(box, "Border colour")

        def border_pushed():
            if int(border_spin.get_value()) != int((page.get("defaults") or {})
                                                   .get("border_width", 0)):
                busy[0] = True
                border_spin.set_value((page.get("defaults") or {}).get("border_width", 0))
                busy[0] = False
            for redraw in previews:
                redraw()
        previews.append(self.build_colour_bars(sec, fixed=target, pick=pick, title="New Cubby",
                                               part="border", on_push=border_pushed))

        def reset(_b):
            busy[0] = True
            page.pop("defaults", None)
            font_btn.set_font(default_font)
            height_spin.set_value(28)
            radius_scale.set_value(DEFAULT_RADIUS)
            border_spin.set_value(0)
            blur_mode.set_active_id("usual")
            glass.set_value(round(float(self.cfg.get("blur_strength", 1.0)) * 100))
            amount.set_value(int(self.cfg.get("blur_level", 18)))
            busy[0] = False
            self.save()
            reopen_here()                     # the colour bars start again from the new look
            if self._settings_dlg and host is None:
                self._settings_dlg.response(Gtk.ResponseType.CLOSE)

        def apply_all(_b):
            look = dict(page.get("defaults") or {})
            self.apply_appearance_to_page(page, look.get("color", "rgb(20,24,36)"),
                                          look.get("opacity", 0.58), look.get("title_font"),
                                          look.get("title_height"),
                                          look.get("radius", DEFAULT_RADIUS),
                                          {k: look[k] for k in ("border_width", "border_color")
                                           if k in look})   # (blur: cleared, so they follow
                                                            # the page's from now on)
            for win in self.windows.values():
                win.apply_title_size()
                win.queue_draw()
            self.save()
            if host is not None:
                host["changed"]()

        btns = Gtk.Box(spacing=8)
        b1 = Gtk.Button(label="Give Every Cubby on This Page This Look")
        b1.connect("clicked", apply_all)
        b2 = Gtk.Button(label="Reset to the Built-in Look")
        b2.connect("clicked", reset)
        btns.pack_start(b1, False, False, 0)
        btns.pack_start(b2, False, False, 0)
        box.pack_start(btns, False, False, 6)
        if host is not None:
            return bg_box, box
        return box
