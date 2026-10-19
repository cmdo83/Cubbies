"""What an icon in a cubby is: its name, picture and place, and how icons sort."""

import os
import time

from gi.repository import GdkPixbuf, Gio, GLib

from .files import trash_has_items


# Names given in Cubbies to items whose real name can't (or shouldn't) change: your Home
# folder, a drive, a Computer / Trash / Network shortcut. {path: name}; kept in cfg
# "item_names" (App keeps this the same dict).
ITEM_NAMES = {}


def home_dir():
    return os.path.normpath(os.path.expanduser("~"))


def is_named_item(path):
    """Renamed in Cubbies only (a name shown in cubbies), never on the disk."""
    p = os.path.normpath(path)
    if p == home_dir():
        return True
    try:
        if os.path.isdir(p) and os.path.ismount(p) and p != "/":
            return True
    except OSError:
        pass
    return bool(place_of(path))


def describe(path, size=48, load_image=True):
    """Return (display name, GIcon, pixbuf-or-None) for a path."""
    name, gicon, pix = _describe(path, size, load_image)
    own = ITEM_NAMES.get(path)
    if own:
        name = own
    elif os.path.normpath(path) == home_dir():
        name = "Home"                    # as the desktop calls it (not your user name)
    return name, gicon, pix


def _describe(path, size=48, load_image=True):
    name = os.path.basename(path.rstrip("/")) or path
    gicon = Gio.ThemedIcon.new("text-x-generic")
    pix = None
    try:
        if path.endswith(".desktop"):
            info = Gio.DesktopAppInfo.new_from_filename(path)
            if info:
                name = info.get_name() or name
                gicon = info.get_icon() or gicon
                if info.get_string("X-Cubbies-Place") == "trash:///":
                    gicon = Gio.ThemedIcon.new("user-trash-full" if trash_has_items()
                                               else "user-trash")
                return name, gicon, None
        f = Gio.File.new_for_path(path)
        info = f.query_info("standard::icon,standard::display-name,standard::content-type", 0, None)
        name = info.get_display_name() or name
        gicon = info.get_icon() or gicon
        if os.path.isdir(path) and os.path.ismount(path) and path != "/":
            try:                       # a mounted drive: its own drive icon and name
                mount = f.find_enclosing_mount(None)
                gicon = mount.get_icon() or gicon
                name = mount.get_name() or name
            except GLib.Error:
                pass
        ctype = info.get_content_type() or ""
        if ctype.startswith("image/") and load_image:
            try:
                pix = GdkPixbuf.Pixbuf.new_from_file_at_size(path, size, size)
            except Exception:
                pix = None
    except Exception:
        pass
    return name, gicon, pix


def place_of(path):
    """The place (computer:///, trash:///...) a Cubbies place shortcut opens, or None."""
    if not path.endswith(".desktop"):
        return None
    try:
        info = Gio.DesktopAppInfo.new_from_filename(path)
        return info.get_string("X-Cubbies-Place") if info else None
    except Exception:
        return None


# Places that aren't folders on the disk: they go into a cubby as small shortcut files
SYSTEM_PLACES = (("computer:///", "Computer", "computer"),
                 ("trash:///", "Trash", "user-trash"),
                 ("network:///", "Network", "network-workgroup"),
                 ("recent:///", "Recent", "document-open-recent"))


def detail_columns(path):
    """(text, width in characters) pairs shown in the Details view: size and date modified."""
    try:
        st = os.stat(path)
        size = "" if os.path.isdir(path) else GLib.format_size(st.st_size)
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))
    except OSError:
        size, when = "", ""
    return [(when, 16), (size, 9)]


SORT_MODES = [
    ("manual", "Manual (Drag to Arrange)"),
    ("name", "Name"),
    ("type", "Type"),
    ("date", "Date Modified (Newest First)"),
    ("size", "Size (Largest First)"),
]


def sort_key(path, mode):
    base = os.path.basename(path.rstrip("/")).casefold()
    try:
        st = os.stat(path)
    except OSError:
        st = None
    if mode == "name":
        return (describe(path)[0].casefold(),)
    if mode == "type":
        is_dir = os.path.isdir(path)
        return (0 if is_dir else 1, "" if is_dir else os.path.splitext(base)[1], base)
    if mode == "date":
        return (-(st.st_mtime if st else 0), base)
    if mode == "size":
        return (-(st.st_size if st else 0), base)
    return (0,)
