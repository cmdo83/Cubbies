"""Dragging a cubby against a screen edge to carry it to the next page."""

from gi.repository import Gdk, GLib, Gtk

from .core import dbg
from .widgets import make_window
from .cubby.cubby import Cubby


class EdgePuller:
    """Grab the left or right edge of the screen and pull it inward to turn the page, like
    turning the page of a book: pull the RIGHT edge to the left to go to the page on the right,
    and the LEFT edge to the right for the page on the left.

    The desktop belongs to Nemo, so a thin, see-through strip of our own sits on each screen
    edge (only on a side where there is a page to go to). Pressing on it gives this program the
    pointer until the button is let go, so the pull can be followed anywhere on the screen.
    Letting go far enough in turns the page,
    letting go near the edge (or pulling back) does nothing.

    While pulling, this page's cubbies slide along with the pointer and the next page's
    cubbies slide in from the other side; letting go finishes (or undoes) the slide."""

    STRIP = 12         # px wide and invisible (only the pointer changes to a hand)

    def __init__(self, app):
        self.app = app
        self.drag = None
        self.strips = {}
        for side in ("left", "right"):
            win = make_window("pullstrip-win")
            win.set_keep_below(True)
            fill = Gtk.Box()
            fill.get_style_context().add_class("pullstrip")
            win.add(fill)
            win.fill = fill
            win.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                           | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK
                           | Gdk.EventMask.LEAVE_NOTIFY_MASK)
            win.connect("button-press-event", self.on_press, side)
            win.connect("motion-notify-event", self.on_motion)
            win.connect("button-release-event", self.on_release)
            win.connect("grab-broken-event", lambda *_a: self.finish(False) or False)
            win.connect("enter-notify-event", self.on_hover, True)
            win.connect("leave-notify-event", self.on_hover, False)
            win.connect("realize", lambda w: self.set_cursor(w, "grab"))
            self.strips[side] = win
        try:
            Gdk.Screen.get_default().connect("size-changed", lambda *_a: self.update())
        except Exception:
            pass

    @staticmethod
    def set_cursor(win, name):
        try:
            gw = win.get_window()
            if gw is not None:
                disp = gw.get_display()
                cur = (Gdk.Cursor.new_from_name(disp, name)
                       or Gdk.Cursor.new_from_name(disp, "sb_h_double_arrow"))
                gw.set_cursor(cur)
        except Exception:
            pass

    def target(self, side):
        """Index of the page that pulling this edge goes to, or None (no wrapping round)."""
        cur, n = self.app.cfg["page"], len(self.app.cfg["pages"])
        i = cur + (1 if side == "right" else -1)
        return i if 0 <= i < n else None

    def update(self):
        """Put the strips on the screen edges where there is a page to go to."""
        if self.drag:
            return
        on = bool(self.app.setting("edge_pull")) and bool(self.app.setting("pages_enabled"))
        try:
            scr = Gdk.Screen.get_default()
            sw, sh = scr.get_width(), scr.get_height()
        except Exception:
            return
        for side, win in self.strips.items():
            if on and self.target(side) is not None:
                win.set_size_request(self.STRIP, sh)
                win.resize(self.STRIP, sh)
                win.show_all()
                win.set_keep_below(True)
                win.move(0 if side == "left" else sw - self.STRIP, 0)
                try:
                    win.get_window().lower()    # under cubbies that touch the edge
                except Exception:
                    pass
            else:
                win.hide()

    def on_hover(self, win, _event, inside):
        ctx = win.fill.get_style_context()
        if inside and not self.drag:
            ctx.add_class("hover")
        else:
            ctx.remove_class("hover")
        return False

    def on_press(self, win, event, side):
        if event.button != 1 or event.type != Gdk.EventType.BUTTON_PRESS:
            return True
        dest = self.target(side)
        if dest is None:
            return True
        sw = Gdk.Screen.get_default().get_width()
        self.drag = {"side": side, "dest": dest, "ready": False, "win": win, "dist": 0,
                     "sw": sw, "anim": 0}
        win.fill.get_style_context().remove_class("hover")
        self.set_cursor(win, "grabbing")
        # the cubbies on this page, and those of the page being pulled in (shown just off
        # the screen on the far side, so they slide in as the page is pulled)
        self.drag["out"] = self.page_windows(self.app.cfg["page"], show=False)
        self.drag["in"] = self.page_windows(dest, show=True)
        self.place(0)
        dbg("edge pull started on the", side, "towards page", dest)
        return True

    def slide_to(self, dest, side):
        """Turn the page with the same slide as pulling the edge (for the keys, the wheel and
        the page switcher). False when it can't (so the page just switches)."""
        if self.drag or not (0 <= dest < len(self.app.cfg["pages"])):
            return False
        sw = Gdk.Screen.get_default().get_width()
        self.drag = {"side": side, "dest": dest, "ready": True, "win": None, "dist": 0,
                     "sw": sw, "anim": 0}
        self.drag["out"] = self.page_windows(self.app.cfg["page"], show=False)
        self.drag["in"] = self.page_windows(dest, show=True)
        if not self.drag["out"] and not self.drag["in"]:
            self.drag = None
            return False
        self.place(0)
        self.animate(True, quick=True)
        return True

    def page_windows(self, index, show):
        """[(window, x, y)] for the cubbies of one page (created and shown if `show`)."""
        if self.app.hidden:
            return []
        out = []
        page = self.app.cfg["pages"][index]
        for fdata in page["cubbies"]:
            if fdata.get("tab_of") or fdata.get("all_pages") or fdata.get("launchbar"):
                continue                   # (cubbies on every page stay put while sliding)
            win = self.app.windows.get(fdata["id"])
            if win is None:
                if not show:
                    continue
                win = Cubby(self.app, fdata)
                self.app.windows[fdata["id"]] = win
            if show:
                win.move(-30000, fdata["y"])        # out of sight until placed
                win.show_all()
                win.sync_roll()
                win.set_keep_below(True)
            out.append((win,) + tuple(win.home_pos()))
        return out

    def place(self, dist):
        """Slide both pages: `dist` px pulled in from the edge."""
        d = self.drag
        sign = -1 if d["side"] == "right" else 1     # pulling the right edge moves things left
        shift = sign * int(dist)
        for win, x, y in d["out"]:
            win.move(x + shift, y)
        for win, x, y in d["in"]:
            win.move(x + shift - sign * d["sw"], y)

    def distance(self, x_root):
        sw = self.drag["sw"]
        dist = x_root if self.drag["side"] == "left" else sw - x_root
        return max(0, min(int(dist), sw))

    def threshold(self):
        return max(120, int(self.drag["sw"] * 0.15))

    def on_motion(self, _win, event):
        if not self.drag or self.drag["anim"]:
            return False
        dist = self.distance(event.x_root)
        self.drag["dist"] = dist
        self.drag["ready"] = dist >= self.threshold()
        self.place(dist)
        return True

    def on_release(self, _win, event):
        if self.drag and event.button == 1 and not self.drag["anim"]:
            dist = self.distance(event.x_root)
            self.drag["dist"] = dist
            self.animate(dist >= self.threshold())
        return True

    def animate(self, turn, quick=False):
        """Finish the slide smoothly: on to the new page, or back where it was. With
        "Lightly bounce after switching pages" it goes a little past and settles back."""
        d = self.drag
        start, goal = d["dist"], (d["sw"] if turn else 0)
        if not d["out"] and not d["in"]:
            self.finish(turn)
            return
        t0 = GLib.get_monotonic_time()
        span = 90_000 + int(abs(goal - start) / max(1, d["sw"]) * (220_000 if quick else 160_000))
        bounce = turn and self.app.setting("page_bounce")
        if bounce:
            span += 140_000

        def step():
            if self.drag is not d:
                return False
            t = min(1.0, (GLib.get_monotonic_time() - t0) / span)
            if bounce:
                c1 = 0.9                                 # ease out with a light overshoot
                c3 = c1 + 1
                k = 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2
            else:
                k = 1 - (1 - t) ** 3                     # ease out
            self.place(start + (goal - start) * k)
            if t >= 1.0:
                d["anim"] = 0
                self.finish(turn)
                return False
            return True

        d["anim"] = GLib.timeout_add(15, step)

    def finish(self, turn):
        drag, self.drag = self.drag, None
        if not drag:
            return
        if drag.get("anim"):
            GLib.source_remove(drag["anim"])
        if drag.get("win") is not None:
            self.set_cursor(drag["win"], "grab")
        dbg("edge pull", "turns the page" if turn else "cancelled")
        if turn and 0 <= drag["dest"] < len(self.app.cfg["pages"]):
            self.app.cfg["page"] = drag["dest"]
            self.app.show_page()      # hides the old page's cubbies, puts the new ones in place
            self.app.save()
        else:
            for win, x, y in drag.get("in", []):
                win.hide()
            for win, x, y in drag.get("out", []):
                win.move(x, y)
            self.update()
