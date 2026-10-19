"""Collecting new desktop files into cubbies, mounted drives, and the store folder."""

import os
import shutil
import sys
import time

from gi.repository import Gio, GLib

from ..core import CONFIG_DIR, dbg
from ..files import file_category, ignorable_new_file


class AppStore:
    """Collecting files, drives and the store folder. Part of App."""

    # -- collecting new desktop files into cubbies (by kind)
    def collect_scope(self, pane):
        """The cubbies that compete with this one for a kind of file: all of them, or (with
        collecting per page) the ones on its page."""
        if not self.setting("collect_per_page"):
            return list(self.all_cubbies())
        page = self.page_of(pane)
        return [f for f in self.all_cubbies() if self.page_of(f) is page]

    def set_collect(self, pane, kinds):
        """This cubby collects these kinds of new desktop files (taking them from any other,
        or from any other on its page when each page collects for itself)."""
        for fdata in self.collect_scope(pane) + [pane]:
            if "drives" in fdata.get("collect", []) and (
                    fdata is not pane and "drives" in kinds
                    or fdata is pane and "drives" not in kinds):
                self.drop_auto_drives(fdata)
        if "drives" in kinds:
            GLib.idle_add(lambda: self.sync_drives() and False)
        for fdata in self.collect_scope(pane):
            if fdata is not pane and fdata.get("collect"):
                fdata["collect"] = [k for k in fdata["collect"] if k not in kinds]
                if not fdata["collect"]:
                    fdata.pop("collect")
        if kinds:
            pane["collect"] = kinds
        else:
            pane.pop("collect", None)
        self.save()

    def collector_for(self, kind, page=None):
        """The cubby that takes this kind of new desktop file. With collecting per page:
        the one on `page` (the page you were on), or a cubby shown on every page."""
        def ok(f):
            return (kind in f.get("collect", []) and not f.get("folder")
                    and not f.get("group"))
        if not self.setting("collect_per_page"):
            return next((f for f in self.all_cubbies() if ok(f)), None)
        page = page if page is not None else self.page()
        here = [f for f in self.all_cubbies() if self.page_of(f) is page and ok(f)]
        if here:
            return here[0]
        every = next((f for f in self.all_cubbies() if ok(f) and f.get("all_pages")), None)
        if every is not None:
            return every
        # a page without its own choice uses the choices of the page picked for that
        # (Settings › Sorting & Organising), or the file stays on the desktop
        fallback = self.page_by_id(self.cfg.get("collect_default_page"))
        if fallback is not None and fallback is not page:
            return next((f for f in self.all_cubbies()
                         if self.page_of(f) is fallback and ok(f)), None)
        return None

    def page_by_id(self, pid):
        return next((p for p in self.cfg["pages"] if pid and p.get("pid") == pid), None)

    # -- mounted drives go into the cubby that collects "drives" (and leave when unmounted)
    def watch_drives(self):
        try:
            mon = self._vol_mon = Gio.VolumeMonitor.get()
            mon.connect("mount-added", lambda _m, _mt: GLib.timeout_add(
                800, lambda: self.sync_drives() and False))
            mon.connect("mount-removed", lambda _m, _mt: GLib.timeout_add(
                300, lambda: self.sync_drives() and False))
            GLib.timeout_add(2500, lambda: self.sync_drives() and False)
        except Exception as exc:
            dbg("drives can't be watched:", exc)

    def drop_auto_drives(self, fdata):
        auto = fdata.pop("auto_drives", [])
        if auto:
            fdata["items"] = [p for p in fdata.get("items", []) if p not in auto]
            self.refresh_cubby(fdata)

    def sync_drives(self):
        """Drives mounted now are in the collecting cubby; ones it took in that are gone
        now leave it again."""
        now = {p for _n, p in self.mounted_drives()}
        changed = False
        for f in self.all_cubbies():
            auto = f.get("auto_drives")
            if not auto:
                continue
            gone = [p for p in auto if p not in now]
            if gone:
                f["items"] = [p for p in f.get("items", []) if p not in gone]
                f["auto_drives"] = [p for p in auto if p not in gone]
                if not f["auto_drives"]:
                    f.pop("auto_drives")
                self.refresh_cubby(f)
                changed = True
        known = {p for f in self.all_cubbies() for p in f.get("items", [])}
        for p in sorted(now - known):
            target = self.collector_for("drives")
            if target is None:
                break
            target.setdefault("items", []).append(p)
            target.setdefault("auto_drives", []).append(p)
            self.refresh_cubby(target)
            dbg("drive", p, "collected into", target.get("title"))
            changed = True
        if changed:
            self.save()

    def set_collect_per_page(self, on):
        self.cfg["collect_per_page"] = bool(on)
        if on and "collect_default_page" not in self.cfg:
            # the page that collected everything so far keeps doing it for the other pages
            owner = next((f for f in self.all_cubbies() if f.get("collect")), None)
            if owner is not None:
                self.cfg["collect_default_page"] = self.page_id(self.page_of(owner))
        if not on:                  # back to one cubby per kind: the first one keeps it
            seen = set()
            for f in self.all_cubbies():
                kinds = [k for k in f.get("collect", []) if k not in seen]
                seen.update(kinds)
                if kinds:
                    f["collect"] = kinds
                else:
                    f.pop("collect", None)
        self.save()
        for win in self.windows.values():
            win.refresh()

    def watch_desktop(self):
        desktop = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DESKTOP)
        desktop = desktop or os.path.expanduser("~/Desktop")
        if not os.path.isdir(desktop):
            return
        self._desktop_dir = desktop
        self._desk_pending = {}
        self._desk_timer = 0
        self._desk_monitor = Gio.File.new_for_path(desktop).monitor_directory(
            Gio.FileMonitorFlags.WATCH_MOVES, None)
        self._desk_monitor.connect("changed", self.on_desktop_changed)

    def on_desktop_changed(self, _mon, file, _other, event):
        # a finished copy/download, or something moved in; a bare "created" is still being
        # written (or is a New Folder waiting for its name), so it is not touched
        if event not in (Gio.FileMonitorEvent.CHANGES_DONE_HINT, Gio.FileMonitorEvent.MOVED_IN):
            return
        path = file.get_path()
        if not path or os.path.dirname(path) != self._desktop_dir or ignorable_new_file(path):
            return
        if path.endswith(".desktop"):
            GLib.timeout_add(400, lambda p=path: self.desktop_link_dropped(p) and False)
        if not any(f.get("collect") for f in self.all_cubbies()):
            return
        # remember the page you're on now: with collecting per page it decides where it goes
        self._desk_pending.setdefault(path, self.cfg["page"])
        if not self._desk_timer:
            self._desk_timer = GLib.timeout_add(1500, self._collect_desktop)

    def _collect_desktop(self):
        self._desk_timer = 0
        pending, self._desk_pending = self._desk_pending, {}
        if not self.setting("move_files"):
            return False
        known = {p for f in self.all_cubbies() for p in f["items"]}
        for path in pending:
            try:
                if not os.path.lexists(path) or path in known:
                    continue
                if time.time() - os.lstat(path).st_mtime < 1.0:
                    self._desk_pending[path] = pending[path]   # changed a moment ago: later
                    continue
                pages = self.cfg["pages"]
                page = pages[pending[path]] if 0 <= pending[path] < len(pages) else None
                target = (self.collector_for(file_category(path), page)
                          or self.collector_for("other", page))
                if target is None:
                    continue
                dbg("collecting", path, "into", target.get("title"))
                self.add_items(target, [path])
            except Exception as exc:
                print("Cubbies: could not collect", path, "-", exc, file=sys.stderr)
        if self._desk_pending:
            self._desk_timer = GLib.timeout_add(1500, self._collect_desktop)
        return False

    def watch_store(self):
        """Keep the cubbies in step with the folder: a stored file moved or deleted elsewhere
        leaves its cubby, and a renamed one keeps its icon."""
        store = self.store_dir()
        if not os.path.isdir(store):
            if not self.setting("move_files"):
                return
            self.make_store(store)
        self._reconcile_id = 0
        self._store_monitor = Gio.File.new_for_path(store).monitor_directory(
            Gio.FileMonitorFlags.WATCH_MOVES, None)
        self._store_monitor.connect("changed", self.on_store_changed)
        self.reconcile_store()

    def on_store_changed(self, _monitor, file, other, event):
        if event == Gio.FileMonitorEvent.RENAMED and other is not None:
            old, new = file.get_path(), other.get_path()
            for fdata in self.all_cubbies():
                if old in fdata["items"]:
                    fdata["items"][fdata["items"].index(old)] = new
                    self.refresh_cubby(fdata)
                    self.save()
        elif event in (Gio.FileMonitorEvent.DELETED, Gio.FileMonitorEvent.MOVED_OUT):
            if not self._reconcile_id:
                self._reconcile_id = GLib.timeout_add(300, self._reconcile_later)

    def _reconcile_later(self):
        self._reconcile_id = 0
        self.reconcile_store()
        return False

    def reconcile_store(self):
        """Drop stored items whose file is no longer there."""
        if not os.path.isdir(self.store_dir()):
            return
        changed = False
        for fdata in self.all_cubbies():
            gone = [p for p in fdata["items"]
                    if self.is_managed(p) and not os.path.lexists(p)]
            for p in gone:
                dbg("no longer in the store, removed from cubby:", p)
                fdata["items"].remove(p)
            if gone:
                self.refresh_cubby(fdata)
                changed = True
        if changed:
            self.save()

    def store_dir(self):
        return self.cfg.get("store_dir") or os.path.expanduser("~/Cubbies")

    STORE_MARK = ".cubbies-store"     # in a store folder Cubbies made (uninstalling empties it)

    def make_store(self, folder=None):
        """Create the store folder if needed. One Cubbies makes itself gets a small hidden
        mark, so uninstalling knows everything in it is Cubbies' to give back."""
        folder = folder or self.store_dir()
        if not os.path.isdir(folder):
            os.makedirs(folder, exist_ok=True)
            try:
                with open(os.path.join(folder, self.STORE_MARK), "w") as fh:
                    fh.write("Cubbies keeps the files you put in cubbies here.\n")
            except OSError:
                pass
        return folder

    def is_managed(self, path):
        store = os.path.realpath(self.store_dir())
        return os.path.realpath(path).startswith(store + os.sep)

    def should_move(self, path):
        """Only real files/folders inside your home folder are moved into the store; system
        launchers, hidden items and the standard folders themselves never are."""
        if not self.setting("move_files"):
            return False
        home = os.path.expanduser("~")
        ap = os.path.abspath(path)
        if not (os.path.lexists(ap) and ap.startswith(home + os.sep)):
            return False
        rel = os.path.relpath(ap, home).split(os.sep)
        if any(part.startswith(".") for part in rel):
            return False
        protected = {home}
        for name in ("DESKTOP", "DOCUMENTS", "DOWNLOAD", "MUSIC", "PICTURES",
                     "PUBLIC_SHARE", "TEMPLATES", "VIDEOS"):
            special = GLib.get_user_special_dir(getattr(GLib.UserDirectory, "DIRECTORY_" + name))
            if special:
                protected.add(os.path.abspath(special))
        if ap in protected or self.is_managed(ap) or os.path.ismount(ap):
            return False
        store = os.path.abspath(self.store_dir())
        if store == ap or store.startswith(ap + os.sep):
            return False
        return os.access(os.path.dirname(ap), os.W_OK)

    def store_dir_problem(self, new):
        """Why a folder can't hold the cubby files, or None when it can."""
        old = os.path.realpath(self.store_dir())
        new = os.path.realpath(new)
        home = os.path.realpath(os.path.expanduser("~"))
        special = {home, "/", os.path.realpath(CONFIG_DIR)}
        for d in (GLib.UserDirectory.DIRECTORY_DESKTOP, GLib.UserDirectory.DIRECTORY_DOCUMENTS,
                  GLib.UserDirectory.DIRECTORY_DOWNLOAD, GLib.UserDirectory.DIRECTORY_MUSIC,
                  GLib.UserDirectory.DIRECTORY_PICTURES, GLib.UserDirectory.DIRECTORY_VIDEOS,
                  GLib.UserDirectory.DIRECTORY_TEMPLATES, GLib.UserDirectory.DIRECTORY_PUBLIC_SHARE):
            p = GLib.get_user_special_dir(d)
            if p:
                special.add(os.path.realpath(p))
        if new == old:
            return "That is already the folder in use."
        if new in special:
            return ("Please choose (or make) a folder of its own, not your home folder or one "
                    "of the standard folders like Desktop or Documents.")
        if new.startswith(old + os.sep):
            return "The new folder can't be inside the current one."
        if old.startswith(new + os.sep):
            return "The new folder can't contain the current one."
        try:
            busy = os.path.isdir(new) and any(n != self.STORE_MARK for n in os.listdir(new))
        except OSError:
            busy = True
        if busy:
            return ("Please choose an empty folder, or a new one: Cubbies' files shouldn't "
                    "mix with files already there.")
        parent = new
        while parent and not os.path.isdir(parent):      # the nearest folder that exists
            parent = os.path.dirname(parent)
        if not os.access(parent or "/", os.W_OK):
            return "You don't have permission to put files there."
        return None

    def change_store_dir(self, new):
        """Keep cubby files in another folder: everything in the old folder is moved there
        (names that clash get " (2)"), every cubby is updated to the new places (this is the
        "store_dir" and item paths in ~/.config/cubbies/config.json), and the old folder is
        removed once it is empty. Returns (moved count, [problems])."""
        old = os.path.abspath(self.store_dir())
        new = os.path.abspath(new)
        problem = self.store_dir_problem(new)
        if problem:
            return 0, [problem]
        self.make_store(new)
        mon = getattr(self, "_store_monitor", None)
        if mon is not None:
            mon.cancel()
            self._store_monitor = None
        mapping, problems = {}, []
        if os.path.isdir(old):
            for name in sorted(os.listdir(old)):
                src = os.path.join(old, name)
                dest = self.unique_path(new, name)
                try:
                    shutil.move(src, dest)
                    mapping[src] = dest
                except Exception as exc:
                    problems.append(f"{name}: {exc}")

        def moved(path):
            if path in mapping:
                return mapping[path]
            for src, dest in mapping.items():          # something inside a moved folder
                if path.startswith(src + os.sep):
                    return dest + path[len(src):]
            return path

        for fdata in self.all_cubbies():
            fdata["items"] = [moved(p) for p in fdata.get("items", [])]
            if fdata.get("folder"):
                fdata["folder"] = moved(fdata["folder"])
        if self.clip:
            self.clip["paths"] = [moved(p) for p in self.clip["paths"]]
        self.cfg["store_dir"] = new
        if not problems and os.path.isdir(old):
            try:
                os.rmdir(old)                       # only ever removed when empty
            except OSError as exc:
                problems.append(f"The old folder could not be removed: {exc}")
        self.save()
        for win in self.windows.values():
            win.refresh()
        self.watch_store()
        dbg("file store moved:", old, "->", new, len(mapping), "items", problems)
        return len(mapping), problems

    def unique_path(self, folder, name):
        stem, ext = os.path.splitext(name)
        candidate, n = os.path.join(folder, name), 2
        while os.path.lexists(candidate):
            candidate = os.path.join(folder, f"{stem} ({n}){ext}")
            n += 1
        return candidate

    def import_paths(self, paths):
        """Move newly added files into the store; return the paths the cubby should hold."""
        existing = {p for page in self.cfg["pages"] for f in page["cubbies"] for p in f["items"]}
        out = []
        for path in paths:
            if path in existing or not self.should_move(path):
                out.append(path)
                continue
            try:
                self.make_store()
                dest = self.unique_path(self.store_dir(), os.path.basename(path.rstrip("/")))
                shutil.move(path, dest)
                self.undo_note("move", path, dest)
                dbg("moved", path, "->", dest)
                out.append(dest)
            except Exception as exc:
                print("Cubbies: could not move", path, "-", exc, "(kept as a link)",
                      file=sys.stderr)
                out.append(path)
        return out
