"""Working with files: trash, network folders, recent files, file kinds for Inbox
Cubbies, opening things."""

import os
import shutil
import sys
import time

from gi.repository import Gio, GLib, Gtk

from .constants import CATEGORY_EXTS, IGNORED_SUFFIXES, INBOX_ICONS, NETWORK_FS
from .core import dbg
from .desktop_env import IS_XFCE


def trash_has_items():
    try:
        info = Gio.File.new_for_uri("trash:///").query_info("trash::item-count", 0, None)
        return info.get_attribute_uint32("trash::item-count") > 0
    except Exception:
        return False
_mounts_cache = [0.0, []]


def _mounts():
    """(mount point, filesystem type) pairs, longest mount point first (re-read every 5 s)."""
    now = time.monotonic()
    if now - _mounts_cache[0] > 5:
        out = []
        try:
            with open("/proc/self/mounts") as fh:
                for line in fh:
                    parts = line.split()
                    if len(parts) >= 3:
                        point = parts[1].replace("\\040", " ").replace("\\011", "\t")
                        out.append((point, parts[2]))
        except OSError:
            pass
        out.sort(key=lambda m: len(m[0]), reverse=True)
        _mounts_cache[:] = [now, out]
    return _mounts_cache[1]


def is_network_path(path):
    """True for a file on a network share (Samba/Windows shares, NFS, SSH, the file manager's
    own network mounts...). Those have no Trash, and the file manager's changes to them are
    not announced to other programs, so Cubbies checks them itself now and then."""
    if not path:
        return False
    try:
        real = os.path.realpath(path)
    except Exception:
        real = path
    if "/gvfs/" in real:
        return True
    for point, fstype in _mounts():
        if real == point or real.startswith(point.rstrip("/") + "/"):
            return fstype in NETWORK_FS
    return False


def can_trash(path):
    """Whether this file can go to the Trash (network folders usually can't)."""
    if is_network_path(path):
        return False
    try:
        info = Gio.File.new_for_path(path).query_info(
            "access::can-trash", Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, None)
        if info.has_attribute("access::can-trash"):
            return info.get_attribute_boolean("access::can-trash")
    except Exception:
        pass
    return True


def delete_permanently(path):
    """Delete a file or a whole folder for good (no Trash). Returns an error text or None."""
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        return None
    except OSError as exc:
        return exc.strerror or str(exc)


def restore_from_trash(orig):
    """Put a file that was moved to the Trash back where it was. Returns True if it worked."""
    try:
        trash = Gio.File.new_for_uri("trash:///")
        best = None
        for info in trash.enumerate_children(
                "standard::name,trash::orig-path,trash::deletion-date", 0, None):
            if info.get_attribute_as_string("trash::orig-path") == orig:
                when = info.get_attribute_as_string("trash::deletion-date") or ""
                if best is None or when > best[0]:
                    best = (when, info.get_name())
        if best is not None:
            trash.get_child(best[1]).move(Gio.File.new_for_path(orig),
                                          Gio.FileCopyFlags.NONE, None, None, None)
            return True
    except Exception as exc:
        dbg("trash via gio:", repr(exc))
    # the Trash folder in your home folder, read directly
    import urllib.parse
    base = os.path.join(GLib.get_user_data_dir(), "Trash")
    best = None
    try:
        for fn in os.listdir(os.path.join(base, "info")):
            if not fn.endswith(".trashinfo"):
                continue
            path = when = None
            with open(os.path.join(base, "info", fn)) as fh:
                for line in fh:
                    if line.startswith("Path="):
                        path = urllib.parse.unquote(line[5:].strip())
                    elif line.startswith("DeletionDate="):
                        when = line[13:].strip()
            if path == orig and (best is None or (when or "") > best[0]):
                best = (when or "", fn[:-len(".trashinfo")])
    except OSError:
        return False
    if best is None:
        return False
    try:
        shutil.move(os.path.join(base, "files", best[1]), orig)
        os.remove(os.path.join(base, "info", best[1] + ".trashinfo"))
        return True
    except OSError as exc:
        print("Cubbies: could not take", orig, "back out of the Trash -", exc, file=sys.stderr)
        return False


def recent_files(limit=20):
    """The files you opened lately, newest first (the same list the system menus use)."""
    try:
        items = Gtk.RecentManager.get_default().get_items()
    except Exception:
        return []
    found = []
    for info in items:
        uri = info.get_uri()
        if not uri.startswith("file://"):
            continue
        path = Gio.File.new_for_uri(uri).get_path()
        if not path or not os.path.exists(path):
            continue
        when = max(info.get_modified() or 0, info.get_visited() or 0)
        if hasattr(when, "to_unix"):
            when = when.to_unix()
        found.append((when, path))
    found.sort(key=lambda t: t[0], reverse=True)
    out, seen = [], set()
    for _when, path in found:
        if path not in seen:
            seen.add(path)
            out.append(path)
        if len(out) >= limit:
            break
    return out


def is_recent(pane):
    return bool(pane.get("recent"))


def file_category(path):
    """Which kind of file this is, for collecting new desktop files into the right cubby."""
    if os.path.isdir(path):
        return "drives" if os.path.ismount(path) and path != "/" else "folders"
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    for cat, exts in CATEGORY_EXTS.items():
        if ext in exts:
            return cat
    return "other"


def parse_exts(text):
    """ "py, .SH  js" -> ["py", "sh", "js"] (file extensions for a filter tab)."""
    out = []
    for part in text.replace(",", " ").replace(";", " ").split():
        ext = part.strip().lstrip("*").lstrip(".").lower()
        if ext and ext not in out:
            out.append(ext)
    return out


def inbox_kind_of(path, custom):
    """The filter tab for a file: a nook it was put in, else a user tab whose extensions
    match, else the built-in kind."""
    for c in custom:
        if c.get("nook") and path in c.get("items", []):
            return "x:" + c["id"]
    if not os.path.isdir(path):
        name = os.path.basename(path).lower()
        for c in custom:
            for ext in c.get("exts", []):
                if name.endswith("." + ext):
                    return "x:" + c["id"]
    return file_category(path)


def is_inbox(pane):
    """An Inbox Cubby takes the files that no other cubby collects (and is not a Folder Cubby)."""
    return "other" in pane.get("collect", []) and not pane.get("folder")


def inbox_icon_name():
    theme = Gtk.IconTheme.get_default()
    return next((n for n in INBOX_ICONS if theme.has_icon(n)), "go-down")


def ignorable_new_file(path):
    """Files that are still being made, hidden files, or names Nemo gives while you rename."""
    name = os.path.basename(path)
    return (name.startswith(".") or name.lower().endswith(IGNORED_SUFFIXES)
            or name.startswith("Untitled"))


def launch(path):
    try:
        if path.endswith(".desktop"):
            info = Gio.DesktopAppInfo.new_from_filename(path)
            if info:
                place = info.get_string("X-Cubbies-Place")
                if place:                  # Computer, Trash, a network share...: the file
                    if IS_XFCE and place == "computer:///":            # manager opens it
                        place = "file:///"     # (Thunar has no Computer view)
                    Gio.AppInfo.launch_default_for_uri(place, None)
                    return
                info.launch([], None)
                return
        Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(path).get_uri(), None)
    except Exception as exc:
        print("Could not open", path, exc, file=sys.stderr)


def uris_to_paths(uris):
    out = []
    for u in uris or []:
        p = Gio.File.new_for_uri(u).get_path()
        if p:
            out.append(p)
    return out
