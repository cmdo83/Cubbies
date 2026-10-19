"""The App: starting up, keys, Undo, and saving."""

import json
import os
import shutil
import sys

from gi.repository import Gdk, Gio, GLib, Gtk

from ..core import LAUNCHER, Wnck, code_stamp, dbg, load_config, save_config
from ..desktop_env import DESKTOP, XFCONF_REMEMBER
from ..desktop_watcher import DesktopWatcher
from ..dialogs import tell
from ..files import _mounts_cache, restore_from_trash
from ..hotkeys import HotkeyGrabber
from ..pager import Pager
from ..wallpapers import _THUMB_FAILED, _THUMB_MEM
from .backup import AppBackup
from .clipboard import AppClipboard
from .commands import AppCommands
from .cubbies import AppCubbies
from .desktop import AppDesktop
from .drawing import AppDrawing
from .file_ops import AppFileOps
from .folders import FolderOps
from .glance_flags import AppGlanceFlags
from .groups import GroupOps
from .launch_bars import AppLaunchBars
from .page_settings import AppPageSettings
from .pages import AppPages
from .places import AppPlaces
from .settings_look import AppSettingsLook
from .settings_tools import AppSettingsTools
from .settings_window import AppSettingsWindow
from .special import AppSpecialCubbies
from .store import AppStore
from .wallpaper import AppWallpaper
from .welcome import AppWelcome


