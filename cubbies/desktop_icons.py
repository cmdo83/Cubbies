"""Where the desktop's own icons sit (Nemo, Caja, Xfdesktop), and drags that start
on the bare desktop."""

import os

from gi.repository import Gdk, Gio, GLib

from .desktop_env import FILE_MANAGER, IS_MATE, IS_XFCE, XfceDesktopIcons, Xfconf
from .hotkeys import selection_owner_info


def _xfce_yaml_icons(path):
    """xfdesktop 4.20's icons.screen0.yaml: [(monitor geometries, {key: (row, col)})] per
    layout it remembers. A small reader for just that file's shape (no YAML library)."""
    import re as _re
    configs, cur, key, in_icons, geo = [], None, None, False, None
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if _re.match(r"^- ", line) or line.startswith("- "):
            cur = {"geos": [], "icons": {}}
            configs.append(cur)
            in_icons, key = False, None
            continue
        if cur is None:
            continue
        text = line.strip()
        if text == "icons:":
            in_icons, key = True, None
            continue
        if text in ("monitors:",):
            in_icons = False
            continue
        if not in_icons:
            if text == "geometry:":
                geo = {}
                cur["geos"].append(geo)
                continue
            m = _re.match(r"^(x|y|width|height):\s*(-?\d+)$", text)
            if m and geo is not None:
                geo[m.group(1)] = int(m.group(2))
            continue
        m = _re.match(r'^"((?:[^"\\]|\\.)*)":\s*$', text) or _re.match(r"^'(.*)':\s*$", text)
        if m:
            key = m.group(1).replace('\\"', '"').replace("\\\\", "\\")
            cur["icons"][key] = [None, None]
            continue
        m = _re.match(r"^(row|col):\s*(-?\d+)$", text)
        if m and key is not None:
            cur["icons"][key][0 if m.group(1) == "row" else 1] = int(m.group(2))
    return [(c["geos"], {k: tuple(v) for k, v in c["icons"].items() if None not in v})
            for c in configs]


def xfce_icon_grid():
    """{icon key: (x, y)} for xfdesktop's icons, in screen pixels like Nemo's positions
    (x + 32, y + 32 is the middle of the icon). The keys are file paths, plus the desktop's own
    icons ("Trash" or "trash:///", "/" for File System, the home folder).

    xfdesktop keeps only grid rows and columns, so the grid is worked out the way it lays it
    out (measured against xfdesktop 4.18 and 4.20 at several icon and screen sizes): square
    cells of 1.9 × icon size + 12 px, as many as fit, and the space left over shared out
    between them. 4.18 (icons.screen0-WxH.rc) leaves a 16 px margin; 4.20 (icons.screen0.yaml)
    leaves 8 px."""
    import glob
    folder = os.path.join(GLib.get_user_config_dir(), "xfce4", "desktop")
    yaml_file = os.path.join(folder, "icons.screen0.yaml")
    rc = os.path.join(folder, "icons.screen.latest.rc")
    real = os.path.realpath(rc) if os.path.exists(rc) else None
    if real is None:
        files = sorted(glob.glob(os.path.join(folder, "icons.screen0-*.rc")),
                       key=os.path.getmtime)
        real = files[-1] if files else None
    use_yaml = os.path.exists(yaml_file) and (
        real is None or os.path.getmtime(yaml_file) >= os.path.getmtime(real))
    if real is None and not use_yaml:
        return {}
    display = Gdk.Display.get_default()
    try:
        mon = display.get_primary_monitor() or display.get_monitor(0)
        wa, mg = mon.get_workarea(), mon.get_geometry()
    except Exception:
        return {}
    places = {}
    if use_yaml:
        margin = 8
        aw, ah = wa.width - 2 * margin, wa.height - 2 * margin
        configs = _xfce_yaml_icons(yaml_file)
        pick = None
        for geos, icons in configs:          # the layout made for this screen, if any
            if any(g.get("width") == mg.width and g.get("height") == mg.height for g in geos):
                pick = icons
        if pick is None and configs:
            pick = configs[-1][1]
        places = pick or {}
    else:
        import re as _re
        margin = 16
        m = _re.search(r"-(\d+)x(\d+)\.rc$", real)
        aw, ah = (int(m.group(1)) - 16, int(m.group(2)) - 16) if m else \
            (wa.width - 32, wa.height - 32)
        kf = GLib.KeyFile()
        try:
            kf.load_from_file(real, GLib.KeyFileFlags.NONE)
        except Exception:
            return {}
        for grp in kf.get_groups()[0]:
            try:
                places[grp] = (kf.get_integer(grp, "row"), kf.get_integer(grp, "col"))
            except Exception:
                continue
    ox, oy = wa.x + margin, wa.y + margin
    size = Xfconf.get("/desktop-icons/icon-size", 48) or 48
    cell = max(20, int(1.9 * size + 12))
    ncols, nrows = max(1, aw // cell), max(1, ah // cell)
    stepx = cell + ((aw - ncols * cell) / (ncols - 1) if ncols > 1 else 0)
    stepy = cell + ((ah - nrows * cell) / (nrows - 1) if nrows > 1 else 0)
    out = {}
    for key, (row, col) in places.items():
        cx = ox + col * stepx + cell / 2
        cy = oy + row * stepy + 6 + size / 2
        out[key] = (int(cx - 32), int(cy - 32))
    return out


def desktop_icon_positions():
    """[(path, x, y)]: where Nemo shows each desktop icon, in screen pixels (the top-left of
    the icon). Nemo keeps these as file metadata; icons it never placed are left out."""
    desk = (GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DESKTOP)
            or os.path.expanduser("~/Desktop"))
    if IS_XFCE:
        return [(g, x, y) for g, (x, y) in xfce_icon_grid().items()
                if os.path.dirname(g) == desk and os.path.lexists(g)]
    out = []
    display = Gdk.Display.get_default()
    fm = FILE_MANAGER          # Caja keeps the same metadata as Nemo, under its own name
    for info in Gio.File.new_for_path(desk).enumerate_children(
            f"standard::name,metadata::{fm}-icon-position,metadata::{fm}-monitor", 0, None):
        pos = info.get_attribute_string(f"metadata::{fm}-icon-position")
        if not pos or info.get_name().startswith("."):
            continue
        try:
            ix, iy = (int(v) for v in pos.split(",")[:2])
        except ValueError:
            continue
        mon = info.get_attribute_string(f"metadata::{fm}-monitor")
        if mon and mon.isdigit() and int(mon) > 0 and display is not None:
            m = display.get_monitor(int(mon))       # positions are per screen
            if m is not None:
                g = m.get_geometry()
                ix, iy = ix + g.x, iy + g.y
        out.append((os.path.join(desk, info.get_name()), ix, iy))
    return out


