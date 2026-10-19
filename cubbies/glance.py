"""Glance: a panel over your windows showing what's in your cubbies."""

import os

from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from .actions import show_in_folder
from .constants import MAX_FOLDER_ITEMS
from .core import dbg
from .files import is_recent, launch, recent_files
from .items import describe
from .wallpapers import make_thumbnail, thumb_pool
from .widgets import SCROLL_MASKS, hand_cursor_window, menu_item, scroll_direction, set_cursor


GLANCE_CSS = b"""
.glance-panel { background-color: rgba(22, 26, 38, 0.94); border-radius: 12px;
                border: 1px solid rgba(255, 255, 255, 0.12); }
.glance-panel label { color: white; }
.glance-head { font-size: 130%; font-weight: bold; }
.glance-section { font-weight: bold; color: rgba(255, 255, 255, 0.78); }
.glance-fold { color: rgba(255, 255, 255, 0.6); }
.glance-line { min-height: 1px; background-color: rgba(255, 255, 255, 0.15); }
.glance-item { border-radius: 6px; background-color: transparent; }
.glance-item:hover { background-color: rgba(255, 255, 255, 0.14); }
.glance-item.sel { background-color: rgba(120, 170, 255, 0.38); }
.glance-panel entry { background-color: rgba(255, 255, 255, 0.10); color: white;
                      border: 1px solid rgba(255, 255, 255, 0.18); caret-color: white; }
.glance-panel button { color: white; }
.glance-empty { color: rgba(255, 255, 255, 0.6); }
.glance-tab { border-radius: 14px; padding: 2px 12px; background-image: none;
              background-color: rgba(255, 255, 255, 0.07); border: none; box-shadow: none; }
.glance-tab:hover { background-color: rgba(255, 255, 255, 0.16); }
.glance-tab.on { background-color: rgba(255, 255, 255, 0.28); }
.glance-tab.drop { background-color: rgba(120, 170, 255, 0.45); }
.glance-tab label { font-weight: normal; }
.glance-tab.on label { font-weight: bold; }
.glance-tabs-sw scrollbar { opacity: 0; }
.glance-go { padding: 2px 10px; }
.glance-grip { color: rgba(255, 255, 255, 0.35); }
.glance-grip-box { background-color: transparent; }
.glance-hint { color: rgba(255, 255, 255, 0.45); font-size: 90%; }
"""


def cairo_filter_good():
    """Smooth scaling for pictures drawn bigger or smaller than they are."""
    try:
        import cairo
        return cairo.FILTER_GOOD
    except Exception:
        return 1


