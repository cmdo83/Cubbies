"""The page switcher: the dots / names that show which page you're on."""

from gi.repository import Gdk, GLib, Gtk, Pango

from .core import HINT, dbg
from .widgets import SCROLL_MASKS, menu_item, page_key_step, scroll_direction, set_cursor


class Pager(Gtk.Window):
    def __init__(self, app):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.app = app
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(HINT)
        self.set_app_paintable(True)
        self.stick()
        self.set_keep_below(True)
        self.set_accept_focus(True)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.get_style_context().add_class("cubbywin")

        ev = Gtk.EventBox()
        ev.set_visible_window(False)
        ev.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | SCROLL_MASKS
                      | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
        ev.connect("scroll-event", self.on_scroll)
        ev.connect("button-press-event", self.on_press)
        ev.connect("motion-notify-event", self.on_drag_motion)
        ev.connect("button-release-event", self.on_drag_release)
        self._press = None         # (x_root, y_root, x, y) while the left button is down
        self._dragging = False
        self.add_events(Gdk.EventMask.KEY_PRESS_MASK)
        self.connect("key-press-event", self.on_key)
        self.add(ev)

        row = Gtk.Box(spacing=4)
        row.get_style_context().add_class("pager")
        row.set_border_width(2)
        left = Gtk.Button(label="◀")
        right = Gtk.Button(label="▶")
        left.set_relief(Gtk.ReliefStyle.NONE)
        right.set_relief(Gtk.ReliefStyle.NONE)
        left.connect("clicked", lambda _b: app.change_page(-1, force=True))
        right.connect("clicked", lambda _b: app.change_page(1, force=True))
        # the page name (double-click: that page's settings) and a dot per page (click one
        # to go there; pointing at one shows its name in place of this page's)
        self.label = Gtk.Label()
        self.label.set_ellipsize(Pango.EllipsizeMode.END)
        name_ev = Gtk.EventBox()
        name_ev.set_visible_window(False)
        name_ev.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        name_ev.connect("button-press-event", self.on_name_press)
        name_ev.add(self.label)
        self.dots = Gtk.Box(spacing=0)
        self.dot_labels = []
        self.hover_dot = None
        self.note = Gtk.Label()
        mid = Gtk.Box(spacing=10)
        mid.pack_start(name_ev, False, False, 0)
        mid.pack_start(self.dots, False, False, 0)
        mid.pack_start(self.note, False, False, 0)
        row.pack_start(left, False, False, 0)
        row.pack_start(mid, True, False, 6)
        row.pack_start(right, False, False, 0)
        ev.add(row)
        self.connect("size-allocate", self.reposition)
        # auto-hide state
        self._top_since = None     # when the pointer first touched the top edge
        self._reveal_until = 0     # keep showing until this time (ms)
        self.menu_open = False

    # -- auto-hide: only visible while the pointer rests at the top edge, briefly after a
    #    page change, or while the pointer / its menu is on it
    def flash(self, ms=1800):
        self._reveal_until = max(self._reveal_until, GLib.get_monotonic_time() // 1000 + ms)

    def set_revealed(self, want):
        if want and not self.get_visible():
            self.show_all()
            self.reposition()
            self.set_keep_above(True)
        elif not want and self.get_visible():
            self.set_keep_above(False)
            self.hide()

    def show_mode(self):
        """"auto" (comes out at the screen edge), "always", or "key" (only with a key)."""
        mode = self.app.cfg.get("pager_show")
        if mode in ("auto", "always", "key"):
            return mode
        return "auto" if self.app.setting("pager_autohide") else "always"

    def key_toggle(self):
        """The page bar key (or  cubbies --page-bar): show it for a while, or hide it."""
        now = GLib.get_monotonic_time() // 1000
        if self.get_visible() and now < self._reveal_until:
            self._reveal_until = 0
            if self.show_mode() != "always":
                self.set_revealed(False)
        else:
            self._reveal_until = now + 5000
            self.set_revealed(True)

    def launch_bar_busy(self, px, py):
        """True while any launch bar is out (auto-hide showing it) or the pointer is on one:
        the page bar stays away then, wherever it sits."""
        for win in self.app.windows.values():
            if not win.data.get("launchbar") or not win.get_visible() or win._ah_hidden:
                continue
            if win.data.get("autohide") and win.ah_edge() is not None:
                return True
            x, y = win.get_position()
            w, h = win.get_size()
            if x <= px < x + w and y <= py < y + h:
                return True
        return False

    def bars_at(self, edge, x, w):
        """Launch bars / auto-hiding cubbies along that screen edge, under the page bar."""
        out = []
        for win in self.app.windows.values():
            if not win.get_visible() or not (win.data.get("autohide")
                                             or win.data.get("launchbar")):
                continue
            e = win.screen_edge()
            if e is None or e[0] != edge:
                continue
            bx, bw = int(win.data["x"]), win.get_size()[0]
            if bx < x + w and x < bx + bw:
                out.append(win)
        return out

    def place(self):
        """(x, y, edge, monitor geometry, workarea): where the page bar goes right now."""
        cfg = self.app.cfg
        self._under = None
        display = Gdk.Display.get_default()
        mon = display.get_primary_monitor() or display.get_monitor(0)
        geo, wa = mon.get_geometry(), mon.get_workarea()
        w, h = self.get_size()
        if cfg.get("pager_pos") == "custom" and "pager_x" in cfg:
            try:
                return int(cfg["pager_x"]), int(cfg["pager_y"]), None, geo, wa
            except (TypeError, ValueError):
                pass
        edge = "bottom" if cfg.get("pager_pos") == "bottom" else "top"
        x = geo.x + (geo.width - w) // 2
        how = cfg.get("pager_bar", "under")
        bars = self.bars_at(edge, x, w) if how != "over" else []
        if bars and how == "under":
            # tucked just under the launch bar: under its hidden strip while it's hidden
            # (rest the pointer there to bring the page bar out), under the whole bar when
            # the bar doesn't auto-hide; out of the way while the bar is out
            b = bars[0]
            by, bh = int(b.data["y"]), b.get_size()[1]
            hidden = b.data.get("autohide") and b._ah_hidden
            shown_ah = b.data.get("autohide") and not b._ah_hidden
            reach = b.ah_strip() if hidden else bh
            if edge == "top":
                y = by + reach + 6
            else:
                y = by + bh - reach - h - 6
            self._under = {"suppress": bool(shown_ah)}
            return x, y, edge, geo, wa
        if bars and how == "other":           # a launch bar there: use the other edge
            edge = "top" if edge == "bottom" else "bottom"
            bars = self.bars_at(edge, x, w)
        y = geo.y + 10 if edge == "top" else wa.y + wa.height - h - 10
        for b in bars:
            if b._ah_hidden:
                continue
            by, bh = int(b.data["y"]), b.get_size()[1]
            y = max(y, by + bh + 6) if edge == "top" else min(y, by - h - 6)
        return x, y, edge, geo, wa

    def tick(self):
        try:
            app = self.app
            mode = self.show_mode()
            x, y, edge, geo, wa = self.place()
            if not app.watcher.supported or mode == "always":
                self.set_revealed(True)
                if not self._dragging and tuple(self.get_position()) != (x, y):
                    self.move(x, y)
                return True
            now = GLib.get_monotonic_time() // 1000
            _w, px, py, _m = app.watcher.root.get_device_position(app.watcher.pointer)
            pw, ph = self.get_size()
            cx = x + pw // 2
            half = max(pw, 200) // 2 + 100
            under = getattr(self, "_under", None)
            if (not self._dragging and app.cfg.get("pager_bar", "under") != "with"
                    and self.launch_bar_busy(px, py)):
                under = {"suppress": True}     # a launch bar is out, or the pointer's on one
            if under is not None and under["suppress"] and not self._dragging:
                self._reveal_until = 0             # the launch bar is out: no page bar
                self._top_since = None
                self.set_revealed(bool(self.menu_open))
                return True
            if mode == "key":
                at_edge = False
            elif under is not None:            # rest the pointer just under the launch bar
                at_edge = x - 20 <= px <= x + pw + 20 and y - 8 <= py <= y + ph + 6
            elif edge == "top":
                at_edge = py <= geo.y + 1 and abs(px - cx) <= half
            elif edge == "bottom":
                bottom, screen_b = wa.y + wa.height, geo.y + geo.height
                at_edge = abs(px - cx) <= half and (
                    py >= screen_b - 2 if bottom >= screen_b - 1 else bottom - 4 <= py <= bottom + 1)
            else:                         # put somewhere by hand: rest the pointer there
                at_edge = x - 4 <= px <= x + pw + 4 and y - 4 <= py <= y + ph + 4
            if at_edge:
                if self._top_since is None:
                    self._top_since = now
            else:
                self._top_since = None
            if self.get_visible():
                vx, vy = self.get_position()
            else:
                vx, vy = x, y
            on_pager = (self.get_visible() and vx - 4 <= px <= vx + pw + 4
                        and vy - 4 <= py <= vy + ph + 4)
            dwell = self._top_since is not None and now - self._top_since >= 250
            if dwell or on_pager:
                self._reveal_until = max(self._reveal_until, now + 700)  # grace while moving
            if (mode == "auto" and edge and app.cfg.get("pager_bar", "under") == "with"
                    and any(b.data.get("autohide") and not b._ah_hidden
                            for b in self.bars_at(edge, x, pw))):
                # comes out together with the launch bar along its edge
                self._reveal_until = max(self._reveal_until, now + 300)
            self.set_revealed(bool(self.menu_open or self._dragging or now < self._reveal_until))
            if self.get_visible() and not self._dragging and (vx, vy) != (x, y):
                self.move(x, y)
        except Exception as exc:  # never let the timer die
            dbg("pager auto-hide error:", repr(exc))
        return True

    def reposition(self, *_args):
        if self._dragging:
            return
        x, y = self.place()[:2]
        self.move(x, y)

    # -- drag the page bar to put it anywhere (Settings › Desktop Pages puts it back)
    def on_drag_motion(self, _w, event):
        p = self._press
        if p is None:
            return False
        dx, dy = event.x_root - p[0], event.y_root - p[1]
        if not self._dragging and abs(dx) + abs(dy) > 6:
            self._dragging = True
            set_cursor(self.get_window(), "move", "fleur")
        if self._dragging:
            self.move(int(p[2] + dx), int(p[3] + dy))
        return True

    def on_drag_release(self, _w, event):
        p, self._press = self._press, None
        if not self._dragging or event.button != 1:
            return False
        self._dragging = False
        set_cursor(self.get_window(), None)
        x, y = self.get_position()
        cfg = self.app.cfg
        cfg.update(pager_pos="custom", pager_x=int(x), pager_y=int(y))
        self.app.save()
        self.flash(1500)
        return True

    NAME_MAX_PX = 280    # longer page names are cut short with …

    def update(self):
        cfg = self.app.cfg
        n = len(cfg["pages"])
        if len(self.dot_labels) != n:               # a dot per page, each one clickable
            for c in self.dots.get_children():
                self.dots.remove(c)
                c.destroy()
            self.dot_labels = []
            self.hover_dot = None
            for i in range(n):
                ev = Gtk.EventBox()
                ev.set_visible_window(False)
                ev.add_events(Gdk.EventMask.BUTTON_PRESS_MASK
                              | Gdk.EventMask.BUTTON_RELEASE_MASK
                              | Gdk.EventMask.ENTER_NOTIFY_MASK
                              | Gdk.EventMask.LEAVE_NOTIFY_MASK)
                lbl = Gtk.Label()
                lbl.set_size_request(14, -1)         # a fair target for the pointer
                ev.add(lbl)
                ev.connect("button-press-event", lambda _w, e: e.button == 1)  # not a drag
                ev.connect("button-release-event", lambda _w, e, i=i: self.on_dot_click(i, e))
                ev.connect("enter-notify-event", lambda _w, _e, i=i: self.on_dot_hover(i))
                ev.connect("leave-notify-event", lambda _w, e, i=i: self.on_dot_leave(i, e))
                self.dots.pack_start(ev, False, False, 0)
                self.dot_labels.append(lbl)
            self.dots.show_all()
        # the name keeps the width of the longest name, so the bar (and its dots) stay put
        # while names change under the pointer
        widest = 0
        for p in cfg["pages"]:
            lay = self.label.create_pango_layout(None)
            lay.set_markup(f"<b>{GLib.markup_escape_text(p.get('name') or 'Page')}</b>", -1)
            widest = max(widest, lay.get_pixel_size()[0])
        self.label.set_size_request(min(widest, self.NAME_MAX_PX), -1)
        self.show_dots()
        self.note.set_markup("<small>(cubbies hidden)</small>" if self.app.hidden else "")
        self.note.set_visible(bool(self.app.hidden))

    def show_dots(self):
        cfg = self.app.cfg
        hv = self.hover_dot
        for i, lbl in enumerate(self.dot_labels):
            if i == cfg["page"]:
                mark = "<span weight='normal'>\u25cf</span>"                  # ●
            elif i == hv:
                mark = "<span weight='normal' alpha='75%'>\u25cf</span>"      # ● (pointed at)
            else:
                mark = "<span weight='normal' alpha='80%'>\u25cb</span>"      # ○
            lbl.set_markup(f"<small>{mark}</small>")
        pages = cfg["pages"]
        if hv is not None and 0 <= hv < len(pages) and hv != cfg["page"]:
            name = GLib.markup_escape_text(pages[hv].get("name") or "Page")
            self.label.set_markup(f"<span alpha='75%'><i>{name}</i></span>")
        else:
            self.label.set_markup(GLib.markup_escape_text(self.app.page()["name"]))

    def on_dot_hover(self, i):
        self.hover_dot = i
        if not self._dragging:
            set_cursor(self.get_window(), "pointer", "hand2")
        self.show_dots()
        return False

    def on_dot_leave(self, i, event):
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False
        if self.hover_dot == i:
            self.hover_dot = None
            if not self._dragging:
                set_cursor(self.get_window(), None)
            self.show_dots()
        return False

    def on_dot_click(self, i, event):
        """Click a dot: go straight to that page."""
        if event.button != 1:
            return False
        self._press = None
        cur = self.app.cfg["page"]
        if 0 <= i < len(self.app.cfg["pages"]) and i != cur:
            self.app.change_page(i - cur, force=True)
        self.flash(1500)
        return True

    def on_name_press(self, _w, event):
        """Double-click the page name: Manage Pages."""
        if event.button == 1 and event.type == Gdk.EventType._2BUTTON_PRESS:
            self._press = None
            self._dragging = False
            GLib.timeout_add(150, lambda: self.app.open_page_order("order") and False)
            return True
        return False

    def on_scroll(self, widget, event):
        if self.app.handle_swipe(event):
            return True
        step = scroll_direction(event)
        if step and self.app.setting("wheel_pages"):
            self.app.change_page(step)
        return True

    def on_key(self, widget, event):
        step = page_key_step(event)
        if step:
            self.app.change_page(step, force=True)
            return True
        return False

    def on_press(self, widget, event):
        if event.button == 1 and event.type == Gdk.EventType.BUTTON_PRESS:
            self._press = (event.x_root, event.y_root) + tuple(self.get_position())
            return True
        if event.button != 3:
            return False
        menu = Gtk.Menu()
        undo = self.app.undo_label()
        entries = ([((f"Undo {undo}", ("edit-undo",)), self.app.undo), (None, None)]
                   if undo else []) + [
            (("New Page\u2026", ("tab-new", "document-new")), self.app.new_page),
            (("Manage Pages\u2026", ("view-grid", "view-list-symbolic", "document-edit")),
             lambda: GLib.timeout_add(150, lambda: self.app.open_page_order() and False)),
            (("Page Bar Position", ("view-restore", "go-top")), "pos-sub"),
            (None, None),
            (("New Cubby", ("list-add", "window-new")), "new-sub"),
            (None, None),
            (("Settings\u2026", ("preferences-system", "preferences-other")), self.app.open_settings),
            (None, None),
            (("Quit Cubbies", ("application-exit", "window-close")), Gtk.main_quit),
        ]
        for label, cb in entries:
            if label is None:
                menu.append(Gtk.SeparatorMenuItem())
                continue
            mi = menu_item(label[0], *label[1])
            if cb == "pos-sub":
                pos_sub = Gtk.Menu()
                now = self.app.cfg.get("pager_pos", "top")
                group, radios = None, []
                for key, text in (("top", "Top Centre"), ("bottom", "Bottom Centre"),
                                  ("custom", "Where I Drag It")):
                    ri = Gtk.RadioMenuItem.new_with_label_from_widget(group, text)
                    group = group or ri
                    ri.set_active(key == now)
                    radios.append((ri, key))
                    pos_sub.append(ri)
                for ri, key in radios:        # connected after the tick is set (see notes)
                    ri.connect("activate", lambda w, k=key: w.get_active()
                               and self.app.set_pager_pos(k))
                mi.set_submenu(pos_sub)
                menu.append(mi)
                continue
            if cb == "new-sub":
                sub = Gtk.Menu()
                for text, icons, act, ok in (
                        ("Cubby", ("list-add", "window-new"), self.app.new_cubby, True),
                        ("Folder Cubby\u2026", ("folder-new", "folder"),
                         self.app.new_folder_cubby, True),
                        ("Inbox Cubby", ("mail-inbox", "folder-download", "document-save"),
                         self.app.new_inbox_cubby, True),
                        ("Recent Files Cubby", ("document-open-recent", "appointment-soon"),
                         self.app.new_recent_cubby, True),
                        ("Launch Bar Cubby", ("go-top", "view-fullscreen"),
                         self.app.new_launch_bar, self.app.can_make_launch_bar())):
                    si = menu_item(text, *icons)
                    si.connect("activate", lambda _w, a=act: a())
                    si.set_sensitive(ok)
                    if not ok:
                        si.set_tooltip_text("This page already has a launch bar. Settings "
                                            "\u203a Launch Bar Cubbies chooses which pages "
                                            "share which bar.")
                    sub.append(si)
                mi.set_submenu(sub)
                menu.append(mi)
                continue
            mi.connect("activate", lambda _w, c=cb: c())
            menu.append(mi)
        menu.show_all()
        self.menu_open = True
        menu.connect("deactivate", lambda _m: (setattr(self, "menu_open", False), self.flash(1500)))
        menu.popup_at_pointer(event)
        return True
