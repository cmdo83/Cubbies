"""Thumbnails (the same cache the file manager uses), finding wallpapers, and the
blurred copy of the wallpaper drawn behind cubbies."""

import os
import sys

from gi.repository import Gdk, GdkPixbuf, Gio, GLib

from .core import dbg
from .desktop_env import DESKTOP, IS_MATE, IS_XFCE


# ---- thumbnails (the same picture cache Nemo uses: ~/.cache/thumbnails)
_THUMB_MEM = {}
_THUMB_FAILED = set()
_THUMB_POOL = None

# ---- wallpapers, found the same way as Mint's own Backgrounds settings
# a page's own background settings: (page key, org.cinnamon.desktop.background key)
PAGE_BG = (("wallpaper_aspect", "picture-options"), ("wallpaper_shading", "color-shading-type"),
           ("wallpaper_color1", "primary-color"), ("wallpaper_color2", "secondary-color"))
SHADINGS = (("solid", "Solid colour"), ("horizontal", "Horizontal gradient"),
            ("vertical", "Vertical gradient"))
WALLPAPER_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".svg", ".bmp", ".tif", ".tiff", ".gif")
PICTURE_ASPECTS = (("none", "No picture"), ("wallpaper", "Mosaic"), ("centered", "Centered"),
                   ("scaled", "Scaled"), ("stretched", "Stretched"), ("zoom", "Zoom"),
                   ("spanned", "Spanned"))


def wallpaper_collections():
    """The system wallpaper sets (/usr/share/cinnamon-background-properties/*.xml), named
    and ordered as Backgrounds does: [(name, icon names, [(path, title)])]."""
    import xml.etree.ElementTree as ET
    found = {}
    kinds = {"mate": ("mate-background-properties", "gnome-background-properties"),
             "xfce": ("cinnamon-background-properties", "mate-background-properties",
                      "gnome-background-properties")}.get(DESKTOP,
                                                          ("cinnamon-background-properties",))
    for d, kind in [(d, k) for k in kinds for d in GLib.get_system_data_dirs()]:
        folder = os.path.join(d, kind)
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for n in names:
            if not n.endswith(".xml") or n in found:
                continue
            try:
                root = ET.parse(os.path.join(folder, n)).getroot()
            except Exception:
                continue
            pics = []
            for wp in root.iter("wallpaper"):
                if wp.get("deleted") == "true":
                    continue
                fn = (wp.findtext("filename") or "").strip()
                if not fn or not os.path.isfile(fn):
                    continue
                title = next((e.text for e in wp.findall("name")
                              if not any(k.endswith("lang") for k in e.attrib) and e.text), None)
                pics.append((fn, (title or os.path.splitext(os.path.basename(fn))[0]).strip()))
            if not pics:
                continue
            name = n[:-4].replace("-", " ").replace("_", " ").split(" ")[-1].capitalize()
            if name == "Linuxmint":
                found[n] = ("Linux Mint", ("linuxmint-logo-badge-symbolic", "linuxmint-logo",
                                           "start-here-symbolic"), 0, pics)
            elif name == "Retro":
                found[n] = (name, ("xsi-document-open-recent-symbolic",
                                   "document-open-recent-symbolic"), 20, pics)
            else:
                found[n] = (name, ("xsi-wallpaper-symbolic", "preferences-desktop-wallpaper-symbolic",
                                   "image-x-generic-symbolic"), 10, pics)
    out = sorted(found.values(), key=lambda c: (c[2], c[0]))
    out = [(c[0], c[1], c[3]) for c in out]
    if IS_XFCE:                    # Xfce has no wallpaper sets: its folders become sets
        have = {p for c in out for p, _t in c[2]}
        root = "/usr/share/backgrounds"
        try:
            subs = sorted(n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n)))
        except OSError:
            subs = []
        for name, folder in [(n, os.path.join(root, n)) for n in subs] + [("Backgrounds", root)]:
            pics = [(fp, t) for fp, t in folder_wallpapers(folder) if fp not in have]
            if pics:
                have.update(fp for fp, _t in pics)
                out.append((name.replace("-", " ").replace("_", " ").title(),
                            ("xsi-wallpaper-symbolic", "preferences-desktop-wallpaper-symbolic",
                             "image-x-generic-symbolic"), pics))
    return out