class GlancePanel(Gtk.Window):
    """Glance: a panel over your windows that shows what's in your cubbies, a tab per page,
    so you can open, drag or reorganise things without moving your windows. The cubbies
    themselves never move: they stay where they are on the desktop the whole time.

    Each view (a page, a search, a folder being browsed) is built once into a Gtk.Stack and
    kept while the panel is open, so an icon being dragged survives a tab switch."""

    def __init__(self, app):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.app = app
        self._closing = False
        self._busy = False                 # a drag or a menu from the panel is going on
        self._desc = {}                    # path -> (name, gicon): quicker rebuilds
        self._search_timer = 0
        self._refresh_timer = 0
        self._tab_timer = 0
        self._drag_src = None              # (path, pane) of an icon dragged from here
        self._internal_drop = False
        self._resized = False
        self.views = {}                    # view name -> list of item widgets
        self.browse = []                   # folders opened inside the panel (a trail)
        self.sel = None                    # the highlighted icon (keyboard)
        self.page_index = app.cfg.get("page", 0)
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_keep_above(True)
        self.set_title("Glance")
        self.set_app_paintable(True)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self._css = Gtk.CssProvider()
        try:
            self._css.load_from_data(GLANCE_CSS)
            Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self._css,
                                                     Gtk.STYLE_PROVIDER_PRIORITY_USER)
        except GLib.Error as exc:
            dbg("glance css:", exc)
        self.connect("destroy", lambda *_a: Gtk.StyleContext.remove_provider_for_screen(
            Gdk.Screen.get_default(), self._css))
        self.connect("key-press-event", self.on_key)
        self.connect("focus-out-event", self.on_focus_out)
        self.connect("configure-event", self.on_configure)
        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        frame.get_style_context().add_class("glance-panel")
        self.add(frame)
        # the top row: drag its empty space to move the panel
        head_ev = Gtk.EventBox()
        head_ev.set_visible_window(False)
        head_ev.connect("button-press-event", self.on_head_press)
        head = Gtk.Box(spacing=10)
        head.set_margin_start(18)
        head.set_margin_end(12)
        head.set_margin_top(14)
        head_ev.add(head)
        title = Gtk.Label(label="Glance", xalign=0)
        title.get_style_context().add_class("glance-head")
        head.pack_start(title, False, False, 0)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Find an icon on any page")
        self.search.set_width_chars(28)
        self.search.connect("search-changed", self.on_search)
        self.search.connect("activate", lambda *_a: self.open_selected())
        close = Gtk.Button(label="✕")
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.set_tooltip_text("Close (Escape)")
        close.connect("clicked", lambda _b: self.close_panel())
        head.pack_end(close, False, False, 0)
        head.pack_end(self.search, False, False, 0)
        frame.pack_start(head_ev, False, False, 0)
        # a tab per page (scrolls sideways when there are many)
        trow = Gtk.Box(spacing=8)
        trow.set_margin_start(16)
        trow.set_margin_end(16)
        self.tabs_sw = Gtk.ScrolledWindow()
        self.tabs_sw.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        self.tabs_sw.get_style_context().add_class("glance-tabs-sw")
        self.tabs_sw.add_events(SCROLL_MASKS)
        self.tabs_sw.connect("scroll-event", self.on_tab_wheel)
        self.tabs = Gtk.Box(spacing=6)
        self.tabs_sw.add(self.tabs)
        trow.pack_start(self.tabs_sw, True, True, 0)
        self.go_btn = Gtk.Button()
        self.go_btn.get_style_context().add_class("glance-go")
        self.go_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.go_btn.set_no_show_all(True)
        self.go_btn.connect("clicked", lambda _b: self.go_to_page())
        trow.pack_end(self.go_btn, False, False, 0)
        frame.pack_start(trow, False, False, 0)
        self.trow = trow
        self.sw = Gtk.ScrolledWindow()
        self.sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(90)
        self.stack.set_vhomogeneous(False)
        self.sw.add(self.stack)
        frame.pack_start(self.sw, True, True, 0)
        # the bottom row: a hint and the resize grip
        foot = Gtk.Box(spacing=8)
        foot.set_margin_start(18)
        foot.set_margin_end(6)
        foot.set_margin_bottom(4)
        hint = Gtk.Label(label="Arrow keys move · Enter opens · Ctrl + Page Up / Down "
                               "changes page · drag icons between cubbies or onto a tab",
                         xalign=0)
        hint.get_style_context().add_class("glance-hint")
        hint.set_ellipsize(Pango.EllipsizeMode.END)
        foot.pack_start(hint, True, True, 0)
        grip = Gtk.EventBox()
        grip.set_visible_window(True)        # (own window: the pointer stays in this corner)
        grip.get_style_context().add_class("glance-grip-box")
        glbl = Gtk.Label(label="◢")
        glbl.get_style_context().add_class("glance-grip")
        grip.add(glbl)
        grip.set_tooltip_text("Drag to resize")
        grip.connect("button-press-event", self.on_grip_press)
        grip.connect("realize", lambda w: set_cursor(w.get_window(), "nwse-resize",
                                                     "size_fdiag"))
        foot.pack_end(grip, False, False, 0)
        frame.pack_start(foot, False, False, 0)

    # -- what a page shows: its own cubbies, the every-page ones, and its launch bar
    def page_hosts(self, index):
        app = self.app
        pages = app.cfg["pages"]
        page = pages[index]
        hosts = [f for f in page["cubbies"] if not f.get("tab_of") and not f.get("launchbar")]
        hosts += [f for p in pages if p is not page for f in p["cubbies"]
                  if f.get("all_pages") and not f.get("tab_of") and not f.get("launchbar")]
        hosts.sort(key=lambda f: (int(f.get("y", 0)) // 80, int(f.get("x", 0))))
        bar = app.bar_for_page(page)
        if bar is not None:
            hosts.insert(0, bar)
        out = []
        for f in hosts:
            for pane in (app.group_panes(f) if f.get("group") else [f]):
                if f.get("launchbar"):
                    title = "Launch Bar"
                elif f.get("group"):
                    title = f"{app.group_title(f)} › {pane.get('title')}"
                else:
                    title = pane.get("title") or "Cubby"
                out.append((f, pane, title))
        return out

    @staticmethod
    def list_folder(folder):
        try:
            names = sorted((n for n in os.listdir(folder)
                            if not n.startswith(".") and not n.endswith("~")),
                           key=lambda n: (not os.path.isdir(os.path.join(folder, n)),
                                          n.casefold()))
        except OSError:
            return []
        return [os.path.join(folder, n) for n in names][:MAX_FOLDER_ITEMS]

    def pane_paths(self, pane):
        if pane.get("folder"):
            return self.list_folder(self.app.folder_of(pane))
        if is_recent(pane):
            return recent_files(self.app.recent_count())
        return list(pane.get("items", []))

    def describe(self, path):
        if path not in self._desc:
            name, gicon, _pix = describe(path, 48, load_image=False)
            self._desc[path] = (name, gicon)
        return self._desc[path]

    # -- the tabs
    def build_tabs(self):
        for c in self.tabs.get_children():
            self.tabs.remove(c)
        self._tab_btns = []
        for i, page in enumerate(self.app.cfg["pages"]):
            n = sum(len(self.pane_paths(p)) for _f, p, _t in self.page_hosts(i))
            b = Gtk.Button(label=f"{page['name']}  {n}" if n else page["name"])
            b.get_style_context().add_class("glance-tab")
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.set_focus_on_click(False)
            b.set_tooltip_text("This page (where you are now)" if i == self.app.cfg["page"]
                               else None)
            b.connect("clicked", lambda _b, i=i: self.show_page(i))
            # dragging an icon over a tab opens that page, so it can go into its cubbies
            b.drag_dest_set(0, [Gtk.TargetEntry.new("text/uri-list", 0, 0)],
                            Gdk.DragAction.MOVE | Gdk.DragAction.COPY)
            b.connect("drag-motion", self.on_tab_drag, i)
            b.connect("drag-leave", self.on_tab_leave)
            self.tabs.pack_start(b, False, False, 0)
            self._tab_btns.append(b)
        self.tabs.show_all()
        self.trow.set_visible(len(self.app.cfg["pages"]) > 1)

    def on_tab_drag(self, btn, ctx, _x, _y, time, index):
        Gdk.drag_status(ctx, Gdk.DragAction(0), time)     # (not a place to drop)
        btn.get_style_context().add_class("drop")
        if not self._tab_timer and index != self.page_index:
            def go():
                self._tab_timer = 0
                self.show_page(index)
                return False
            self._tab_timer = GLib.timeout_add(450, go)
        return True

    def on_tab_leave(self, btn, _ctx, _time):
        btn.get_style_context().remove_class("drop")
        if self._tab_timer:
            GLib.source_remove(self._tab_timer)
            self._tab_timer = 0

    def show_page(self, index):
        self.page_index = max(0, min(index, len(self.app.cfg["pages"]) - 1))
        self.browse = []
        if self.search.get_text():
            self.search.set_text("")
            if self._search_timer:
                GLib.source_remove(self._search_timer)
                self._search_timer = 0
        self.show_view()

    def mark_tabs(self):
        plain = not self.search.get_text().strip()
        for i, b in enumerate(getattr(self, "_tab_btns", [])):
            ctx = b.get_style_context()
            if i == self.page_index and plain:
                ctx.add_class("on")
            else:
                ctx.remove_class("on")
        cur = self.app.cfg["page"]
        if self.page_index != cur and plain:
            self.go_btn.set_label(f"Go to “{self.app.cfg['pages'][self.page_index]['name']}"
                                  "” ›")
            self.go_btn.show()
        else:
            self.go_btn.hide()
        if 0 <= self.page_index < len(getattr(self, "_tab_btns", [])):
            b = self._tab_btns[self.page_index]
            GLib.idle_add(lambda: self._scroll_to(b) and False)

    def _scroll_to(self, b):
        adj = self.tabs_sw.get_hadjustment()
        a = b.get_allocation()
        if a.x < adj.get_value():
            adj.set_value(a.x)
        elif a.x + a.width > adj.get_value() + adj.get_page_size():
            adj.set_value(a.x + a.width - adj.get_page_size())

    def on_tab_wheel(self, _w, event):
        step = scroll_direction(event)
        if step:
            self.show_page(self.page_index + step)
        return True

    def go_to_page(self):
        dest = self.page_index
        self.close_panel()
        if dest != self.app.cfg["page"]:
            self.app.change_page(dest - self.app.cfg["page"], force=True)

    # -- views
    def view_name(self):
        if self.search.get_text().strip():
            return "search"
        if self.browse:
            return "browse:" + self.browse[-1]
        return f"page:{self.page_index}"

    def show_view(self, rebuild=False):
        name = self.view_name()
        if name == "search" or name.startswith("browse:"):
            rebuild = True
        if rebuild or name not in self.views:
            old = self.stack.get_child_by_name(name)
            box, items = self.build_view(name)
            if old is not None:
                self.stack.remove(old)
            self.stack.add_named(box, name)
            box.show_all()
            self.views[name] = items
        self.stack.set_visible_child_name(name)
        self.sw.get_vadjustment().set_value(0)
        self.set_sel(None)
        self.mark_tabs()

    def build_view(self, name):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_start(18)
        box.set_margin_end(18)
        box.set_margin_bottom(10)
        items = []
        if name == "search":
            text = self.search.get_text().strip().casefold()
            seen = set()
            for i, page in enumerate(self.app.cfg["pages"]):
                for f, pane, title in self.page_hosts(i):
                    if id(pane) in seen:        # (every-page cubbies only once)
                        continue
                    seen.add(id(pane))
                    paths = [p for p in self.pane_paths(pane)
                             if text in self.describe(p)[0].casefold()]
                    if paths:
                        self.add_group(box, items, f, pane, f"{page['name']} › {title}",
                                       paths, fold=False)
            if not items:
                self.note(box, "Nothing on any page matches “"
                          + self.search.get_text() + "”.")
        elif name.startswith("browse:"):
            folder = name[len("browse:"):]
            back = Gtk.Button(label="‹  Back")
            back.set_relief(Gtk.ReliefStyle.NONE)
            back.set_halign(Gtk.Align.START)
            back.connect("clicked", lambda _b: self.browse_back())
            box.pack_start(back, False, False, 4)
            self.add_group(box, items, None, None, folder.replace(
                os.path.expanduser("~"), "~", 1), self.list_folder(folder), fold=False)
        else:
            index = int(name.split(":")[1])
            favs = self.app.favourites() if self.app.setting("glance_favourites") else []
            if favs:
                self.add_group(box, items, None, None, "★ Favourites", favs,
                               fold_key="favourites")
            groups = self.page_hosts(index)
            for f, pane, title in groups:
                self.add_group(box, items, f, pane, title, self.pane_paths(pane),
                               fold_key=pane.get("id"))
            if not groups:
                self.note(box, "No cubbies on this page yet.")
        return box, items

    def note(self, box, text):
        lbl = Gtk.Label(label=text, xalign=0)
        lbl.get_style_context().add_class("glance-empty")
        lbl.set_margin_top(10)
        box.pack_start(lbl, False, False, 0)

    def add_group(self, box, items, f, pane, title, paths, fold=True, fold_key=None):
        sec = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        head_ev = Gtk.EventBox()
        head_ev.set_visible_window(False)
        hrow = Gtk.Box(spacing=8)
        hrow.set_margin_top(8)
        head_ev.add(hrow)
        folded = fold and fold_key and fold_key in self.app.cfg.get("glance_folded", [])
        arrow = Gtk.Label(label="▸" if folded else "▾")
        arrow.get_style_context().add_class("glance-fold")
        if fold and fold_key:
            hrow.pack_start(arrow, False, False, 0)
        if f is not None:                  # a dot in the cubby's own colour
            dot = Gtk.DrawingArea()
            dot.set_size_request(10, 10)
            dot.set_valign(Gtk.Align.CENTER)
            rgba = Gdk.RGBA()
            if not rgba.parse(f.get("color") or "rgb(20,24,36)"):
                rgba.parse("rgb(20,24,36)")

            def draw_dot(_w, cr, c=rgba):
                import math
                cr.arc(5, 5, 4.5, 0, 2 * math.pi)
                cr.set_source_rgba(c.red, c.green, c.blue, 1)
                cr.fill_preserve()
                cr.set_source_rgba(1, 1, 1, 0.6)
                cr.set_line_width(1)
                cr.stroke()
                return False
            dot.connect("draw", draw_dot)
            hrow.pack_start(dot, False, False, 0)
        lbl = Gtk.Label(label=title + (f"  ({len(paths)})" if folded else ""), xalign=0)
        lbl.get_style_context().add_class("glance-section")
        line = Gtk.Box()
        line.get_style_context().add_class("glance-line")
        line.set_valign(Gtk.Align.CENTER)
        hrow.pack_start(lbl, False, False, 0)
        hrow.pack_start(line, True, True, 0)
        sec.pack_start(head_ev, False, False, 0)
        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_homogeneous(True)
        flow.set_max_children_per_line(30)
        flow.set_valign(Gtk.Align.START)
        flow.set_no_show_all(bool(folded))
        for path in paths:
            w = self.make_item(path, f, pane)
            flow.add(w)
            if not folded:
                items.append(w)
        if not paths and pane is not None:
            empty = Gtk.Label(label="Empty: drop files here", xalign=0)
            empty.get_style_context().add_class("glance-empty")
            sec.pack_start(empty, False, False, 2)
        sec.pack_start(flow, False, False, 0)
        if fold and fold_key:              # click the heading to fold the group away
            head_ev.connect("button-press-event", lambda _w, e, k=fold_key:
                            e.button == 1 and self.toggle_fold(k))
            hand_cursor_window(head_ev)
            head_ev.set_visible_window(True)
            head_ev.get_style_context().add_class("glance-item")
        if pane is not None:               # files dropped on a group go into that cubby
            sec.drag_dest_set(Gtk.DestDefaults.ALL,
                              [Gtk.TargetEntry.new("text/uri-list", 0, 0)],
                              Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
            sec.connect("drag-data-received", self.on_drop, pane)
        box.pack_start(sec, False, False, 0)

    def toggle_fold(self, key):
        folded = self.app.cfg.setdefault("glance_folded", [])
        if key in folded:
            folded.remove(key)
        else:
            folded.append(key)
        self.app.save()
        self.show_view(rebuild=True)
        return True

    def make_item(self, path, host, pane):
        name, gicon = self.describe(path)
        ev = Gtk.EventBox()
        ev.get_style_context().add_class("glance-item")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_size_request(96, -1)
        box.set_margin_top(4)
        box.set_margin_bottom(4)
        img = Gtk.Image.new_from_gicon(gicon, Gtk.IconSize.DIALOG)
        img.set_pixel_size(48)
        if not os.path.isdir(path) and not path.endswith(".desktop"):
            def got(fut, img=img):         # its preview picture, when there is one
                try:
                    pb = fut.result()
                except Exception:
                    pb = None
                if pb is not None:
                    GLib.idle_add(lambda: (not self._closing and img.set_from_pixbuf(pb))
                                  and False)
            try:
                thumb_pool().submit(make_thumbnail, path, 48).add_done_callback(got)
            except Exception:
                pass
        lbl = Gtk.Label(label=name)
        lbl.set_line_wrap(True)
        lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        lbl.set_max_width_chars(12)
        lbl.set_lines(2)
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
        lbl.set_justify(Gtk.Justification.CENTER)
        box.pack_start(img, False, False, 0)
        box.pack_start(lbl, False, False, 0)
        ev.add(box)
        ev.set_tooltip_text(path)
        ev.glance_path = path
        ev.glance_host = host
        ev.glance_pane = pane
        hand_cursor_window(ev)
        ev.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK)
        ev.connect("button-press-event", self.on_item_press)
        ev.connect("button-release-event", self.on_item_release)
        ev.drag_source_set(Gdk.ModifierType.BUTTON1_MASK,
                           [Gtk.TargetEntry.new("text/uri-list", 0, 0)],
                           Gdk.DragAction.COPY | Gdk.DragAction.MOVE | Gdk.DragAction.LINK)
        ev.connect("drag-begin", self.on_drag_begin)
        ev.connect("drag-data-get", lambda _w, _c, sel, _i, _t, p=path:
                   sel.set_uris([Gio.File.new_for_path(p).get_uri()]))
        ev.connect("drag-end", lambda *_a: self.after_drag())
        return ev

    # -- the keyboard highlight
    def cur_items(self):
        return self.views.get(self.view_name(), [])

    def set_sel(self, w):
        if self.sel is not None:
            try:
                self.sel.get_style_context().remove_class("sel")
            except Exception:
                pass
        self.sel = w
        if w is not None:
            w.get_style_context().add_class("sel")
            # keep it in view
            pos = w.translate_coordinates(self.stack, 0, 0)
            if pos:
                adj = self.sw.get_vadjustment()
                y, h = pos[1], w.get_allocated_height()
                if y < adj.get_value():
                    adj.set_value(y - 30)
                elif y + h > adj.get_value() + adj.get_page_size():
                    adj.set_value(y + h - adj.get_page_size() + 10)

    def move_sel(self, dx, dy):
        items = [w for w in self.cur_items() if w.get_mapped()]
        if not items:
            return
        if self.sel not in items:
            self.set_sel(items[0])
            return
        if dx:
            i = items.index(self.sel) + dx
            if 0 <= i < len(items):
                self.set_sel(items[i])
            return

        def where(w):
            p = w.translate_coordinates(self.stack, 0, 0) or (0, 0)
            return p[0] + w.get_allocated_width() / 2, p[1]
        cx, cy = where(self.sel)
        best = None
        for w in items:
            x, y = where(w)
            if (y - cy) * dy <= 2:
                continue
            score = (abs(y - cy), abs(x - cx))
            if best is None or score < best[0]:
                best = (score, w)
        if best is not None:
            self.set_sel(best[1])

    def open_selected(self):
        if self._search_timer:             # (Enter right after typing)
            GLib.source_remove(self._search_timer)
            self._search_timer = 0
            self.show_view()
        w = self.sel or next((w for w in self.cur_items()), None)
        if w is not None:
            self.open_item(w)

    # -- using it
    def open_item(self, w):
        path = w.glance_path
        if os.path.isdir(path) and self.app.setting("glance_browse"):
            self.browse.append(path)        # look inside it, right here in the panel
            self.show_view()
            return
        self.app.note_open(path)
        launch(path)                        # opened: Glance goes away
        self.close_panel()

    def browse_back(self):
        if self.browse:
            self.browse.pop()
        self.show_view()

    def on_item_press(self, w, event):
        if event.button == 1 and event.type == Gdk.EventType.BUTTON_PRESS:
            self._press = (w, event.x_root, event.y_root)
            return False                    # (a drag may start)
        if event.button == 3:
            path, host = w.glance_path, w.glance_host
            win = self.app.windows.get(host["id"]) if host is not None else None
            if win is not None:            # the icon's usual menu, from its own cubby
                win.selected = {path}
                menu = win.build_item_menu(path)
            else:
                menu = Gtk.Menu()
                for label, act, icons in (
                        ("Open", lambda: launch(path), ("document-open",)),
                        ("Show in Folder", lambda: show_in_folder([path]), ("folder-open",))):
                    mi = menu_item(label, *icons)
                    mi.connect("activate", lambda _m, a=act: a())
                    menu.append(mi)
                menu.show_all()
            self._busy = True

            def done(_m):
                self._busy = False
                GLib.timeout_add(200, self.refocus)
            menu.connect("deactivate", done)
            menu.popup_at_pointer(event)
            return True
        return False

    def on_item_release(self, w, event):
        p, self._press = getattr(self, "_press", None), None
        if (event.button == 1 and p and p[0] is w
                and abs(event.x_root - p[1]) + abs(event.y_root - p[2]) < 6):
            self.open_item(w)
            return True
        return False

    def on_drag_begin(self, w, ctx):
        self._busy = True
        self._drag_src = (w.glance_path, w.glance_pane)
        try:
            Gtk.drag_set_icon_gicon(ctx, self.describe(w.glance_path)[1], 0, 0)
        except Exception:
            pass

    def after_drag(self):
        self._busy = False
        self._drag_src = None
        if self._internal_drop:            # moved between cubbies: keep going
            self._internal_drop = False
            self.refresh_soon()
            GLib.timeout_add(150, self.refocus)
        else:
            self.close_panel()             # dropped into an app (or let go): done

    def on_drop(self, _w, _ctx, _x, _y, sel, _info, _time, pane):
        src = self._drag_src
        app = self.app
        if src is not None:
            self._internal_drop = True
            if src[1] is pane:
                return                     # dropped back where it was
        paths = app.drop_paths(sel.get_uris(), make_places=not pane.get("folder"))
        if not paths:
            return
        undo = app.undo_begin("Move Icons" if src else "Add Icons")
        try:
            if src is not None and src[1] is not None and not src[1].get("folder") \
                    and src[0] in src[1].get("items", []):
                src[1]["items"].remove(src[0])     # out of the cubby it came from
                app.refresh_cubby(src[1])
            app.add_items(pane, paths)
            app.save()
        finally:
            app.undo_end(undo)
        if src is None:
            self.refresh_soon()

    def on_search(self, *_a):
        if self._search_timer:
            GLib.source_remove(self._search_timer)

        def go():
            self._search_timer = 0
            self.show_view()
            return False
        self._search_timer = GLib.timeout_add(120, go)

    def on_key(self, _w, event):
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        k = event.keyval
        if k == Gdk.KEY_Escape:
            self.escape()
            return True
        if ctrl and k in (Gdk.KEY_Page_Down, Gdk.KEY_Tab):
            self.show_page((self.page_index + 1) % len(self.app.cfg["pages"]))
            return True
        if ctrl and k in (Gdk.KEY_Page_Up, Gdk.KEY_ISO_Left_Tab):
            self.show_page((self.page_index - 1) % len(self.app.cfg["pages"]))
            return True
        if k in (Gdk.KEY_Down, Gdk.KEY_Up):
            self.move_sel(0, 1 if k == Gdk.KEY_Down else -1)
            return True
        if k in (Gdk.KEY_Left, Gdk.KEY_Right) and (self.sel is not None
                                                  or not self.search.get_text()):
            self.move_sel(1 if k == Gdk.KEY_Right else -1, 0)
            return True
        if k in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.open_selected()
            return True
        if k == Gdk.KEY_BackSpace and self.browse and not self.search.get_text():
            self.browse_back()
            return True
        if not self.search.has_focus() and event.string and event.string.isprintable():
            self.search.grab_focus()        # typing goes into the search box
        return False

    def escape(self):
        """Escape steps back: out of a search, out of a folder, then closes."""
        if self.search.get_text():
            self.search.set_text("")
        elif self.browse:
            self.browse_back()
        else:
            self.close_panel()

    def on_focus_out(self, *_a):
        # clicked somewhere else: Glance goes away (not while its own menu or a drag is on)
        GLib.timeout_add(150, lambda: (not self._busy and not self.is_active()
                                       and self.close_panel()) and False)
        return False

    def refocus(self):
        if not self._closing:
            self.present()
        return False

    # -- live: changes made elsewhere while it's open show up
    def refresh_soon(self):
        if self._closing or self._refresh_timer:
            return

        def go():
            self._refresh_timer = 0
            if self._closing:
                return False
            if self._busy:                 # not in the middle of a drag or a menu
                self.refresh_soon()
                return False
            self._desc = {}
            for name in list(self.views):
                old = self.stack.get_child_by_name(name)
                if old is not None and name != self.view_name():
                    self.stack.remove(old)
                    del self.views[name]
            self.build_tabs()
            self.show_view(rebuild=True)
            return False
        self._refresh_timer = GLib.timeout_add(350, go)

    # -- moving and resizing the panel
    def on_head_press(self, _w, event):
        if event.button == 1:
            self.begin_move_drag(event.button, int(event.x_root), int(event.y_root), event.time)
        return False

    def on_grip_press(self, _w, event):
        if event.button == 1:
            self._resized = True
            self.begin_resize_drag(Gdk.WindowEdge.SOUTH_EAST, event.button,
                                   int(event.x_root), int(event.y_root), event.time)
        return True

    def on_configure(self, *_a):
        if self._resized and not self._closing:
            w, h = self.get_size()
            self.app.cfg["glance_w"], self.app.cfg["glance_h"] = int(w), int(h)
            if not getattr(self, "_size_save", 0):
                def later():
                    self._size_save = 0
                    self.app.save()
                    return False
                self._size_save = GLib.timeout_add(500, later)
        return False

    def open_panel(self):
        self.build_tabs()
        try:
            display = Gdk.Display.get_default()
            seat = display.get_default_seat()
            _s, px, py = seat.get_pointer().get_position()
            geo = display.get_monitor_at_point(px, py).get_workarea()
        except Exception:
            px = py = 0
            geo = Gdk.Rectangle()
            geo.x, geo.y, geo.width, geo.height = 0, 0, 1280, 800
        cfg = self.app.cfg
        if cfg.get("glance_w") and cfg.get("glance_h"):        # the size you gave it
            w = max(420, min(geo.width, int(cfg["glance_w"])))
            h = max(260, min(geo.height, int(cfg["glance_h"])))
        else:
            w = min(1100, int(geo.width * 0.8))
            # just tall enough for the fullest page, so switching tabs doesn't resize it
            cols = max(1, (w - 36) // 100)
            need = 0
            for i in range(len(cfg["pages"])):
                est = sum(34 + -(-max(1, len(self.pane_paths(p))) // cols) * 92
                          for _f, p, _t in self.page_hosts(i))
                need = max(need, est)
            if self.app.setting("glance_favourites") and self.app.favourites():
                need += 34 + 92 * (-(-len(self.app.favourites()) // cols))
            h = max(260, min(int(geo.height * 0.75), need + 180))
        self.set_default_size(w, h)
        self.resize(w, h)
        if cfg.get("glance_place") == "pointer":               # at the pointer, on screen
            x = min(max(geo.x, px - w // 2), geo.x + geo.width - w)
            y = min(max(geo.y, py - 60), geo.y + geo.height - h)
        else:
            x, y = geo.x + (geo.width - w) // 2, geo.y + (geo.height - h) // 2
        self.move(int(x), int(y))
        self.set_opacity(0.0)
        self.show_all()
        self.show_view()
        try:
            from gi.repository import GdkX11
            self.get_window().focus(GdkX11.x11_get_server_time(self.get_window()))
        except Exception:
            self.present()
        self.search.grab_focus()
        t0 = GLib.get_monotonic_time()

        def fade():
            k = min(1.0, (GLib.get_monotonic_time() - t0) / 140_000)
            self.set_opacity(k)
            return k < 1.0
        GLib.timeout_add(15, fade)

    def close_panel(self):
        if self._closing:
            return False
        self._closing = True
        for name in ("_search_timer", "_refresh_timer", "_tab_timer"):
            if getattr(self, name):
                GLib.source_remove(getattr(self, name))
                setattr(self, name, 0)
        self.hide()
        self.app.glance = None
        GLib.idle_add(lambda: self.destroy() and False)
        dbg("glance closed")
        return False
