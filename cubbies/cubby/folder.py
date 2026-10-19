"""Folder Cubbies: showing a real folder live, and moving around inside it."""

import os

from gi.repository import Gio, GLib

from ..constants import MAX_FOLDER_ITEMS
from ..core import dbg
from ..files import is_network_path


class CubbyFolder:
    """Folder Cubbies. Part of Cubby."""

    # -- navigating inside a Folder Cubby (double-click a folder; ↑ goes back up)
    def navigate(self, path):
        root = self.pane.get("folder")
        if not root:
            return
        if path is None or os.path.abspath(path) == os.path.abspath(root):
            self.pane.pop("nav", None)
        else:
            self.pane["nav"] = os.path.abspath(path)
        self.selected = set()
        self.refresh()
        self.app.save()
        dbg("folder cubby now shows", self.app.folder_of(self.pane))

    def navigate_up(self, *_a):
        cur = self.app.folder_of(self.pane)
        root = self.pane.get("folder")
        if cur and root and os.path.abspath(cur) != os.path.abspath(root):
            self.navigate(os.path.dirname(cur))

    # -- Folder Cubbies: the cubby shows what is inside a real folder, live
    def folder_items(self, folder):
        try:
            names = os.listdir(folder)
        except OSError:
            return []
        return [os.path.join(folder, n) for n in names
                if not n.startswith(".") and not n.endswith("~")][:MAX_FOLDER_ITEMS]

    def watch_folder(self):
        folder = self.app.folder_of(self.pane)
        if folder == self._monitor_path:
            return
        self.stop_watching()
        if not folder or not os.path.isdir(folder):
            return
        try:
            mon = Gio.File.new_for_path(folder).monitor_directory(
                Gio.FileMonitorFlags.WATCH_MOVES, None)
            mon.connect("changed", self.on_folder_changed)
            self._monitor, self._monitor_path = mon, folder
        except GLib.Error as exc:
            dbg("could not watch", folder, exc)
        self._monitor_path = folder
        if is_network_path(folder):
            # Changes made on a network share (or by the file manager through its own network
            # connection) are not announced, so look at the folder every few seconds.
            dbg("network folder, checking it every 3 s:", folder)
            self._net_names = None
            self._net_timer = GLib.timeout_add_seconds(3, self._poll_network)

    def _poll_network(self):
        folder = self._monitor_path
        if not folder or not self.get_visible():
            return True
        if self._net_busy:
            return True
        self._net_busy = True
        import threading

        def work():
            try:
                names = frozenset(os.listdir(folder))
            except OSError:
                names = None
            GLib.idle_add(done, names)

        def done(names):
            self._net_busy = False
            if folder != self._monitor_path or names is None:
                return False
            if self._net_names is not None and names != self._net_names:
                dbg("network folder changed:", folder)
                self._net_names = names
                if self.pane.get("folder"):
                    self.refresh()
            self._net_names = names
            return False
        threading.Thread(target=work, daemon=True).start()
        return True

    def stop_watching(self):
        if self._monitor is not None:
            self._monitor.cancel()
        self._monitor = None
        self._monitor_path = None
        if self._net_timer:
            GLib.source_remove(self._net_timer)
            self._net_timer = 0
        self._net_names = None
        if self._folder_timer:
            GLib.source_remove(self._folder_timer)
            self._folder_timer = 0

    def on_folder_changed(self, _mon, _file, _other, event):
        if event in (Gio.FileMonitorEvent.CREATED, Gio.FileMonitorEvent.DELETED,
                     Gio.FileMonitorEvent.MOVED_IN, Gio.FileMonitorEvent.MOVED_OUT,
                     Gio.FileMonitorEvent.RENAMED, Gio.FileMonitorEvent.CHANGES_DONE_HINT):
            if not self._folder_timer:
                self._folder_timer = GLib.timeout_add(250, self._folder_refresh)

    def _folder_refresh(self):
        self._folder_timer = 0
        if self.pane.get("folder"):
            self.refresh()
        return False