def wallpaper_folders_file():
    if IS_MATE or IS_XFCE:         # they keep no such list: Cubbies keeps its own
        return os.path.join(GLib.get_user_config_dir(), "cubbies", "wallpaper-folders.lst")
    return os.path.join(GLib.get_user_config_dir(), "cinnamon", "backgrounds", "user-folders.lst")


def wallpaper_folders():
    """Your own wallpaper folders: the same list Backgrounds keeps (so a folder added in either
    place shows in both). Pictures when there is no list yet."""
    files = [wallpaper_folders_file()]
    if DESKTOP == "cinnamon":
        files.append(os.path.expanduser("~/.cinnamon/backgrounds/user-folders.lst"))
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                return [ln.strip() for ln in fh if ln.strip()]
        except OSError:
            continue
    pics = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES) or \
        os.path.expanduser("~/Pictures")
    return [pics]


def save_wallpaper_folders(folders):
    f = wallpaper_folders_file()
    try:
        os.makedirs(os.path.dirname(f), exist_ok=True)
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("".join(x + "\n" for x in folders))
    except OSError as exc:
        print("Cubbies: could not save the wallpaper folders:", exc, file=sys.stderr)


def folder_wallpapers(folder):
    """The pictures in a folder, sorted by file name: [(path, title)]."""
    try:
        names = sorted(os.listdir(folder), key=str.lower)
    except OSError:
        return []
    return [(os.path.join(folder, n), os.path.splitext(n)[0]) for n in names
            if n.lower().endswith(WALLPAPER_EXTS) and not n.startswith(".")
            and os.path.isfile(os.path.join(folder, n))][:600]


