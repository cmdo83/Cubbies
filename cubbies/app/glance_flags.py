"""Glance, copying a cubby's style, and on/off flags such as locking."""

import os

from gi.repository import Gdk, GLib

from ..constants import STYLE_KEYS
from ..core import dbg, undoable
from ..glance import GlancePanel


class AppGlanceFlags:
    """Glance, style copying and flags. Part of App."""

    # -- Glance: a panel over your windows showing what's in your cubbies. (The cubbies
    #    themselves never move between layers: they stay on the desktop.)
    glance = None

    def toggle_on_top(self):
        if self.glance is not None:
            self.glance.close_panel()
        else:
            self.open_glance()

    def note_open(self, path):
        """Count what you open from cubbies and Glance, for Glance's Favourites row."""
        counts = self.cfg.setdefault("open_counts", {})
        counts[path] = counts.get(path, 0) + 1
        if len(counts) > 300:              # keep the list short: drop the least used
            for p, _n in sorted(counts.items(), key=lambda kv: kv[1])[:50]:
                counts.pop(p, None)
        self.save()

    def favourites(self, n=8):
        counts = self.cfg.get("open_counts", {})
        best = sorted(counts.items(), key=lambda kv: -kv[1])
        return [p for p, c in best if c >= 2 and os.path.lexists(p)][:n]

    def corner_tick(self):
        """Glance by pushing the pointer into a screen corner (Settings › Glance; off by
        default)."""
        corner = self.cfg.get("glance_corner", "off")
        if corner == "off" or self.glance is not None:
            self._corner_since = None
            return True
        try:
            _w, px, py, mask = self.watcher.root.get_device_position(self.watcher.pointer)
            geo = Gdk.Display.get_default().get_monitor_at_point(px, py).get_geometry()
            left, top = px <= geo.x + 1, py <= geo.y + 1
            right, bottom = px >= geo.x + geo.width - 2, py >= geo.y + geo.height - 2
            at = {"top-left": left and top, "top-right": right and top,
                  "bottom-left": left and bottom, "bottom-right": right and bottom}.get(corner)
            if at and not (mask & Gdk.ModifierType.BUTTON1_MASK):
                now = GLib.get_monotonic_time() // 1000
                since = getattr(self, "_corner_since", None)
                if since is None:
                    self._corner_since = now
                elif since > 0 and now - since >= 250:
                    self._corner_since = -1          # once, until the pointer leaves
                    self.open_glance()
            else:
                self._corner_since = None
        except Exception as exc:
            dbg("glance corner:", exc)
        return True

    def open_glance(self):
        if self.glance is not None or self.hidden and not any(
                w.get_visible() for w in self.windows.values()):
            if self.glance is None:
                dbg("glance: no cubbies shown")
            return
        self.glance = GlancePanel(self)
        self.glance.open_panel()
        dbg("glance opened")

    def set_on_top(self, on):
        """(Older name.) True opens the Glance panel, False closes it."""
        if on:
            self.open_glance()
        elif self.glance is not None:
            self.glance.close_panel()

    def rollup_open(self):
        """How a rolled-up cubby opens for a look: "hover", "click" or "never"."""
        mode = self.cfg.get("rollup_open")
        if mode in ("hover", "click", "never"):
            return mode
        return "hover" if self.setting("peek") else "never"

    style_clip = None
    on_top = False            # (always False now: cubbies never leave the desktop layer)

    def copy_style(self, fdata):
        self.style_clip = {k: fdata[k] for k in STYLE_KEYS + ("title_align",) if k in fdata}

    @undoable("Paste Style")
    def paste_style(self, fdata):
        if not self.style_clip:
            return
        for k in STYLE_KEYS + ("title_align",):
            fdata.pop(k, None)
        fdata.update(self.style_clip)
        win = self.windows.get(fdata["id"])
        if win is not None:
            win.apply_style()
            win.apply_title_size()
        self.save()

    def set_flag(self, fdata, key, on):
        if on:
            fdata[key] = True
        else:
            fdata.pop(key, None)
        self.save()
        win = self.windows.get(fdata["id"])
        if win is not None:
            win.update_title()
        if key in ("all_pages", "same_place"):
            if not self.own_positions(fdata):    # one place again: the one it has now
                fdata.pop("page_pos", None)
                fdata.pop("pos_page", None)
            self.show_page()

    def toggle_lock_all(self):
        self.cfg["lock_all"] = not self.cfg.get("lock_all")
        self.save()
        for win in self.windows.values():
            win.update_title()

    def is_locked(self, fdata):
        return bool(fdata.get("locked") or self.cfg.get("lock_all"))

    def set_pager_pos(self, pos):
        if pos == "custom" and "pager_x" not in self.cfg:
            x, y = self.pager.get_position()
            self.cfg.update(pager_x=int(x), pager_y=int(y))
        self.cfg["pager_pos"] = pos
        self.save()
        self.pager.reposition()
        self.pager.flash(1500)

    def set_keep_visible(self, fdata, on):
        if on:
            fdata["keep_visible"] = True
        else:
            fdata.pop("keep_visible", None)
        self.save()
