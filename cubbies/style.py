"""Turning a cubby's look (colours, fonts, opacity) into GTK CSS, and colour swatches."""

from gi.repository import Gdk, Gtk, Pango

from .constants import DEFAULT_BORDER_COLOR, DEFAULT_RADIUS, MAX_BORDER, MAX_RADIUS


def selection_colors(ctx):
    """The active GTK theme's selection colours (background, text) as (r, g, b) ints."""
    def look(names, fallback):
        for name in names:
            ok, rgba = ctx.lookup_color(name)
            if ok:
                return rgba
        rgba = Gdk.RGBA()
        rgba.parse(fallback)
        return rgba

    bg = look(("theme_selected_bg_color", "selected_bg_color"), "#3584e4")
    fg = look(("theme_selected_fg_color", "selected_fg_color"), "#ffffff")
    to_int = lambda c: (int(c.red * 255), int(c.green * 255), int(c.blue * 255))  # noqa: E731
    return to_int(bg), to_int(fg)


def font_css(font_str):
    """CSS declarations for a Pango font string such as 'Ubuntu Italic 12'."""
    if not font_str:
        return ""
    try:
        desc = Pango.FontDescription(font_str)
        rules = []
        family = desc.get_family()
        if family:
            names = ", ".join('"%s"' % f.strip().replace('"', "")
                              for f in family.split(",") if f.strip())
            if names:
                rules.append(f"font-family: {names};")
        size = desc.get_size()
        if size > 0:
            unit = "px" if desc.get_size_is_absolute() else "pt"
            rules.append(f"font-size: {size / Pango.SCALE:g}{unit};")
        rules.append(f"font-weight: {int(desc.get_weight())};")
        style = desc.get_style()
        if style == Pango.Style.ITALIC:
            rules.append("font-style: italic;")
        elif style == Pango.Style.OBLIQUE:
            rules.append("font-style: oblique;")
        else:
            rules.append("font-style: normal;")
        return " ".join(rules)
    except Exception:
        return ""


def buttons_shown(d):
    """(show the + button, show the gear button) for a cubby or a page default. Older
    settings had one switch for both ("show_buttons"); the newer keys win over it."""
    both = d.get("show_buttons", True) is not False
    return (d.get("show_add", both) is not False, d.get("show_gear", both) is not False)


def style_css(cls, color_str, opacity, sel_bg=(53, 132, 228), sel_fg=(255, 255, 255),
              title_font=None, radius=DEFAULT_RADIUS, border_width=0, border_color=None,
              tab_font=None, tab_colors=()):
    """CSS for one cubby: background colour/opacity, readable text, and desktop-style
    hover glow / selection using the system's selection colour.

    Every rule is scoped by the cubby's own class (cls) because this stylesheet is installed
    screen-wide: a stylesheet attached to just one widget would not reach the icons inside it.
    """
    c = Gdk.RGBA()
    if not c.parse(color_str):
        c.parse("rgb(20,24,36)")
    r, g, b = int(c.red * 255), int(c.green * 255), int(c.blue * 255)
    lum = 0.299 * c.red + 0.587 * c.green + 0.114 * c.blue
    dark_text = lum > 0.6 and opacity > 0.45
    active_tab = "rgba(0,0,0,0.22)" if dark_text else "rgba(255,255,255,0.30)"
    fg = "rgb(20,20,20)" if dark_text else "white"
    shadow = "none" if dark_text else "1px 1px 2px black"
    bar = "rgba(0,0,0,0.12)" if dark_text else "rgba(255,255,255,0.14)"
    c = f".{cls}"
    rad = max(0, min(MAX_RADIUS, int(radius)))
    font_rule = font_css(title_font)
    font_line = (f"{c} .cubby-title label, {c} .cubby-title button {{ {font_rule} }}\n"
                 if font_rule else "")
    tab_rule = font_css(tab_font)        # a tabbed cubby's own tab font, over the page's
    if tab_rule:
        font_line += f"{c} .cubby-tab label {{ {tab_rule} }}\n"
    bw = max(0, min(MAX_BORDER, int(border_width or 0)))
    bc = Gdk.RGBA()
    if not bc.parse(border_color or DEFAULT_BORDER_COLOR):
        bc.parse(DEFAULT_BORDER_COLOR)
    border = (f" border: {bw}px solid rgba({int(bc.red * 255)},{int(bc.green * 255)},"
              f"{int(bc.blue * 255)},{bc.alpha:.2f});") if bw else ""
    return (
        f".cubby{c} {{ background: rgba({r},{g},{b},{opacity:.2f}); border-radius: {rad}px;{border} }}\n"
        f"{c} .cubby-title {{ background: {bar}; border-radius: {rad}px {rad}px 0 0; }}\n"
        f"{c} .cubby-title.flipped {{ border-radius: 0 0 {rad}px {rad}px; }}\n"
        f"{c} .cubby-title.title-hidden {{ background: transparent; }}\n"
        f"{c} .cubby-title.rolled {{ border-radius: {rad}px; }}\n"
        f"{c} .cubby-tab.active, {c} .cubby-kind.active {{ background: {active_tab}; }}\n"
        # tab designs (Settings › Tabbed Cubbies): rounded, flat, segmented
        f"{c} .tabs-rounded .cubby-tab {{ border-radius: 8px; background: rgba(128,128,128,0.22); }}\n"
        f"{c} .tabs-rounded .cubby-tab.active {{ background: rgba(0,0,0,0.32); }}\n"
        f"{c} .tabs-flat .cubby-tab, {c} .tabs-flat .cubby-tab.active {{ background: transparent;"
        f" border-radius: 0; }}\n"
        f"{c} .tabs-flat .cubby-tab.active label {{ font-weight: bold; }}\n"
        f"{c} .tabs-segmented .cubby-tab {{ border-radius: {min(rad, 8)}px {min(rad, 8)}px 0 0;"
        f" background: rgba(128,128,128,0.40); }}\n"
        f"{c} .tabs-segmented .cubby-tab.active {{ background: rgba({r},{g},{b},{max(opacity, 0.5):.2f}); }}\n"
        f"{c} .cubby-tab:not(.active) label {{ color: alpha({fg}, 0.58); }}\n"
        f"{c} .cubby-kind label {{ color: {fg}; text-shadow: {shadow}; }}\n"
        f"{c} .cubby-heads label {{ color: {fg}; }}\n"
        f"{c} .cubby-title.merge-target {{ background: rgba({sel_bg[0]},{sel_bg[1]},{sel_bg[2]},0.85); }}\n"
        f"{c} .cubby-title label, {c} .cubby-title button, {c} .cubby-grip,"
        f" {c} .cubby-grip label {{ color: {fg}; }}\n"
        f"{c} .cubby-item label {{ color: {fg}; text-shadow: {shadow}; }}\n"
        f"{font_line}"
        f"{tab_colour_css(c, tab_colors)}"
        # (the hover glow and selection highlight are painted per icon in Cubby.paint_item)
    ).encode()