def framed_thumbnail(pb):
    """A thumbnail with rounded corners and a soft shadow, like Backgrounds shows them."""
    import cairo
    import math
    w, h = pb.get_width(), pb.get_height()
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w + 6, h + 6)
    cr = cairo.Context(surf)

    def rounded(x, y, rw, rh, r):
        cr.new_sub_path()
        cr.arc(x + rw - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + rw - r, y + rh - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + rh - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
        cr.close_path()
    for i, a in ((3, 0.10), (2, 0.16)):
        rounded(1 + i / 2, 1 + i, w, h, 5)
        cr.set_source_rgba(0, 0, 0, a)
        cr.fill()
    rounded(1, 1, w, h, 5)
    cr.clip()
    Gdk.cairo_set_source_pixbuf(cr, pb, 1, 1)
    cr.paint()
    return Gdk.pixbuf_get_from_surface(surf, 0, 0, w + 6, h + 6)


def thumb_pool():
    global _THUMB_POOL
    if _THUMB_POOL is None:
        from concurrent.futures import ThreadPoolExecutor
        _THUMB_POOL = ThreadPoolExecutor(max_workers=2)
    return _THUMB_POOL


def _thumbnailers():
    """{mime type: Exec line} from /usr/share/thumbnailers (videos, PDFs, fonts ...)."""
    out = {}
    for d in [os.path.join(GLib.get_user_data_dir(), "thumbnailers")] + \
             [os.path.join(x, "thumbnailers") for x in GLib.get_system_data_dirs()]:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            if not n.endswith(".thumbnailer"):
                continue
            kf = GLib.KeyFile()
            try:
                kf.load_from_file(os.path.join(d, n), GLib.KeyFileFlags.NONE)
                execl = kf.get_string("Thumbnailer Entry", "Exec")
                mimes = kf.get_string("Thumbnailer Entry", "MimeType")
            except Exception:
                continue
            for m in mimes.split(";"):
                if m.strip() and m.strip() not in out:
                    out[m.strip()] = execl
    return out


_THUMBNAILERS = None


def make_thumbnail(path, size):
    """A preview picture of a file, at most `size` px, or None. Uses a thumbnail already in
    the cache when it is up to date; otherwise makes one (pictures directly, other files with
    the system's thumbnailers) and saves it to the cache for Nemo too. Runs in a worker."""
    global _THUMBNAILERS
    import hashlib
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (path, int(st.st_mtime), size)
    if key in _THUMB_MEM:
        return _THUMB_MEM[key]
    if (path, int(st.st_mtime)) in _THUMB_FAILED:
        return None
    uri = Gio.File.new_for_path(path).get_uri()
    name = hashlib.md5(uri.encode()).hexdigest() + ".png"
    cache = os.path.join(GLib.get_user_cache_dir(), "thumbnails")
    big = None
    for folder in (("normal", "large", "x-large") if size <= 128 else ("large", "x-large")):
        tp = os.path.join(cache, folder, name)
        if os.path.exists(tp):
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file(tp)
                if pb.get_option("tEXt::Thumb::MTime") in (str(int(st.st_mtime)), None):
                    big = pb
                    break
            except Exception:
                pass
    if big is None:
        ctype = ""
        try:
            ctype = Gio.File.new_for_path(path).query_info(
                "standard::content-type", 0, None).get_content_type() or ""
        except Exception:
            pass
        try:
            if ctype.startswith("image/"):
                big = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 256, 256, True)
            else:
                if _THUMBNAILERS is None:
                    _THUMBNAILERS = _thumbnailers()
                execl = _THUMBNAILERS.get(ctype)
                if execl:
                    import subprocess
                    import tempfile
                    out = tempfile.mktemp(suffix=".png", prefix="cubbies-thumb-")
                    cmd = (execl.replace("%i", GLib.shell_quote(path))
                           .replace("%u", GLib.shell_quote(uri))
                           .replace("%o", GLib.shell_quote(out)).replace("%s", "256"))
                    subprocess.run(GLib.shell_parse_argv(cmd)[1], timeout=20,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if os.path.exists(out):
                        big = GdkPixbuf.Pixbuf.new_from_file_at_scale(out, 256, 256, True)
                        os.remove(out)
            if big is not None:
                folder = os.path.join(cache, "large")
                os.makedirs(folder, mode=0o700, exist_ok=True)
                import threading
                tmp = os.path.join(folder, f"{name}.{os.getpid()}-{threading.get_ident()}"
                                           ".cubbies-tmp")
                big.savev(tmp, "png", ["tEXt::Thumb::URI", "tEXt::Thumb::MTime"],
                          [uri, str(int(st.st_mtime))])
                os.replace(tmp, os.path.join(folder, name))
        except Exception as exc:
            dbg("no thumbnail for", path, "-", exc)
            big = None
    if big is None:
        _THUMB_FAILED.add((path, int(st.st_mtime)))
        return None
    w, h = big.get_width(), big.get_height()
    k = min(size / max(w, 1), size / max(h, 1), 1.0)
    pb = big.scale_simple(max(1, int(w * k)), max(1, int(h * k)), GdkPixbuf.InterpType.BILINEAR)
    if len(_THUMB_MEM) > 600:
        _THUMB_MEM.clear()
    _THUMB_MEM[key] = pb
    return pb


def _background_canvas(sw, sh, colours):
    """The desktop's background colour (solid or a gradient) as a desktop-sized picture."""
    import cairo
    shade, c1, c2 = colours or ("solid", "#000000", "#000000")

    def rgb(code):
        c = Gdk.RGBA()
        if not c.parse(code or "#000000"):
            c.parse("#000000")
        return c.red, c.green, c.blue
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, sw, sh)
    cr = cairo.Context(surf)
    if shade in ("horizontal", "vertical"):
        grad = cairo.LinearGradient(0, 0, sw if shade == "horizontal" else 0,
                                    sh if shade == "vertical" else 0)
        grad.add_color_stop_rgb(0, *rgb(c1))
        grad.add_color_stop_rgb(1, *rgb(c2))
        cr.set_source(grad)
    else:
        cr.set_source_rgb(*rgb(c1))
    cr.paint()
    surf.flush()
    return Gdk.pixbuf_get_from_surface(surf, 0, 0, sw, sh)


