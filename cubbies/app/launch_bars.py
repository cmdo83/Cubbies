"""Auto-hiding cubbies and launch bars."""

from gi.repository import Gdk, GLib, Gtk

from ..constants import LINE_KEYS, MAX_ICON, MIN_ICON
from ..core import dbg, undoable
from ..cubby.cubby import Cubby


class AppLaunchBars:
    """Auto-hide and launch bars. Part of App."""

    # -- auto-hide (cubbies at the top / bottom edge that slide away) and launch bars
    _ah_timer = 0

    def autohide_start(self):
        """Watch the pointer for auto-hiding cubbies (only while there are any)."""
        watcher = getattr(self, "watcher", None)
        if self._ah_timer or watcher is None or not watcher.supported:
            return
        if any(w.data.get("autohide") for w in self.windows.values()):
            self._ah_timer = GLib.timeout_add(40, self.autohide_tick)

    def autohide_tick(self):
        wins = [w for w in self.windows.values() if w.data.get("autohide") or w._ah_hidden]
        if not wins:
            self._ah_timer = 0
            return False
        try:
            _w, px, py, _m = self.watcher.root.get_device_position(self.watcher.pointer)
            now = GLib.get_monotonic_time() // 1000
            down = bool(_m & Gdk.ModifierType.BUTTON1_MASK)
            for win in wins:
                if win.get_visible():
                    win.ah_tick(px, py, now, down)
        except Exception as exc:          # never let the timer die
            dbg("auto-hide error:", repr(exc))
        return True

    def rebuild_window(self, fdata):
        """Make a cubby's window again from its data (after a big change to it)."""
        win = self.windows.pop(fdata["id"], None)
        if win is not None:
            win.destroy()
        self.show_page()
        return self.windows.get(fdata["id"])

    def launch_bar_icon(self):
        try:
            return max(MIN_ICON, min(MAX_ICON, int(self.cfg.get("launchbar_icon", 48))))
        except (TypeError, ValueError):
            return 48

    def make_launch_bar(self, fdata):
        """One step: no title bar, along the top (or bottom) of the screen, auto-hiding,
        on every page, and still there during Quick-hide. Settings › Launch Bars says how."""
        pane = self.active_pane(fdata)
        prev = {k: fdata[k] for k in Cubby.LB_KEYS if k in fdata}
        prev["pane"] = {k: pane[k] for k in ("icon_size", "view", "names", "sort")
                        if k in pane and pane is not fdata}
        fdata["lb_prev"] = prev
        fdata["launchbar"] = True
        fdata["title_pos"] = "none"
        fdata.pop("rolled", None)
        fdata.pop("docked", None)
        fdata.pop("flip", None)
        if self.cfg.get("launchbar_autohide", True):
            fdata["autohide"] = True
        else:
            fdata.pop("autohide", None)
        fdata.pop("all_pages", None)           # (which pages: bar_all / bar_pages)
        if "bar_all" not in fdata and "bar_pages" not in fdata:
            if any(g is not fdata for g in self.launch_bars()):
                fdata["bar_pages"] = [self.page_id(self.page())]
            else:
                fdata["bar_all"] = True        # the first launch bar: on every page
        fdata["keep_visible"] = True
        for k in LINE_KEYS:
            if k in self.cfg:
                fdata[k] = self.cfg[k]
        size = self.launch_bar_icon()
        pane["icon_size"] = size
        pane.pop("view", None)                 # icons
        if not self.cfg.get("launchbar_names", True):
            pane["names"] = False
        else:
            pane.pop("names", None)
        names = pane.get("names", True) is not False
        # a first guess at the size; fitted to the real icons once they are shown
        h = size + (58 if names else 26)
        self.place_launch_bar(fdata, h)
        self.save()
        win = self.rebuild_window(fdata)
        if win is not None:
            GLib.timeout_add(350, lambda: self.fit_launch_bar(fdata) and False)

    def bar_monitor(self, fdata):
        try:
            x, y = int(fdata.get("x", 0)), int(fdata.get("y", 0))
            w, h = int(fdata.get("w", 300)), int(fdata.get("h", 200))
            mon = Gdk.Display.get_default().get_monitor_at_point(x + w // 2, y + h // 2)
            return mon.get_workarea()
        except Exception:
            return None

    def place_launch_bar(self, fdata, h, w=None):
        wa = self.bar_monitor(fdata)
        if wa is None:
            return
        m = self.snap_gap_value() if self.setting("gap_screen") else 0
        if w is None or self.cfg.get("launchbar_width", "full") == "full":
            x, w = wa.x, wa.width
        else:
            w = max(160, min(wa.width, int(w)))
            x = wa.x + (wa.width - w) // 2
        edge = self.cfg.get("launchbar_edge", "top")
        y = wa.y + m if edge != "bottom" else wa.y + wa.height - m - h
        fdata.update(x=int(x), y=int(y), w=int(w), h=int(h))

    def keep_bar_on_edge(self, fdata):
        """Put a launch bar back against its edge (top or bottom of the work area) if it has
        drifted off it: the screen was resized, a panel appeared or moved, the theme made it
        taller, or it was dragged. True when it had to be moved."""
        win = self.windows.get(fdata.get("id"))
        if win is None or not fdata.get("launchbar") or not win.get_visible():
            return False
        if win._drag or win._ah_anim or win.ah_busy():
            return False
        try:
            rw, rh = win.get_size()
        except Exception:
            return False
        h = max(int(fdata.get("h", rh)), rh)
        old = (fdata.get("x"), fdata.get("y"), fdata.get("w"), fdata.get("h"))
        self.place_launch_bar(fdata, h, int(fdata.get("w", rw)))
        new = (fdata.get("x"), fdata.get("y"), fdata.get("w"), fdata.get("h"))
        moved = new != old
        if moved:
            dbg("launch bar back on its edge:", old, "->", new)
            self.save()
            if (rw, rh) != (fdata["w"], fdata["h"]):
                win.resize(fdata["w"], fdata["h"])
        if moved or tuple(win.get_position()) != tuple(win.home_pos()):
            GLib.timeout_add(40, lambda: win.move(*win.home_pos()) and False)
            moved = True
        return moved

    def bars_tick(self):
        """Every second: launch bars stay on their edge."""
        try:
            for f in self.launch_bars():
                self.keep_bar_on_edge(f)
        except Exception as exc:          # never let the timer die
            dbg("launch bar check:", repr(exc))
        return True

    def snap_gap_value(self):
        try:
            return max(0, min(200, int(self.cfg.get("snap_gap", 0))))
        except (TypeError, ValueError):
            return 0

    def fit_launch_bar(self, fdata):
        """Make a new launch bar just tall enough for one row of its icons (and, if chosen,
        just wide enough for them)."""
        win = self.windows.get(fdata["id"])
        if win is None or not fdata.get("launchbar"):
            return
        kids = win.flow.get_children()
        if kids:
            ch = max(k.get_preferred_height()[1] for k in kids)
            cw = max(k.get_preferred_width()[1] for k in kids)
            extra = max(0, win.get_allocated_height() - win.sw.get_allocated_height())
            h = max(win.min_h(), extra + ch + 8 + 4 + 6)
            w = len(kids) * (cw + win.flow.get_column_spacing()) + 30
        else:                              # empty: as tall as one row of icons would be
            names = self.active_pane(fdata).get("names", True) is not False
            h, w = self.launch_bar_icon() + (58 if names else 26), 360
        self.place_launch_bar(fdata, h, w)
        self.save()
        win._ah_hidden = False
        win.resize(fdata["w"], fdata["h"])
        GLib.timeout_add(40, lambda: win.move(fdata["x"], fdata["y"]) and False)
        self.autohide_start()

    def unmake_launch_bar(self, fdata):
        prev = fdata.pop("lb_prev", None) or {}
        pane = self.active_pane(fdata)
        for k in Cubby.LB_KEYS:
            if k in prev:
                fdata[k] = prev[k]
            elif k not in ("x", "y", "w", "h"):
                fdata.pop(k, None)
        for k in ("icon_size", "view", "names", "sort"):
            if pane is fdata:
                continue
            if k in prev.get("pane", {}):
                pane[k] = prev["pane"][k]
            else:
                pane.pop(k, None)
        fdata.pop("launchbar", None)
        if not prev:                       # (made as a launch bar: give it a normal shape)
            fdata["h"] = max(220, int(fdata.get("h", 0)))
            fdata["w"] = min(int(fdata.get("w", 300)), 480)
            fdata["y"] = int(fdata.get("y", 0)) + 60
        self.save()
        self.rebuild_window(fdata)

    def launch_bars(self):
        return [f for p in self.cfg["pages"] for f in p["cubbies"]
                if f.get("launchbar") and not f.get("tab_of")]

    def bar_for_page(self, page):
        """The launch bar shown on a page: one that lists the page, else the "every page"
        bar, else None. (A page has at most one launch bar.)"""
        pid = self.page_id(page)
        bars = self.launch_bars()
        for f in bars:
            if pid in f.get("bar_pages", []):
                return f
        return next((f for f in bars if f.get("bar_all")), None)

    def bar_covers(self, f):
        """The pages a launch bar is shown on."""
        return [p for p in self.cfg["pages"] if self.bar_for_page(p) is f]

    def migrate_bars(self):
        """Launch bars from before page groups: one for every page, or one per page."""
        per_page = self.cfg.pop("launchbar_per_page", False)
        first = True
        for f in self.launch_bars():
            if "bar_pages" in f or "bar_all" in f:
                continue
            if per_page:
                f["bar_pages"] = [self.page_id(self.page_of(f))]
            elif f.get("all_pages") or first:
                f["bar_all"] = True
                first = False
            else:
                f["bar_pages"] = []          # set aside: Settings can give it pages
            f.pop("all_pages", None)

    def can_make_launch_bar(self):
        """Only for a page that has no launch bar yet."""
        return self.bar_for_page(self.page()) is None

    def shown_launch_bar_ok(self, fdata):
        return not fdata.get("launchbar") or fdata is self.bar_for_page(self.page())

    def set_bar_page(self, f, page, on):
        """Settings: show launch bar f on this page (taking the page from any other bar),
        or not."""
        pid = self.page_id(page)
        if on:
            for g in self.launch_bars():
                if g is not f and pid in g.get("bar_pages", []):
                    g["bar_pages"].remove(pid)
            if not f.get("bar_all"):
                f.setdefault("bar_pages", []).append(pid)
        else:
            if f.get("bar_all"):             # "every page" becomes a list without this one
                f["bar_pages"] = [self.page_id(p) for p in self.bar_covers(f) if p is not page]
                f.pop("bar_all", None)
            elif pid in f.get("bar_pages", []):
                f["bar_pages"].remove(pid)
        self.save()
        self.show_page()

    def set_bar_all(self, f, on):
        for g in self.launch_bars():
            g.pop("bar_all", None)
        if on:
            f["bar_all"] = True
            f["bar_pages"] = []
        else:
            f["bar_pages"] = [self.page_id(p) for p in self.cfg["pages"]
                              if self.bar_for_page(p) is None or p is self.page()]
        self.save()
        self.show_page()

    def update_launch_bars(self, place=True):
        """Settings › Launch Bar Cubbies changed: the existing bars follow straight away."""
        for f in self.launch_bars():
            pane = self.active_pane(f)
            pane["icon_size"] = self.launch_bar_icon()
            if self.cfg.get("launchbar_names", True):
                pane.pop("names", None)
            else:
                pane["names"] = False
            if self.cfg.get("launchbar_autohide", True):
                f["autohide"] = True
            else:
                f.pop("autohide", None)
            for k in LINE_KEYS:
                if k in self.cfg:
                    f[k] = self.cfg[k]
            win = self.windows.get(f["id"])
            if win is None:
                continue
            if not f.get("autohide"):
                win.ah_set(False, animate=False)
                win.ah_on_top(False)
            win.refresh()
            win.queue_draw()
            if place:
                GLib.timeout_add(200, lambda f=f: self.fit_launch_bar(f) and False)
        self.save()
        self.autohide_start()
        self.pager.reposition()

    @undoable("New Launch Bar Cubby")
    def new_launch_bar(self):
        if not self.can_make_launch_bar():
            return
        if self.hidden:
            self.toggle_hidden()
        fdata = self.new_cubby_data(self.page(), "Launch Bar", 100, 160, 300, 120)
        self.page()["cubbies"].append(fdata)
        self.make_launch_bar(fdata)
        fdata.pop("lb_prev", None)
        self.save()

    def apply_title_colour(self):
        """One colour for every title (Settings › Colour & Appearance), or automatic."""
        colour = self.cfg.get("title_color")
        prov = getattr(self, "_title_colour_css", None)
        if prov is None:
            prov = self._title_colour_css = Gtk.CssProvider()
            Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                                     Gtk.STYLE_PROVIDER_PRIORITY_USER + 5)
        rule = (f".cubby-title label, .cubby-title button {{ color: {colour}; }}"
                if colour else "")
        try:
            prov.load_from_data(rule.encode())
        except GLib.Error as exc:
            dbg("title colour:", exc)

    def set_rollup_enabled(self, on):
        """Turning rolling up off opens every rolled-up cubby."""
        if not on:
            for fdata in self.all_cubbies():
                if fdata.get("rolled"):
                    fdata["rolled"] = False
                    fdata.pop("docked", None)
                    win = self.windows.get(fdata["id"])
                    if win is not None:
                        win.sync_roll()
            self.save()
