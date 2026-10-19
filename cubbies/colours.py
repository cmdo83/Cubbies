"""Colour codes, the wallpaper's main colour, and picking a colour off the screen."""

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

from .core import dbg


def parse_colour_code(text):
    """A colour typed by hand -> (r, g, b) as 0-255, or None. Takes "#1a2b3c", "#abc",
    "1a2b3c", "rgb(26, 43, 60)", "rgba(26,43,60,0.5)", "26, 43, 60" or "26 43 60"."""
    import re
    t = (text or "").strip().lower()
    if not t:
        return None
    m = re.fullmatch(r"#?([0-9a-f]{3}|[0-9a-f]{6})", t)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    m = re.fullmatch(r"(?:rgba?\s*\(\s*)?(\d{1,3})\s*[,\s]\s*(\d{1,3})\s*[,\s]\s*(\d{1,3})"
                     r"(?:\s*[,\s]\s*[\d.]+%?)?\s*\)?", t)
    if m:
        vals = tuple(int(v) for v in m.groups())
        if all(0 <= v <= 255 for v in vals):
            return vals
    c = Gdk.RGBA()                       # colour names: "teal", "slategray"...
    if t.isalpha() and c.parse(t):
        return (round(c.red * 255), round(c.green * 255), round(c.blue * 255))
    return None


def hex_code(r, g, b):
    return f"#{int(r):02X}{int(g):02X}{int(b):02X}"


def wallpaper_main_colour(path):
    """The colour most of a picture is made of (not a muddy average of everything):
    similar colours are grouped, and the biggest group wins. Returns (r, g, b) or None."""
    try:
        pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 64, 64, True)
    except Exception:
        return None
    w, h, n, stride = pb.get_width(), pb.get_height(), pb.get_n_channels(), pb.get_rowstride()
    data = pb.get_pixels()
    groups = {}
    for y in range(h):
        row = y * stride
        for x in range(w):
            i = row + x * n
            r, g, b = data[i], data[i + 1], data[i + 2]
            key = (r >> 5, g >> 5, b >> 5)
            acc = groups.setdefault(key, [0, 0, 0, 0])
            acc[0] += r
            acc[1] += g
            acc[2] += b
            acc[3] += 1
    if not groups:
        return None
    r, g, b, count = max(groups.values(), key=lambda a: a[3])
    return (r // count, g // count, b // count)


def eyedropper_cursor(display):
    """An eyedropper pointer; it picks at the very tip of the dropper (bottom left)."""
    try:
        import cairo
        size = 32
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
        cr = cairo.Context(surf)
        cr.translate(2, 30)
        cr.rotate(-0.785398)              # the dropper leans 45 degrees, tip at bottom left
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)

        def shape():
            cr.new_path()
            cr.move_to(0, 0)              # tip
            cr.line_to(5, -2.2)
            cr.line_to(19, -2.2)          # glass tube
            cr.line_to(19, 2.2)
            cr.line_to(5, 2.2)
            cr.close_path()
            cr.rectangle(19, -4.5, 3, 9)  # collar
            cr.rectangle(22, -3.2, 9, 6.4)  # rubber bulb
        for width, rgb in ((3.6, (1, 1, 1)), (1.4, (0, 0, 0))):
            shape()
            cr.set_source_rgb(*rgb)
            cr.set_line_width(width)
            cr.stroke()
        shape()
        cr.set_source_rgb(0.95, 0.95, 0.95)
        cr.fill()
        cr.rectangle(22, -3.2, 9, 6.4)
        cr.set_source_rgb(0.15, 0.15, 0.15)
        cr.fill()
        pb = Gdk.pixbuf_get_from_surface(surf, 0, 0, size, size)
        return Gdk.Cursor.new_from_pixbuf(display, pb, 2, 29)
    except Exception as exc:
        dbg("eyedropper pointer:", repr(exc))
        return None


def pick_screen_colour(on_done, on_start=None, on_end=None):
    """Eyedropper: the pointer becomes a cross; a small swatch beside it shows the colour
    under it. Click to take that colour, Escape (or right-click) to cancel.
    on_done((r, g, b)) is called with the colour, or not at all when cancelled."""
    display = Gdk.Display.get_default()
    seat = display.get_default_seat()
    root = Gdk.get_default_root_window()
    tip = Gtk.Window(type=Gtk.WindowType.POPUP)
    tip.set_keep_above(True)
    tip.set_app_paintable(True)
    tip.set_size_request(150, 34)
    tip.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.KEY_PRESS_MASK)
    state = {"rgb": (0, 0, 0), "done": False, "timer": 0}

    def sample():
        try:
            _w, x, y, _m = root.get_device_position(seat.get_pointer())
            pb = Gdk.pixbuf_get_from_window(root, x, y, 1, 1)
            if pb is not None:
                px = pb.get_pixels()
                state["rgb"] = (px[0], px[1], px[2])
            tip.move(x + 18, y + 18)
            tip.queue_draw()
        except Exception as exc:
            dbg("eyedropper:", repr(exc))
        return True

    def draw(_w, cr):
        r, g, b = state["rgb"]
        w, h = tip.get_allocated_width(), tip.get_allocated_height()
        cr.set_source_rgb(0.12, 0.12, 0.12)
        cr.paint()
        cr.set_source_rgb(r / 255, g / 255, b / 255)
        cr.rectangle(4, 4, h - 8, h - 8)
        cr.fill()
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(4.5, 4.5, h - 9, h - 9)
        cr.set_line_width(1)
        cr.stroke()
        cr.select_font_face("monospace")
        cr.set_font_size(13)
        cr.move_to(h + 4, h / 2 + 5)
        cr.show_text(hex_code(r, g, b))
        return True

    def finish(take):
        if state["done"]:
            return
        state["done"] = True
        if state["timer"]:
            GLib.source_remove(state["timer"])
        try:
            seat.ungrab()
        except Exception:
            pass
        tip.destroy()
        if on_end:
            on_end()
        if take:
            on_done(state["rgb"])

    def press(_w, event):
        if event.button == 1:
            sample()
            finish(True)
        else:
            finish(False)
        return True

    def key(_w, event):
        if event.keyval == Gdk.KEY_Escape:
            finish(False)
        elif event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            finish(True)
        return True

    tip.connect("draw", draw)
    tip.connect("button-press-event", press)
    tip.connect("key-press-event", key)
    if on_start:
        on_start()

    def begin():
        tip.show_all()
        sample()
        cross = (eyedropper_cursor(display) or Gdk.Cursor.new_from_name(display, "crosshair")
                 or Gdk.Cursor.new_for_display(display, Gdk.CursorType.CROSSHAIR))
        status = seat.grab(tip.get_window(), Gdk.SeatCapabilities.ALL, False, cross,
                           None, None)
        if status != Gdk.GrabStatus.SUCCESS:
            dbg("eyedropper: could not take the pointer:", status)
            finish(False)
            return False
        state["timer"] = GLib.timeout_add(30, sample)
        return False
    GLib.timeout_add(250, begin)        # let hidden windows actually go first