def tab_colour_css(c, tab_colors):
    """Tabs with a colour of their own: a tab not shown is
    nearly solid in its colour; the shown one matches the cubby under it (which takes the
    tab's colour while it's shown). tab_colors: [(pane id, colour, opacity)]."""
    out = []
    for pid, colour, opacity in tab_colors:
        k = Gdk.RGBA()
        if not k.parse(colour or ""):
            continue
        r, g, b = int(k.red * 255), int(k.green * 255), int(k.blue * 255)
        dark = 0.299 * k.red + 0.587 * k.green + 0.114 * k.blue > 0.6
        fg = "rgb(20,20,20)" if dark else "white"
        t = f"{c} .cubby-tab.tabc-{pid}"
        out.append(f"{t} {{ background: rgba({r},{g},{b},0.88); }}\n"
                   f"{t}:hover {{ background: rgba({r},{g},{b},0.97); }}\n"
                   f"{t}.active {{ background: rgba({r},{g},{b},{max(0.35, opacity):.2f}); }}\n"
                   f"{t} label {{ color: alpha({fg}, 0.72); text-shadow: none; }}\n"
                   f"{t}.active label {{ color: {fg}; }}\n")
    return "".join(out)


def colour_swatch(colour, opacity, w=44, h=22):
    """A small rounded sample of a colour at its transparency (over a checkerboard, so the
    transparency shows)."""
    import math
    area = Gtk.DrawingArea()
    area.set_size_request(w, h)
    area.set_valign(Gtk.Align.CENTER)

    def draw(_a, cr):
        c = Gdk.RGBA()
        if not c.parse(colour or ""):
            c.parse("rgb(20,24,36)")
        r = 5
        cr.new_sub_path()
        cr.arc(w - r, r, r, -math.pi / 2, 0)
        cr.arc(w - r, h - r, r, 0, math.pi / 2)
        cr.arc(r, h - r, r, math.pi / 2, math.pi)
        cr.arc(r, r, r, math.pi, 1.5 * math.pi)
        cr.close_path()
        cr.save()
        cr.clip_preserve()
        for i in range(0, w, 6):
            for j in range(0, h, 6):
                v = 0.85 if (i // 6 + j // 6) % 2 else 0.6
                cr.set_source_rgb(v, v, v)
                cr.rectangle(i, j, 6, 6)
                cr.fill()
        try:
            op = float(opacity)
        except (TypeError, ValueError):
            op = 0.58
        cr.set_source_rgba(c.red, c.green, c.blue, op)
        cr.paint()
        cr.restore()
        cr.set_source_rgba(0, 0, 0, 0.35)
        cr.set_line_width(1)
        cr.stroke()
        return False
    area.connect("draw", draw)
    return area
