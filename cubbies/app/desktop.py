"""The desktop itself: its icons, double-click, several picked cubbies, and screens
being plugged in or unplugged."""

from gi.repository import Gdk, Gio, GLib

from ..core import dbg, save_config
from ..desktop_env import IS_MATE, IS_XFCE, Xfconf, settings_schema, variant_to_saved


class AppDesktop:
    """The desktop and screens. Part of App."""

    def handle_swipe(self, event):
        """A sideways two-finger swipe on a touchpad (or a tilt of the wheel) over a cubby or
        the page switcher turns the page. True when the event was used."""
        if not (self.setting("swipe_pages") and self.setting("pages_enabled")):
            return False
        d = event.direction
        if d in (Gdk.ScrollDirection.LEFT, Gdk.ScrollDirection.RIGHT):
            self.change_page(1 if d == Gdk.ScrollDirection.RIGHT else -1)
            return True
        if d != Gdk.ScrollDirection.SMOOTH:
            return False
        dx, dy = event.delta_x, event.delta_y
        now = GLib.get_monotonic_time()
        if now - getattr(self, "_swipe_t", 0) > 400_000:
            self._swipe_acc, self._swipe_done = 0.0, False   # a new swipe
        self._swipe_t = now
        try:
            stop = event.is_scroll_stop_event()
        except Exception:
            stop = False
        if stop:
            self._swipe_acc, self._swipe_done = 0.0, False
            return True
        if abs(dx) <= abs(dy) and not self._swipe_acc:
            return False                                      # an ordinary up/down scroll
        self._swipe_acc += dx
        if not self._swipe_done and abs(self._swipe_acc) >= 1.6:
            self._swipe_done = True                           # one page per swipe
            self.change_page(1 if self._swipe_acc > 0 else -1)
        return True

    def set_desktop_icons(self, visible):
        """Hide or bring back the file manager's own desktop icons (Nemo's "desktop-layout"
        setting). The setting you had is remembered and put back exactly."""
        try:
            if IS_MATE:
                self.set_mate_desktop_icons(visible)
                return
            if IS_XFCE:
                self.set_xfce_desktop_icons(visible)
                return
            src = Gio.SettingsSchemaSource.get_default()
            if not (src and src.lookup("org.nemo.desktop", True)):
                return
            nemo = Gio.Settings.new("org.nemo.desktop")
            if not visible:
                if "nemo_layout" not in self.cfg:
                    self.cfg["nemo_layout"] = nemo.get_string("desktop-layout")
                nemo.set_string("desktop-layout", "false::false")
            elif "nemo_layout" in self.cfg:
                old = str(self.cfg.pop("nemo_layout") or "")
                nemo.set_string("desktop-layout", old if "::" in old else "true::false")
            Gio.Settings.sync()
            self.save()
            dbg("desktop icons", "shown" if visible else "hidden")
        except Exception as exc:
            dbg("could not change the desktop icons:", exc)

    def remember_xfconf(self, prop, old):
        """Xfce: keep the first value Cubbies ever replaced, for the uninstall clean-up."""
        base = self.cfg.setdefault("xfce_base", {})
        if prop not in base:
            base[prop] = variant_to_saved(old)
            save_config(self.cfg)

    def set_xfce_desktop_icons(self, visible):
        """Xfce: xfdesktop's icons go with /desktop-icons/style (0 = none, 2 = files and
        launchers). The old value is kept in "nemo_layout" as "xfce:N"."""
        if not visible:
            if "nemo_layout" not in self.cfg:
                self.cfg["nemo_layout"] = "xfce:" + str(Xfconf.get("/desktop-icons/style", 2))
            Xfconf.set("/desktop-icons/style", GLib.Variant("i", 0))
        elif "nemo_layout" in self.cfg:
            old = str(self.cfg.pop("nemo_layout") or "")
            try:
                n = int(old.split(":", 1)[1]) if old.startswith("xfce:") else 2
            except ValueError:
                n = 2
            Xfconf.set("/desktop-icons/style", GLib.Variant("i", n if n != 0 else 2))
        self.save()
        dbg("desktop icons", "shown" if visible else "hidden")

    def set_mate_desktop_icons(self, visible):
        """MATE: Caja's desktop icons go with org.mate.background show-desktop-icons. The old
        value is kept in the same config key as Nemo's ("nemo_layout"), as "mate:true"."""
        mate = settings_schema("org.mate.background")
        if mate is None:
            return
        if not visible:
            if "nemo_layout" not in self.cfg:
                self.cfg["nemo_layout"] = "mate:" + (
                    "true" if mate.get_boolean("show-desktop-icons") else "false")
            mate.set_boolean("show-desktop-icons", False)
        elif "nemo_layout" in self.cfg:
            old = str(self.cfg.pop("nemo_layout") or "")
            mate.set_boolean("show-desktop-icons", old != "mate:false")
        Gio.Settings.sync()
        self.save()
        dbg("desktop icons", "shown" if visible else "hidden")

    def toggle_hidden(self):
        self.hidden = not self.hidden
        if self.setting("hide_desktop_icons") or "nemo_layout" in self.cfg:
            self.set_desktop_icons(not self.hidden)
        self.cfg["hidden"] = self.hidden
        self.clear_selection()
        self.show_page()
        self.save()

    def set_desktop_dblclick(self, enabled):
        self.cfg["desktop_dblclick"] = bool(enabled)
        self.watcher.enabled = bool(enabled)
        self.save()

    # -- several cubbies picked to move together (Ctrl + click their title bars)
    picked = set()

    def toggle_picked(self, win):
        fid = win.data["id"]
        if fid in self.picked:
            self.picked.discard(fid)
        else:
            self.picked = set(self.picked) | {fid}
        dbg("cubbies picked to move together:", len(self.picked))
        win.outer.queue_draw()

    def picked_windows(self):
        return [w for fid, w in self.windows.items() if fid in self.picked and w.get_visible()]

    def clear_picked(self):
        if not self.picked:
            return
        wins = self.picked_windows()
        self.picked = set()
        for w in wins:
            w.outer.queue_draw()

    def on_outside_click(self):
        self.clear_picked()
        self.clear_selection()

    def clear_selection(self):
        for win in self.windows.values():
            if win.selected:
                win.set_selection(set())

    # -- screens plugged in or unplugged
    def monitor_rects(self):
        """The usable area of each screen: [(x, y, w, h)]."""
        display = Gdk.Display.get_default()
        out = []
        for i in range(display.get_n_monitors()):
            wa = display.get_monitor(i).get_workarea()
            out.append((wa.x, wa.y, wa.width, wa.height))
        return out

    def screens_changed(self):
        if getattr(self, "_screens_timer", 0):
            GLib.source_remove(self._screens_timer)

        def go():
            self._screens_timer = 0
            self.check_screens()
            return False
        self._screens_timer = GLib.timeout_add(1200, go)   # let the screens settle first

    @staticmethod
    def title_visible(x, y, w, rects, th=28):
        """Is enough of a cubby's title bar on some screen to grab it (60 px or so)?"""
        for mx, my, mw, mh in rects:
            seen = min(x + w, mx + mw) - max(x, mx)
            if seen >= min(60, w) and my <= y + th // 2 < my + mh:
                return True
        return False

    def check_screens(self):
        """A cubby left off every screen (its screen was unplugged) is brought onto a screen
        that is still there; its own place is remembered, and it goes back there when that
        screen returns. Cubbies you moved yourself in the meantime stay where you put them."""
        rects = self.monitor_rects()
        if not rects:
            return False
        changed = 0
        for page in self.cfg["pages"]:
            for f in page["cubbies"]:
                if f.get("tab_of"):
                    continue
                x, y = int(f.get("x", 0)), int(f.get("y", 0))
                w = int(f.get("w", 300))
                h = 30 if f.get("rolled") else int(f.get("h", 200))
                ty = y + (h - 28 if f.get("flip") else 0)      # where its title bar is
                home = f.get("displaced")
                if home:
                    hy = home["y"] + (h - 28 if f.get("flip") else 0)
                    if self.title_visible(home["x"], hy, w, rects):
                        f["x"], f["y"] = home["x"], home["y"]
                        f.pop("displaced")
                        changed += 1
                    continue
                if self.title_visible(x, ty, w, rects):
                    continue
                # nearest screen to where it was, and inside it
                cx, cy = x + w / 2, y + h / 2

                def dist(r):
                    rx = min(max(cx, r[0]), r[0] + r[2])
                    ry = min(max(cy, r[1]), r[1] + r[3])
                    return (rx - cx) ** 2 + (ry - cy) ** 2
                mx, my, mw, mh = min(rects, key=dist)
                f["displaced"] = {"x": x, "y": y}
                f["x"] = int(min(max(x, mx), mx + max(0, mw - w)))
                f["y"] = int(min(max(y, my), my + max(0, mh - h)))
                changed += 1
        if changed:
            dbg("screens changed:", changed, "cubbies moved onto / back to their screens")
            for win in self.windows.values():
                if win.get_visible():
                    win.move(*win.home_pos())
            self.show_page()
            self.save()
        return False
