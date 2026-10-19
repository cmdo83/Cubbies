"""Manage Pages: every page side by side, to reorder, lock and set up."""

import os

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk

from .core import dbg
from .glance import cairo_filter_good
from .wallpapers import PAGE_BG, make_thumbnail, thumb_pool
from .widgets import calm_scroll


PAGE_MANAGE_CSS = b"""
.pm-panel { background-color: transparent; }
.pm-panel label { color: white; }
.pm-question { font-size: 125%; font-weight: bold; }
.pm-note { color: rgba(255, 255, 255, 0.72); }
.pm-panel button { color: white; background-image: none; background-color: rgba(255, 255, 255, 0.12);
    border: 1px solid rgba(255, 255, 255, 0.22); border-radius: 8px; padding: 6px 18px;
    box-shadow: none; text-shadow: none; -gtk-icon-shadow: none; }
.pm-panel button label { color: white; }
.pm-panel button:hover { background-color: rgba(255, 255, 255, 0.24); }
.pm-panel button.pm-danger { background-color: rgba(200, 50, 50, 0.55);
    border-color: rgba(255, 120, 120, 0.55); }
.pm-panel button.pm-danger:hover { background-color: rgba(220, 60, 60, 0.85); }
.pm-panel button.pm-main { background-color: rgba(53, 132, 228, 0.70);
    border-color: rgba(120, 180, 255, 0.6); }
.pm-panel button.pm-main:hover { background-color: rgba(53, 132, 228, 0.95); }
.pm-panel button:disabled { opacity: 0.4; }
.pm-settings { background-color: @theme_base_color; border-radius: 12px;
    border: 1px solid alpha(@theme_fg_color, 0.22); }
.pm-settings-head { background-color: @theme_bg_color; border-radius: 11px 11px 0 0;
    border-bottom: 1px solid alpha(@theme_fg_color, 0.12); padding: 10px 12px; }
.pm-settings-foot { background-color: @theme_bg_color; border-radius: 0 0 11px 11px;
    border-top: 1px solid alpha(@theme_fg_color, 0.12); padding: 8px 12px; }
.pm-settings scrolledwindow, .pm-settings viewport, .pm-settings stack {
    background-color: transparent; border: none; box-shadow: none; }
.pm-panel entry { background-color: rgba(255, 255, 255, 0.12); color: white;
    border: 1px solid rgba(255, 255, 255, 0.35); border-radius: 8px; padding: 6px 10px;
    caret-color: white; box-shadow: none; }
"""


