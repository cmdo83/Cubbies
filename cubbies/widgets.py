"""Small GTK helpers: menu items, cursors, scrolling, the colour bar, snapping."""

from gi.repository import Gdk, Gtk

from .core import HINT, dbg


def menu_item(label, *icons, gicon=None):
    """A menu item with a small icon, like the system menus. `icons` are icon-theme names
    tried in order (the first one the current theme has is used); `gicon` is a Gio icon."""
    icon = None
    if not gicon:
        theme = Gtk.IconTheme.get_default()
        icon = next((n for n in icons if n and theme.has_icon(n)), None)
    if not (gicon or icon):
        return Gtk.MenuItem(label=label)
    mi = Gtk.ImageMenuItem(label=label)
    img = (Gtk.Image.new_from_gicon(gicon, Gtk.IconSize.MENU) if gicon
           else Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU))
    mi.set_image(img)
    mi.set_always_show_image(True)
    return mi


def calm_scroll(root):
    """no_wheel() for parts built after a window opened (Settings pages shown later, Manage
    Pages' page settings): the wheel scrolls the page, never changes a setting."""
    no_wheel(root)


def menu_item_text(mi):
    """The text shown on a menu item (also one made by menu_item, with an icon)."""
    if mi.get_label():
        return mi.get_label()
    stack = [mi]
    while stack:
        w = stack.pop()
        if isinstance(w, Gtk.Label):
            return w.get_text()
        if isinstance(w, Gtk.Container):
            stack.extend(w.get_children())
    return ""


def menu_label(text):
    """Nemo action names use _ for keyboard mnemonics: drop single ones, keep doubled."""
    return text.replace("__", "\0").replace("_", "").replace("\0", "_")


def set_cursor(gdk_window, *names):
    """Give a GdkWindow the first of these named pointers the cursor theme has (None = plain)."""
    if gdk_window is None:
        return
    try:
        cur = None
        disp = gdk_window.get_display()
        for name in names:
            if name is None:
                break
            if isinstance(name, Gdk.Cursor):
                cur = name
                break
            cur = Gdk.Cursor.new_from_name(disp, name)
            if cur is not None:
                break
        gdk_window.set_cursor(cur)
    except Exception:
        pass


def hand_cursor(btn):
    """The pointing-hand pointer over a button. A button draws on its parent's window but
    catches the mouse with a small window of its own, so the pointer is set on that one
    (setting it on the parent would change the pointer over the whole title bar)."""
    def realized(w):
        try:
            set_cursor(w.get_event_window(), "pointer", "hand2", "hand1")
        except Exception:
            pass
    btn.connect_after("realize", realized)


def no_wheel(widget):
    """Sliders, number boxes and drop-down lists inside `widget` ignore the mouse wheel, so
    scrolling a settings page never changes a setting the pointer happens to pass over (the
    page scrolls instead). Safe to call again after parts are rebuilt."""
    def stop(w, _event):
        w.stop_emission_by_name("scroll-event")    # not for the slider / list itself...
        return False                               # ...but on up to the scrolling page

    def walk(w):
        if isinstance(w, (Gtk.Scale, Gtk.SpinButton, Gtk.ComboBox)) \
                and not getattr(w, "_cubbies_no_wheel", False):
            w._cubbies_no_wheel = True
            w.connect("scroll-event", stop)
        if isinstance(w, Gtk.Container):
            for child in w.get_children():
                walk(child)
    walk(widget)


def hand_cursor_window(widget):
    """The pointing hand over a widget that has a window of its own (an event box)."""
    widget.connect_after("realize", lambda w: set_cursor(w.get_window(), "pointer", "hand2"))


_TEXT_MOVE_CURSOR = {}


def text_move_cursor(display):
    """A text-bar pointer with a small four-way arrow beside it: over a cubby's name, which
    can be dragged (to move the cubby) or clicked again to type a new name."""
    if display in _TEXT_MOVE_CURSOR:
        return _TEXT_MOVE_CURSOR[display]
    cur = None
    try:
        import cairo
        size = 32
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
        cr = cairo.Context(surf)

        def ibeam():
            cr.move_to(5, 3); cr.line_to(13, 3)        # top serif
            cr.move_to(9, 3); cr.line_to(9, 21)        # stem
            cr.move_to(5, 21); cr.line_to(13, 21)      # bottom serif

        def arrows(cx, cy, r, a):
            for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                tx, ty = cx + dx * r, cy + dy * r
                cr.move_to(cx, cy); cr.line_to(tx, ty)
                # arrow head
                px, py = -dy, dx
                cr.move_to(tx, ty); cr.line_to(tx - dx * a + px * a, ty - dy * a + py * a)
                cr.move_to(tx, ty); cr.line_to(tx - dx * a - px * a, ty - dy * a - py * a)

        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        for width, rgb in ((3.4, (1, 1, 1)), (1.4, (0, 0, 0))):   # white outline, black line
            cr.set_source_rgb(*rgb)
            cr.set_line_width(width)
            ibeam(); cr.stroke()
            cr.set_line_width(width * 0.9)
            arrows(22.5, 22.5, 6.5, 2.4); cr.stroke()
        pb = Gdk.pixbuf_get_from_surface(surf, 0, 0, size, size)
        cur = Gdk.Cursor.new_from_pixbuf(display, pb, 9, 12)
    except Exception as exc:
        dbg("text/move pointer:", repr(exc))
    if cur is None:
        for name in ("text", "xterm"):
            cur = Gdk.Cursor.new_from_name(display, name)
            if cur is not None:
                break
    _TEXT_MOVE_CURSOR[display] = cur
    return cur


