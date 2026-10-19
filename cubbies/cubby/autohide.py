"""Auto-hide, launch bars, peek, and the pointer moving over a cubby."""

from gi.repository import Gdk, GLib, Gtk

from ..constants import DEFAULT_RADIUS
from ..core import dbg, undoable


class CubbyAutohide:
    """Auto-hide, launch bars, peek and pointer hover. Part of Cubby."""

    # -- auto-hide: a cubby touching the top or bottom of the screen slides out of sight and
    #    comes back when the pointer reaches that edge (like an auto-hiding panel)
    def ah_edge(self):
        """("top" | "bottom", workarea, monitor geometry) while auto-hide is on and the cubby
        sits against the top or bottom of the screen; None otherwise."""
        if not self.data.get("autohide"):
            return None
        return self.screen_edge()

    def screen_edge(self):
        """Like ah_edge, whether or not auto-hide is on."""
        if self.data.get("rolled"):
            return None
        x, y = int(self.data["x"]), int(self.data["y"])
        w, h = self.get_size()
        try:
            mon = Gdk.Display.get_default().get_monitor_at_point(x + w // 2, y + h // 2)
            wa, geo = mon.get_workarea(), mon.get_geometry()
        except Exception:
            return None
        if self.data.get("launchbar"):
            # a launch bar belongs to its edge, wherever the window happens to be just now
            # (the screen size, the panels or the theme can shift it by a few pixels)
            side = "bottom" if self.app.cfg.get("launchbar_edge", "top") == "bottom" else "top"
            return side, wa, geo
        m = self.screen_margin()
        if abs(y - (wa.y + m)) <= 3:
            return "top", wa, geo
        if abs(y + h - (wa.y + wa.height - m)) <= 3:
            return "bottom", wa, geo
        return None

    def ah_mode(self, edge=None):
        """"slide", "fade" or "instant". Sliding off a screen edge that has another screen
        behind it would show the cubby there, so it fades instead."""
        mode = self.app.cfg.get("autohide_anim", "slide")
        if mode not in ("slide", "fade", "instant"):
            mode = "slide"
        edge = edge or self.ah_edge()
        if mode == "slide" and edge is not None:
            side, _wa, geo = edge
            px = int(self.data["x"]) + self.get_size()[0] // 2
            py = geo.y - 4 if side == "top" else geo.y + geo.height + 4
            for rx, ry, rw, rh in self.app.monitor_rects() or []:
                if rx <= px < rx + rw and ry <= py < ry + rh:
                    return "fade"
        return mode

    def ah_strip(self):
        try:
            return max(0, min(40, int(self.app.cfg.get("autohide_strip", 3))))
        except (TypeError, ValueError):
            return 3

    def ah_hidden_pos(self):
        x, y = int(self.data["x"]), int(self.data["y"])
        edge = self.ah_edge()
        if edge is None:
            return x, y
        if self.ah_mode(edge) != "slide":
            return -30000, y                      # parked out of sight
        h = self.get_size()[1]
        keep = self.ah_strip()
        return (x, y - (h - keep)) if edge[0] == "top" else (x, y + (h - keep))

    def ah_on_top(self, on=None):
        """Which layer the cubby lives in. An auto-hiding cubby set to come out over your
        windows lives in the top layer the whole time, like an auto-hiding panel (hidden, it
        is slid out of sight and clicks pass through its strip); every other cubby stays on
        the desktop. A cubby is never moved from one layer to the other to be shown."""
        above = bool(self.data.get("autohide")) and bool(self.app.setting("autohide_on_top"))
        self.set_keep_below(not above)
        self.set_keep_above(above)
        if above and on:
            try:
                self.get_window().raise_()      # (within its own layer)
            except Exception:
                pass

    def click_through(self, on):
        """While slid away, clicks on the thin strip go to whatever is under it."""
        try:
            import cairo
            self.input_shape_combine_region(cairo.Region() if on else None)
        except Exception as exc:
            dbg("click-through:", exc)

    def ah_busy(self):
        """Something is going on in the cubby: it must not slide away now."""
        return bool(self._drag or self._band or getattr(self, "_editor", None) is not None
                    or getattr(self, "_name_editor", None) is not None
                    or self.search_rev.get_reveal_child()
                    or Gtk.grab_get_current() is not None      # a menu is open
                    or getattr(self, "_menu_open", False))

    def ah_set(self, hidden, animate=True):
        """Slide (or fade) the cubby out of sight, or bring it back."""
        if self._ah_anim:
            GLib.source_remove(self._ah_anim)
            self._ah_anim = 0
        edge = self.ah_edge()
        if edge is None:
            hidden = False
        self._ah_hidden = hidden
        self._ah_since = self._ah_away = None
        home = (int(self.data["x"]), int(self.data["y"]))
        mode = self.ah_mode(edge) if edge else "instant"
        dbg("auto-hide:", "hide" if hidden else "show", self.pane.get("title"), mode)
        self.click_through(hidden)
        if not hidden:
            self.ah_on_top(True)
        if mode == "slide":
            if self.get_opacity() < 0.05:
                self.update_fade()
            start = self.get_position()
            if start[0] <= -20000:                 # was parked (another way of hiding)
                start = self.ah_hidden_pos() if not hidden else home
            end = self.ah_hidden_pos() if hidden else home
            if not animate or start == end:
                self.move(*end)
                if hidden:
                    self.ah_on_top(False)
                return
            t0 = GLib.get_monotonic_time()
            span = 170_000 if not hidden else 230_000

            def step():
                k = min(1.0, (GLib.get_monotonic_time() - t0) / span)
                e = 1 - (1 - k) ** 3                   # ease out
                self.move(int(start[0] + (end[0] - start[0]) * e),
                          int(start[1] + (end[1] - start[1]) * e))
                if k >= 1.0:
                    self._ah_anim = 0
                    if hidden:
                        self.ah_on_top(False)
                    return False
                return True
            self._ah_anim = GLib.timeout_add(15, step)
            return
        # fade, or no animation at all
        if not hidden:
            if getattr(self, "_fade_timer", 0):
                GLib.source_remove(self._fade_timer)
                self._fade_timer = 0
            if mode == "fade" and animate:
                self.set_opacity(0.0)
            self.move(*home)
            self.update_fade()                     # fades in (or just shows)
            return
        if getattr(self, "_fade_timer", 0):
            GLib.source_remove(self._fade_timer)
            self._fade_timer = 0

        def park():
            self.move(-30000, home[1])
            self.ah_on_top(False)
        if mode != "fade" or not animate:
            park()
            return
        a0, t0 = self.get_opacity(), GLib.get_monotonic_time()

        def fade():
            k = min(1.0, (GLib.get_monotonic_time() - t0) / 220_000)
            self.set_opacity(a0 * (1 - k))
            if k >= 1.0:
                self._ah_anim = 0
                park()
                return False
            return True
        self._ah_anim = GLib.timeout_add(15, fade)

    def ah_delay(self, key, default):
        try:
            return max(0, min(5000, int(self.app.cfg.get(key, default))))
        except (TypeError, ValueError):
            return default

    def ah_tick(self, px, py, now, down=False):
        """Called often by the app with the pointer position (and whether the left button
        is held): show / hide as needed."""
        was_down, self._ah_down = getattr(self, "_ah_down", False), down
        pressed, released = down and not was_down, was_down and not down
        if pressed:
            self._ah_down_t = GLib.get_monotonic_time()
        # the button held for a file drag (not a window being dragged to the edge)
        file_drag = down and self.app.watcher.dnd_started_after(getattr(self, "_ah_down_t", 0))
        edge = self.ah_edge()
        if edge is None:
            if self._ah_hidden:
                self.ah_set(False)
            return
        side, wa, geo = edge
        x, y = int(self.data["x"]), int(self.data["y"])
        w, h = self.get_size()
        if self._ah_hidden:
            band = max(2, self.ah_strip())
            m = self.screen_margin()
            if side == "top":
                lo = geo.y if y - geo.y <= m + 2 else y - 1     # a panel above: its edge
                hi = y + band
            else:
                bottom = y + h
                hi = geo.y + geo.height if geo.y + geo.height - bottom <= m + 2 else bottom + 1
                lo = bottom - band
            # the corners stay free (window buttons live there), unless the bar is narrow
            try:
                corner = max(0, int(self.app.cfg.get("autohide_corners", 100)))
            except (TypeError, ValueError):
                corner = 100
            corner = min(corner, w // 4)
            in_zone = x + corner <= px < x + w - corner and lo <= py <= hi
            if self.app.cfg.get("autohide_open", "hover") == "click":
                if file_drag and in_zone:           # a file dragged there still opens it
                    if self._ah_since is None:
                        self._ah_since = now
                    if now - self._ah_since >= self.ah_delay("autohide_show_ms", 150):
                        self.ah_set(False)
                    return
                self._ah_since = None
                # click at the edge: press and let go there without dragging
                if pressed:
                    self._ah_press = (px, py, now) if in_zone else None
                elif released:
                    p0, self._ah_press = getattr(self, "_ah_press", None), None
                    if (p0 and in_zone and abs(px - p0[0]) + abs(py - p0[1]) <= 8
                            and now - p0[2] <= 700):
                        self.ah_set(False)
                return
            if in_zone and (not down or file_drag):
                if self._ah_since is None:
                    self._ah_since = now
                if now - self._ah_since >= self.ah_delay("autohide_show_ms", 150):
                    self.ah_set(False)
            else:
                self._ah_since = None
            return
        if self._ah_anim:
            return
        over = (x - 6 <= px < x + w + 6
                and (geo.y if side == "top" else y - 6) <= py
                < (y + h + 6 if side == "top" else geo.y + geo.height))
        if self.app.cfg.get("autohide_close", "leave") == "click":
            # stays out until a click somewhere else (or an icon is opened)
            if pressed and not over and not self.ah_busy():
                self.ah_set(True)
            return
        if over or self.ah_busy() or self.app.glance is not None:
            self._ah_away = None
            return
        if self._ah_away is None:
            self._ah_away = now
        if now - self._ah_away >= self.ah_delay("autohide_hide_ms", 600):
            self.ah_set(True)

    @undoable("Auto-hide")
    def set_autohide(self, on):
        if on:
            self.data["autohide"] = True
        else:
            self.data.pop("autohide", None)
            self.ah_set(False, animate=False)
            self.ah_on_top(False)
        self.app.save()
        self.app.autohide_start()

    # -- launch bars: a cubby without a title bar, along a screen edge, that auto-hides
    LB_KEYS = ("title_pos", "autohide", "all_pages", "keep_visible", "x", "y", "w", "h",
               "icon_size", "view", "names", "sort")

    @undoable("Turn into a Launch Bar")
    def make_launch_bar(self):
        self.app.make_launch_bar(self.data)

    @undoable("Turn Back into a Cubby")
    def unmake_launch_bar(self):
        self.app.unmake_launch_bar(self.data)

    # -- peek: a rolled-up cubby opens while the pointer rests on it
    def cancel_timers(self):
        for name in ("_peek_timer", "_icon_timer", "_edge_poll"):
            if getattr(self, name):
                GLib.source_remove(getattr(self, name))
                setattr(self, name, 0)

    def on_blur_draw(self, _w, cr):
        on, level, strength = self.app.blur_of(self.data)
        if not on:
            return False
        pb = self.app.blurred_wallpaper(level)
        if pb is None or not hasattr(self, "outer"):
            return False
        import math
        x, y = self.get_position()
        a = self.outer.get_allocation()
        r = max(0, min(int(self.data.get("radius", DEFAULT_RADIUS)), a.width / 2, a.height / 2))
        cr.save()
        cr.new_sub_path()
        cr.arc(a.x + a.width - r, a.y + r, r, -math.pi / 2, 0)
        cr.arc(a.x + a.width - r, a.y + a.height - r, r, 0, math.pi / 2)
        cr.arc(a.x + r, a.y + a.height - r, r, math.pi / 2, math.pi)
        cr.arc(a.x + r, a.y + r, r, math.pi, 1.5 * math.pi)
        cr.close_path()
        cr.clip()
        Gdk.cairo_set_source_pixbuf(cr, pb, -x, -y)
        # Glass strength: how much of the blurred picture shows; the rest stays clear, so
        # the desktop (and the Transparency setting) still show through
        cr.paint_with_alpha(strength)
        cr.restore()
        return False

    def on_win_enter(self, widget, event):
        if event.mode == Gdk.CrossingMode.NORMAL:
            self.set_inside(True)
        if (self.data.get("rolled") and not self._peeking and not self._drag
                and not self._peek_timer and event.mode == Gdk.CrossingMode.NORMAL
                and (self.app.rollup_open() == "hover"
                     or (self.data.get("docked") and self.app.rollup_open() != "click"))):
            self._peek_timer = GLib.timeout_add(450, self._peek_open)
        return False

    # -- the pointer over the cubby: shows a hidden title, un-fades a faded cubby
    def set_inside(self, inside):
        if getattr(self, "_inside", False) == inside:
            return
        self._inside = inside
        self.update_title_visibility()
        self.update_fade()

    def update_title_visibility(self):
        """Titles: always shown, only while the pointer is over the cubby, or never (a
        rolled-up cubby always shows its title bar, or there would be nothing to see)."""
        mode = self.app.cfg.get("show_titles", "always")
        show = (mode == "always" or self.data.get("rolled") or self._peeking
                or getattr(self, "_editor", None) is not None
                or (mode == "hover" and getattr(self, "_inside", False)) or self._drag)
        for w in (self.name_box, self.tab_box):
            w.set_opacity(1.0 if show else 0.0)
        ctx = self.title_ev.get_style_context()
        if show:
            ctx.remove_class("title-hidden")
        else:
            ctx.add_class("title-hidden")

    def update_fade(self):
        """"Fade cubbies when the pointer isn't over them": a gentle fade either way."""
        target = 1.0
        if (self.app.setting("fade_idle") and not getattr(self, "_inside", False)
                and not self._drag and getattr(self, "_editor", None) is None):
            target = float(self.app.cfg.get("fade_level", 0.35))
        if getattr(self, "_fade_timer", 0):
            GLib.source_remove(self._fade_timer)
            self._fade_timer = 0
        start = self.get_opacity()
        if abs(start - target) < 0.01:
            self.set_opacity(target)
            return
        t0 = GLib.get_monotonic_time()
        span = 180_000 if target > start else 450_000      # in quickly, out slowly

        def step():
            k = min(1.0, (GLib.get_monotonic_time() - t0) / span)
            self.set_opacity(start + (target - start) * k)
            if k >= 1.0:
                self._fade_timer = 0
                return False
            return True
        self._fade_timer = GLib.timeout_add(16, step)

    def on_win_leave(self, widget, event):
        if event.mode != Gdk.CrossingMode.NORMAL or event.detail == Gdk.NotifyType.INFERIOR:
            return False
        x, y = self.get_position()
        w, h = self.get_size()
        if x <= event.x_root < x + w and y <= event.y_root < y + h:
            return False   # still over the cubby (the pointer only moved onto an icon)
        if self._peek_timer:
            GLib.source_remove(self._peek_timer)
            self._peek_timer = 0
        if self._peeking:
            self.sync_roll()   # close it again
        if not self._drag:
            self.set_inside(False)
        return False

    def _peek_open(self):
        self._peek_timer = 0
        if self.data.get("rolled") and not self._drag:
            self._peeking = True
            self.title_ev.get_style_context().remove_class("rolled")
            self.content.set_visible(True)
            self.kind_row.set_visible(bool(self.kind_box.get_children()))
            self.set_size_request(130, self.min_h())
            self.resize(self.data["w"], self.data["h"])
            if self._flipped:          # title at the bottom: it opens upwards
                GLib.timeout_add(40, lambda: self.move(self.data["x"], self.data["y"]) and False)
        return False