class PageOrder(Gtk.Window):
    """A see-through layer over the whole screen with the pages as small pictures across the
    middle (their wallpaper and cubbies). Two uses:
    - "order" (page bar menu › Manage Pages…): hovering a page lifts it a little; a click
      brings it to the middle, bigger, with Rename, Delete and Go to Page under it. Dragging
      a page moves it (the page order).
    - "pick" (Ctrl + Up): choose a page: click it, press its number, or use the arrow keys
      and Enter.
    Pictures shrink as pages are added, down to MIN_W wide, then wrap onto more rows, so
    every page is always in sight. Escape or a click outside the pages closes it (in Manage
    Pages, with a page brought forward, it goes back to all the pages first)."""
    MAX_H = 230          # a picture's height when there's room
    MIN_W = 200          # narrower than this: another row instead
    GAP = 26
    ROW_GAP = 58         # room for the names under a row
    HOVER_GROW = 1.07    # Manage Pages: how much the page under the pointer grows
    DIM = 0.62           # the shade over the desktop
    DIM_FOCUS = 0.88     # … and with a page brought forward

    def __init__(self, app, mode="order"):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.app, self.mode = app, mode
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        self.set_app_paintable(True)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        display = Gdk.Display.get_default()
        _s, px, py = display.get_default_seat().get_pointer().get_position()
        g = display.get_monitor_at_point(px, py).get_geometry()
        self.mon = g
        self.move(g.x, g.y)
        self.set_default_size(g.width, g.height)
        self.order = list(app.cfg["pages"])          # page dicts, as shown
        self.pos = {}                                # id(page) -> [x, y] drawn (animated)
        self.thumbs = {}
        self.big = {}                                # id(page) -> a sharper picture (focus)
        self.grow = {}                               # id(page) -> drawn size (1 = normal)
        self.focus = None                            # Manage Pages: the page brought forward
        self.focus_t = 0.0                           # 0 = in its place … 1 = in the middle
        self._focus_in = False                       # on its way to the middle (or back)
        self.lock_hover = None                       # "page", "gear", a cubby, or None
        self.settings_on = False                     # the gear: page settings beside it
        self.settings_t = 0.0                        # 0 = big picture … 1 = settings shown
        self.settings_card = None
        self.settings_tab = 0
        self.pointer = (0, 0)
        self.panel_mode = None
        self.drag = None
        self.anim = 0
        self.hover = None
        self._cursor = None
        self.sel = min(max(app.cfg["page"], 0), len(self.order) - 1)   # keyboard choice
        self.area = Gtk.DrawingArea()
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                             | Gdk.EventMask.POINTER_MOTION_MASK
                             | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.area.connect("draw", self.on_draw)
        self.area.connect("button-press-event", self.on_press)
        self.area.connect("motion-notify-event", self.on_motion)
        self.area.connect("button-release-event", self.on_release)
        self.area.connect("leave-notify-event", self.on_leave)
        overlay = Gtk.Overlay()
        overlay.add(self.area)
        self.panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.panel.get_style_context().add_class("pm-panel")
        self.panel.set_halign(Gtk.Align.CENTER)
        self.panel.set_valign(Gtk.Align.START)
        self.panel.set_no_show_all(True)
        overlay.add_overlay(self.panel)
        self.overlay = overlay
        self.add(overlay)
        try:
            css = Gtk.CssProvider()
            css.load_from_data(PAGE_MANAGE_CSS)
            Gtk.StyleContext.add_provider_for_screen(
                self.get_screen(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        except Exception as exc:
            dbg("manage pages css:", exc)
        self.connect("key-press-event", self.on_key)
        self._had_focus = False             # (it may lose focus before it ever had it)
        self.connect("focus-in-event", lambda *_a: setattr(self, "_had_focus", True) or False)
        self.connect("focus-out-event", lambda *_a: self._had_focus and GLib.timeout_add(
            250, self.focus_gone) and False)
        self.layout()
        for i, page in enumerate(self.order):
            self.pos[id(page)] = list(self.slot_xy(i))
        self.load_thumbs()
        self.show_all()
        self.resize(g.width, g.height)
        self.kb_grab = None
        self.take_keys()
        GLib.timeout_add(80, lambda: self.take_keys() and False)

    def take_keys(self):
        """Opened by a key Cubbies caught for itself, so the window manager won't hand this
        window the focus on its own (keys would go to the desktop behind it). Ask with the X
        server's own time, and hold the keyboard while it's open, as Expo does."""
        if getattr(self, "_closed", False):
            return False
        gw = self.get_window()
        if gw is None:
            return False
        try:
            from gi.repository import GdkX11
            t = GdkX11.x11_get_server_time(gw)
            self.present_with_time(t)
            gw.focus(t)
        except Exception:
            self.present()
        if self.kb_grab is None:
            try:
                seat = Gdk.Display.get_default().get_default_seat()
                if seat.grab(gw, Gdk.SeatCapabilities.KEYBOARD, True, None, None, None,
                             None) == Gdk.GrabStatus.SUCCESS:
                    self.kb_grab = seat
            except Exception as exc:
                dbg("page chooser: no keyboard grab:", repr(exc))
        return False

    # -- geometry
    def layout(self):
        import math
        W, H = self.mon.width, self.mon.height
        ratio = W / max(1, H)
        n = max(1, len(self.order))
        room_w = W - 120
        rows = 1
        while True:
            cols = math.ceil(n / rows)
            cw = min(self.MAX_H * ratio, (room_w - (cols - 1) * self.GAP) / cols)
            if cw >= self.MIN_W or cols == 1:
                break
            rows += 1
        ch = cw / ratio
        room_h = H - 220                             # titles above, hint below
        need = rows * ch + (rows - 1) * self.ROW_GAP
        if need > room_h:                            # lots of pages: smaller still
            k = room_h / need
            cw, ch = cw * k, ch * k
        self.cw, self.ch, self.cols, self.rows = cw, ch, cols, rows
        total_h = rows * ch + (rows - 1) * self.ROW_GAP
        self.y0 = (H - total_h) / 2 + 20

    def slot_xy(self, i):
        n = len(self.order)
        row, col = divmod(i, self.cols)
        k = self.cols if row < self.rows - 1 else n - row * self.cols   # pages on this row
        x0 = (self.mon.width - (k * self.cw + (k - 1) * self.GAP)) / 2
        return x0 + col * (self.cw + self.GAP), self.y0 + row * (self.ch + self.ROW_GAP)

    def nearest_slot(self, x, y):
        cx, cy = x + self.cw / 2, y + self.ch / 2
        best, bd = 0, None
        for i in range(len(self.order)):
            sx, sy = self.slot_xy(i)
            d = (sx + self.cw / 2 - cx) ** 2 + (sy + self.ch / 2 - cy) ** 2
            if bd is None or d < bd:
                best, bd = i, d
        return best

    def card_at(self, x, y):
        for page in self.order:
            px, py = self.pos[id(page)]
            if px <= x <= px + self.cw and py <= y <= py + self.ch + 30:
                return page
        return None

    def cubby_rects(self, page, x, y, w, h):
        """(cubby, x, y, w, h) of each cubby as drawn in a page picture at x, y, w, h."""
        sx, sy = w / self.mon.width, h / self.mon.height
        out = []
        for f, fx0, fy0 in self.cubbies_on(page):
            out.append((f, x + (fx0 - self.mon.x) * sx, y + (fy0 - self.mon.y) * sy,
                        max(4, f.get("w", 300) * sx),
                        max(3, (30 if f.get("rolled") else f.get("h", 200)) * sy)))
        return out

    # -- locking, from a page brought forward
    def page_cubbies(self, page):
        return [f for f, _x, _y in self.cubbies_on(page)]

    def page_locked(self, page):
        fs = self.page_cubbies(page)
        return bool(fs) and all(self.app.is_locked(f) for f in fs)

    def lock_button_rect(self):
        """The page's padlock: top right, just above the big picture."""
        fx, fy, fw, _fh = self.card_rect(self.focus)
        s = 32
        return fx + fw - s, fy - s - 6, s, s

    def gear_button_rect(self):
        """The page's settings gear, just left of the padlock."""
        bx, by, bw, bh = self.lock_button_rect()
        return bx - bw - 8, by, bw, bh

    SETTINGS_GAP = 36
    SETTINGS_EDGE = 20       # kept clear at the screen's sides
    CARD_W_GUESS = 790       # the settings' own width, until it has been measured

    def settings_layout(self):
        """With the gear on: (picture x, y, w, h) at half size on the left, and the settings
        card (x, y, w, h) on its right, the two centred together. The card is as wide as
        its settings need; on a narrow screen the picture gives way (down to 35 %), and if
        even that isn't enough the card keeps to the screen's right edge."""
        W, H = self.mon.width, self.mon.height
        _fx, _fy, fw, fh = self.focus_rect()
        ratio = fw / max(1, fh)
        need = getattr(self.app, "_page_card_w", None) or self.CARD_W_GUESS
        edge, gap = self.SETTINGS_EDGE, self.SETTINGS_GAP
        cw = min(max(need, W * 0.40), W - 2 * edge)
        ch = min(H - 120, max(420, H * 0.74))
        if W - 2 * edge - gap - cw < fw * 0.5:      # narrow screen: closer together
            edge, gap = 10, 18
        room = W - 2 * edge - gap - cw
        pw = max(fw * 0.30, min(fw * 0.5, room))
        ph = pw / ratio
        total = pw + gap + cw
        x0 = max(edge, (W - total) / 2)
        cx = min(x0 + pw + gap, W - edge - cw)
        return ((x0, (H - ph) / 2, pw, ph), (cx, (H - ch) / 2, cw, ch))

    def set_locks(self, cubbies, on):
        for f in cubbies:
            if bool(f.get("locked")) != on:
                self.app.set_flag(f, "locked", on)

    def lock_tip(self, target):
        page = self.focus
        name = (page.get("name") or "this page") if page else "this page"
        if target == "gear":
            return ("Back to the page" if self.settings_on
                    else f"Settings for {name}: background and cubby defaults")
        if self.app.cfg.get("lock_all"):
            return "All cubbies are locked (Settings \u203a Layout & Snapping)"
        if target == "page":
            return (f"Unlock all cubbies on {name}" if self.page_locked(page)
                    else f"Lock all cubbies on {name}")
        title = target.get("title") or "this cubby"
        return f"Unlock {title}" if target.get("locked") else f"Lock {title}"

    def lock_target_at(self, x, y):
        """In a page brought forward: "page" (its padlock), a cubby, or None."""
        if self.focus is None or self.focus_t < 1:
            return None
        if 0 < self.settings_t < 1:
            return None
        gx, gy, gw, gh = self.gear_button_rect()
        if gx - 4 <= x <= gx + gw + 4 and gy - 4 <= y <= gy + gh + 4:
            return "gear"
        bx, by, bw, bh = self.lock_button_rect()
        if bx - 4 <= x <= bx + bw + 4 and by - 4 <= y <= by + bh + 4:
            return "page" if self.page_cubbies(self.focus) else None
        fx, fy, fw, fh = self.card_rect(self.focus)
        if not (fx <= x <= fx + fw and fy <= y <= fy + fh):
            return None
        for f, cx, cy, cw, ch in reversed(self.cubby_rects(self.focus, fx, fy, fw, fh)):
            if cx <= x <= cx + cw and cy <= y <= cy + ch:
                return f
        return None

    def toggle_lock(self, target):
        if target == "gear":
            self.set_settings(not self.settings_on)
            return
        if self.app.cfg.get("lock_all"):
            return                                   # everything's locked anyway
        if target == "page":
            self.set_locks(self.page_cubbies(self.focus), not self.page_locked(self.focus))
        elif target is not None:
            self.set_locks([target], not target.get("locked"))
        self.area.queue_draw()

    def focus_rect(self):
        """Where a page brought forward sits: big, in the middle, a little above centre so
        its buttons fit under it."""
        W, H = self.mon.width, self.mon.height
        ratio = W / max(1, H)
        w = min(W * 0.56, H * 0.56 * ratio)
        h = w / ratio
        return (W - w) / 2, (H - h) / 2 - 60, w, h

    def card_rect(self, page):
        """The rectangle a page is drawn in now: its place, grown when hovered, and on its
        way to the middle when brought forward."""
        x, y = self.pos[id(page)]
        w, h = self.cw, self.ch
        k = self.grow.get(id(page), 1.0)
        if k != 1.0:
            x, y, w, h = x - w * (k - 1) / 2, y - h * (k - 1) / 2, w * k, h * k
        if page is self.focus and self.focus_t > 0:
            t = self.focus_t
            t = 1 - (1 - t) ** 3                     # ease out
            fx, fy, fw, fh = self.focus_rect()
            x, y = x + (fx - x) * t, y + (fy - y) * t
            w, h = w + (fw - w) * t, h + (fh - h) * t
            if self.settings_t > 0:                  # the gear: half size, to the left
                s = self.settings_t
                s = s * s * (3 - 2 * s)              # ease in and out
                (sx, sy, sw, sh), _card = self.settings_layout()
                x, y = x + (sx - x) * s, y + (sy - y) * s
                w, h = w + (sw - w) * s, h + (sh - h) * s
        return x, y, w, h

    # -- pictures
    def page_bg_value(self, page, key):
        """A page's own background setting (PAGE_BG key), else the desktop's from before
        Cubbies, else the desktop's now."""
        gkey = dict(PAGE_BG)[key]
        v = page.get(key) or (self.app.cfg.get("base_bg") or {}).get(gkey)
        if not v:
            bg = self.app.bg_settings()
            try:
                v = bg.get_string(gkey) if bg is not None else None
            except Exception:
                v = None
        return v

    def bg_colours(self, page):
        return (self.page_bg_value(page, "wallpaper_shading") or "solid",
                self.page_bg_value(page, "wallpaper_color1") or "#000000",
                self.page_bg_value(page, "wallpaper_color2") or "#000000")

    def paint_bg_colour(self, cr, page, x, y, w, h):
        """The page's background colour (solid or gradient), as its desktop shows it."""
        shade, c1, c2 = self.bg_colours(page)

        def rgb(code):
            c = Gdk.RGBA()
            if not c.parse(code):
                c.parse("#000000")
            return c.red, c.green, c.blue
        import cairo
        if shade in ("horizontal", "vertical"):
            grad = cairo.LinearGradient(x, y, x + w if shade == "horizontal" else x,
                                        y + h if shade == "vertical" else y)
            grad.add_color_stop_rgb(0, *rgb(c1))
            grad.add_color_stop_rgb(1, *rgb(c2))
            cr.set_source(grad)
        else:
            cr.set_source_rgb(*rgb(c1))
        cr.paint()

    def wallpaper_of(self, page):
        if self.page_bg_value(page, "wallpaper_aspect") == "none":
            return None                  # "No picture": only the colour shows
        wp = page.get("wallpaper")
        if wp and os.path.exists(wp):
            return wp
        uri = self.app.cfg.get("base_wallpaper")
        bg = self.app.bg_settings()
        if not uri and bg is not None:
            uri = bg.get_string("picture-uri")
        try:
            path = Gio.File.new_for_uri(uri).get_path() if uri else None
        except Exception:
            path = None
        return path if path and os.path.exists(path) else None

    def load_thumbs(self):
        for page in self.order:
            path = self.wallpaper_of(page)
            if not path:
                continue

            def work(page=page, path=path):
                pb = make_thumbnail(path, 256)
                GLib.idle_add(lambda: (self.thumbs.__setitem__(id(page), pb),
                                       self.area.queue_draw(), False)[-1])
            thumb_pool().submit(work)

    def load_big(self, page):
        """A sharper picture for a page brought forward (the small one stays till it's in)."""
        if id(page) in self.big:
            return
        path = self.wallpaper_of(page)
        if not path:
            return
        self.big[id(page)] = None
        size = int(max(self.focus_rect()[2], 512))

        def work():
            pb = None
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, size, size, True)
            except Exception:
                pb = make_thumbnail(path, 1024)
            GLib.idle_add(lambda: (self.big.__setitem__(id(page), pb),
                                   self.area.queue_draw(), False)[-1])
        thumb_pool().submit(work)

    def cubbies_on(self, page):
        """(cubby, x, y) for what shows on a page: its own cubbies and every-page ones (each
        where it is on that page)."""
        out = []
        for p in self.app.cfg["pages"]:
            for f in p["cubbies"]:
                if f.get("tab_of") or f.get("launchbar"):
                    continue
                if f.get("all_pages"):
                    out.append((f,) + tuple(self.app.position_on_page(f, page)))
                elif p is page:
                    out.append((f, f.get("x", 0), f.get("y", 0)))
        return out

    # -- drawing
    def on_draw(self, _w, cr):
        import math
        W, H = self.get_allocated_width(), self.get_allocated_height()
        ft = self.focus_t if self.focus is not None else 0.0
        cr.set_source_rgba(0.02, 0.03, 0.06, self.DIM)
        cr.paint()

        def text(s, x, y, size, alpha=0.95, bold=False, centre=True):
            cr.select_font_face("Sans", 0, 1 if bold else 0)
            cr.set_font_size(size)
            e = cr.text_extents(s)
            cr.move_to(x - (e.width / 2 + e.x_bearing if centre else 0), y)
            cr.set_source_rgba(1, 1, 1, alpha)
            cr.show_text(s)

        def rounded(x, y, w, h, r):
            r = max(0, min(r, w / 2, h / 2))
            cr.new_sub_path()
            cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
            cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
            cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
            cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
            cr.close_path()

        def gear(cx, cy, s, alpha=0.95, teeth=8):
            """A cog about s px across, centred on cx, cy."""
            ro, ri, rh = s * 0.5, s * 0.36, s * 0.15
            cr.save()
            cr.new_path()
            n = teeth * 4
            for k in range(n + 1):
                a = 2 * math.pi * k / n - math.pi / 2
                r = ro if (k % 4) in (1, 2) else ri
                (cr.line_to if k else cr.move_to)(cx + r * math.cos(a), cy + r * math.sin(a))
            cr.close_path()
            cr.new_sub_path()
            cr.arc_negative(cx, cy, rh, 2 * math.pi, 0)     # the hole
            cr.set_fill_rule(1)                              # even-odd: the hole stays open
            cr.set_source_rgba(0, 0, 0, 0.45 * alpha)
            cr.set_line_width(1.5)
            cr.stroke_preserve()
            cr.set_source_rgba(1, 1, 1, alpha)
            cr.fill()
            cr.restore()

        def padlock(cx, cy, s, opened, alpha=0.95):
            """A padlock about s px tall, centred on cx, cy: closed, or open (shackle up
            and swung out on its right leg)."""
            bw, bh = s * 0.78, s * 0.56                  # the body
            bx, by = cx - bw / 2, cy - s / 2 + s * 0.44
            sw = bw * 0.62                               # the shackle
            lw = max(1.5, s * 0.12)
            lift = s * 0.16 if opened else 0
            sx0 = cx - sw / 2 + (bw * 0.18 if opened else 0)
            top = by - s * 0.30 - lift
            cr.save()
            cr.set_line_cap(1)                           # round ends
            cr.set_line_width(lw)
            cr.new_path()
            cr.move_to(sx0, by + (-lift if opened else 0.5))
            cr.line_to(sx0, top + sw / 2)
            cr.arc(sx0 + sw / 2, top + sw / 2, sw / 2, math.pi, 2 * math.pi)
            cr.line_to(sx0 + sw, by + (-lift if opened else 0.5))
            cr.set_source_rgba(0, 0, 0, 0.45 * alpha)    # a faint dark edge, then white
            cr.set_line_width(lw + 1.5)
            cr.stroke_preserve()
            cr.set_source_rgba(1, 1, 1, alpha)
            cr.set_line_width(lw)
            cr.stroke()
            cr.new_path()
            rounded(bx, by, bw, bh, s * 0.1)
            cr.set_source_rgba(0, 0, 0, 0.45 * alpha)
            cr.set_line_width(1.5)
            cr.stroke_preserve()
            cr.set_source_rgba(1, 1, 1, alpha)
            cr.fill()
            cr.new_path()                                # the keyhole
            cr.arc(cx, by + bh * 0.42, max(1, s * 0.07), 0, 2 * math.pi)
            cr.set_source_rgba(0.1, 0.12, 0.18, alpha)
            cr.fill()
            cr.restore()

        pick = self.mode == "pick"
        manage = not pick
        if pick:
            text("Go to Page", W / 2, self.y0 - 52, 20, bold=True)
            text("Click a page or press its number (arrow keys and Enter work too).",
                 W / 2, self.y0 - 26, 12, 0.7)
        else:                        # (faded out while a page is brought forward)
            fade = 1.0 - (self.focus_t if self.focus is not None else 0.0)
            if fade > 0.01:
                text("Select a page to manage", W / 2, self.y0 - 52, 20, 0.95 * fade,
                     bold=True)
                text("(or drag & drop to re-order)", W / 2, self.y0 - 26, 12, 0.7 * fade)
        pages = self.app.cfg["pages"]
        here = pages[self.app.cfg["page"]] if 0 <= self.app.cfg["page"] < len(pages) else None
        dragged = self.drag and self.drag.get("moved") and self.drag["page"]
        chosen = self.order[self.sel] if pick and 0 <= self.sel < len(self.order) else None

        def draw_card(i, page, focused=False):
            x, y, w, h = self.card_rect(page)
            y -= 8 if page is dragged else 0
            sy = h / self.mon.height
            hovered = manage and page is self.hover and not focused and self.focus is None
            lit = (pick and (page is self.hover or page is chosen)) or hovered
            r = 8 + (6 * ft if focused else 0)
            cr.save()
            cr.new_path()
            if page is dragged or lit or focused:    # lifted: a soft, feathered shadow
                layers = 22 if focused else 12
                for k in range(1, layers + 1):       # faint layers, wider and fainter
                    cr.new_path()
                    rounded(x - k + 1, y - k + 5, w + 2 * k - 2, h + 2 * k - 2, r + k)
                    cr.set_source_rgba(0, 0, 0, 0.026 if (page is dragged or focused)
                                       else 0.018)
                    cr.fill()
            rounded(x, y, w, h, r)
            cr.clip()
            pb = self.big.get(id(page)) if focused else None
            pb = pb or self.thumbs.get(id(page))
            if self.wallpaper_of(page) is None:
                pb = None                            # (no picture: a thumbnail made before)
            self.paint_bg_colour(cr, page, x, y, w, h)   # the colour, under any picture
            if pb is not None:                       # the wallpaper, zoomed to fill
                k = max(w / pb.get_width(), h / pb.get_height())
                cr.save()
                cr.translate(x + (w - pb.get_width() * k) / 2,
                             y + (h - pb.get_height() * k) / 2)
                cr.scale(k, k)
                Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
                try:
                    cr.get_source().set_filter(cairo_filter_good())
                except Exception:
                    pass
                cr.paint()
                cr.restore()
            for f, fx, fy, fw, fh in self.cubby_rects(page, x, y, w, h):   # its cubbies
                c = Gdk.RGBA()
                if not c.parse(f.get("color") or "rgb(20,24,36)"):
                    c.parse("rgb(20,24,36)")
                cr.new_path()
                rounded(fx, fy, fw, fh, 3 * max(1, w / max(1, self.cw)) ** 0.5)
                cr.set_source_rgba(c.red, c.green, c.blue,
                                   max(0.45, float(f.get("opacity", 0.58))))
                cr.fill()
                cr.rectangle(fx, fy, fw, min(fh, max(2, 28 * sy)))
                cr.set_source_rgba(1, 1, 1, 0.18)
                cr.fill()
                if focused and ft >= 1:              # a page brought forward: locks
                    if f is self.lock_hover:
                        cr.new_path()
                        rounded(fx, fy, fw, fh, 4)
                        cr.set_source_rgba(1, 1, 1, 0.9)
                        cr.set_line_width(2)
                        cr.stroke()
                    if self.app.is_locked(f):
                        s = max(10, min(20, fh * 0.45, fw * 0.3))
                        padlock(fx + fw - s * 0.75 - 4, fy + 4 + s * 0.55, s, False)
            if lit and pick:                         # a light wash over the one to choose
                cr.set_source_rgba(1, 1, 1, 0.10)
                cr.paint()
            cr.restore()
            cr.new_path()
            rounded(x, y, w, h, r)
            if page is here:
                cr.set_source_rgba(0.21, 0.52, 0.89, 1)
                cr.set_line_width(3)
            elif lit or focused:
                cr.set_source_rgba(1, 1, 1, 0.9)
                cr.set_line_width(2)
            else:
                cr.set_source_rgba(1, 1, 1, 0.35)
                cr.set_line_width(1)
            cr.stroke()
            name = page.get("name") or "Page"
            if focused and ft > 0:                   # its name, above it, bigger
                size = 13 + 9 * ft
                cr.select_font_face("Sans", 0, 1)
                cr.set_font_size(size)
                room = max(60, w - 2 * 84 * ft)      # (clear of the gear and padlock)
                while len(name) > 2 and cr.text_extents(name).width > room:
                    name = name.rstrip("…")[:-1] + "…"
                text(name, x + w / 2, y - 16 * ft - 4 * (1 - ft), size, 1.0, bold=True)
                return
            cr.select_font_face("Sans", 0, 0)
            cr.set_font_size(13)
            while len(name) > 2 and cr.text_extents(name).width > w:
                name = name.rstrip("…")[:-1] + "…"
            text(name, x + w / 2, y + h + 24, 13, 1.0 if page is here else 0.85,
                 bold=page is here or hovered)
            if i < 10:                               # its number key (10 = 0)
                cr.new_path()
                cr.arc(x + 17, y + 17, 11, 0, 2 * math.pi)
                cr.set_source_rgba(0, 0, 0, 0.45)
                cr.fill()
                text(str((i + 1) % 10), x + 17, y + 22, 12, 0.95, bold=True)

        # the hovered (and dragged) one is drawn last, so it lies over its neighbours
        def stacking(t):
            page = t[1]
            return (page is self.focus, page is dragged, page is self.hover)
        for i, page in sorted(enumerate(self.order), key=stacking):
            if page is self.focus and ft > 0:
                continue
            draw_card(i, page)
        bottom = self.y0 + self.rows * self.ch + (self.rows - 1) * self.ROW_GAP
        if ft < 1:
            text("Esc or a click outside the pages closes this", W / 2, bottom + 66, 11,
                 0.55 * (1 - ft))
        if self.focus is not None and ft > 0:        # darker still, then the page on top
            cr.set_source_rgba(0.0, 0.0, 0.02, (self.DIM_FOCUS - self.DIM) / (1 - self.DIM)
                               * ft)
            cr.paint()
            draw_card(self.order.index(self.focus) if self.focus in self.order else 99,
                      self.focus, focused=True)
            if ft >= 1:
                text("Esc or a click outside goes back to the page" if self.settings_on else
                     "Esc or a click outside goes back to all the pages", W / 2, H - 40, 11,
                     0.5)
                gx, gy, gw, gh = self.gear_button_rect()     # the page's settings gear
                cr.new_path()
                cr.arc(gx + gw / 2, gy + gh / 2, gw / 2, 0, 2 * math.pi)
                cr.set_source_rgba(1, 1, 1, 0.30 if self.settings_on else
                                   0.22 if self.lock_hover == "gear" else 0.10)
                cr.fill()
                gear(gx + gw / 2, gy + gh / 2, 18)
                if self.page_cubbies(self.focus):    # the page's padlock
                    bx, by, bw, bh = self.lock_button_rect()
                    cr.new_path()
                    cr.arc(bx + bw / 2, by + bh / 2, bw / 2, 0, 2 * math.pi)
                    cr.set_source_rgba(1, 1, 1, 0.22 if self.lock_hover == "page" else 0.10)
                    cr.fill()
                    # closed padlock: click to lock them all; open: click to unlock them
                    padlock(bx + bw / 2, by + bh / 2 + 1, 18, self.page_locked(self.focus))
                tip = self.lock_tip(self.lock_hover) if self.lock_hover is not None else None
                if tip:                              # its tooltip, by the pointer
                    tx, ty = self.pointer
                    cr.select_font_face("Sans", 0, 0)
                    cr.set_font_size(12)
                    e = cr.text_extents(tip)
                    tw, th = e.width + 20, 26
                    tx = min(max(8, tx + 14), W - tw - 8)
                    ty = min(max(8, ty + 20), H - th - 8)
                    cr.new_path()
                    rounded(tx, ty, tw, th, 6)
                    cr.set_source_rgba(0.08, 0.09, 0.12, 0.96)
                    cr.fill_preserve()
                    cr.set_source_rgba(1, 1, 1, 0.25)
                    cr.set_line_width(1)
                    cr.stroke()
                    text(tip, tx + 10, ty + 17, 12, 0.95, centre=False)
        return False

    # -- moving
    def animate(self):
        if self.anim:
            return

        def step():
            busy = False
            for i, page in enumerate(self.order):
                k_want = (self.HOVER_GROW if (self.mode != "pick" and page is self.hover
                                              and self.focus is None and self.drag is None)
                          else 1.0)
                k = self.grow.get(id(page), 1.0)
                if k != k_want:
                    k += (k_want - k) * 0.35
                    if abs(k_want - k) < 0.003:
                        k = k_want
                    else:
                        busy = True
                    self.grow[id(page)] = k
                if self.drag and self.drag.get("moved") and page is self.drag["page"]:
                    continue
                want = self.slot_xy(i)
                cur = self.pos[id(page)]
                for c in (0, 1):
                    nxt = cur[c] + (want[c] - cur[c]) * 0.3
                    if abs(want[c] - nxt) < 0.6:
                        nxt = want[c]
                    else:
                        busy = True
                    cur[c] = nxt
            if self.focus is not None:
                want = 1.0 if self._focus_in else 0.0
                t = self.focus_t + (0.16 if want > self.focus_t else -0.2)
                t = max(0.0, min(1.0, t))
                if (want == 1.0 and t >= 1.0) or (want == 0.0 and t <= 0.0):
                    t = want
                    if want == 1.0:
                        if getattr(self, "_settings_after_focus", False):
                            self._settings_after_focus = False
                            self.focus_t = t
                            self.set_settings(True)
                        elif not self.settings_on and self.settings_t == 0:
                            self.show_panel("actions")
                    else:
                        self.focus = None
                else:
                    busy = True
                self.focus_t = t
            want_s = 1.0 if (self.settings_on and self.focus is not None) else 0.0
            if self.settings_t != want_s:            # the gear: picture to the side, or back
                st = self.settings_t + (0.11 if want_s > self.settings_t else -0.14)
                st = max(0.0, min(1.0, st))
                if (want_s == 1.0 and st >= 1.0) or (want_s == 0.0 and st <= 0.0):
                    st = want_s
                    self.settings_t = st
                    if want_s == 1.0:
                        self.show_settings_card()
                    elif self.focus is not None and self._focus_in and self.focus_t >= 1:
                        self.show_panel("actions")
                else:
                    busy = True
                self.settings_t = st
            self.area.queue_draw()
            if not busy:
                self.anim = 0
            return busy
        self.anim = GLib.timeout_add(16, step)

    def set_cursor(self, name):
        if name == self._cursor:
            return
        self._cursor = name
        gw = self.area.get_window()
        if gw is None:
            return
        try:
            cur = Gdk.Cursor.new_from_name(gw.get_display(), name) if name else None
        except Exception:
            cur = None
        gw.set_cursor(cur)

    # -- a page brought forward (Manage Pages)
    def open_focus(self, page):
        self.focus, self._focus_in = page, True
        self.hover = None
        self.set_cursor(None)
        self.load_big(page)
        self.animate()

    # -- the gear: this page's settings beside a smaller picture of it
    def set_settings(self, on):
        if self.focus is None or self.focus_t < 1 or on == self.settings_on:
            return
        self.settings_on = on
        self.lock_hover = None
        if on:
            self.hide_panel()
            # dialogs (wallpapers, colours, fonts) need the keyboard: let go of it
            if getattr(self, "kb_grab", None) is not None:
                try:
                    self.kb_grab.ungrab()
                except Exception:
                    pass
                self.kb_grab = None
        else:
            self.hide_settings_card()
        self.animate()

    def hide_settings_card(self):
        if self.settings_card is not None:
            self.settings_card.destroy()
            self.settings_card = None

    def show_settings_card(self):
        """Tabs "Page Background" and "Cubby Defaults" (what Settings › Desktop Pages had
        for each page), in a card to the right of the picture."""
        page = self.focus
        if page is None or self.settings_card is not None:
            return
        _pic, (cx, cy, cw, ch) = self.settings_layout()
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card.get_style_context().add_class("pm-settings")
        card.set_halign(Gtk.Align.START)
        card.set_valign(Gtk.Align.START)
        card.set_margin_start(int(cx))
        card.set_margin_top(int(cy))
        card.set_size_request(int(cw), int(ch))
        app = self.app

        def leave():                         # Pick from Screen: out of the way...
            self.close()

        def come_back():                     # ...and back here, on the same tab
            GLib.idle_add(lambda: app.open_page_settings(page, tab) and False)
        tab = self.settings_tab
        host = {"parent": self, "pick": (leave, come_back),
                "reopen": lambda: GLib.idle_add(lambda: self.rebuild_settings() and False),
                "changed": lambda: self.page_changed(page)}
        app.settings_css()                   # (headings with their dividing lines)
        try:
            bg_box, look_box = app.build_page_settings(page, host=host)
        except Exception as exc:
            dbg("page settings:", repr(exc))
            return
        # a header with a switcher, the two pages, and a footer with Done: plain parts that
        # every theme draws the same way (a GtkNotebook's tab strip differs a lot by theme)
        nb = Gtk.Stack()
        nb.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        nb.set_transition_duration(150)
        names = ("background", "defaults")
        for name, box, label in (("background", bg_box, "Page Background"),
                                 ("defaults", look_box, "Cubby Defaults")):
            sw = Gtk.ScrolledWindow()
            sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            sw.add(box)
            calm_scroll(box)                 # the wheel scrolls, never changes a setting
            nb.add_titled(sw, name, label)
        head = Gtk.Box()
        head.get_style_context().add_class("pm-settings-head")
        switch = Gtk.StackSwitcher()
        switch.set_stack(nb)
        switch.set_halign(Gtk.Align.CENTER)
        head.set_center_widget(switch)
        card.pack_start(head, False, False, 0)
        card.pack_start(nb, True, True, 0)
        foot = Gtk.Box(spacing=8)
        foot.get_style_context().add_class("pm-settings-foot")
        done = Gtk.Button(label="Done")
        done.connect("clicked", lambda _b: self.set_settings(False))
        foot.pack_end(done, False, False, 0)
        card.pack_start(foot, False, False, 0)
        self.overlay.add_overlay(card)
        card.show_all()
        # measured now: how wide the settings really are (fonts and themes differ); if the
        # guess was off, both the card and the picture take their right places
        need = nb.get_preferred_width()[0] + 4
        if need != getattr(app, "_page_card_w", None):
            app._page_card_w = need
            _pic, (cx, cy, cw, ch) = self.settings_layout()
            card.set_margin_start(int(cx))
            card.set_margin_top(int(cy))
            card.set_size_request(int(cw), int(ch))
            self.area.queue_draw()
        nb.set_visible_child_name(names[min(max(self.settings_tab, 0), 1)])
        nb.connect("notify::visible-child-name", lambda s, _p: setattr(
            self, "settings_tab", names.index(s.get_visible_child_name())
            if s.get_visible_child_name() in names else 0))
        self.settings_card = card

    def rebuild_settings(self):
        if self.settings_on and self.settings_t >= 1:
            self.hide_settings_card()
            self.show_settings_card()
            self.page_changed(self.focus)
        return False

    def page_changed(self, page):
        """The page's background (or its cubbies' look) changed: picture it again."""
        if page is None:
            return
        self.thumbs.pop(id(page), None)
        self.big.pop(id(page), None)
        path = self.wallpaper_of(page)
        if path:
            def work():
                pb = make_thumbnail(path, 256)
                GLib.idle_add(lambda: (self.thumbs.__setitem__(id(page), pb),
                                       self.area.queue_draw(), False)[-1])
            thumb_pool().submit(work)
        if page is self.focus:
            self.load_big(page)
        self.area.queue_draw()

    def close_focus(self):
        if self.focus is None:
            return
        self.settings_on = False
        self.hide_settings_card()
        self.lock_hover = None
        self.set_cursor(None)
        self.hide_panel()
        self._focus_in = False
        self.animate()

    def hide_panel(self):
        self.panel_mode = None
        for c in self.panel.get_children():
            self.panel.remove(c)
            c.destroy()
        self.panel.hide()

    def show_panel(self, mode):
        """Under the page brought forward: its buttons ("actions"), a name box ("rename"), or
        the question before deleting ("delete")."""
        page = self.focus
        if page is None or self.panel_mode == mode:
            return
        self.hide_panel()
        self.panel_mode = mode
        _x, fy, _w, fh = self.focus_rect()
        self.panel.set_margin_top(int(fy + fh + 26))
        row = Gtk.Box(spacing=10)
        row.set_halign(Gtk.Align.CENTER)

        def button(label, cb, cls=None, icon=None):
            b = Gtk.Button(label=label)
            if icon:
                img = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
                b.set_image(img)
                b.set_always_show_image(True)
            if cls:
                b.get_style_context().add_class(cls)
            b.set_can_focus(True)
            b.connect("clicked", lambda _b: cb())
            row.pack_start(b, False, False, 0)
            return b

        if mode == "actions":
            button("Rename", lambda: self.show_panel("rename"), icon="document-edit-symbolic")
            d = button("Delete", lambda: self.show_panel("delete"), "pm-danger",
                       "user-trash-symbolic")
            if len(self.app.cfg["pages"]) <= 1:
                d.set_sensitive(False)
                d.set_tooltip_text("Your only page can't be deleted.")
            pages = self.app.cfg["pages"]
            if page in pages and pages.index(page) != self.app.cfg["page"]:
                button("Go to Page", lambda: self.go(self.app.cfg["pages"].index(page)),
                       "pm-main", "go-jump-symbolic")
            self.panel.pack_start(row, False, False, 0)
        elif mode == "rename":
            entry = Gtk.Entry(text=page.get("name") or "")
            entry.set_width_chars(28)
            entry.set_halign(Gtk.Align.CENTER)
            entry.connect("activate", lambda _e: self.do_rename(entry.get_text()))
            self.panel.pack_start(entry, False, False, 0)
            button("Cancel", lambda: self.show_panel("actions"))
            button("Save", lambda: self.do_rename(entry.get_text()), "pm-main")
            self.panel.pack_start(row, False, False, 0)
            GLib.idle_add(lambda: (entry.grab_focus(), entry.select_region(0, -1), False)[-1])
        elif mode == "delete":
            q = Gtk.Label(label=f"Delete the page “{page.get('name') or 'Page'}”?")
            q.get_style_context().add_class("pm-question")
            note = Gtk.Label(label=self.app.delete_page_note(page))
            note.get_style_context().add_class("pm-note")
            note.set_line_wrap(True)
            note.set_max_width_chars(70)
            note.set_justify(Gtk.Justification.CENTER)
            self.panel.pack_start(q, False, False, 0)
            self.panel.pack_start(note, False, False, 0)
            c = button("Cancel", lambda: self.show_panel("actions"))
            button("Delete Page", self.do_delete, "pm-danger", "user-trash-symbolic")
            self.panel.pack_start(row, False, False, 0)
            GLib.idle_add(lambda: (c.grab_focus(), False)[-1])
        for c in self.panel.get_children():         # (the panel itself is no-show-all)
            c.show_all()
        self.panel.show()
        self.area.queue_draw()

    def do_rename(self, name):
        page = self.focus
        if page is not None and (name or "").strip():
            self.app.rename_page(page, name.strip())
        self.show_panel("actions")
        self.area.queue_draw()

    def do_delete(self):
        page = self.focus
        if page is None:
            return
        self.hide_panel()
        done = self.app.delete_page(page, ask_first=False)
        if getattr(self, "_closed", False):
            return
        if not done:                                 # (it said why, if anything went wrong)
            self.show_panel("actions")
            return
        self.focus, self.focus_t, self._focus_in = None, 0.0, False
        self.order = list(self.app.cfg["pages"])
        self.hover = None
        self.layout()
        for i, p in enumerate(self.order):           # the others close up the gap
            self.pos.setdefault(id(p), list(self.slot_xy(i)))
        self.sel = min(max(self.app.cfg["page"], 0), len(self.order) - 1)
        self.animate()
        self.take_keys()

    # -- the pointer
    def on_press(self, _w, event):
        if event.button != 1:
            return True
        if self.focus is not None:                   # a page is forward
            target = self.lock_target_at(event.x, event.y)
            if target is not None:                   # a padlock or a cubby: lock / unlock
                self.toggle_lock(target)
                return True
            if self.settings_on:                     # outside the settings: back to the page
                fx, fy, fw, fh = self.card_rect(self.focus)
                if not (fx <= event.x <= fx + fw and fy <= event.y <= fy + fh):
                    self.set_settings(False)
                return True
            fx, fy, fw, fh = self.card_rect(self.focus)
            if not (fx <= event.x <= fx + fw and fy <= event.y <= fy + fh):
                self.close_focus()                   # outside it: back to all the pages
            return True
        page = self.card_at(event.x, event.y)
        if page is None:
            self.close_later()
            return True
        x, y = self.pos[id(page)]
        self.drag = {"page": page, "sx": event.x, "sy": event.y, "offx": event.x - x,
                     "offy": event.y - y, "moved": False,
                     "from": self.app.cfg["pages"].index(page)}
        return True

    def on_leave(self, _w, _event):
        if self.drag is None and self.hover is not None and self.mode != "pick":
            self.hover = None
            self.animate()
        return False

    def on_motion(self, _w, event):
        d = self.drag
        if self.focus is not None:
            self.pointer = (event.x, event.y)
            target = self.lock_target_at(event.x, event.y)
            self.set_cursor("pointer" if target is not None else None)
            if target is not self.lock_hover or target is not None:
                self.lock_hover = target
                self.area.queue_draw()
            return True
        if d is None or self.mode == "pick":
            hover = self.card_at(event.x, event.y)
            if self.mode != "pick":
                self.set_cursor("pointer" if hover is not None else None)
            if hover is not self.hover:
                self.hover = hover
                if hover is not None:
                    self.sel = self.order.index(hover)
                if self.mode != "pick":
                    self.animate()
                self.area.queue_draw()
            return False
        if not d["moved"] and abs(event.x - d["sx"]) < 6 and abs(event.y - d["sy"]) < 6:
            return True
        if not d["moved"]:
            self.set_cursor("grabbing")
        d["moved"] = True
        x, y = event.x - d["offx"], event.y - d["offy"]
        self.pos[id(d["page"])] = [x, y]
        slot = self.nearest_slot(x, y)
        if self.order.index(d["page"]) != slot:
            self.order.remove(d["page"])
            self.order.insert(slot, d["page"])
        self.animate()
        self.area.queue_draw()
        return True

    def on_release(self, _w, event):
        d, self.drag = self.drag, None
        if d is None:
            return True
        if not d["moved"]:                          # a click
            if self.mode == "pick":
                self.go(self.app.cfg["pages"].index(d["page"]))
            else:
                self.open_focus(d["page"])          # Manage Pages: bring it forward
            return True
        to = self.order.index(d["page"])
        if to != d["from"]:
            self.app.move_page(d["from"], to)
        self.order = list(self.app.cfg["pages"])
        self.set_cursor("pointer" if self.card_at(event.x, event.y) else None)
        self.animate()
        return True

    def go(self, dest):
        self.close()
        if 0 <= dest < len(self.app.cfg["pages"]) and dest != self.app.cfg["page"]:
            GLib.timeout_add(120, lambda: self.app.change_page(
                dest - self.app.cfg["page"], force=True) and False)

    def on_key(self, _w, event):
        k = event.keyval
        n = len(self.order)
        if k in (Gdk.KEY_m, Gdk.KEY_M) and self.is_manage_key(event):
            app = self.app                   # the Manage Pages key: close it, or from the
            was = self.mode                  # page chooser, swap to Manage Pages
            self.close()
            if was == "pick":
                GLib.idle_add(lambda: app.open_page_order("order") and False)
            return True
        if self.focus is not None:                   # a page is forward
            if k == Gdk.KEY_Escape and self.settings_on:
                self.set_settings(False)
                return True
            if k == Gdk.KEY_Escape:
                if self.panel_mode in ("rename", "delete"):
                    self.show_panel("actions")
                else:
                    self.close_focus()
                return True
            return False                             # the buttons and name box get the rest
        if k == Gdk.KEY_Up and event.state & Gdk.ModifierType.CONTROL_MASK:
            self.close()                     # the chooser key again (the keyboard is ours)
            return True
        if k == Gdk.KEY_Escape:
            self.close()
            return True
        digits = {getattr(Gdk, f"KEY_{d}"): d for d in range(10)}
        digits.update({getattr(Gdk, f"KEY_KP_{d}"): d for d in range(10)})
        if k in digits:                              # 1 … 9, and 0 for the tenth
            idx = (digits[k] - 1) % 10
            if idx < n:
                if self.mode == "pick":
                    self.go(idx)
                else:
                    self.sel = idx
                    self.open_focus(self.order[idx])
            return True
        moves = {Gdk.KEY_Left: -1, Gdk.KEY_Right: 1, Gdk.KEY_Up: -self.cols,
                 Gdk.KEY_Down: self.cols}
        if k in moves:
            self.sel = max(0, min(n - 1, self.sel + moves[k]))
            if self.mode == "pick":
                self.hover = None
            else:
                self.hover = self.order[self.sel]
                self.animate()
            self.area.queue_draw()
            return True
        if k in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            if self.mode == "pick":
                self.go(self.sel)
            elif 0 <= self.sel < n:
                self.open_focus(self.order[self.sel])
            return True
        return False

    def is_manage_key(self, event):
        st = event.state
        ctrl = bool(st & Gdk.ModifierType.CONTROL_MASK)
        sup = bool(st & (Gdk.ModifierType.SUPER_MASK | Gdk.ModifierType.MOD4_MASK))
        alt = bool(st & Gdk.ModifierType.MOD1_MASK)
        want = self.app.cfg.get("manage_key", "ctrl_super_m")
        return ctrl and ((want == "ctrl_super_m" and sup and not alt)
                         or (want == "ctrl_alt_m" and alt and not sup))

    def focus_gone(self):
        """Another window took over (Alt+Tab, say): don't stay over it."""
        if (not self.is_active() and self.drag is None and self.kb_grab is None
                and not self.settings_on):
            self.close()
        return False

    def close_later(self):
        GLib.idle_add(lambda: self.close() and False)
        return False

    def close(self):
        if getattr(self, "_closed", False):
            return
        self._closed = True
        if self.anim:
            GLib.source_remove(self.anim)
            self.anim = 0
        if getattr(self.app, "page_order", None) is self:
            self.app.page_order = None
        if getattr(self, "kb_grab", None) is not None:
            try:
                self.kb_grab.ungrab()
            except Exception:
                pass
            self.kb_grab = None
        self.destroy()
