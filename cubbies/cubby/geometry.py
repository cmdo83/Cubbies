"""Moving and resizing a cubby, snapping, the title bar position, rolling up."""

from gi.repository import Gdk, GLib, Gtk

from ..core import dbg, undoable
from ..files import launch
from ..widgets import best_snap, scroll_direction, set_cursor, text_move_cursor


class CubbyGeometry:
    """Moving, resizing, snapping and rolling up. Part of Cubby."""

    # -- moving / resizing (done by hand so it works for desktop-type windows)
    def on_title_press(self, widget, event):
        if self._ah_hidden or self._ah_anim:
            return True
        if event.button == 1 and event.type == Gdk.EventType.DOUBLE_BUTTON_PRESS:
            self._drag = None
            self.cancel_title_click()
            if (event.state & Gdk.ModifierType.CONTROL_MASK) and self.pane.get("folder"):
                launch(self.app.folder_of(self.pane))   # Ctrl + double-click: open the folder
                return True
            if self.app.setting("dblclick_roll") and (self.app.setting("rollup_enabled")
                                                      or self.data.get("rolled")):
                self.toggle_roll()  # double-click the title bar: roll the cubby up / down
            return True
        if event.button == 1 and self.app.is_locked(self.data):
            # locked: no moving, but a click on the name / a rolled-up cubby still works
            self._press_on_name = (self.on_name(event.x_root, event.y_root)
                                   and not getattr(self, "_title_click_timer", 0))
            self._drag = ("locked", event.x_root, event.y_root, 0, 0, 0, 0)
            return True
        if event.button == 1:
            wx, wy = self.get_position()
            self._drag = ("move", event.x_root, event.y_root, wx, wy, 0, 0)
            self._title_top0 = self.title_top()
            ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
            app = self.app
            if app.picked and self.data["id"] not in app.picked and not ctrl:
                app.clear_picked()             # a plain click elsewhere ends the group
            # picked cubbies all move together with this one
            self._group = None
            if self.data["id"] in app.picked and len(app.picked) > 1:
                self._group = [(w, *w.get_position()) for w in app.picked_windows()
                               if w is not self and not app.is_locked(w.data)]
            self._press_on_name = (self.on_name(event.x_root, event.y_root)
                                   and not getattr(self, "_title_click_timer", 0))
            self.cancel_title_click()
            # where on the title bar it was picked up: kept the same across page hops
            self._grab_off = (event.x_root - wx, event.y_root - wy)
            self._hopped = False
            self._edge_seen, self._edge_ticks = None, 0
            self._edge_locked, self._edge_moved = False, False
            if not self._edge_poll:
                self._edge_poll = GLib.timeout_add(60, self._poll_edge)
        elif event.button == 3:
            menu = self.build_main_menu()
            self.track_menu(menu)
            menu.popup_at_pointer(event)
        return True

    def track_menu(self, menu):
        """While one of this cubby's menus is open it stays shown (auto-hide waits)."""
        self._menu_open = True

        def done(_m):
            self._menu_open = False
            self._ah_away = None
        menu.connect("deactivate", done)

    def on_grip_press(self, widget, event):
        if event.button == 1:
            w, h = self.get_size()
            self._drag = ("resize", event.x_root, event.y_root, 0, 0, w, h)
        return True

    def on_motion(self, widget, event):
        if not self._drag and widget is self.title_ev:
            self.update_title_cursor(event.x_root, event.y_root)
        if not self._drag or self._drag[0] == "locked":
            return False
        kind, sx, sy, wx, wy, w, h = self._drag
        dx, dy = event.x_root - sx, event.y_root - sy
        # hold Shift to move/resize without snapping
        snap = not (event.state & Gdk.ModifierType.SHIFT_MASK)
        xs, ys, widths, heights = (self.snap_targets() if snap else
                                   ({"lo": [], "hi": []}, {"lo": [], "hi": []}, [], []))
        if kind == "move":
            cw, ch = self.get_size()
            th = self.title_h()
            title_top = int(getattr(self, "_title_top0", wy) + dy)
            # near the bottom of the screen the title goes to the bottom, contents above it
            self.update_flip_for(title_top)
            nx = int(wx + dx)
            ny = title_top - (ch - th) if self._flipped else title_top
            # either side of this cubby can line up with either side of another
            nx += best_snap([(nx, t) for t in xs["lo"]] + [(nx + cw, t) for t in xs["hi"]])
            ny += best_snap([(ny, t) for t in ys["lo"]] + [(ny + ch, t) for t in ys["hi"]])
            if snap and self.app.setting("edge_snap"):
                ny = self.edge_snap_y(ny, ch)
                if self.app.setting("edge_snap_sides"):
                    nx = self.edge_snap_x(nx, cw)
            self.move(nx, ny)
            self._last_move = (nx, ny)     # (the window manager may not have caught up yet)
            group = getattr(self, "_group", None)
            if group:
                for win, ox, oy in group:      # the others keep their distance from this one
                    win.move(int(ox + nx - wx), int(oy + ny - wy))
            # hovering over another cubby's title bar: dropping here combines them as tabs
            target = None
            if abs(dx) + abs(dy) > 6 and not group and self.has_title():
                target = self.app.merge_target_at(self, event.x_root, event.y_root)
            if target is not self._merge_target:
                if self._merge_target is not None:
                    self._merge_target.set_merge_hint(False)
                self._merge_target = target
                if target is not None:
                    target.set_merge_hint(True)
            # the pointer at the left/right edge of the screen: dropping moves it to another page
            if abs(dx) + abs(dy) > 6:
                self._edge_moved = True
            side = (self.edge_side(event.x_root)
                    if (target is None and self._edge_moved and not self._edge_locked
                        and not group) else None)
            self.app.show_edge_hint(side)
        else:
            nw, nh = max(130, int(w + dx)), max(self.min_h(), int(h + dy))
            x0, y0 = self.get_position()
            # the right/bottom edge sticks to other edges; the size sticks to other sizes
            nw += best_snap([(x0 + nw, t) for t in xs["hi"]] + [(nw, t) for t in widths])
            nh += best_snap([(y0 + nh, t) for t in ys["hi"]] + [(nh, t) for t in heights])
            self.resize(max(130, nw), max(self.min_h(), nh))
        return True

    def pointer_pos(self, fallback=(0, 0)):
        """Where the pointer is on the screen right now (asked directly, not from an event)."""
        try:
            _w, x, y, _m = self.app.watcher.root.get_device_position(self.app.watcher.pointer)
            return x, y
        except Exception:
            return fallback

    def pointer_x(self, fallback):
        return self.pointer_pos((fallback, 0))[0]

    def _poll_edge(self):
        """While a cubby is held: the pointer resting on the left/right screen edge for a
        moment takes the cubby to the page on that side, and the cubby stays in your hand."""
        if not self._drag or self._drag[0] != "move":
            self._edge_poll = 0
            return False
        try:
            raw = self.edge_side(self.pointer_x(-100))
            if self._edge_locked:
                if raw is None:            # left the edge after a hop: ready for the next one
                    self._edge_locked = False
                side = None
            else:
                side = raw if self._edge_moved else None
            if side != self._edge_seen:
                self._edge_seen, self._edge_ticks = side, 0
                self.app.show_edge_hint(side)
                dbg("pointer edge:", side)
            elif side:
                self._edge_ticks += 1
                if self._edge_ticks >= 6 and self._merge_target is None:   # ~0.4 s
                    self.carry_to_edge(side)
        except Exception as exc:
            dbg("edge poll error:", repr(exc))
        return True

    def carry_to_edge(self, side):
        """Hop to the next page (making one if needed) WITHOUT letting go: the same window
        keeps the pointer grab, so the cubby just carries on following the pointer."""
        self.app.show_edge_hint(None)
        if self._merge_target is not None:
            self._merge_target.set_merge_hint(False)
            self._merge_target = None
        x, y = self.get_position()
        self.store_geometry(x, y)
        self.app.save()
        src = self.app.page_of(self.data)
        self.app.move_cubby_to_edge(self.data, side, carry=self)
        if self.app.page_of(self.data) is src:
            return                              # nothing moved: keep dragging as before
        px, py = self.pointer_pos((x, y))
        # the same spot of the title bar stays under the pointer (the cubby may hang over the
        # screen edge for now; it is pulled back on screen when it is let go)
        offx, offy = getattr(self, "_grab_off", (px - x, py - y))
        nx, ny = int(px - offx), int(py - offy)
        self.move(nx, ny)
        self.store_geometry(nx, ny)
        self._hopped = True
        self._last_move = None
        self._drag = ("move", px, py, nx, ny, 0, 0)
        self._title_top0 = self.title_top(ny)
        self._edge_locked, self._edge_moved = True, False
        self._edge_seen, self._edge_ticks = None, 0

    # -- geometry: title height, the bottom-title ("flipped") layout, all-side resizing
    def after_title_click(self, event):
        """A plain click on the title bar (no drag): open a rolled-up cubby in "click to
        open" mode, or start renaming / choose a tab when the click was on the name.
        (Waits out the double-click time, so double-clicks still roll up.)"""
        dbl = Gtk.Settings.get_default().get_property("gtk-double-click-time") or 400
        on_name = getattr(self, "_press_on_name", False)
        self._press_on_name = False
        click_open = (self.data.get("rolled") and not self._peeking
                      and self.app.rollup_open() == "click")
        if not (click_open or on_name):
            return

        def go():
            self._title_click_timer = 0
            if click_open:
                self._peek_open()
            elif self.data.get("group") and self.app.cfg.get("tab_style") == "menu":
                self.show_tab_menu()
            else:
                self.edit_title()
            return False
        self.cancel_title_click()
        self._title_click_timer = GLib.timeout_add(dbl + 40, go)

    def check_edge_dock(self):
        """"Roll up cubbies placed at the top or bottom edge of the screen": let go against
        the top (or, title at the bottom, the bottom) and it rolls up; it opens while the
        pointer is on it. Moved away again, it unrolls."""
        if not self.has_title() or self.data.get("autohide"):
            return                      # (auto-hide takes care of a cubby at the edge)
        wa = self.workarea()
        if wa is None:
            return
        th = self.title_h()
        top = self.title_top()
        at_edge = (abs(top - wa.y) <= 1 or
                   (self._flipped and abs(top + th - (wa.y + wa.height)) <= 1))
        if at_edge and self.app.setting("edge_rollup") and self.app.setting("rollup_enabled"):
            if not self.data.get("rolled"):
                self.data["docked"] = True
                self.toggle_roll()
                dbg("docked at the screen edge: rolled up")
        elif self.data.get("docked"):
            self.data.pop("docked", None)
            if self.data.get("rolled"):
                self.toggle_roll()
                dbg("moved away from the screen edge: unrolled")

    def title_h(self):
        if not self.has_title():
            return 0
        return self.title_ev.get_allocated_height() or 28

    def min_h(self):
        """The smallest height: a cubby without a title bar can be a slim bar."""
        return 90 if self.has_title() else 40

    def has_title(self):
        """False for a cubby without a title bar (right-click › Options › Title Bar › None)."""
        return self.data.get("title_pos") != "none"

    def apply_title_mode(self):
        """Show or take away the whole title bar (a "show everything" must not bring it back)."""
        on = self.has_title()
        self.title_ev.set_no_show_all(not on)
        if not on:
            self.set_flipped(False)
            self.title_ev.hide()
        elif not self.title_ev.get_visible():
            self.title_ev.show_all()
            self.update_title()        # show_all() brought back parts that stay hidden

    def title_top(self, wy=None):
        """Where the title bar's top is on the screen now."""
        if wy is None:
            wy = self.get_position()[1]
        return wy + (self.get_size()[1] - self.title_h() if self._flipped else 0)

    def home_pos(self):
        """Window position from the saved data (y is the top of the full, unrolled cubby; a
        rolled-up bottom-title cubby sits where its title bar is)."""
        if self._ah_hidden:
            return self.ah_hidden_pos()          # auto-hide: slid out of sight
        x, y = self.data["x"], self.data["y"]
        if self._flipped and self.data.get("rolled") and not self._peeking:
            y += self.data["h"] - self.title_h()
        return x, y

    def store_geometry(self, x, y):
        """Save the place and size from where the window is now."""
        if self._ah_hidden or self._ah_anim:
            return               # slid away by auto-hide: that's not its place
        w, hc = self.get_size()
        th = self.title_h()
        rolled = bool(self.data.get("rolled")) and not self._peeking
        full_h = self.data.get("h", hc) if (rolled or self._peeking) else hc
        top = y + (hc - th if self._flipped else 0)          # the title bar's top
        y_full = top - (full_h - th) if self._flipped else top
        self.data.update(x=int(x), y=int(y_full), w=int(w))
        self.data.pop("displaced", None)     # placed by hand: this is its home now
        if not (rolled or self._peeking):
            self.data["h"] = int(full_h)

    def workarea(self):
        try:
            x, y = self.get_position()
            return Gdk.Display.get_default().get_monitor_at_point(x + 10, y + 10).get_workarea()
        except Exception:
            return None

    def forced_title_pos(self):
        """"top" or "bottom" when this cubby keeps its title bar in one place, else None."""
        if not self.app.setting("title_pos_choice"):
            return None
        pos = self.data.get("title_pos")
        return pos if pos in ("top", "bottom") else None

    @undoable("Title Bar Position")
    def set_title_pos(self, pos):
        """Title bar at the "top", the "bottom", "auto" (bottom only near the bottom of
        the screen) or "none" (no title bar at all). The cubby's box stays where it is."""
        if pos in ("top", "bottom", "none"):
            self.data["title_pos"] = pos
        else:
            self.data.pop("title_pos", None)
        if pos == "none" and self.data.get("rolled"):
            self.data["rolled"] = False            # nothing would be left to see
            self.sync_roll()
        self.apply_title_mode()
        self.apply_title_pos()
        self.app.save()

    def apply_title_pos(self):
        if not self.has_title():
            self.set_flipped(False)
            return
        forced = self.forced_title_pos()
        if forced:
            self.set_flipped(forced == "bottom")
        else:
            self.update_flip_for(self.title_top(), auto_only=True)

    def update_flip_for(self, title_top, auto_only=False):
        """While moving: the title goes to the bottom once the contents would run off the
        bottom of the screen, and back to the top when there is room again (unless this
        cubby keeps its title bar in one place)."""
        if not self.has_title():
            self.set_flipped(False)
            return
        forced = self.forced_title_pos()
        if forced:
            self.set_flipped(forced == "bottom")
            return
        wa = self.workarea()
        if wa is None:
            return
        th = self.title_h()
        rolled = bool(self.data.get("rolled")) and not self._peeking
        full_h = self.data.get("h", 200) if rolled else self.get_size()[1]
        bottom = wa.y + wa.height
        if not self._flipped and title_top + full_h > bottom + 2 \
                and title_top + th - full_h >= wa.y:
            self.set_flipped(True)
        elif self._flipped and title_top + full_h <= bottom:
            self.set_flipped(False)

    def edge_snap_y(self, ny, ch, reach=None):
        """"Snap to the top and bottom of the screen": a stronger pull to those two edges,
        from as far away as the "snap distance" setting says."""
        if reach is None:
            try:
                reach = max(1, min(400, int(self.app.cfg.get("edge_snap_px", 40))))
            except (TypeError, ValueError):
                reach = 40
        wa = self.workarea()
        if wa is None:
            return ny
        m = self.screen_margin()
        if abs(ny - (wa.y + m)) <= reach:
            return wa.y + m
        if abs(ny + ch - (wa.y + wa.height - m)) <= reach:
            return wa.y + wa.height - m - ch
        return ny

    def edge_snap_x(self, nx, cw, reach=None):
        """The same stronger pull to the left and right edges of the screen. (Pages still
        turn by holding the pointer itself against the edge.)"""
        if reach is None:
            try:
                reach = max(1, min(400, int(self.app.cfg.get("edge_snap_px", 40))))
            except (TypeError, ValueError):
                reach = 40
        wa = self.workarea()
        if wa is None:
            return nx
        m = self.screen_margin()
        if abs(nx - (wa.x + m)) <= reach:
            return wa.x + m
        if abs(nx + cw - (wa.x + wa.width - m)) <= reach:
            return wa.x + wa.width - m - cw
        return nx

    def set_flipped(self, on, save=True):
        on = bool(on)
        if on == getattr(self, "_flipped", None):
            return
        self._flipped = on
        outer = self.outer
        order = (self.content, self.kind_row, self.title_ev) if on else \
            (self.title_ev, self.kind_row, self.content)
        for i, child in enumerate(order):
            outer.reorder_child(child, i)
        ctx = self.title_ev.get_style_context()
        if on:
            ctx.add_class("flipped")
            self.kind_row.set_margin_top(0)
            self.kind_row.set_margin_bottom(5)
        else:
            ctx.remove_class("flipped")
            self.kind_row.set_margin_top(5)
            self.kind_row.set_margin_bottom(0)
        if on:
            self.data["flip"] = True
        else:
            self.data.pop("flip", None)
        dbg("title at the", "bottom" if on else "top", "for", self.data.get("title"))

    EDGE, CORNER = 6, 16
    ZONE_CURSORS = {"n": ("ns-resize", "sb_v_double_arrow"), "s": ("ns-resize", "sb_v_double_arrow"),
                    "e": ("ew-resize", "sb_h_double_arrow"), "w": ("ew-resize", "sb_h_double_arrow"),
                    "nw": ("nwse-resize", "size_fdiag"), "se": ("nwse-resize", "size_fdiag"),
                    "ne": ("nesw-resize", "size_bdiag"), "sw": ("nesw-resize", "size_bdiag")}

    def edge_zone(self, xr, yr):
        """Which edge/corner of the cubby the pointer is on ("n", "se", ...), or None."""
        if self.app.is_locked(self.data):
            return None
        x, y = self.get_position()
        w, h = self.get_size()
        lx, ly = xr - x, yr - y
        if not (0 <= lx < w and 0 <= ly < h):
            return None
        rolled = bool(self.data.get("rolled")) and not self._peeking
        E, C = self.EDGE, self.CORNER
        west, east = lx < E, lx >= w - E
        north = ly < E and not rolled
        south = ly >= h - E and not rolled
        if not rolled:
            if (west or east) and ly < C:
                north = True
            if (west or east) and ly >= h - C:
                south = True
            if (north or south) and lx < C:
                west = True
            if (north or south) and lx >= w - C:
                east = True
        zone = ("n" if north else "s" if south else "") + ("w" if west else "e" if east else "")
        return zone or None

    def title_cursor_at(self, x_root, y_root):
        """Over the name: a text bar with a small move arrow (drag to move, click again to
        rename). Elsewhere on the title bar: the four-way move pointer."""
        if self.on_name(x_root, y_root) and self._zone is None:
            cur = text_move_cursor(self.title_ev.get_display())
            if cur is not None:
                return (cur,)
        return ("move", "fleur")

    def update_title_cursor(self, x_root, y_root):
        if self._zone is not None:
            return                      # a resize pointer is showing (at the very edge)
        spec = self.title_cursor_at(x_root, y_root)
        if spec != getattr(self, "_title_cur", None):
            self._title_cur = spec
            set_cursor(self.title_ev.get_window(), *spec)

    def default_cursor_for(self, gdk_window):
        if gdk_window is not None and gdk_window == self.title_ev.get_window():
            self._title_cur = None
            return ("move", "fleur")
        return (None,)

    def show_zone_cursor(self, zone, gdk_window):
        if self._zone_win is not None and (gdk_window != self._zone_win or not zone):
            set_cursor(self._zone_win, *self.default_cursor_for(self._zone_win))
            self._zone_win = None
        if zone:
            set_cursor(gdk_window, *self.ZONE_CURSORS[zone])
            self._zone_win = gdk_window
        self._zone = zone

    @staticmethod
    def _cur_event():
        ev = Gtk.get_current_event()
        return ev if ev is not None and hasattr(ev, "x_root") else None

    def on_edge_motion(self, _ctl, _x, _y):
        if self._drag:
            return
        ev = self._cur_event()
        if ev is None or (ev.state & Gdk.ModifierType.BUTTON1_MASK):
            return
        zone = self.edge_zone(ev.x_root, ev.y_root)
        if zone != self._zone or (zone and ev.window != self._zone_win):
            self.show_zone_cursor(zone, ev.window)

    def on_edge_begin(self, gesture, _x, _y):
        ev = self._cur_event()
        zone = self.edge_zone(ev.x_root, ev.y_root) if ev is not None else None
        if not zone or self._drag:
            gesture.set_state(Gtk.EventSequenceState.DENIED)   # not an edge: carry on as usual
            return
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        x, y = self.get_position()
        w, h = self.get_size()
        self._drag = ("edges", ev.x_root, ev.y_root, x, y, w, h, zone)
        self.show_zone_cursor(zone, ev.window)

    def on_edge_update(self, _gesture, _ox, _oy):
        if self._drag and self._drag[0] == "edges":
            ev = self._cur_event()
            if ev is not None:
                self.edge_resize_motion(ev)

    def on_edge_end(self, _gesture, _ox, _oy):
        if self._drag and self._drag[0] == "edges":
            self._drag = None
            undo = self.app.undo_begin("Resize Cubby")
            x, y = self.get_position()
            self.store_geometry(x, y)
            self.app.save()
            self.app.undo_end(undo)
            if self.data.get("launchbar"):
                GLib.timeout_add(60, lambda: self.app.keep_bar_on_edge(self.data) and False)

    def edge_resize_motion(self, event):
        _k, sx, sy, x0, y0, w0, h0, zone = self._drag
        dx, dy = event.x_root - sx, event.y_root - sy
        snap = not (event.state & Gdk.ModifierType.SHIFT_MASK)
        xs, ys, _ws, _hs = (self.snap_targets() if snap else
                            ({"lo": [], "hi": []}, {"lo": [], "hi": []}, [], []))
        rolled = bool(self.data.get("rolled")) and not self._peeking
        minw, minh = 130, (h0 if rolled else self.min_h())
        x, y, w, h = x0, y0, w0, h0
        if "e" in zone:
            r = x0 + w0 + dx
            r += best_snap([(r, t) for t in xs["hi"]])
            w = max(minw, int(r - x0))
        if "w" in zone:
            left = x0 + dx
            left += best_snap([(left, t) for t in xs["lo"]])
            left = min(int(left), x0 + w0 - minw)
            x, w = left, x0 + w0 - left
        if "s" in zone:
            b = y0 + h0 + dy
            b += best_snap([(b, t) for t in ys["hi"]])
            h = max(minh, int(b - y0))
        if "n" in zone:
            top = y0 + dy
            top += best_snap([(top, t) for t in ys["lo"]])
            top = min(int(top), y0 + h0 - minh)
            y, h = top, y0 + h0 - top
        if (x, y) != (x0, y0) or (x, y) != tuple(self.get_position()):
            self.move(int(x), int(y))
        self.resize(int(w), int(h))

    def edge_side(self, x_root):
        if not self.app.setting("pages_enabled"):
            return None
        try:
            width = self.get_screen().get_width()
        except Exception:
            return None
        if x_root <= 4:
            return "left"
        if x_root >= width - 5:
            return "right"
        return None

    def snap_gap(self):
        try:
            return max(0, min(200, int(self.app.cfg.get("snap_gap", 0))))
        except (TypeError, ValueError):
            return 0

    def screen_margin(self):
        return self.snap_gap() if self.app.setting("gap_screen") else 0

    def snap_targets(self):
        """Where this cubby's edges can stick: xs["lo"] / ys["lo"] are spots for its left /
        top edge, xs["hi"] / ys["hi"] for its right / bottom edge. Edges line up with other
        cubbies' edges, or sit beside them with the chosen gap in between. Also the sizes of
        the other cubbies, and the top and bottom of the screen."""
        g = self.snap_gap()
        xs, ys, widths, heights = {"lo": [], "hi": []}, {"lo": [], "hi": []}, [], []
        for win in self.app.windows.values():
            if win is self or not win.get_visible() or not self.app.setting("snap_cubbies"):
                continue
            if win._ah_hidden:
                ox, oy = win.data["x"], win.data["y"]    # slid away: its real place counts
            else:
                ox, oy = win.get_position()
            ow, oh = win.get_size()
            xs["lo"] += [ox, ox + ow + g]       # lined up with its left / just right of it
            xs["hi"] += [ox + ow, ox - g]       # lined up with its right / just left of it
            ys["lo"] += [oy, oy + oh + g]
            ys["hi"] += [oy + oh, oy - g]
            widths.append(ow)
            heights.append(oh)
        try:
            x, y = self.get_position()
            mon = Gdk.Display.get_default().get_monitor_at_point(x, y)
            wa = mon.get_workarea()
            m = self.screen_margin()
            ys["lo"].append(wa.y + m)
            ys["hi"].append(wa.y + wa.height - m)
            if self.app.setting("edge_snap_sides"):
                xs["lo"].append(wa.x + m)
                xs["hi"].append(wa.x + wa.width - m)
        except Exception:
            pass
        return xs, ys, widths, heights

    def on_release(self, widget, event):
        if self._drag and self._drag[0] == "locked":
            self._drag = None
            self.after_title_click(event)
            return True
        if self._drag:
            kind = self._drag[0]
            moved = abs(event.x_root - self._drag[1]) + abs(event.y_root - self._drag[2]) > 6
            self._drag = None
            target, self._merge_target = self._merge_target, None
            if target is not None:
                target.set_merge_hint(False)
            side = None
            group, self._group = getattr(self, "_group", None), None
            if kind == "move" and target is None and moved and not self._edge_locked \
                    and not group:
                side = self.edge_side(self.pointer_x(event.x_root)) or self.edge_side(event.x_root)
            dbg("released; edge:", side)
            if kind == "move" and not moved and event.button == 1:
                if event.state & Gdk.ModifierType.CONTROL_MASK:
                    self.app.toggle_picked(self)   # Ctrl + click: pick for moving together
                else:
                    self.after_title_click(event)
            self._press_on_name = False
            if self._edge_poll:
                GLib.source_remove(self._edge_poll)
                self._edge_poll = 0
            self.app.show_edge_hint(None)
            x, y = self.get_position()
            last, self._last_move = getattr(self, "_last_move", None), None
            if kind == "move" and moved and last and not getattr(self, "_hopped", False):
                x, y = last
            w, h = self.get_size()
            undo = (self.app.undo_begin("Move Cubby" if kind == "move" else "Resize Cubby")
                    if moved and not getattr(self, "_hopped", False) else None)
            if group and moved:
                for win, _ox, _oy in group:
                    gx, gy = win.get_position()
                    win.store_geometry(gx, gy)
            if kind == "move" and getattr(self, "_hopped", False) and not side:
                # carried over from another page and let go hanging off the edge: pull it in
                try:
                    sw = self.get_screen().get_width()
                except Exception:
                    sw = x + w
                nx = min(max(0, x), max(0, sw - w))
                if nx != x:
                    x = nx
                    self.move(x, y)
            self._hopped = False
            self.store_geometry(x, y)
            if kind == "move" and not side and target is None:
                self.check_edge_dock()
            self.app.save()
            self.app.undo_end(undo)
            if self.data.get("launchbar"):
                GLib.timeout_add(60, lambda: self.app.keep_bar_on_edge(self.data) and False)
            if target is not None and kind == "move":
                GLib.idle_add(self.app.merge_cubbies, self.data, target.data)
            elif side:
                GLib.idle_add(self.app.move_cubby_to_edge, self.data, side)
        return True

    def toggle_roll(self):
        if not self.data.get("rolled") and (not self.app.setting("rollup_enabled")
                                            or not self.has_title()):
            return                      # rolling up is turned off (unrolling still works)
        if not self.data.get("rolled"):
            w, h = self.get_size()
            self.data.update(w=w, h=h)
        self.data["rolled"] = not self.data.get("rolled", False)
        self.sync_roll()
        self.app.save()

    def sync_roll(self):
        """Show only the title bar while rolled up; otherwise the whole cubby."""
        rolled = bool(self.data.get("rolled"))
        self._peeking = False
        GLib.idle_add(lambda: self.update_title_visibility() and False)
        ctx = self.title_ev.get_style_context()
        if rolled:
            ctx.add_class("rolled")
        else:
            ctx.remove_class("rolled")
        self.content.set_visible(not rolled)
        self.kind_row.set_visible(bool(self.kind_box.get_children()) and not rolled)
        self.apply_title_mode()
        if rolled:
            self.set_size_request(130, -1)
            self.resize(self.data["w"], 1)
        else:
            self.set_size_request(130, self.min_h())
            self.resize(self.data["w"], self.data["h"])
        if self.get_visible() and self._flipped:
            # a bottom-title cubby rolls up downwards / opens upwards. Moved a moment after
            # the resize: asking for both at once makes the window manager drop the resize.
            GLib.timeout_add(40, lambda: self.move(*self.home_pos()) and False)

    def on_scroll(self, widget, event):
        if self.app.handle_swipe(event):
            return True
        step = scroll_direction(event)
        if step and self.app.setting("wheel_pages"):
            self.app.change_page(step)
        return True