# Nemo's own desktop icons that aren't files: (name, its on/off key in org.nemo.desktop, place)
DESKTOP_LINKS = (("computer", "computer-icon-visible", "computer:///"),
                 ("home", "home-icon-visible", None),
                 ("trash", "trash-icon-visible", "trash:///"),
                 ("network", "network-icon-visible", "network:///"))


_NEMO_DESKTOP = []


def nemo_desktop_settings():
    if not _NEMO_DESKTOP:
        src = Gio.SettingsSchemaSource.get_default()
        name = "org.mate.caja.desktop" if IS_MATE else "org.nemo.desktop"
        if IS_XFCE:
            _NEMO_DESKTOP.append(XfceDesktopIcons())
        else:
            _NEMO_DESKTOP.append(Gio.Settings.new(name) if src and src.lookup(name, True)
                                 else None)
    return _NEMO_DESKTOP[0]


def desktop_link_positions():
    """[(name, x, y)] for Computer / Home / Trash / Network while they show on the desktop.
    Nemo keeps their places in ~/.config/nemo/desktop-metadata (a group per icon)."""
    settings = nemo_desktop_settings()
    if settings is None:
        return []
    if IS_XFCE:                    # xfdesktop's groups: "Trash", "/" and the home folder
        grid = xfce_icon_grid()
        groups = {"trash": ("Trash", "trash:///"), "computer": ("/",),
                  "home": (os.path.expanduser("~"),)}
        out = []
        for name, key, _uri in DESKTOP_LINKS:
            g = next((k for k in groups.get(name, ()) if k in grid), None)
            if g is not None and settings.get_boolean(key):
                out.append((name, grid[g][0], grid[g][1]))
        return out
    kf = GLib.KeyFile()
    try:
        kf.load_from_file(os.path.join(GLib.get_user_config_dir(), FILE_MANAGER,
                                       "desktop-metadata"), GLib.KeyFileFlags.NONE)
    except Exception:
        return []
    display = Gdk.Display.get_default()
    out = []
    for name, key, _uri in DESKTOP_LINKS:
        try:
            if not settings.get_boolean(key):
                continue
            ix, iy = (int(v) for v in kf.get_string(
                name, f"{FILE_MANAGER}-icon-position").split(",")[:2])
        except Exception:
            continue
        try:
            mon = kf.get_string(name, f"{FILE_MANAGER}-monitor")
        except Exception:
            mon = None
        if mon and mon.isdigit() and int(mon) > 0 and display is not None:
            m = display.get_monitor(int(mon))
            if m is not None:
                g = m.get_geometry()
                ix, iy = ix + g.x, iy + g.y
        out.append((name, ix, iy))
    return out


DND_FROM_DESKTOP = [False]    # set by DesktopWatcher when a drag starts over the bare desktop


def drag_from_desktop():
    """Is the file drag going on now coming from the desktop (not a file manager window)?
    Nemo draws its desktop in a process of its own; Caja draws it in the same process as its
    windows, so there it counts as the desktop when the drag began over the bare desktop."""
    owner = selection_owner_info("XdndSelection")
    if IS_XFCE:
        return "xfdesktop" in owner
    if IS_MATE:
        return "caja" in owner and DND_FROM_DESKTOP[0]
    return "nemo-desktop" in owner
