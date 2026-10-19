"""Watches clicks on the bare desktop (double-click to hide the cubbies, drags)."""

import os

from gi.repository import Gdk, GLib, Gtk

from .core import Wnck, dbg
from .desktop_env import IS_MATE
from .desktop_icons import DND_FROM_DESKTOP, desktop_icon_positions


class DesktopWatcher:
    """Notices a double-click on the empty desktop (best effort).

    The desktop belongs to Cinnamon/Nemo, so an ordinary app never receives those clicks.
    Instead this polls the pointer a few dozen times a second, and when it sees two quick
    left-clicks it checks that nothing but the desktop was under the pointer.
    """

    POLL_MS = 25

    def __init__(self, on_double_click, is_own_window_at):
        self.on_double_click = on_double_click
        self.is_own_window_at = is_own_window_at  # (x, y) -> True if one of our windows is there
        self.enabled = True
        self.was_down = False
        self.last = None  # (time_ms, x, y) of a previous desktop click
        self.was_down3 = False
        self.on_outside_click = lambda: None  # a click landed outside every Cubbies window
        # left-button drag on the empty desktop draws a new cubby: (x0, y0, x, y) callbacks
        self.band_enabled = lambda: False
        self.on_band = lambda *_a: None        # while dragging (None = hide the box)
        self.on_band_done = lambda *_a: None   # let go: the box that was drawn
        self.band = None
        self._dnd_t = 0
        try:   # a file drag (from Nemo's desktop or anywhere) takes the XdndSelection
            Gtk.Clipboard.get(Gdk.Atom.intern("XdndSelection", False)).connect(
                "owner-change", self._on_dnd_owner)
        except Exception as exc:
            dbg("could not watch for file drags:", repr(exc))
        display = Gdk.Display.get_default()
        self.supported = "X11" in type(display).__name__
        if not self.supported:
            return
        self.pointer = display.get_default_seat().get_pointer()
        self.root = Gdk.get_default_root_window()
        settings = Gtk.Settings.get_default()
        self.dbl_time = settings.get_property("gtk-double-click-time")
        self.dbl_dist = max(settings.get_property("gtk-double-click-distance"), 8)
        dbg("desktop watcher started; window list via",
            "libwnck" if Wnck is not None else "GDK (libwnck not installed)",
            f"; double-click time {self.dbl_time} ms")
        GLib.timeout_add(self.POLL_MS, self.poll)

    def poll(self):
        try:
            _win, x, y, mask = self.root.get_device_position(self.pointer)
        except Exception:
            return True
        down = bool(mask & Gdk.ModifierType.BUTTON1_MASK)
        down3 = bool(mask & Gdk.ModifierType.BUTTON3_MASK)
        if down3 and not self.was_down3 and not self.pointer_over_own_window():
            self.on_outside_click()  # a right-click elsewhere also drops the selection
        self.was_down3 = down3
        # left-button drag on the empty desktop draws the outline of a new cubby
        if down and not self.was_down:
            self.band = None
            try:
                if (self.band_enabled() and not self.pointer_over_own_window()
                        and self.over_bare_desktop(x, y) and not self.over_desktop_icon(x, y)):
                    self.band = (x, y, False, GLib.get_monotonic_time())
            except Exception as exc:
                dbg("drag check failed:", repr(exc))
        elif down and self.band:
            x0, y0, shown, t0 = self.band
            if self.dnd_started_after(t0):
                # a desktop icon is being dragged (a file drag began): not a new cubby
                dbg("a file drag started: no new cubby")
                self.band = None
                self.on_band(None)
            elif shown or abs(x - x0) > 12 or abs(y - y0) > 12:
                self.band = (x0, y0, True, t0)
                self.on_band(x0, y0, x, y)
        elif not down and self.was_down and self.band:
            x0, y0, shown, t0 = self.band
            self.band = None
            if shown and not self.dnd_started_after(t0):
                self.on_band_done(x0, y0, x, y)
            else:
                self.on_band(None)
        if down and not self.was_down:
            try:
                self.on_press(x, y)
            except Exception as exc:  # never let one bad click stop the watcher
                dbg("error while handling a click:", repr(exc))
        self.was_down = down
        return True

    def _on_dnd_owner(self, *_a):
        self._dnd_t = GLib.get_monotonic_time()
        if IS_MATE and self.supported:
            try:
                _w, x, y, _m = self.root.get_device_position(self.pointer)
                DND_FROM_DESKTOP[0] = self.over_bare_desktop(x, y)
            except Exception:
                DND_FROM_DESKTOP[0] = False

    def dnd_started_after(self, t0):
        return self._dnd_t > t0

    def pointer_over_own_window(self):
        """True when the pointer is over one of this program's own windows (a cubby, the pager,
        a menu or a dialog). GDK only knows its own windows, so anything else gives None."""
        try:
            win, _x, _y = self.pointer.get_window_at_position()
        except Exception as exc:
            dbg("could not ask GDK which window is under the pointer:", repr(exc))
            return False
        if win is None:
            return False
        # GDK also hands back "foreign" wrappers for other programs' windows (it creates them
        # once something has looked at the window list) and the root window; those are not ours.
        kind = win.get_window_type()
        if kind in (Gdk.WindowType.FOREIGN, Gdk.WindowType.ROOT):
            return False
        return True

    def on_press(self, x, y):
        now = GLib.get_monotonic_time() // 1000
        gdk_says_ours = self.pointer_over_own_window()
        if gdk_says_ours or self.is_own_window_at(x, y):
            dbg(f"click at ({x}, {y}): on a Cubbies window, ignored "
                f"(GDK says ours: {gdk_says_ours})")
            self.last = None
            return
        self.on_outside_click()  # clicking anywhere else deselects, like the real desktop
        bare = self.over_bare_desktop(x, y)
        if not self.enabled:
            self.last = None
            return
        if not bare:
            self.last = None
            return
        if self.over_desktop_icon(x, y):
            self.last = None
            return
        if (self.last and now - self.last[0] <= self.dbl_time
                and abs(x - self.last[1]) <= self.dbl_dist
                and abs(y - self.last[2]) <= self.dbl_dist):
            self.last = None
            dbg("double-click on desktop -> toggling cubbies (unless a window opens)")
            self.schedule_toggle()
        else:
            dbg(f"first desktop click at ({x}, {y})")
            self.last = (now, x, y)

    def over_desktop_icon(self, x, y):
        """True when (x, y) is on one of Nemo's own desktop icons. Nemo remembers each icon's
        position as file metadata, so those positions are read back and compared."""
        try:
            found = desktop_icon_positions()
            for path, ix, iy in found:
                if ix - 30 <= x <= ix + 130 and iy - 30 <= y <= iy + 130:
                    dbg(f"click at ({x}, {y}): on desktop icon {os.path.basename(path)!r}, "
                        "ignored")
                    return True
            if not found:
                dbg("Nemo has stored no icon positions for the desktop; "
                    "relying on the window-opened check only")
            return False
        except Exception as exc:
            dbg("could not read desktop icon positions:", repr(exc))
            return False

    def window_count(self):
        if Wnck is None:
            return None
        screen = Wnck.Screen.get_default()
        screen.force_update()
        return len(screen.get_windows())

    def schedule_toggle(self):
        """Hide/show the cubbies a moment later, and not at all if a new window appeared in
        between (the double-click was probably opening something)."""
        before = self.window_count()

        def finish():
            after = self.window_count()
            if before is not None and after is not None and after > before:
                dbg("a window opened right after the double-click; cubbies left alone")
            else:
                self.on_double_click()
            return False

        GLib.timeout_add(600, finish)

    def over_bare_desktop(self, x, y):
        """True when (x, y) is on the desktop: inside the work area (not on a panel) and not
        covered by any visible application window. Any doubt means False (do nothing)."""
        try:
            if self.is_own_window_at(x, y):
                dbg(f"click at ({x}, {y}): on one of our own windows, ignored")
                return False
            display = Gdk.Display.get_default()
            mon = display.get_monitor_at_point(x, y)
            wa = mon.get_workarea()
            if not (wa.x <= x < wa.x + wa.width and wa.y <= y < wa.y + wa.height):
                dbg(f"click at ({x}, {y}): outside the work area (panel), ignored")
                return False
            if Wnck is not None:
                return self._bare_by_wnck(x, y)
            return self._bare_by_gdk(x, y, mon)
        except Exception as exc:
            dbg(f"click at ({x}, {y}): error while checking: {exc!r}")
            return False

    def _bare_by_wnck(self, x, y):
        screen = Wnck.Screen.get_default()
        screen.force_update()
        if screen.get_showing_desktop():
            return True  # Show Desktop is active, so nothing is covering the desktop
        workspace = screen.get_active_workspace()
        for win in screen.get_windows_stacked():
            if win.get_window_type() == Wnck.WindowType.DESKTOP:
                continue  # Nemo's desktop layer is the desktop, not an application
            if win.is_minimized() or (workspace and not win.is_on_workspace(workspace)):
                continue
            wx, wy, ww, wh = win.get_geometry()
            if wx <= x < wx + ww and wy <= y < wy + wh:
                dbg(f"click at ({x}, {y}): covered by window {win.get_name()!r}, ignored")
                return False
        return True

    def _bare_by_gdk(self, x, y, mon):
        geo = mon.get_geometry()
        for win in Gdk.Screen.get_default().get_window_stack() or []:
            if not win.is_visible() or (win.get_state() & Gdk.WindowState.ICONIFIED):
                continue
            r = win.get_frame_extents()
            if not (r.x <= x < r.x + r.width and r.y <= y < r.y + r.height):
                continue
            if (r.width >= geo.width and r.height >= geo.height
                    and r.x <= geo.x and r.y <= geo.y):
                continue  # a full-monitor window is the desktop itself, not an app
            dbg(f"click at ({x}, {y}): covered by a window at {r.x},{r.y} {r.width}x{r.height}")
            return False
        return True