class ColourBar(Gtk.DrawingArea):
    """A colour slider like a paint program's: the bar shows the colours it goes through and
    a marker is dragged along it. kind: transparency, intensity, tint or saturation."""

    def __init__(self, kind, value, hsv, on_change):
        super().__init__()
        self.kind, self.value, self.hsv, self.on_change = kind, value, hsv, on_change
        self.set_size_request(340, 26)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                        | Gdk.EventMask.BUTTON1_MOTION_MASK)
        self.connect("draw", self.on_draw)
        self.connect("button-press-event", self.on_press)
        self.connect("motion-notify-event", self.on_press)

    PAD = 8

    def on_press(self, _w, event):
        W = self.get_allocated_width()
        self.value = max(0.0, min(1.0, (event.x - self.PAD) / max(1, W - 2 * self.PAD)))
        self.queue_draw()
        self.on_change(self.kind, self.value)
        return True

    def on_draw(self, _w, cr):
        import colorsys
        import cairo
        W, H = self.get_allocated_width(), self.get_allocated_height()
        x0, x1 = self.PAD, W - self.PAD
        y, h = H / 2 - 3, 6
        g = cairo.LinearGradient(x0, 0, x1, 0)
        hue, sat, val = self.hsv()
        if self.kind == "transparency":
            g.add_color_stop_rgba(0, 1, 1, 1, 0.25)
            g.add_color_stop_rgba(1, 0, 0, 0, 1)
        elif self.kind == "tint":
            for i in range(13):
                r, gg, b = colorsys.hsv_to_rgb(i / 12.0, 1, 1)
                g.add_color_stop_rgb(i / 12.0, r, gg, b)
        elif self.kind == "intensity":
            for i in range(9):
                r, gg, b = colorsys.hsv_to_rgb(hue, max(sat, 0.85), i / 8.0)
                g.add_color_stop_rgb(i / 8.0, r, gg, b)
        else:   # saturation
            for i in range(9):
                r, gg, b = colorsys.hsv_to_rgb(hue, i / 8.0, 1)
                g.add_color_stop_rgb(i / 8.0, r, gg, b)
        cr.set_source(g)
        cr.rectangle(x0, y, x1 - x0, h)
        cr.fill()
        mx = x0 + self.value * (x1 - x0)
        cr.set_source_rgb(0.21, 0.52, 0.89)
        cr.move_to(mx - 5, H / 2 - 9)
        cr.line_to(mx + 5, H / 2 - 9)
        cr.line_to(mx + 5, H / 2 + 5)
        cr.line_to(mx, H / 2 + 10)
        cr.line_to(mx - 5, H / 2 + 5)
        cr.close_path()
        cr.fill()
        return False


def make_window(css_class):
    win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    win.set_decorated(False)
    win.set_skip_taskbar_hint(True)
    win.set_skip_pager_hint(True)
    win.set_type_hint(HINT)
    win.set_app_paintable(True)
    win.stick()
    visual = win.get_screen().get_rgba_visual()
    if visual:
        win.set_visual(visual)
    win.get_style_context().add_class(css_class)
    return win


SCROLL_MASKS = Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK


def scroll_direction(event):
    """Return -1 (previous), +1 (next) or 0 for a scroll event."""
    if event.direction == Gdk.ScrollDirection.UP:
        return -1
    if event.direction == Gdk.ScrollDirection.DOWN:
        return 1
    if event.direction == Gdk.ScrollDirection.SMOOTH:
        if event.delta_y < -0.2:
            return -1
        if event.delta_y > 0.2:
            return 1
    return 0


def page_key_step(event):
    """Ctrl+Left -> -1, Ctrl+Right -> +1 (no other modifiers), else 0."""
    mods = event.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK
                          | Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.SUPER_MASK)
    if mods != Gdk.ModifierType.CONTROL_MASK:
        return 0
    if event.keyval in (Gdk.KEY_Left, Gdk.KEY_KP_Left):
        return -1
    if event.keyval in (Gdk.KEY_Right, Gdk.KEY_KP_Right):
        return 1
    return 0


SNAP_DISTANCE = 12  # pixels within which a cubby edge/size "sticks" to a neighbour


def best_snap(pairs):
    """pairs of (current value, target value). Returns the correction to the closest target
    that lies within SNAP_DISTANCE, or 0 when nothing is near enough."""
    best = None
    for value, target in pairs:
        delta = target - value
        if abs(delta) <= SNAP_DISTANCE and (best is None or abs(delta) < abs(best)):
            best = delta
    return best or 0
