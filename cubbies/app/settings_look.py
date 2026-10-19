"""Settings sections: home, look, pages, folders, tabs, roll-up, hide, peek."""

from gi.repository import Gdk, Gio, GLib, Gtk

from ..colours import hex_code, parse_colour_code, pick_screen_colour, wallpaper_main_colour
from ..constants import DEFAULT_BORDER_COLOR
from ..desktop_env import DESKTOP, DESKTOP_NAME, IS_MATE, IS_XFCE, SHORTCUTS_SHORT
from ..hotkeys import HOTKEY_CHOICES
from ..runtime import autostart_enabled, set_autostart
from ..widgets import ColourBar


class AppSettingsLook:
    """Settings sections (look and behaviour). Part of App."""

    # ---- the sections
    def settings_home(self):
        n_pages = len(self.cfg["pages"])
        n_cubbies = sum(1 for f in self.all_cubbies() if not f.get("tab_of"))
        sw, box = self.s_page("Home", "Cubbies keeps your desktop tidy: boxes that hold your "
                              "icons, as see-through or as solid as you like, spread over as "
                              "many desktop pages as you want.",
                              self.s_preview("cubby"))
        sec = self.s_section(box, "Getting started")
        self.s_link(sec, "Open the Welcome Guide", lambda: GLib.idle_add(
            lambda: self.show_welcome() and False))
        self.s_link(sec, "Make a new cubby on this page", lambda: GLib.idle_add(
            lambda: self.new_cubby() and False))
        self.s_link(sec, "Hide or show all cubbies now", self.toggle_hidden)
        self.s_note(sec, "Tip: hold the left mouse button and drag on the empty desktop to "
                         "draw a new cubby. Right-click a cubby for everything else.")
        sec = self.s_section(box, "Startup")
        auto = Gtk.CheckButton(label="Start Cubbies when I log in")
        auto.set_active(autostart_enabled())
        auto.connect("toggled", lambda b: set_autostart(b.get_active()))
        sec.pack_start(auto, False, False, 0)
        sec = self.s_section(box, "Your desktop")
        self.s_note(sec, f"{n_pages} page{'s' if n_pages != 1 else ''} and {n_cubbies} "
                         f"cubb{'ies' if n_cubbies != 1 else 'y'}. Files you add are kept in "
                         f"{self.store_dir()}.", dim=False)
        return sw

    def settings_look(self):
        sw, box = self.s_page("Colour & Appearance", "Change how your cubbies look.")
        try:
            composited = Gdk.Screen.get_default().is_composited()
        except Exception:
            composited = True
        if not composited:
            where = {"xfce": "Settings Manager \u203a Window Manager Tweaks \u203a Compositor",
                     "mate": "Control Center \u203a Windows (or MATE Tweak)"}.get(
                DESKTOP, "your window manager's settings")
            sec = self.s_section(box, "Transparency is off")
            self.s_note(sec, "Your desktop isn't running a compositor right now, so cubbies "
                             "can't be see-through and show solid. Turn compositing on in "
                             f"{where}, then restart Cubbies.", dim=False)
        sec = self.s_section(box, "Show titles")
        row = Gtk.Box(spacing=26)
        sec.pack_start(row, False, False, 0)
        current = self.cfg.get("show_titles", "always")
        group = None

        def titles_changed(btn, mode):
            if btn.get_active():
                self.cfg["show_titles"] = mode
                self.save()
                for win in self.windows.values():
                    win.update_title_visibility()

        for mode, label in (("never", "Never"), ("hover", "On Mouseover"), ("always", "Always")):
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            pic = self.s_preview("titles-" + mode)
            pic.set_size_request(120, 76)
            col.pack_start(pic, False, False, 0)
            rb = Gtk.RadioButton.new_with_label_from_widget(group, label)
            group = group or rb
            rb.set_active(mode == current)
            rb.set_halign(Gtk.Align.CENTER)
            rb.connect("toggled", titles_changed, mode)
            col.pack_start(rb, False, False, 0)
            row.pack_start(col, False, False, 0)
        self.s_note(sec, "A rolled-up cubby always shows its title bar. A hidden title bar can "
                         "still be used to move the cubby.")

        sec = self.s_section(box, "Title bars")

        def hover_changed(_on):
            for win in self.windows.values():
                win.apply_title_size()
                win.update_title()
        self.s_check(sec, "Show the \u2630 (sort and view) and \u2715 (delete) buttons when the "
                          "pointer is on a title bar", "hover_buttons", hover_changed)
        self.s_note(sec, "While these buttons are on, names sit in the middle of the title bar. "
                         "Turn them off to put names on the left, centre or right (per cubby, "
                         "in its Styling Options).")
        row = Gtk.Box(spacing=10)
        auto = Gtk.CheckButton(label="Title text colour: automatic (matches each cubby's colour)")
        rgba = Gdk.RGBA()
        rgba.parse(self.cfg.get("title_color") or "rgb(255,255,255)")
        colour = Gtk.ColorButton.new_with_rgba(rgba)
        colour.set_use_alpha(False)
        auto.set_active(not self.cfg.get("title_color"))
        colour.set_sensitive(bool(self.cfg.get("title_color")))

        def colour_changed(*_a):
            if auto.get_active():
                self.cfg.pop("title_color", None)
            else:
                self.cfg["title_color"] = colour.get_rgba().to_string()
            colour.set_sensitive(not auto.get_active())
            self.apply_title_colour()
            self.save()
        auto.connect("toggled", colour_changed)
        colour.connect("color-set", colour_changed)
        row.pack_start(auto, False, False, 0)
        row.pack_start(colour, False, False, 0)
        sec.pack_start(row, False, False, 0)

        sec = self.s_section(box, "Fading")
        # (each slider has its own name: they used to share one, so ticking Fading switched
        # the blur slider on and off instead of this one)
        fade_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 10, 90, 5)
        fade_scale.set_value(round(float(self.cfg.get("fade_level", 0.35)) * 100))
        fade_scale.set_size_request(300, -1)
        fade_scale.add_mark(10, Gtk.PositionType.BOTTOM, "Faint")
        fade_scale.add_mark(90, Gtk.PositionType.BOTTOM, "Strong")

        def fade_changed(_on=None):
            fade_scale.set_sensitive(bool(self.setting("fade_idle")))
            for win in self.windows.values():
                win.update_fade()
        self.s_check(sec, "Fade cubbies when the pointer isn't over them (they come back when "
                          "the pointer is over them)", "fade_idle", fade_changed)
        lrow = Gtk.Box(spacing=10)
        lrow.pack_start(Gtk.Label(label="How visible a faded cubby is:"), False, False, 0)
        lrow.pack_start(fade_scale, False, False, 0)
        sec.pack_start(lrow, False, False, 0)

        def fade_level_changed(sc):
            self.cfg["fade_level"] = round(sc.get_value() / 100.0, 2)
            self.save()
            fade_changed()
        fade_scale.connect("value-changed", fade_level_changed)
        fade_scale.set_sensitive(bool(self.setting("fade_idle")))

        sec = self.s_section(box, "Background blur")

        def blur_changed(_on=None):
            for win in self.windows.values():
                win.queue_draw()
        self.s_check(sec, "Blur the wallpaper behind cubbies (frosted glass)", "blur_bg",
                     blur_changed)
        self.s_note(sec, "This is the usual choice. How much it blurs and the glass strength "
                         "are set for each page (Manage Pages \u203a click the page \u203a its "
                         "gear \u203a Cubby Defaults \u203a Background blur), and each cubby can "
                         "choose for itself: right-click it \u203a Style \u203a Styling "
                         "Options\u2026 \u203a Background blur. Needs a picture as the "
                         "wallpaper.")

        sec = self.s_section(box, "Colour, corners and borders")
        self.s_note(sec, "These are set where they apply, not here:")

        def to_page(_w=None):
            if self._settings_dlg:
                self._settings_dlg.response(Gtk.ResponseType.CLOSE)
            GLib.timeout_add(200, lambda: self.open_page_settings(None, 1) and False)
        self.s_bullets(sec, [
            "<b>Each page's look for its cubbies</b> (background colour, transparency, corners, "
            "border, title bar, blur): Manage Pages \u203a click the page \u203a its gear "
            "\u203a Cubby Defaults. New cubbies start with it; <i>Give Every Cubby on This "
            "Page This Look</i> brings the page's existing cubbies in line.",
            "<b>One cubby's own look</b>: right-click it \u203a Style \u203a Styling "
            "Options\u2026 There, <i>Share this look</i> copies just the parts you tick to the "
            "cubbies on the pages you tick. Ctrl + mouse wheel over its icons changes their "
            "size."])
        link = self.s_link(sec, "Cubby Defaults for this page\u2026", to_page)
        link.set_margin_top(6)
        return sw

    def build_colour_bars(self, sec, fixed=None, pick=None, title="General", part="background",
                          on_push=None, base=None):
        """Transparency / Colour intensity / Tint / Saturation bars for a choice of cubbies:
        all of them, every cubby on one page, or one cubby. Changes show straight away.
        part "background" sets color + opacity; part "border" sets border_color (its own
        alpha is the transparency) and gives a cubby without a border a 2 px one, so the
        change can be seen. on_push() runs after every change. Returns a function that
        redraws the preview from the cubby's current look."""
        import colorsys
        border = part == "border"
        tab = part == "tab"                   # a tab's own colour (base: the cubby's)
        BASE = DEFAULT_BORDER_COLOR if border else (base[0] if tab and base else
                                                    "rgb(20,24,36)")
        combo = Gtk.ComboBoxText()
        combo.append("all", "Every cubby (all pages)")
        for i, page in enumerate(self.cfg["pages"]):
            combo.append(f"page:{i}", f"Every cubby on \u201c{page['name']}\u201d")
        for i, page in enumerate(self.cfg["pages"]):
            for f in page["cubbies"]:
                if not f.get("tab_of"):
                    combo.append(f"cubby:{f['id']}", f"{page['name']} \u203a "
                                 f"{self.group_title(f) if f.get('group') else f['title']}")
        pref, self._colour_target_pref = getattr(self, "_colour_target_pref", None), None
        if not (pref and combo.set_active_id(pref)):
            combo.set_active_id(f"page:{self.cfg['page']}")
        combo.set_halign(Gtk.Align.START)
        if fixed:                       # one cubby's own Styling Options: no choice to make
            if not combo.set_active_id(fixed):
                combo.append(fixed, fixed)          # (a page's defaults: not in the list)
                combo.set_active_id(fixed)
        else:
            sec.pack_start(combo, False, False, 0)
        row = Gtk.Box(spacing=26)
        sec.pack_start(row, False, False, 4)
        grid = Gtk.Grid(row_spacing=4, column_spacing=12)
        row.pack_start(grid, False, False, 0)
        preview = self.s_preview("cubby", look={}, title=title)
        preview.set_valign(Gtk.Align.START)
        row.pack_start(preview, False, False, 0)
        state = {"h": 0.6, "s": 0.4, "v": 0.15, "o": 0.58, "busy": False, "save": 0}

        def targets(key):
            if key.startswith("defaults:"):    # only a page's look for NEW cubbies
                page = self.page_by_id(key[9:])
                return [], [page] if page is not None else []
            if key == "all":
                return [f for f in self.all_cubbies() if not f.get("tab_of")], \
                    list(self.cfg["pages"])
            if key.startswith("page:"):
                page = self.cfg["pages"][int(key[5:])]
                return [f for f in page["cubbies"] if not f.get("tab_of")], [page]
            fid = key[6:]
            return [f for f in self.all_cubbies() if f["id"] == fid], []

        def source():
            fs, pages = targets(combo.get_active_id() or "all")
            return fs[0] if fs else (pages[0].get("defaults", {}) if pages else {})

        def load(*_a):
            src = source()
            c = Gdk.RGBA()
            key = "border_color" if border else "tab_color" if tab else "color"
            if not c.parse(src.get(key) or BASE):
                c.parse(BASE)
            state["h"], state["s"], state["v"] = colorsys.rgb_to_hsv(c.red, c.green, c.blue)
            state["o"] = (c.alpha if border else
                          float(src.get("tab_opacity", base[1] if base else 0.58)) if tab else
                          float(src.get("opacity", 0.58)))
            state["busy"] = True
            for bar in bars.values():
                bar.value = {"transparency": state["o"], "intensity": state["v"],
                             "tint": state["h"], "saturation": state["s"]}[bar.kind]
                bar.queue_draw()
            state["busy"] = False
            show_preview()
            show_code()

        def colour_string():
            r, g, b = colorsys.hsv_to_rgb(state["h"], state["s"], state["v"])
            if border:
                return f"rgba({round(r * 255)},{round(g * 255)},{round(b * 255)}," \
                       f"{round(state['o'], 3)})"
            return f"rgb({round(r * 255)},{round(g * 255)},{round(b * 255)})"

        def show_preview():
            src = source()
            for k in ("color", "opacity", "radius", "border_width", "border_color"):
                if k in src:
                    preview.look[k] = src[k]
                else:
                    preview.look.pop(k, None)
            if border:
                preview.look["border_color"] = colour_string()
                preview.look.setdefault("border_width", 2)
            elif tab and base:
                preview.look.update(color=colour_string(), opacity=state["o"])
            else:
                preview.look.update(color=colour_string(), opacity=state["o"])
            preview.queue_draw()

        def give(f, colour, opacity):
            """Put the colour on one cubby entry (or a page's defaults)."""
            if border:
                f["border_color"] = colour
                if not f.get("border_width"):
                    f["border_width"] = 2
            elif tab:
                f["tab_color"], f["tab_opacity"] = colour, opacity
            else:
                f["color"], f["opacity"] = colour, opacity

        def save_later():
            state["save"] = 0
            self.save()
            return False

        def changed(kind, value):
            if state["busy"]:
                return
            key = {"transparency": "o", "intensity": "v", "tint": "h", "saturation": "s"}[kind]
            state[key] = value
            if kind == "transparency":
                state["o"] = max(0.05, value)
            push()

        def push():
            """Give the chosen cubbies the colour now in `state`."""
            for bar in bars.values():
                bar.queue_draw()
            show_preview()
            colour = colour_string()
            fs, pages = targets(combo.get_active_id() or "all")
            for f in fs:
                give(f, colour, state["o"])
                win = self.windows.get(f["id"])
                if win is not None:
                    win.apply_style()
                    win.queue_draw()
            for page in pages:                 # new cubbies on those pages match too
                give(page.setdefault("defaults", {}), colour, state["o"])
            if not state["save"]:
                state["save"] = GLib.timeout_add(400, save_later)
            show_code()
            if on_push is not None:
                on_push()

        def set_rgb(rgb):
            state["h"], state["s"], state["v"] = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
            state["busy"] = True
            for bar in bars.values():
                bar.value = {"transparency": state["o"], "intensity": state["v"],
                             "tint": state["h"], "saturation": state["s"]}[bar.kind]
            state["busy"] = False
            push()

        hsv = lambda: (state["h"], state["s"], state["v"])
        bars = {}
        for r, (kind, label) in enumerate((("transparency", "Transparency:"),
                                            ("intensity", "Colour intensity:"),
                                            ("tint", "Tint:"), ("saturation", "Saturation:"))):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1)
            bar = ColourBar(kind, 0.5, hsv, changed)
            bars[kind] = bar
            grid.attach(bar, 1, r, 1, 1)
        # ---- an exact colour: eyedropper, the wallpaper's own colour, or a typed code
        crow = Gtk.Box(spacing=8)
        crow.set_margin_top(6)
        pick_btn = Gtk.Button()
        pbox = Gtk.Box(spacing=6)
        pbox.pack_start(Gtk.Image.new_from_icon_name(
            next((n for n in ("color-select-symbolic", "gtk-color-picker", "color-picker",
                              "applications-graphics-symbolic")
                  if Gtk.IconTheme.get_default().has_icon(n)), "color-select-symbolic"),
            Gtk.IconSize.BUTTON), False, False, 0)
        pbox.pack_start(Gtk.Label(label="Pick from Screen"), False, False, 0)
        pick_btn.add(pbox)
        pick_btn.set_tooltip_text("Click anywhere on the screen (your wallpaper, a picture, any "
                              "window) to use its colour. Escape cancels.")
        wall = Gtk.Button(label="Wallpaper’s Main Colour")
        wall.set_tooltip_text("Use the colour most of your current wallpaper is made of")
        crow.pack_start(pick_btn, False, False, 0)
        crow.pack_start(wall, False, False, 0)
        crow.pack_start(Gtk.Label(label="Colour code:"), False, False, 6)
        code = Gtk.Entry()
        code.set_width_chars(16)
        code.set_placeholder_text("#1A2B3C")
        code.set_tooltip_text("Type a colour as #1A2B3C, rgb(26, 43, 60) or 26, 43, 60 and "
                              "press Enter")
        crow.pack_start(code, False, False, 0)
        sec.pack_start(crow, False, False, 0)
        code_msg = self.s_note(sec, "")
        code_msg.set_no_show_all(True)

        def show_code():
            if code.has_focus() and state.get("typing"):
                return
            r, g, b = colorsys.hsv_to_rgb(state["h"], state["s"], state["v"])
            code.set_text(hex_code(r * 255 + 0.5, g * 255 + 0.5, b * 255 + 0.5))
            code_msg.hide()

        def code_typed(_e=None, *_a):
            state["typing"] = False
            rgb = parse_colour_code(code.get_text())
            if rgb is None:
                code_msg.set_text("That isn't a colour code Cubbies understands. Try "
                                  "#1A2B3C, rgb(26, 43, 60) or 26, 43, 60.")
                code_msg.show()
                return False
            code_msg.hide()
            set_rgb(rgb)
            return False
        code.connect("activate", code_typed)
        code.connect("changed", lambda _e: state.__setitem__("typing", code.has_focus()))
        code.connect("focus-out-event", lambda *_a: state.get("typing") and code_typed())

        def do_pick(_b):
            """Settings closes for real while picking (so nothing is left in the way) and
            opens again afterwards at this same spot, picked or cancelled."""
            dlg = getattr(self, "_settings_dlg", None)
            key = combo.get_active_id() or "all"
            opacity = state["o"]
            scroller = sec.get_parent()
            while scroller is not None and not isinstance(scroller, Gtk.ScrolledWindow):
                scroller = scroller.get_parent()
            scroll = scroller.get_vadjustment().get_value() if scroller is not None else 0

            def took(rgb):
                colour = ("rgba({},{},{},{})".format(*rgb, round(opacity, 3)) if border
                          else "rgb({},{},{})".format(*rgb))
                fs, pages = targets(key)
                for f in fs:
                    give(f, colour, opacity)
                    win = self.windows.get(f["id"])
                    if win is not None:
                        win.apply_style()
                for page in pages:
                    give(page.setdefault("defaults", {}), colour, opacity)
                self.save()

            def start():                     # get out of the way of what's being picked
                for w in self.windows.values():
                    w.hide()

            def end():
                self.show_page()
                if pick is not None:
                    pick[1]()                   # open that cubby's Styling Options again
                    return
                self._colour_target_pref = key
                GLib.idle_add(lambda: self.open_settings(section="look", scroll=scroll)
                              and False)
            if pick is not None:
                pick[0]()
            elif dlg is not None:
                dlg.response(Gtk.ResponseType.CLOSE)
            GLib.timeout_add(120, lambda: pick_screen_colour(took, start, end) and False)
        pick_btn.connect("clicked", do_pick)

        def do_wall(_b):
            path = None
            bg = self.bg_settings()
            try:
                path = Gio.File.new_for_uri(bg.get_string("picture-uri")).get_path()
            except Exception:
                pass
            rgb = wallpaper_main_colour(path) if path else None
            if rgb is None:
                code_msg.set_text("Couldn't read the wallpaper picture.")
                code_msg.show()
                return
            set_rgb(rgb)
        wall.connect("clicked", do_wall)

        combo.connect("changed", load)
        load()
        show_code()
        n = self.s_note(sec, "Transparency: further right is more solid." + (
            " Choosing a colour while the border width is 0 gives the cubby a 2 px border."
            if border else "" if fixed else " With \u201cEvery cubby\u201d chosen, new "
            "cubbies on those pages get this colour too."))
        n.set_margin_top(12)
        return show_preview

    def group_title(self, group):
        panes = self.group_panes(group)
        return " + ".join(p["title"] for p in panes) or "Tabs"

    def settings_pages(self, page_index=None):
        sw, box = self.s_page("Desktop Pages", "Keep different parts of your life on separate "
                              "pages of the desktop, each with its own cubbies and wallpaper.",
                              self.s_preview("pages", title="General"))
        sec = self.s_section(box, "Using desktop pages")
        self.s_bullets(sec, [
            "<b>Mouse:</b> hold the left or right edge of the screen and pull it inwards, "
            "or turn the mouse wheel over a title bar or the page switcher",
            "<b>Keyboard:</b> the page keys below (Ctrl + Left / Right by default; Ctrl + Up "
            "shows all your pages to pick from)",
            "<b>New page:</b> right-click the page switcher (top centre) › New Page…",
            "<b>Moving a cubby to another page:</b> drag it by its title bar to the left or "
            "right edge of the screen and hold it there",
            "<b>The page switcher</b> appears when the pointer rests at the top centre of the "
            "screen; right-click it for the page menu"])
        sec = self.s_section(box, "Settings")

        def pages_on(on):
            if self.puller:
                self.puller.update()
            self.pager.update()
        self.s_check(sec, "Enabled (more than one page; turn off to keep to the page you're on)",
                     "pages_enabled", pages_on)
        self.s_check(sec, "Lightly bounce after switching pages", "page_bounce")

        def wall_changed(_on):
            self.apply_wallpaper()
        self.s_check(sec, "Change the desktop wallpaper with the page", "page_wallpapers",
                     wall_changed)
        sec = self.s_section(box, "Page bar")
        key_combo = [None]

        def show_changed(mode):
            self.cfg["pager_autohide"] = mode != "always"     # (older setting, kept in step)
            if mode == "key" and self.cfg.get("pager_key", "off") == "off":
                self.cfg["pager_key"] = "ctrl_alt_p"
                if key_combo[0] is not None:
                    key_combo[0].set_active_id("ctrl_alt_p")
            self.save()
            self.pager.flash(1500)
        self.s_combo(sec, "Show the page bar:", "pager_show",
                     (("auto", "When the pointer rests at its screen edge"),
                      ("always", "Always"),
                      ("key", "Only when I press a key")),
                     self.pager.show_mode(), show_changed)
        key_combo[0] = self.s_combo(sec, "Key that shows or hides it:", "pager_key",
                                    (("off", "None"), ("ctrl_alt_p", "Ctrl + Alt + P"),
                                     ("ctrl_super_p", "Ctrl + Super + P")), "off")
        self.s_combo(sec, "Key that opens Manage Pages (in any window):", "manage_key",
                     (("off", "None"), ("ctrl_super_m", "Ctrl + Super + M"),
                      ("ctrl_alt_m", "Ctrl + Alt + M")), "ctrl_super_m")
        self.s_combo(sec, "Where it sits:", "pager_pos",
                     (("top", "Top centre"), ("bottom", "Bottom centre"),
                      ("custom", "Where I drag it")), "top",
                     lambda pos: self.set_pager_pos(pos))
        self.s_note(sec, "Drag the page bar by its name to put it anywhere. Click a dot to go "
                         "to that page (point at one to see its name), and double-click the "
                         "name for Manage Pages. The keys work in every mode, and so "
                         "do the commands  cubbies --page-bar  and  cubbies --manage-pages. If "
                         f"a key does nothing, another program (probably {DESKTOP_NAME}) has "
                         f"it: free it in {SHORTCUTS_SHORT} or pick the other one. A launch bar along "
                         "the same edge: see Settings › Launch Bar Cubbies.")
        sec = self.s_section(box, "Page switching")
        self.s_check(sec, "Switch pages by pulling the edge of the screen with the mouse",
                     "edge_pull", lambda _on: self.puller and self.puller.update())
        self.s_check(sec, "Switch pages with the mouse wheel over a title bar or the page "
                          "switcher", "wheel_pages")
        self.s_check(sec, "Switch pages with a sideways two-finger swipe on a touchpad (over a "
                          "cubby or the page switcher)", "swipe_pages")
        row = Gtk.Box(spacing=8)
        row.pack_start(Gtk.Label(label="Switch pages with these keys:"), False, False, 0)
        combo = Gtk.ComboBoxText()
        for ident, label in HOTKEY_CHOICES:
            combo.append(ident, label)
        combo.set_active_id(self.cfg.get("hotkeys", "ctrl"))
        row.pack_start(combo, False, False, 0)
        sec.pack_start(row, False, False, 0)
        msg = self.s_note(sec, "")
        newpage = self.s_check(sec, "Pressing a page key twice at the last page makes a new "
                                    "page", "newpage_keys")
        newpage.set_sensitive(combo.get_active_id() != "off")

        def keys_changed(_c):
            mode = combo.get_active_id() or "off"
            ok, message = self.apply_hotkeys(mode)
            if ok:
                self.cfg["hotkeys"] = mode
                self.save()
            msg.set_text(message)
            newpage.set_sensitive(mode != "off")
        combo.connect("changed", keys_changed)
        self.s_combo(sec, "The page keys work:", "page_keys_where",
                     (("desktop", "Only while the desktop is in front"),
                      ("everywhere", "In every program")), "desktop",
                     lambda _v: self.keys and self.keys.sync_page_keys())
        self.s_note(sec, "\u201cOnly while the desktop is in front\u201d leaves these keys to "
                         "the program you're using (Ctrl + Left / Right jump by word in text, "
                         "for example). Click the empty desktop first, then use them. Keys "
                         f"{DESKTOP_NAME} or another program already uses can't be taken at all; "
                         "Cubbies says so here. Ctrl + Up (or Super + Ctrl + Up) shows every "
                         "page to choose from.")

        sec = self.s_section(box, "Additional settings")
        self.s_check(sec, "Animate the page switching (keys, mouse wheel and page switcher too)",
                     "animate_pages")
        self.s_check(sec, "If hidden, show my cubbies again when switching pages",
                     "unhide_on_switch")

        sec = self.s_section(box, "Your pages")
        self.s_note(sec, "Each page's background and the starting look for new cubbies on it "
                         "are in Manage Pages: click a page, then its gear. (Manage Pages is "
                         "on the page bar menu, or Ctrl + Super + M.)")
        btns = Gtk.Box(spacing=8)
        btns.set_margin_top(4)
        here = Gtk.Button(label="Settings for This Page\u2026")
        here.connect("clicked", lambda _b: (
            self._settings_dlg and self._settings_dlg.response(Gtk.ResponseType.CLOSE),
            GLib.timeout_add(200, lambda: self.open_page_settings(
                self.cfg["pages"][page_index] if page_index is not None
                and 0 <= page_index < len(self.cfg["pages"]) else None) and False)))
        allp = Gtk.Button(label="Manage Pages\u2026")
        allp.connect("clicked", lambda _b: (
            self._settings_dlg and self._settings_dlg.response(Gtk.ResponseType.CLOSE),
            GLib.timeout_add(200, lambda: self.open_page_order() and False)))
        btns.pack_start(here, False, False, 0)
        btns.pack_start(allp, False, False, 0)
        sec.pack_start(btns, False, False, 0)
        return sw

    def settings_folders(self):
        sw, box = self.s_page("Folder Cubbies", "Show the contents of any folder right on the "
                              "desktop, always up to date.",
                              self.s_preview("folder", title="Dropbox"))
        sec = self.s_section(box, "Making a Folder Cubby")
        self.s_bullets(sec, [
            "Drag on the empty desktop to draw a box, then choose <b>Create Folder Cubby Here</b>",
            "Right-click a folder in the file manager › <b>Show as a Folder Cubby on the "
            "Desktop</b>",
            "Drop a folder onto any cubby's title bar",
            "Right-click a cubby › <b>Cubby Type</b> › <b>Folder Cubby…</b>",
            "Right-click the page switcher › <b>New Folder Cubby…</b>"])
        sec = self.s_section(box, "Settings")
        self.s_check(sec, "Double-clicking a folder inside a Folder Cubby opens it right there "
                          "(\u2191 in the title bar goes back up)", "folder_navigate")
        self.s_check(sec, "Show the folder icon in Folder Cubby title bars", "folder_title_icon",
                     lambda _on: [w.update_title() for w in self.windows.values()])
        self.s_note(sec, "Right-click a folder \u203a Open (or turn this off) to open it in the "
                         "file manager instead.")
        self.s_check(sec, "Rest the pointer on a folder to see what's inside it", "folder_preview")
        self.s_check(sec, "Pressing F5 on the desktop refreshes the cubbies too", "f5_refresh")
        self.s_note(sec, "Folders on network shares can't tell Cubbies when they change, so "
                         "Cubbies looks at them every few seconds. Their files can't go to the "
                         "Trash: deleting them deletes them for good (Cubbies asks first).")
        sec = self.s_section(box, "Using a Folder Cubby")
        self.s_bullets(sec, [
            "Open the real folder: double-click empty space in it, Ctrl + double-click its "
            "title bar, or right-click › <b>Open Folder</b>",
            "Files dropped or pasted into it go into the real folder",
            "Deleting a Folder Cubby only removes the view: the folder and its files stay",
            "Change the view (Icons, List, Details) and the order with the ☰ button or the "
            "right-click menu; Ctrl + mouse wheel changes the icon size"])
        return sw

    def settings_tabs(self):
        sw, box = self.s_page("Tabbed Cubbies", "Stack several cubbies in one place and switch "
                              "between them with tabs in the title bar.",
                              self.s_preview("tabs"))
        sec = self.s_section(box, "Making tabs")
        self.s_bullets(sec, [
            "Drag a cubby by its title bar onto another cubby's title bar. When that title bar "
            "lights up, let go: the two become tabs of one cubby",
            "Drop more cubbies on it to add more tabs; a whole tabbed cubby can be dropped "
            "onto another too",
            "Folder Cubbies and Inbox Cubbies can be tabs as well (their tab shows their icon)"])
        sec = self.s_section(box, "Tab design")
        row = Gtk.Box(spacing=18)
        sec.pack_start(row, False, False, 0)
        current = self.cfg.get("tab_style", "rounded")
        group = None

        def style_changed(btn, style):
            if btn.get_active():
                self.cfg["tab_style"] = style
                self.save()
                for win in self.windows.values():
                    win.update_title()

        for style, label in (("rounded", "Rounded"), ("segmented", "Segmented"),
                             ("flat", "Flat"), ("menu", "Menu only")):
            colw = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            pic = self.s_preview("tabstyle-" + style)
            pic.set_size_request(170, 80)
            colw.pack_start(pic, False, False, 0)
            rb = Gtk.RadioButton.new_with_label_from_widget(group, label)
            group = group or rb
            rb.set_active(style == current)
            rb.set_halign(Gtk.Align.CENTER)
            rb.connect("toggled", style_changed, style)
            colw.pack_start(rb, False, False, 0)
            row.pack_start(colw, False, False, 0)
        self.s_note(sec, "Rounded: the shown tab is darker. Segmented: the shown tab takes the "
                         "cubby's colour. Flat: only the lettering changes. Menu only: just the "
                         "shown tab's name with a \u25be; click it (or use the \u2630 button or "
                         "the right-click menu \u203a Show Tab) to choose another.")

        sec = self.s_section(box, "Tab widths")

        def tabs_redo(*_a):
            self.save()
            for win in self.windows.values():
                if win.data.get("group"):
                    win.update_title()
                    win.queue_resize()
        self.s_check(sec, "Stretch the tabs to fill the title bar (all the same width when "
                          "there's room)", "tab_fill", tabs_redo)
        self.s_combo(sec, "When a cubby is too narrow for every tab name:", "tab_fit",
                     (("keep", "Don't let it get that narrow (names always in full)"),
                      ("scroll", "Scroll the tabs with \u2039 \u203a arrows"),
                      ("shorten", "Shorten the names (\u2026)")), "keep", tabs_redo)
        self.s_note(sec, "With the first choice, adding a tab can make the cubby a little "
                         "wider so every name still fits.")

        sec = self.s_section(box, "Dragging a tab")
        self.s_combo(sec, "A drag on a tab:", "tab_drag",
                     (("cubby", "Moves the whole cubby (Ctrl + drag moves the tab)"),
                      ("tab", "Moves the tab (Ctrl + drag moves the cubby)")), "cubby")
        self.s_note(sec, "Moving the tab: slide it along the row to change the order, or pull "
                         "it away to make it a cubby of its own. A click just shows the tab.")

        sec = self.s_section(box, "Using tabs")
        self.s_bullets(sec, [
            "Click a tab to show that cubby. With the pointer on a tab, its own \u2630 (sort and "
            "view) and \u2715 (delete that tab) appear",
            "Right-click \u203a <b>Delete All Tabs\u2026</b> deletes the whole tabbed cubby",
            "Drag a tab to move the whole tabbed cubby",
            "<b>Ctrl</b> + drag a tab sideways along the title bar to change the order",
            "<b>Ctrl</b> + drag a tab away from the cubby and let go to make it its own cubby "
            "again",
            "Right-click a tab for <b>Rename Tab</b>, <b>Move Tab Out to Its Own Cubby</b>, "
            "<b>Delete Tab</b> and <b>Tab Colour\u2026</b> (each tab can have its own colour; "
            "the cubby takes it while that tab is shown)",
            "When only one tab is left, it turns back into an ordinary cubby"])
        return sw

    def settings_rollup(self):
        sw, box = self.s_page("Roll-up Cubbies", "Fold a cubby up into its title bar to keep "
                              "its icons tucked away.", self.s_preview("rollup"))
        sec = self.s_section(box, "Using roll-up cubbies")
        self.s_bullets(sec, ["Double-click a cubby's title bar to roll it up, and again to open "
                             "it",
                             "Or move it against the top or bottom edge of the screen to dock "
                             "it there rolled up (turn that on below)",
                             "Rest the pointer on a rolled-up cubby to look inside",
                             "A cubby whose title bar is at the bottom rolls down instead"])
        sec = self.s_section(box, "Settings")
        self.s_check(sec, "Enabled", "rollup_enabled", self.set_rollup_enabled)
        self.s_check(sec, "Double-click a title bar to roll the cubby up", "dblclick_roll")
        self.s_check(sec, "Roll up cubbies placed against the top or bottom edge of the screen "
                          "(they open while the pointer is over them)", "edge_rollup")
        row = Gtk.Box(spacing=16)
        row.pack_start(Gtk.Label(label="Open a rolled-up cubby for a look:"), False, False, 0)
        group = None
        current = self.rollup_open()
        for mode, label in (("hover", "When the pointer rests on it"),
                            ("click", "When I click its title bar"), ("never", "Never")):
            rb = Gtk.RadioButton.new_with_label_from_widget(group, label)
            group = group or rb
            rb.set_active(mode == current)
            rb.connect("toggled", lambda b, m=mode: b.get_active() and (
                self.cfg.__setitem__("rollup_open", m), self.save()))
            row.pack_start(rb, False, False, 0)
        sec.pack_start(row, False, False, 0)
        return sw

    def settings_hide(self):
        sw, box = self.s_page("Quick-hide", "Hide and show all your cubbies by double-clicking "
                              "empty space on the desktop.", self.s_preview("hide"))
        sec = self.s_section(box, "Using quick-hide")
        self.s_bullets(sec, ["Double-click empty desktop space to hide every cubby, and again "
                             "to bring them back",
                             "Or use Settings › Home › <b>Hide or show all cubbies now</b>, or "
                             "the command <tt>cubbies --toggle</tt> (for a keyboard shortcut)"])
        sec = self.s_section(box, "Settings")
        self.s_check(sec, "Double-click the empty desktop to hide or show cubbies",
                     "desktop_dblclick",
                     lambda on: setattr(self.watcher, "enabled", bool(on)))
        sec = self.s_section(box, "Additional options")
        self.s_check(sec, "Always show cubbies when Cubbies starts", "show_on_start")
        self.s_check(sec, "Also hide the desktop's own icons (the ones not in cubbies)",
                     "hide_desktop_icons")
        self.s_note(sec, "While they are hidden, the desktop's right-click menu is hidden too. "
                         "Your setting is put back when the cubbies come back (and if Cubbies "
                         "is closed).")
        self.s_note(sec, "To keep a cubby on screen while the others hide: right-click it "
                         "\u203a Options \u203a Stay Visible When Cubbies Are Hidden.")
        return sw

    def settings_peek(self):
        sw, box = self.s_page("Glance", "See what's in your cubbies without moving your "
                              "windows: a panel opens over them with every cubby's icons.",
                              self.s_preview("cubby"))
        sec = self.s_section(box, "Using Glance")
        self.s_bullets(sec, [
            "Press the Glance key: a panel opens over your windows with a tab for each page, "
            "showing each page's cubbies",
            "Click an icon to open it, or drag it straight into an app",
            "Drag an icon onto another cubby's group to move it there; hold it over a page's "
            "tab to open that page first",
            "Type to find an icon on any page; arrow keys move, Enter opens",
            "Click a group's heading to fold it away (remembered)",
            "Drag the panel by its top to move it, and its \u25e2 corner to resize it",
            "Press the key again, press Escape, or click anywhere else to close it",
            "Also the command <tt>cubbies --glance</tt> (for your own shortcut)"])
        self.s_note(sec, "Your cubbies stay where they are on the desktop the whole time.")
        sec = self.s_section(box, "Settings")
        row = Gtk.Box(spacing=8)
        row.pack_start(Gtk.Label(label="Glance key:"), False, False, 0)
        combo = Gtk.ComboBoxText()
        for ident, label in (("super_space", "Super + Space"),
                             ("ctrl_super_space", "Ctrl + Super + Space"),
                             ("ctrl_alt_space", "Ctrl + Alt + Space"), ("off", "None")):
            combo.append(ident, label)
        combo.set_active_id(self.cfg.get("peek_key", "super_space"))
        row.pack_start(combo, False, False, 0)
        sec.pack_start(row, False, False, 0)
        msg = self.s_note(sec, "")

        def changed(_c):
            mode = combo.get_active_id() or "off"
            if self.keys is None:
                msg.set_text("System-wide keys are unavailable (they need an X11 session).")
                return
            ok, message = self.keys.set_peek_key(mode)
            if ok:
                self.cfg["peek_key"] = mode
                self.save()
            msg.set_text(message)
        combo.connect("changed", changed)
        sec = self.s_section(box, "In the panel")
        self.s_check(sec, "Show a Favourites row: the icons you open most, at the top",
                     "glance_favourites")
        clear = Gtk.Button(label="Forget My Favourites")
        clear.set_halign(Gtk.Align.START)
        clear.set_margin_start(26)

        def forget(_b):
            self.cfg.pop("open_counts", None)
            self.save()
        clear.connect("clicked", forget)
        sec.pack_start(clear, False, False, 0)
        self.s_check(sec, "Open folders inside Glance (instead of in the file manager)",
                     "glance_browse")
        self.s_note(sec, "Click a folder to look inside it right there; Back (or Backspace, "
                         "or Escape) goes up again.")
        sec = self.s_section(box, "Opening it")
        self.s_combo(sec, "Also open it by pushing the pointer into a corner:", "glance_corner",
                     (("off", "No"), ("top-left", "Top left"), ("top-right", "Top right"),
                      ("bottom-left", "Bottom left"), ("bottom-right", "Bottom right")), "off")
        if IS_MATE or IS_XFCE:
            self.s_note(sec, f"Pick a corner your panels don't use (many {DESKTOP_NAME} layouts "
                             "keep a button in one), or both will happen at once.")
        else:
            self.s_note(sec, "Pick a corner Cinnamon doesn't use itself (System Settings "
                             "\u203a Hot Corners), or both will happen at once.")
        self.s_combo(sec, "Where it opens:", "glance_place",
                     (("centre", "In the middle of the screen"),
                      ("pointer", "Where the pointer is")), "centre")
        reset = Gtk.Button(label="Reset Its Size")
        reset.set_halign(Gtk.Align.START)
        reset.set_tooltip_text("Drag the \u25e2 corner of the panel to give it a size; this "
                               "goes back to fitting its contents")

        def reset_size(_b):
            self.cfg.pop("glance_w", None)
            self.cfg.pop("glance_h", None)
            self.save()
        reset.connect("clicked", reset_size)
        sec.pack_start(reset, False, False, 0)
        return sw