def make_blurred_wallpaper(path, options, sw, sh, level=18, monitors=None, colours=None):
    """The wallpaper laid out the way Cinnamon shows it (zoom, scaled, stretched, centred,
    tiled) on each screen, desktop-sized and softly blurred. Runs in a worker thread.
    monitors: [(x, y, w, h)] of each screen ("spanned" uses the whole desktop).
    colours: (shading, colour 1, colour 2), drawn where the picture doesn't cover; with no
    picture (path None) the colour is all there is."""
    canvas = _background_canvas(sw, sh, colours)
    if not path:
        return _blur_pixbuf(canvas, sw, sh, level)
    src = GdkPixbuf.Pixbuf.new_from_file(path)
    w, h = src.get_width(), src.get_height()
    if src.get_has_alpha():
        # a picture with a see-through layer (many PNG wallpapers) can't be scaled straight
        # onto a solid canvas: GdkPixbuf refuses and leaves it black. Flatten it first.
        flat = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, w, h)
        flat.fill(0x000000ff)
        src.composite(flat, 0, 0, w, h, 0, 0, 1.0, 1.0, GdkPixbuf.InterpType.NEAREST, 255)
        src = flat
    areas = [(0, 0, sw, sh)] if (options == "spanned" or not monitors) else monitors
    for ax, ay, aw, ah in areas:
        aw, ah = min(aw, sw - ax), min(ah, sh - ay)
        if aw <= 0 or ah <= 0:
            continue
        if options in ("stretched",):
            src.scale(canvas, ax, ay, aw, ah, ax, ay, aw / w, ah / h,
                      GdkPixbuf.InterpType.BILINEAR)
        elif options in ("scaled", "centered", "wallpaper"):
            k = min(aw / w, ah / h) if options == "scaled" else 1.0
            nw, nh = int(w * k), int(h * k)
            if options == "wallpaper":
                for ty in range(ay, ay + ah, max(1, nh)):
                    for tx in range(ax, ax + aw, max(1, nw)):
                        cw, ch = min(nw, ax + aw - tx), min(nh, ay + ah - ty)
                        src.scale(canvas, tx, ty, cw, ch, tx, ty, k, k,
                                  GdkPixbuf.InterpType.BILINEAR)
            else:
                ox, oy = ax + (aw - nw) // 2, ay + (ah - nh) // 2
                dx, dy = max(ax, ox), max(ay, oy)
                cw = min(ox + nw, ax + aw) - dx
                ch = min(oy + nh, ay + ah) - dy
                if cw > 0 and ch > 0:
                    src.scale(canvas, dx, dy, cw, ch, ox, oy, k, k,
                              GdkPixbuf.InterpType.BILINEAR)
        else:                               # zoom / spanned: fill the area, cropping
            k = max(aw / w, ah / h)
            ox, oy = ax + (aw - w * k) / 2, ay + (ah - h * k) / 2
            src.scale(canvas, ax, ay, aw, ah, ox, oy, k, k, GdkPixbuf.InterpType.BILINEAR)
    return _blur_pixbuf(canvas, sw, sh, level)


def _blur_pixbuf(canvas, sw, sh, level):
    # blur: shrink a lot, then grow back smoothly (twice, for a softer result)
    # shrink in halving steps (each step averages, so nothing flickers), then grow back in
    # doubling steps: growing in small steps gives a smooth haze instead of soft squares
    f = max(4, int(level))
    w, h = sw, sh
    pb = canvas
    while w // 2 >= max(1, sw // f):
        w, h = max(1, w // 2), max(1, h // 2)
        pb = pb.scale_simple(w, h, GdkPixbuf.InterpType.BILINEAR)
    pb = pb.scale_simple(max(1, sw // f), max(1, sh // f), GdkPixbuf.InterpType.BILINEAR)
    w, h = pb.get_width(), pb.get_height()
    while w * 2 < sw:
        w, h = w * 2, h * 2
        pb = pb.scale_simple(w, h, GdkPixbuf.InterpType.BILINEAR)
    return pb.scale_simple(sw, sh, GdkPixbuf.InterpType.BILINEAR)