# App is put together from the mixins imported above, one file per part of the job.
# No two of them define the same name, so their order here doesn't matter.
class App(AppStore, AppPlaces, AppClipboard, AppFileOps, AppWallpaper, AppSettingsWindow,
          AppSettingsLook, AppSettingsTools, AppPageSettings, AppPages, AppWelcome,
          AppGlanceFlags, AppLaunchBars, AppDesktop, AppCubbies, AppCommands, AppDrawing,
          AppBackup, AppSpecialCubbies, GroupOps, FolderOps):
    def __init__(self):
        self.cfg = load_config()
        self.bind_item_names()
        seen = list(self.cfg.get("desktops") or [])
        if DESKTOP not in seen:            # (the uninstall clean-up puts back each one's settings)
            self.cfg["desktops"] = seen + [DESKTOP]
        XFCONF_REMEMBER[0] = self.remember_xfconf
        self.hidden = bool(self.cfg.get("hidden", False))
        GLib.idle_add(lambda: self.watch_background() and False)
        if self.setting("show_on_start"):
            self.hidden = False            # "Always show cubbies when Cubbies starts"
            self.cfg["hidden"] = False
        if not self.hidden and "nemo_layout" in self.cfg:
            GLib.idle_add(lambda: self.set_desktop_icons(True) and False)
        self.windows = {}
        self._last_flip = 0
        self._applied_wp = None      # wallpaper uri we last set
        self.repair_groups()
        self.migrate_bars()
        self.pager = Pager(self)
        self.puller = None
        self.pager.show_all()
        self.pager.set_keep_below(True)
        self.show_page()
        # re-read the system selection colour if the theme changes
        Gtk.Settings.get_default().connect("notify::gtk-theme-name", lambda *_a: self.restyle_all())
        # double-click the empty desktop to hide/show every cubby
        self.watcher = DesktopWatcher(self.toggle_hidden, self.own_window_at)
        self.watcher.enabled = bool(self.cfg.get("desktop_dblclick", True))
        self.watcher.on_outside_click = self.on_outside_click
        self.watcher.band_enabled = lambda: bool(self.setting("draw_new")
                                                 or self.setting("box_select"))
        self.watcher.on_band = self.show_new_band
        self.watcher.on_band_done = self.new_cubby_from_band
        self.keys = None
        self.on_top = False
        self._busy = False
        self.clip = None
        self._clip_ignore_until = 0
        try:
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).connect("owner-change", self.on_clip_owner)
        except Exception as exc:
            dbg("clipboard watch unavailable:", repr(exc))
        if self.watcher.supported:
            GLib.timeout_add(100, self.pager.tick)   # pager auto-hide
            GLib.timeout_add(100, self.corner_tick)  # Glance hot corner (when chosen)
        try:
            if not self.watcher.supported:
                raise RuntimeError("system-wide keys need an X11 session")
            self.keys = HotkeyGrabber(lambda step: self.key_page_step(step),
                                      self.delete_selected, self.want_delete_grab)
            self.keys.on_rename = self.rename_selected
            self.keys.on_refresh_key = self.on_refresh_key
            self.keys.page_keys_when = self.page_keys_wanted
            self.watch_front_window()
            self.keys.add_conditional(0x7A, HotkeyGrabber.CONTROL, self.want_undo_grab,
                                      lambda: GLib.idle_add(lambda: self.undo() and False))
            self.keys.add_conditional(0x66, HotkeyGrabber.CONTROL, self.want_find_grab,
                                      lambda: GLib.idle_add(lambda: self.search_here() and False))
            self.keys.on_peek = lambda: GLib.idle_add(lambda: self.toggle_on_top() and False)
            self.keys.want_escape = lambda: bool(self.picked) or self.glance is not None

            def escape():
                self.clear_picked()
                if self.glance is not None:
                    self.glance.escape()            # out of a search / folder, then closes
                return False
            self.keys.on_escape = lambda: GLib.idle_add(escape)
            ok, msg = self.keys.set_peek_key(self.cfg.get("peek_key", "super_space"))
            dbg("peek key:", msg)
            for name, mods in (("ctrl_alt_p", HotkeyGrabber.CONTROL | HotkeyGrabber.ALT),
                               ("ctrl_super_p", HotkeyGrabber.CONTROL | HotkeyGrabber.SUPER)):
                self.keys.add_conditional(
                    0x70, mods, lambda n=name: self.cfg.get("pager_key", "off") == n,
                    lambda: GLib.idle_add(lambda: self.pager.key_toggle() and False))
            # Manage Pages: a key held all the time, so it works over any window
            for name, mods in (("ctrl_super_m", HotkeyGrabber.CONTROL | HotkeyGrabber.SUPER),
                               ("ctrl_alt_m", HotkeyGrabber.CONTROL | HotkeyGrabber.ALT)):
                self.keys.add_conditional(
                    0x6D, mods, lambda n=name: self.cfg.get("manage_key", "ctrl_super_m") == n,
                    lambda: GLib.idle_add(lambda: self.open_page_order(toggle=True) and False))
            GLib.timeout_add(40, self.keys.poll)
            ok, message = self.apply_hotkeys(self.cfg.get("hotkeys", "ctrl"))
            dbg("page keys:", message)
            if not ok:
                print("Cubbies:", message, file=sys.stderr)
        except Exception as exc:
            print("Cubbies: system-wide keys are unavailable:", exc, file=sys.stderr)
        self.watch_recent()
        try:
            scr = Gdk.Screen.get_default()
            scr.connect("monitors-changed", lambda *_a: self.screens_changed())
            scr.connect("size-changed", lambda *_a: self.screens_changed())
            GLib.timeout_add(1500, lambda: self.check_screens() and False)
        except Exception as exc:
            dbg("screen changes can't be watched:", exc)
        try:
            self.watch_store()
        except Exception as exc:
            print("Cubbies: could not watch the", self.store_dir(), "folder:", exc,
                  file=sys.stderr)
        try:
            self._code_path = LAUNCHER
            self._code_stamp = code_stamp()
            self._code_seen = None
            GLib.timeout_add_seconds(4, self.check_for_update)
        except Exception as exc:
            dbg("update check unavailable:", repr(exc))
        try:
            self.watch_desktop()
        except Exception as exc:
            print("Cubbies: could not watch the Desktop folder:", exc, file=sys.stderr)
        self.autohide_start()
        GLib.timeout_add(1000, self.bars_tick)
        GLib.timeout_add_seconds(90, self.backup_tick)           # (first look: a bit after
        GLib.timeout_add_seconds(30 * 60, self.backup_tick_repeat)  # start-up, then every 30 min)
        self.watch_trash()
        self.watch_drives()

    # -- page hotkeys and the Delete key
    def apply_hotkeys(self, mode):
        """Returns (ok, message)."""
        if self.keys is None:
            return False, "System-wide keys are unavailable (they need an X11 session)."
        return self.keys.set_page_keys(mode)

    def want_delete_grab(self):
        """Catch Delete only while the pointer is over a cubby that has selected icons."""
        if not self.setting("delete_key") or self._busy:
            return False
        if not any(w.selected and w.get_visible() for w in self.windows.values()):
            return False
        return self.watcher.pointer_over_own_window()

    # -- Undo (Ctrl + Z over a cubby, or the menus)
    UNDO_MAX = 25

    def undo_begin(self, label):
        if getattr(self, "_undo_open", None) is not None or getattr(self, "_undoing", False):
            return None                     # part of a bigger step already being recorded
        entry = {"label": label, "pages": json.dumps(self.cfg["pages"]),
                 "page": self.cfg["page"], "ops": [],
                 "links": list(self.cfg.get("hidden_links", []))}
        self._undo_open = entry
        return entry

    def undo_end(self, entry):
        if entry is None:
            return
        self._undo_open = None
        if entry.get("cancel"):
            return
        if not entry["ops"] and json.dumps(self.cfg["pages"]) == entry["pages"]:
            return                          # nothing changed (cancelled, say)
        stack = self.__dict__.setdefault("_undo_stack", [])
        stack.append(entry)
        del stack[:-self.UNDO_MAX]
        dbg("undo step recorded:", entry["label"], entry["ops"])

    def undo_note(self, *op):
        """A file was moved ("move", from, to), put in the Trash ("trash", where) or made
        ("made", path) as part of the step being recorded."""
        if getattr(self, "_undo_open", None) is not None:
            self._undo_open["ops"].append(op)

    def undo_forbid(self):
        """This step can't be undone (a file was deleted for good): don't offer it."""
        if getattr(self, "_undo_open", None) is not None:
            self._undo_open["cancel"] = True

    def undo_label(self):
        stack = getattr(self, "_undo_stack", [])
        return stack[-1]["label"] if stack else None

    def undo(self):
        stack = getattr(self, "_undo_stack", [])
        if not stack:
            return False
        entry = stack.pop()
        self._undoing = True
        problems = []
        try:
            for op in reversed(entry["ops"]):
                try:
                    if op[0] == "move":
                        src, dst = op[1], op[2]
                        if os.path.lexists(dst) and not os.path.lexists(src):
                            os.makedirs(os.path.dirname(src), exist_ok=True)
                            shutil.move(dst, src)
                        else:
                            problems.append(os.path.basename(src))
                    elif op[0] == "trash":
                        if not restore_from_trash(op[1]):
                            problems.append(os.path.basename(op[1]))
                    elif op[0] == "made":
                        if os.path.lexists(op[1]):
                            Gio.File.new_for_path(op[1]).trash(None)
                except Exception as exc:
                    print("Cubbies: undo:", op, "-", exc, file=sys.stderr)
                    problems.append(os.path.basename(op[-1]))
            self.cfg["pages"] = json.loads(entry["pages"])
            self.cfg["page"] = min(max(0, entry["page"]), len(self.cfg["pages"]) - 1)
            for name in entry.get("links", []):     # desktop icons that were hidden then
                self.want_link_hidden(name)
            self.picked = set()
            for win in list(self.windows.values()):
                win.destroy()
            self.windows = {}
            self.show_page()
            self.save()
        finally:
            self._undoing = False
        dbg("undone:", entry["label"])
        if problems:
            tell("Not everything could be undone",
                 "These could not be put back: " + ", ".join(problems[:8]))
        return True

    def cubby_under_pointer(self):
        try:
            _w, px, py, _m = self.watcher.root.get_device_position(self.watcher.pointer)
        except Exception:
            return None
        for win in self.windows.values():
            if not win.get_visible():
                continue
            x, y = win.get_position()
            w, h = win.get_size()
            if x <= px < x + w and y <= py < y + h:
                return win
        return None

    def want_find_grab(self):
        return self.watcher.pointer_over_own_window() and not any(
            getattr(w, "_search_ed", None) for w in self.windows.values())

    def search_here(self):
        win = self.cubby_under_pointer()
        if win is not None:
            win.open_search()

    def want_undo_grab(self):
        return bool(getattr(self, "_undo_stack", None)) and \
            self.watcher.pointer_over_own_window()

    def on_refresh_key(self):
        """F5 was pressed. Refresh the cubbies too when it was pressed on the desktop (the
        desktop refreshes its own icons as usual) or with no window in front."""
        if not self.setting("f5_refresh"):
            return
        if self.desktop_is_active():
            dbg("F5 on the desktop: refreshing the cubbies")
            GLib.idle_add(lambda: self.refresh_all() and False)

    def page_keys_wanted(self):
        """The page keys are Cubbies' only while the desktop (or a Cubbies window) is in
        front, unless Settings says every program. So Ctrl+Left / Right / Up keep working
        as usual in the program you're using."""
        if self.cfg.get("page_keys_where", "desktop") == "everywhere":
            return True
        return getattr(self, "_desk_front", True)

    def watch_front_window(self):
        """Keep _desk_front up to date: is the desktop (or one of ours) the active window?"""
        def check(*_a):
            self._desk_front = self.desktop_is_active()
            return True
        try:
            if Wnck is not None:
                Wnck.Screen.get_default().connect(     # (checked just after: not inside
                    "active-window-changed",           #  Wnck's own update)
                    lambda *_a: GLib.idle_add(lambda: check() and False) and None)
        except Exception as exc:
            dbg("active window changes can't be watched:", exc)
        check()
        GLib.timeout_add(400, check)        # (and now and then, to be sure)

    def desktop_is_active(self):
        try:
            if Wnck is not None:
                screen = Wnck.Screen.get_default()
                screen.force_update()
                win = screen.get_active_window()
                return (win is None or win.get_window_type() == Wnck.WindowType.DESKTOP
                        or win.get_pid() == os.getpid())
            win = Gdk.Screen.get_default().get_active_window()
            if win is None:
                return True
            r = win.get_frame_extents()
            mon = Gdk.Display.get_default().get_monitor_at_point(r.x + 1, r.y + 1)
            geo = mon.get_geometry()
            return r.width >= geo.width and r.height >= geo.height  # the desktop fills it
        except Exception as exc:
            dbg("could not tell which window is active:", repr(exc))
            return False

    def refresh_all(self):
        """Look at every cubby again: folders are re-read, pictures and thumbnails are made
        afresh, and icons of stored files that have been deleted are taken out."""
        _THUMB_MEM.clear()
        _THUMB_FAILED.clear()
        _mounts_cache[0] = 0.0
        changed = False
        for fdata in self.all_cubbies():
            if fdata.get("folder") or fdata.get("group"):
                continue
            # only Cubbies' own files: a link to a drive that is unplugged right now stays
            gone = [p for p in fdata.get("items", [])
                    if self.is_managed(p) and not os.path.lexists(p)]
            for p in gone:
                fdata["items"].remove(p)
                changed = True
        for win in list(self.windows.values()):
            try:
                if win.pane.get("folder"):
                    win.stop_watching()        # watch again from scratch
                win.refresh()
            except Exception as exc:
                dbg("refresh failed:", repr(exc))
        if changed:
            self.save()
        return True

    def rename_selected(self):
        """F2 over a cubby: rename its one selected icon in place."""
        for win in list(self.windows.values()):
            if win.selected and win.get_visible() and len(win.selected) == 1:
                path = next(iter(win.selected))
                if self.can_rename(path):
                    GLib.idle_add(lambda: win.edit_item_name(path) and False)
                return

    def delete_selected(self):
        if self._busy:
            return
        for win in list(self.windows.values()):
            if win.selected and win.get_visible():
                targets = [p for p in win.ordered_items() if p in win.selected]
                self._busy = True
                try:
                    win.request_remove(targets)
                finally:
                    self._busy = False
                return

    # -- files that live in Cubbies' own folder
    def all_cubbies(self):
        for page in self.cfg["pages"]:
            for fdata in page["cubbies"]:
                yield fdata

    def check_for_update(self):
        """Installing a newer version replaces this file; restart on it so the new code runs
        (nothing is lost: everything is saved, and the cubbies come straight back)."""
        try:
            stamp = code_stamp()
        except OSError:
            return True
        if stamp == self._code_stamp:
            return True
        if stamp != self._code_seen:       # wait until the file has stopped changing
            self._code_seen = stamp
            return True
        if any(isinstance(w, Gtk.Dialog) and w.get_visible()
               for w in Gtk.Window.list_toplevels()):
            return True                      # not while a dialog is open
        try:
            self.save()
            dbg("Cubbies was updated; restarting")
            os.execv(sys.executable, [sys.executable, self._code_path])
        except Exception as exc:
            print("Cubbies: could not restart after the update:", exc, file=sys.stderr)
            self._code_stamp = stamp
        return True

    def own_window_at(self, x, y):
        for win in list(self.windows.values()) + [self.pager]:
            if win.get_visible():
                wx, wy = win.get_position()
                ww, wh = win.get_size()
                if wx <= x < wx + ww and wy <= y < wy + wh:
                    return True
        return False

    def page(self):
        return self.cfg["pages"][self.cfg["page"]]

    def save(self):
        self.bind_item_names()
        save_config(self.cfg)
        if self.cfg.get("hidden_links") or getattr(self, "_link_wanted", None):
            self.sync_links_soon()
