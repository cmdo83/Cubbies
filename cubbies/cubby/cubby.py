"""The Cubby window: building it, and showing its icons and title."""

import os

from gi.repository import Gdk, GLib, Gtk, Pango

from ..constants import DEFAULT_ICON, ICON_GAP, MAX_ICON, MIN_ICON
from ..core import HINT
from ..files import inbox_icon_name, is_inbox, is_recent
from ..widgets import SCROLL_MASKS, hand_cursor, set_cursor
from .appearance import CubbyAppearance
from .autohide import CubbyAutohide
from .editing import CubbyEditing
from .folder import CubbyFolder
from .geometry import CubbyGeometry
from .icons import CubbyIcons
from .interaction import CubbyInteraction
from .menus import CubbyMenus
from .search import CubbySearch
from .tabs import CubbyTabs


# Cubby is put together from the mixins imported above, one file per part of the job.
# No two of them define the same name, so their order here doesn't matter.
class Cubby(CubbyTabs, CubbyFolder, CubbyIcons, CubbySearch, CubbyInteraction, CubbyGeometry,
            CubbyAutohide, CubbyMenus, CubbyAppearance, CubbyEditing, Gtk.Window):
    def __init__(self, app, data):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.app = app
        self.data = data                       # the cubby window itself: place, size, look
        self.pane = app.active_pane(data)      # what it shows: the cubby, or the active tab
        self._monitor = None                   # watches the folder of a Folder Cubby
        self._monitor_path = None
        self._folder_timer = 0
        self._net_timer = 0          # network folders are checked every few seconds instead
        self._net_names = None
        self._net_busy = False
        self._merge_target = None              # cubby whose title bar a drag is hovering over
        self._tab_drag = None
        self._drag = None
        self._edge_poll = 0                    # watches the pointer while a cubby is dragged
        self._edge_seen = None
        self._edge_ticks = 0
        self._edge_locked = False              # just hopped to another page: leave the edge first
        self._edge_moved = False
        self._peeking = False                  # a rolled-up cubby is open for a look
        self._peek_timer = 0
        self._ah_hidden = False                # auto-hide: slid out of sight right now
        self._ah_anim = 0
        self._ah_since = None                  # when the pointer reached the screen edge
        self._ah_away = None                   # when the pointer left the shown cubby
        self._click_arm = None                 # single-click opening: (path, x, y) of a press
        self._icon_timer = 0
        self.selected = set()        # paths currently selected (highlighted) in this cubby
        self.item_widgets = {}       # path -> its widget
        self._item_clicked = False   # set by an icon click so the background handler skips it
        self._band = None            # rubber-band selection state while dragging on empty space
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                        | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.KEY_PRESS_MASK
                        | Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.connect("draw", self.on_blur_draw)               # runs before the parts are drawn
        self.connect("configure-event", lambda *_a: self.app.cubby_blur(self.data)
                     and self.queue_draw() and False)
        self.connect("enter-notify-event", self.on_win_enter)
        self.connect("leave-notify-event", self.on_win_leave)
        self.connect("button-press-event", self.on_background_press)
        self.connect("motion-notify-event", self.on_band_motion)
        self.connect("button-release-event", self.on_band_release)
        self.connect("key-press-event", self.on_key_press)

        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(HINT)
        self.set_app_paintable(True)
        self.stick()
        self.set_keep_below(True)
        self.set_accept_focus(True)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.get_style_context().add_class("cubbywin")
        self.set_size_request(130, 90 if data.get("title_pos") != "none" else 40)
        self.set_default_size(data["w"], data["h"])
        self.move(data["x"], data["y"])

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.get_style_context().add_class("cubby")
        self.add(outer)
        self.outer = outer
        # Per-cubby stylesheet, installed screen-wide but scoped to this cubby by a unique class.
        self.css_class = "cubby-" + data["id"]
        outer.get_style_context().add_class(self.css_class)
        self._provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self._provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        self.connect("destroy", lambda *_a: Gtk.StyleContext.remove_provider_for_screen(
            Gdk.Screen.get_default(), self._provider))
        self.connect("destroy", lambda *_a: self.stop_watching())
        self.connect("destroy", lambda *_a: self.cancel_timers())
        self.connect("destroy", lambda *_a: self.cancel_folder_preview())
        self.connect("destroy", lambda *_a: getattr(self, "_search_ed", None)
                     and self._search_ed.destroy())
        self.apply_style()

        # title bar (drag to move, wheel to change page, right-click for menu)
        self.title_ev = Gtk.EventBox()
        self.title_ev.get_style_context().add_class("cubby-title")
        self.title_lbl = Gtk.Label(label=self.pane["title"], xalign=0)
        self.title_lbl.set_no_show_all(True)
        self.tab_box = Gtk.Box(spacing=3)      # one tab per cubby when cubbies are combined
        self.tab_box.set_no_show_all(True)
        title_row = self.title_row = Gtk.Box()
        # the ☰ (sort / view) and ✕ (delete) buttons: only seen while the pointer is on the
        # title bar, but their space is always kept so the title never shifts
        self.menu_btn = self.hover_button("\u2630", "Sort and view", self.show_sort_menu)
        title_row.pack_start(self.menu_btn, False, False, 0)
        # the name and its Folder / Inbox icon, kept together (centred as one when centred)
        self.name_box = Gtk.Box(spacing=0)
        self.folder_img = Gtk.Image.new_from_icon_name("folder", Gtk.IconSize.MENU)
        self.folder_img.set_no_show_all(True)   # only Folder Cubbies show it
        self.folder_img.set_margin_start(6)
        self.up_btn = Gtk.Button(label="\u2191")
        self.up_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.up_btn.set_no_show_all(True)
        self.up_btn.set_tooltip_text("Back up one folder")
        self.up_btn.get_style_context().add_class("cubby-hover-btn")
        self.up_btn.connect("clicked", self.navigate_up)
        hand_cursor(self.up_btn)
        self.name_box.pack_start(self.up_btn, False, False, 0)
        self.lock_img = Gtk.Image.new_from_icon_name(
            next((n for n in ("changes-prevent-symbolic", "system-lock-screen-symbolic",
                              "locked") if Gtk.IconTheme.get_default().has_icon(n)),
                 "changes-prevent-symbolic"), Gtk.IconSize.MENU)
        self.lock_img.set_no_show_all(True)
        self.lock_img.set_margin_end(4)
        self.lock_img.set_tooltip_text("Locked: it can't be moved or resized")
        self.name_box.pack_start(self.lock_img, False, False, 0)
        self.name_box.pack_start(self.folder_img, False, False, 0)
        self.inbox_img = Gtk.Image.new_from_icon_name(inbox_icon_name(), Gtk.IconSize.MENU)
        self.inbox_img.set_no_show_all(True)    # only Inbox Cubbies show it
        self.inbox_img.set_margin_start(6)
        self.inbox_img.set_tooltip_text("Inbox: new files that land on the Desktop come here")
        self.name_box.pack_start(self.inbox_img, False, False, 0)
        self.title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.name_box.pack_start(self.title_lbl, True, True, 0)
        self.name_box.show()
        # shown or hidden only by update_title (a "show everything" must not bring it back
        # over a row of tabs, where it used to take half of the title bar)
        self.name_box.set_no_show_all(True)
        self._name_centred = None
        # the tabs of combined cubbies scroll sideways (with an arrow at each end) when they
        # don't all fit, instead of making the cubby wider
        self.tab_strip = Gtk.Box()
        self.tab_strip.set_no_show_all(True)
        self.tab_left = self.make_tab_arrow("\u2039", -1)
        self.tab_right = self.make_tab_arrow("\u203a", 1)
        self.tab_sw = Gtk.ScrolledWindow()
        self.tab_sw.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        self.tab_sw.set_shadow_type(Gtk.ShadowType.NONE)
        self.tab_sw.get_style_context().add_class("cubby-kinds-sw")
        self.tab_sw.set_hexpand(True)
        try:
            self.tab_sw.set_propagate_natural_height(True)
        except Exception:
            pass
        self.tab_sw.add(self.tab_box)
        self.tab_sw.add_events(SCROLL_MASKS)
        self.tab_sw.connect("size-allocate", lambda *_a: GLib.idle_add(self.even_tabs)
                            and None)
        tadj = self.tab_sw.get_hadjustment()
        tadj.connect("changed", self.queue_tab_arrows)
        tadj.connect("value-changed", self.queue_tab_arrows)
        self.tab_strip.pack_start(self.tab_left, False, False, 0)
        self.tab_strip.pack_start(self.tab_sw, True, True, 0)
        self.tab_strip.pack_start(self.tab_right, False, False, 0)
        self.tab_sw.show()
        self.tab_sw.get_child().show()      # the viewport around the tabs
        title_row.pack_start(self.tab_strip, True, True, 0)
        self.close_btn = self.hover_button("\u2715", "Delete this cubby", self.delete_whole)
        title_row.pack_end(self.close_btn, False, False, 0)
        self.title_ev.add(title_row)
        self.title_ev.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                                 | Gdk.EventMask.POINTER_MOTION_MASK | SCROLL_MASKS)
        self.title_ev.connect("button-press-event", self.on_title_press)
        self.title_ev.connect("motion-notify-event", self.on_motion)
        self.title_ev.connect("button-release-event", self.on_release)
        self.title_ev.connect("scroll-event", self.on_scroll)
        self.title_ev.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.title_ev.connect("enter-notify-event", self.on_title_hover, True)
        self.title_ev.connect("leave-notify-event", self.on_title_hover, False)
        # the four-way "move" pointer over the title bar
        self.title_ev.connect("realize", lambda w: set_cursor(w.get_window(), "move", "fleur"))
        outer.pack_start(self.title_ev, False, False, 0)

        # tabs under the title bar (not part of it): any cubby can filter by kind of file
        # They scroll sideways, with an arrow at each end, when they do not all fit.
        self.kind_row = Gtk.Box(spacing=2)
        self.kind_row.get_style_context().add_class("cubby-kinds")
        self.kind_row.set_no_show_all(True)
        self.kind_row.set_margin_start(6)
        self.kind_row.set_margin_end(6)
        self.kind_row.set_margin_top(5)
        self.kind_left = self.make_kind_arrow("\u2039", -1)
        self.kind_right = self.make_kind_arrow("\u203a", 1)
        self.kind_sw = Gtk.ScrolledWindow()
        self.kind_sw.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        self.kind_sw.set_shadow_type(Gtk.ShadowType.NONE)
        self.kind_sw.get_style_context().add_class("cubby-kinds-sw")
        self.kind_sw.set_hexpand(True)
        try:
            self.kind_sw.set_propagate_natural_height(True)
        except Exception:
            pass
        self.kind_box = Gtk.Box(spacing=4)
        self.kind_sw.add(self.kind_box)
        self.kind_sw.add_events(SCROLL_MASKS)
        self.kind_sw.connect("scroll-event", self.on_kind_scroll)
        kadj = self.kind_sw.get_hadjustment()
        kadj.connect("changed", self.queue_kind_arrows)
        kadj.connect("value-changed", self.queue_kind_arrows)
        self.kind_row.pack_start(self.kind_left, False, False, 0)
        self.kind_row.pack_start(self.kind_sw, True, True, 0)
        self.kind_row.pack_start(self.kind_right, False, False, 0)
        self.kind_sw.show_all()     # kind_row is no_show_all: its parts are shown by hand
        outer.pack_start(self.kind_row, False, False, 0)

        # icon area
        self.flow = Gtk.FlowBox()
        self.flow.set_margin_top(8)
        self.flow.set_margin_bottom(4)
        self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flow.set_valign(Gtk.Align.START)
        self.flow.set_homogeneous(True)
        self.flow.set_min_children_per_line(1)
        self.flow.set_max_children_per_line(40)
        self.flow.set_activate_on_single_click(False)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.add(self.flow)
        sw.connect("scroll-event", self.on_icon_scroll)   # Ctrl + wheel: bigger / smaller icons
        self.sw = sw
        self._cell_w = None
        # (changing the columns while sizes are being handed out isn't allowed: a moment later)
        sw.connect("size-allocate", lambda *_a: GLib.idle_add(self.fit_columns))
        # Details view: column headings above the list (click one to sort by it)
        self.head_row = Gtk.Box(spacing=0)
        self.head_row.get_style_context().add_class("cubby-heads")
        self.head_row.set_no_show_all(True)
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        # the search strip: slides down above the icons while searching (Ctrl + F)
        self.search_rev = Gtk.Revealer()
        self.search_rev.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.search_rev.set_transition_duration(160)
        strip = Gtk.Box(spacing=6)
        strip.get_style_context().add_class("cubby-kind")
        strip.set_margin_start(6)
        strip.set_margin_end(6)
        strip.set_margin_top(5)
        icon = Gtk.Image.new_from_icon_name("edit-find-symbolic", Gtk.IconSize.MENU)
        icon.set_margin_start(6)
        strip.pack_start(icon, False, False, 0)
        self.search_slot = Gtk.Box()          # the typing box sits right over this
        self.search_slot.set_size_request(-1, 26)
        strip.pack_start(self.search_slot, True, True, 0)
        self.search_count = Gtk.Label(label="")
        self.search_count.set_margin_end(8)
        self.search_count.set_width_chars(9)     # room kept, so the typing box never covers it
        self.search_count.set_xalign(1.0)
        strip.pack_start(self.search_count, False, False, 0)
        self.search_rev.add(strip)
        self.search_rev.show_all()
        self.search_rev.set_reveal_child(False)
        self._search = ""
        self.content.pack_start(self.search_rev, False, False, 0)
        self.content.pack_start(self.head_row, False, False, 0)
        self.content.pack_start(sw, True, True, 0)
        self.content.show()
        sw.show()
        outer.pack_start(self.content, True, True, 0)
        # the see-through selection rectangle is painted over everything after the children
        outer.connect_after("draw", self.on_band_draw)
        outer.connect_after("draw", self.on_picked_draw)
        outer.connect_after("draw", self.on_line_draw)

        # resize grip
        grip_row = self.grip_row = Gtk.Box()
        self.grip = Gtk.EventBox()
        self.grip.get_style_context().add_class("cubby-grip")
        self.grip.add(Gtk.Label(label="◢"))
        self.grip.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                             | Gdk.EventMask.POINTER_MOTION_MASK)
        self.grip.connect("button-press-event", self.on_grip_press)
        self.grip.connect("motion-notify-event", self.on_motion)
        self.grip.connect("button-release-event", self.on_release)
        grip_row.pack_end(self.grip, False, False, 0)
        # (not packed any more: every side and corner of a cubby resizes it now)
        self._zone, self._zone_win = None, None
        # edges/corners: these see the pointer before the title bar and icons do
        self._edge_motion = Gtk.EventControllerMotion.new(self)
        self._edge_motion.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self._edge_motion.connect("motion", self.on_edge_motion)
        self._edge_motion.connect("leave", lambda *_a: self.show_zone_cursor(None, None)
                                  if not self._drag else None)
        # (CAPTURE: presses on the title bar / icons near an edge; TARGET: presses that land
        # on the window itself, its thin rim, which capture-phase gestures never see)
        self._edge_gestures = []
        for phase in (Gtk.PropagationPhase.CAPTURE, Gtk.PropagationPhase.TARGET):
            g = Gtk.GestureDrag.new(self)
            g.set_button(1)
            g.set_propagation_phase(phase)
            g.connect("drag-begin", self.on_edge_begin)
            g.connect("drag-update", self.on_edge_update)
            g.connect("drag-end", self.on_edge_end)
            self._edge_gestures.append(g)
        forced = self.forced_title_pos()
        self.set_flipped((forced == "bottom") if forced else data.get("flip", False),
                         save=False)

        # accept dropped files
        target = Gtk.TargetEntry.new("text/uri-list", 0, 0)
        self.drag_dest_set(Gtk.DestDefaults.ALL, [target],
                           Gdk.DragAction.COPY | Gdk.DragAction.MOVE | Gdk.DragAction.LINK)
        self.connect("drag-data-received", self.on_drop)
        self.connect("drag-motion", self.on_drop_hover)
        self.connect("drag-leave", lambda *_a: self.light_drop_target(None))

        self.apply_title_size()
        self.refresh()
        self._inside = False
        self.update_title_visibility()
        GLib.idle_add(lambda: self.update_fade() and False)

    # -- content
    def refresh(self):
        self._refresh_gen = getattr(self, "_refresh_gen", 0) + 1
        for child in self.flow.get_children():
            self.flow.remove(child)
        self.item_widgets = {}
        icons = self.pane.get("view", "icons") == "icons"
        mode = self.scroll_mode()
        horiz = icons and mode == "horizontal"
        # horizontal: icons go down in columns and the cubby scrolls sideways
        self.flow.set_orientation(Gtk.Orientation.VERTICAL if horiz
                                  else Gtk.Orientation.HORIZONTAL)
        self.sw.set_policy(Gtk.PolicyType.AUTOMATIC if mode != "vertical"
                           else Gtk.PolicyType.NEVER,
                           Gtk.PolicyType.NEVER if horiz else Gtk.PolicyType.AUTOMATIC)
        self._cell_h = None
        self.flow.set_max_children_per_line(40 if icons else 1)
        # icons: a fixed grid from the left, so resizing never spreads or shifts them; a new
        # column appears only once a whole icon fits (see fit_columns)
        self.flow.set_halign(Gtk.Align.START if icons else Gtk.Align.FILL)
        self.flow.set_column_spacing(ICON_GAP if icons else 0)
        self.flow.set_size_request(-1, -1)
        self._cell_w = None
        for path in self.ordered_items():
            widget = self.make_item(path)
            self.item_widgets[path] = widget
            self.flow.add(widget)
        self.selected &= set(self.item_widgets)
        self.flow.show_all()
        self.fit_columns()
        self.update_kind_tabs()
        self.update_headings()
        self.update_title()
        self.watch_folder()
        self.set_selection(self.selected)
        if self.app.glance is not None:    # Glance open: it shows the change too
            self.app.glance.refresh_soon()

    def fit_columns(self, *_a):
        """Icons view: as many columns as whole icons fit in the width, no more."""
        if self.pane.get("view", "icons") != "icons":
            return False
        kids = self.flow.get_children()
        if not kids:
            return False
        mode = self.scroll_mode()
        if not self._cell_w:
            # one fixed cell size for every icon: the grid can't squeeze or stretch them
            # (a squeezed cell re-wraps long names; a stretched one spreads the icons)
            self._cell_w = max(k.get_preferred_width()[1] for k in kids)
            self._cell_h = max(k.get_preferred_height_for_width(self._cell_w)[1]
                               for k in kids)
            for k in kids:
                k.set_size_request(self._cell_w, self._cell_h)
        cw, ch = self._cell_w, self._cell_h
        gap = ICON_GAP
        if mode == "both":                 # a fixed number of columns: no reflowing at all
            try:
                n = max(1, min(40, int(self.pane.get("cols", 4))))
            except (TypeError, ValueError):
                n = 4
            want = n * cw + (n - 1) * gap
            if n != self.flow.get_max_children_per_line():
                self.flow.set_max_children_per_line(n)
            if self.flow.get_size_request()[0] != want:
                self.flow.set_size_request(want, -1)
            return False
        if mode == "horizontal":           # as many rows as whole icons fit in the height
            avail = (self.sw.get_allocated_height() - self.flow.get_margin_top()
                     - self.flow.get_margin_bottom() - 2)
            if avail <= 1:
                return False
            n = max(1, avail // max(1, ch))
            cols = -(-len(kids) // n)
            want = cols * cw + (cols - 1) * gap     # exactly as wide as its columns
            if n != self.flow.get_max_children_per_line():
                self.flow.set_max_children_per_line(n)
            if self.flow.get_size_request()[0] != want:
                self.flow.set_size_request(want, -1)
            return False
        if self.flow.get_size_request()[0] != -1:
            self.flow.set_size_request(-1, -1)
        avail = (self.sw.get_allocated_width() - self.flow.get_margin_start()
                 - self.flow.get_margin_end() - 2)
        if avail <= 1:
            return False
        n = max(1, (avail + ICON_GAP) // (self._cell_w + ICON_GAP))
        if n != self.flow.get_max_children_per_line():
            self.flow.set_max_children_per_line(n)
        return False

    def scroll_mode(self):
        """"vertical" (the usual), "horizontal" or "both" (View › Scroll Bars). List and
        Details always scroll down; "horizontal" there just adds a sideways bar too."""
        mode = self.pane.get("scroll", "vertical")
        if mode not in ("vertical", "horizontal", "both"):
            return "vertical"
        if mode == "horizontal" and self.pane.get("view", "icons") != "icons":
            return "both"
        return mode

    def set_scroll_mode(self, mode):
        if mode == "both":                 # keep the columns it has now
            self.pane["cols"] = max(1, self.flow.get_max_children_per_line()
                                    if self.flow.get_orientation() == Gtk.Orientation.HORIZONTAL
                                    else 4)
        if mode == "vertical":
            self.pane.pop("scroll", None)
        else:
            self.pane["scroll"] = mode
        self.refresh()
        self.app.save()

    def update_headings(self):
        """Column headings for the Details view (unless turned off for this cubby)."""
        for child in self.head_row.get_children():
            self.head_row.remove(child)
        show = (self.pane.get("view", "icons") == "details"
                and self.pane.get("details_head", True))
        if not show:
            self.head_row.hide()
            return
        size = max(MIN_ICON, min(MAX_ICON, int(self.pane.get("icon_size", DEFAULT_ICON))))
        small = max(16, min(32, size // 2))
        mode = self.pane.get("sort", "manual")
        if self.pane.get("folder") and mode == "manual":
            mode = "name"
        arrow = " \u25be" if self.pane.get("sort_rev") else " \u25b4"

        def head(text, key, chars=None, xalign=0.0):
            ev = Gtk.EventBox()
            ev.set_visible_window(False)
            lbl = Gtk.Label(label=text + (arrow if mode == key else ""), xalign=xalign)
            if chars:
                lbl.set_width_chars(chars)
            lbl.set_margin_start(4)          # the same padding the file names and dates have
            lbl.set_margin_end(4)
            ev.add(lbl)
            ev.set_tooltip_text("Click to sort by this; click again to reverse")
            ev.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)

            def press(_w, e):
                if e.button == 1:
                    if self.pane.get("sort", "manual") == key or (key == "name" and mode == "name"):
                        self.set_sort(rev=not self.pane.get("sort_rev"))
                    else:
                        self.set_sort(mode=key, rev=False)
                return True
            ev.connect("button-press-event", press)
            ev.show_all()
            return ev

        name = head("Name", "name")
        name.set_margin_start(small + 10)
        self.head_row.pack_start(name, True, True, 0)
        self.head_row.pack_end(head("Modified", "date", 16, 1.0), False, False, 6)
        self.head_row.pack_end(head("Size", "size", 9, 1.0), False, False, 6)
        self.head_row.set_visible(not self.data.get("rolled") or self._peeking)

    def update_title(self):
        """Show the cubby's name, or one tab per cubby when several are combined."""
        group = bool(self.data.get("group"))
        style = self.app.cfg.get("tab_style", "rounded")
        menu_only = group and style == "menu"
        ctx = self.title_ev.get_style_context()
        for st in ("rounded", "flat", "segmented"):
            if st == style:
                ctx.add_class("tabs-" + st)
            else:
                ctx.remove_class("tabs-" + st)
        named = not group or menu_only        # a name in the title bar (not a row of tabs)
        self.place_name()
        hover = bool(self.app.setting("hover_buttons"))
        for btn in (self.menu_btn, self.close_btn):
            btn.set_visible(hover and (not group or menu_only))
        self.title_lbl.set_visible(named)
        self.name_box.set_visible(named)
        self.tab_box.set_visible(group and not menu_only)
        self.tab_strip.set_visible(group and not menu_only)
        is_folder = bool(self.pane.get("folder")) and named
        self.folder_img.set_visible(is_folder and self.app.setting("folder_title_icon"))
        recent = is_recent(self.pane)
        self.inbox_img.set_from_icon_name("document-open-recent" if recent else inbox_icon_name(),
                                          Gtk.IconSize.MENU)
        self.inbox_img.set_tooltip_text(
            "Recent Files: what you opened lately, newest first" if recent else
            "Inbox: new files that land on the Desktop come here")
        self.inbox_img.set_visible((is_inbox(self.pane) or recent) and named)
        if is_folder:
            self.folder_img.set_tooltip_text("Shows the folder " + self.pane["folder"])
        self.lock_img.set_visible(self.app.is_locked(self.data))
        shown = self.app.folder_of(self.pane) if self.pane.get("folder") else None
        inside = bool(shown and os.path.abspath(shown) != os.path.abspath(self.pane["folder"]))
        self.up_btn.set_visible(inside and named)
        if self.up_btn.get_visible():
            self.up_btn.get_child().show()
        if named:
            # "Menu only" tabs: the shown tab's name and a ▾; click it to choose a tab.
            # A Folder Cubby that was navigated into a sub-folder shows that folder's name.
            name = os.path.basename(shown.rstrip("/")) if inside else self.pane["title"]
            self.title_lbl.set_text(name + ("  \u25be" if menu_only else ""))
            self.title_lbl.set_tooltip_text("Click to choose a tab" if menu_only else None)
            return
        for child in self.tab_box.get_children():
            self.tab_box.remove(child)
        self._tab_menu_btns = {}
        self._tab_widgets = {}
        fit = self.app.cfg.get("tab_fit", "keep")     # keep / scroll / shorten
        fill = self.app.setting("tab_fill")
        # "keep": the tabs set the narrowest the cubby can be (all names in full); "scroll":
        # arrows when they don't fit; "shorten": names shortened with "…" so all fit
        self.tab_sw.set_policy(Gtk.PolicyType.NEVER if fit == "keep"
                               else Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        self.tab_box.set_homogeneous(False)
        self._tab_fill = fill
        for pane in self.app.group_panes(self.data):
            ev = Gtk.EventBox()
            ev.set_visible_window(True)
            ctx = ev.get_style_context()
            ctx.add_class("cubby-tab")
            if pane.get("tab_color"):
                ctx.add_class("tabc-" + pane["id"])
            if pane is self.pane:
                ctx.add_class("active")
            lbl = Gtk.Label(label=pane["title"])
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
            if fit == "shorten":                  # names give way ("…") so every tab fits
                lbl.set_width_chars(min(len(pane["title"]), 3))
            else:                                 # the whole name always shows
                lbl.set_width_chars(len(pane["title"]))
            # widget margins (an EventBox ignores CSS padding: that crammed the tabs together)
            lbl.set_margin_start(12)
            lbl.set_margin_end(12)
            lbl.set_margin_top(3)
            lbl.set_margin_bottom(3)
            if style == "rounded":
                ev.set_margin_top(3)
                ev.set_margin_bottom(3)
            elif style == "segmented":
                ev.set_margin_top(4)
            tab_icon = ("folder" if pane.get("folder")      # Folder and Inbox Cubbies carry
                        else inbox_icon_name() if is_inbox(pane) else None)   # their icon in a tab
            inner = Gtk.Box(spacing=4)
            # each tab has its own ☰ (sort / view of that tab) and ✕ (delete that tab), seen
            # while the pointer is on the tab; their space is kept so the tabs don't jump
            hover = bool(self.app.setting("hover_buttons"))
            tmenu = self.tab_button("\u2630", "Sort and view this tab",
                                    lambda _b, p=pane: self.tab_sort_menu(p))
            tclose = self.tab_button("\u2715", "Delete this tab",
                                     lambda _b, p=pane: GLib.idle_add(
                                         lambda: self.app.delete_cubby(p) and False))
            if hover:
                inner.pack_start(tmenu, False, False, 0)
                lbl.set_margin_start(2)
                lbl.set_margin_end(2)
            if tab_icon:
                inner.pack_start(Gtk.Image.new_from_icon_name(tab_icon, Gtk.IconSize.MENU),
                                 False, False, 0 if hover else 0)
            inner.pack_start(lbl, True, True, 0)
            if hover:
                inner.pack_start(tclose, False, False, 0)
            ev.add(inner)
            ev.tab_buttons = (tmenu, tclose)
            ev.tab_label = lbl
            self._tab_menu_btns[pane["id"]] = tmenu
            self._tab_widgets[pane["id"]] = ev
            ev.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                          | Gdk.EventMask.POINTER_MOTION_MASK | SCROLL_MASKS
                          | Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
            ev.connect("realize", lambda w: set_cursor(w.get_window(), "move", "fleur"))
            # drop files straight onto a tab: they go into that tab (not the one shown)
            ev.drag_dest_set(Gtk.DestDefaults.ALL, [Gtk.TargetEntry.new("text/uri-list", 0, 0)],
                             Gdk.DragAction.COPY | Gdk.DragAction.MOVE | Gdk.DragAction.LINK)
            ev.connect("drag-data-received", self.on_tab_drop, pane)
            ev.connect("enter-notify-event", self.on_tab_hover, True)
            ev.connect("leave-notify-event", self.on_tab_hover, False)
            ev.connect("button-press-event", self.on_tab_press, pane)
            ev.connect("motion-notify-event", self.on_tab_motion, pane)
            ev.connect("button-release-event", self.on_tab_release, pane)
            ev.connect("scroll-event", self.on_tab_scroll)
            self.tab_box.pack_start(ev, fill, fill, 0)    # fill: tabs share out the width
            # tab_box is a "no_show_all" widget, so show_all() on it (or on the window) skips
            # it entirely: every new tab has to be shown by hand or it stays invisible.
            ev.show_all()
        self.tab_box.show()
        GLib.idle_add(self.show_active_tab)
        GLib.idle_add(self.even_tabs)
