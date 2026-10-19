"""Settings sections: layout, launch bars, sorting, command line, about, backup."""

import os
import shutil
import time

from gi.repository import Gdk, GLib, Gtk, Pango

from ..backups import BACKUP_DIR, BACKUP_KEEP, auto_backup, list_backups, read_backup
from ..cli import CLI_COMMANDS
from ..constants import COLLECT_CHOICES, LINE_STYLES, MAX_ICON, MIN_ICON, VERSION
from ..core import CONFIG_DIR, CONFIG_FILE
from ..desktop_env import DESKTOP_ICONS_PLACE, DESKTOP_NAME, IS_MATE, IS_XFCE
from ..dialogs import confirm, tell
from ..files import inbox_icon_name, is_recent, launch
from ..layouts import delete_layout, layout_list, save_layout
from ..widgets import no_wheel
from ..cubby.cubby import Cubby


class AppSettingsTools:
    """Settings sections (tools). Part of App."""

    def settings_layout(self):
        sw, box = self.s_page("Layout & Snapping", "How cubbies line up and how new ones are "
                              "made.")
        sec = self.s_section(box, "Snapping")
        self.s_check(sec, "Keep cubbies lined up with each other when moving or resizing",
                     "snap_cubbies")
        self.s_check(sec, "Snap cubbies to the top and bottom edges of the screen", "edge_snap")
        side = self.s_check(sec, "\u2026and to the left and right edges too", "edge_snap_sides")
        side.set_margin_start(26)
        row = Gtk.Box(spacing=8)
        row.set_margin_start(26)
        row.pack_start(Gtk.Label(label="Snap from this close:"), False, False, 0)
        reach = Gtk.SpinButton.new_with_range(1, 400, 1)
        reach.set_value(int(self.cfg.get("edge_snap_px", 40)))
        row.pack_start(reach, False, False, 0)
        row.pack_start(Gtk.Label(label="px"), False, False, 0)
        sec.pack_start(row, False, False, 0)

        def reach_changed(b):
            self.cfg["edge_snap_px"] = int(b.get_value())
            self.save()
        reach.connect("value-changed", reach_changed)
        row = Gtk.Box(spacing=8)
        row.pack_start(Gtk.Label(label="Space between cubbies:"), False, False, 0)
        gap = Gtk.SpinButton.new_with_range(0, 200, 1)
        gap.set_value(int(self.cfg.get("snap_gap", 0)))
        row.pack_start(gap, False, False, 0)
        row.pack_start(Gtk.Label(label="px"), False, False, 0)
        sec.pack_start(row, False, False, 0)

        def gap_changed(b):
            self.cfg["snap_gap"] = int(b.get_value())
            self.save()
        gap.connect("value-changed", gap_changed)
        self.s_check(sec, "Keep the same space from the edges of the screen", "gap_screen")
        self.s_note(sec, "Cubbies placed side by side (or one above another) stick with exactly "
                         "this much space between them. Edges that line up still line up "
                         "exactly. 0 = they touch.")
        self.s_note(sec, "Hold Shift while moving or resizing to turn snapping off for a moment.")
        sec = self.s_section(box, "Locking")

        def lock_changed(_on):
            for win in self.windows.values():
                win.update_title()
        self.s_check(sec, "Lock all cubbies (they can't be moved or resized)", "lock_all",
                     lock_changed)
        self.s_note(sec, "To lock just one: right-click it \u203a Options \u203a Lock Position and Size. A "
                         "locked cubby shows a small padlock by its name.")
        sec = self.s_section(box, "Every page")
        self.s_note(sec, "To keep a cubby on every page: right-click it \u203a Options \u203a Show "
                         "on Every Page. It can sit in a different place on each page (move it "
                         "on any page), or tick Options \u203a Same Place on Every Page. "
                         "Deleting it warns you which pages it's on.")
        sec = self.s_section(box, "Making cubbies")
        self.s_check(sec, "Hold the left mouse button and drag on the empty desktop to draw a "
                          "new cubby", "draw_new")
        self.s_check(sec, "Desktop icons inside a newly drawn cubby go into it", "draw_takes_icons")
        self.s_check(sec, "Computer, Home, Trash and Network icons taken from the desktop into a "
                          "cubby (dragged in, or drawn around) disappear from the desktop",
                     "hide_taken_links", lambda _on: self.sync_links_soon())
        self.s_note(sec, "They come back on the desktop when no cubby holds them any more "
                         "(Move Back to Desktop, Remove from Cubby, deleting the cubby). This "
                         f"uses the same switches as {DESKTOP_ICONS_PLACE}.")
        sec = self.s_section(box, "Moving several cubbies at once")
        self.s_check(sec, "Drawing a box around cubbies on the desktop picks them", "box_select")
        self.s_note(sec, "Picked cubbies get a bright outline and move together when you drag any "
                         "one of them. You can also Ctrl + click title bars to pick or unpick "
                         "them. A click on the desktop or Escape lets them go.")
        sec = self.s_section(box, "Title bar position")
        self.s_note(sec, "Normally a cubby moved close to the bottom of the screen gets its title "
                         "bar at the bottom, so its icons stay on the screen.")

        def pos_choice(_on):
            for win in self.windows.values():
                win.apply_title_pos()
        self.s_check(sec, "Let each cubby keep its title bar at the top or the bottom "
                          "(right-click a cubby \u203a Options \u203a Title Bar)", "title_pos_choice", pos_choice)
        return sw

    def settings_bars(self):
        sw, box = self.s_page("Launch Bar Cubbies", "A row of your favourite apps along the top "
                              "(or bottom) of the screen, out of sight until you push the "
                              "pointer against that edge.")
        sec = self.s_section(box, "Your launch bars and their pages")
        self.s_note(sec, "Each page shows at most one launch bar, and pages can share one: tick "
                         "the pages each bar is on. Ticking a page for one bar takes it from "
                         "another. \u201cEvery page\u201d also covers pages you add later "
                         "(pages ticked for another bar keep that one).")
        holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        sec.pack_start(holder, False, False, 6)
        btn = Gtk.Button(label="Make a Launch Bar Cubby for This Page")
        btn.set_halign(Gtk.Align.START)
        btn.connect("clicked", lambda _b: (self.new_launch_bar(), fill()))
        sec.pack_start(btn, False, False, 0)
        left = Gtk.Label(xalign=0)
        left.get_style_context().add_class("dim-label")
        left.set_line_wrap(True)
        sec.pack_start(left, False, False, 0)

        def fill():
            for c in holder.get_children():
                holder.remove(c)
            bars = self.launch_bars()
            if not bars:
                lbl = Gtk.Label(label="You don't have a launch bar yet.", xalign=0)
                holder.pack_start(lbl, False, False, 0)
            for i, f in enumerate(bars):
                card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
                card.get_style_context().add_class("cb-card")
                head = Gtk.Box(spacing=10)
                n = len(self.active_pane(f).get("items", []))
                title = Gtk.Label(xalign=0)
                title.set_markup(f"<b>Launch bar {i + 1}</b>   <small>{n} icon"
                                 f"{'s' if n != 1 else ''} \u00b7 lives on "
                                 f"\u201c{GLib.markup_escape_text(self.page_of(f)['name'])}"
                                 "\u201d</small>")
                head.pack_start(title, False, False, 0)
                every = Gtk.CheckButton(label="Every page")
                every.set_active(bool(f.get("bar_all")))
                every.connect("toggled", lambda b, f=f: (self.set_bar_all(f, b.get_active()),
                                                         GLib.idle_add(fill_later)))
                head.pack_end(every, False, False, 0)
                card.pack_start(head, False, False, 0)
                flow = Gtk.FlowBox()
                flow.set_selection_mode(Gtk.SelectionMode.NONE)
                flow.set_max_children_per_line(6)
                flow.set_column_spacing(14)
                covered = self.bar_covers(f)
                for page in self.cfg["pages"]:
                    c = Gtk.CheckButton(label=page["name"])
                    c.set_active(page in covered)
                    owner = self.bar_for_page(page)
                    if owner is not None and owner is not f:
                        c.set_tooltip_text(f"Now on launch bar {bars.index(owner) + 1}")
                    c.connect("toggled", lambda b, f=f, p=page: (
                        self.set_bar_page(f, p, b.get_active()), GLib.idle_add(fill_later)))
                    flow.add(c)
                card.pack_start(flow, False, False, 0)
                if not covered:
                    note = Gtk.Label(label="Not shown on any page right now.", xalign=0)
                    note.get_style_context().add_class("dim-label")
                    card.pack_start(note, False, False, 0)
                holder.pack_start(card, False, False, 0)
            holder.show_all()
            btn.set_sensitive(self.can_make_launch_bar())
            bare = [p["name"] for p in self.cfg["pages"] if self.bar_for_page(p) is None]
            left.set_text(("Pages without a launch bar: " + ", ".join(bare)) if bare and bars
                          else "")
            left.set_visible(bool(bare and bars))

        def fill_later():
            fill()
            return False
        fill()
        self.s_bullets(sec, [
            "<b>Make one:</b> the button above, or right-click the page bar \u203a New Cubby "
            "\u203a Launch Bar Cubby (on a page that has none yet)",
            "<b>Fill it:</b> drag apps from the menu onto it, or right-click it \u203a Add "
            "Applications\u2026",
            "<b>Move or resize it:</b> drag its empty space to move it, an edge to resize it"])

        later = {"id": 0}

        def changed(*_a, place=True):
            if later["id"]:
                GLib.source_remove(later["id"])

            def go():
                later["id"] = 0
                self.update_launch_bars(place)
                return False
            later["id"] = GLib.timeout_add(250, go)

        sec = self.s_section(box, "Place and size")
        self.s_combo(sec, "Edge of the screen:", "launchbar_edge",
                     (("top", "Top"), ("bottom", "Bottom")), "top", changed)
        self.s_combo(sec, "Width:", "launchbar_width",
                     (("full", "The full width of the screen"),
                      ("fit", "As wide as its icons, centred")), "full", changed)
        self.s_spin(sec, "Icon size:", "launchbar_icon", MIN_ICON, MAX_ICON, 48, "px",
                    after=changed)
        for key, text in (("launchbar_names", "Show the names under the icons"),
                          ("launchbar_autohide", "Auto-hide (slides away until the pointer "
                                                 "reaches that edge)")):
            c = Gtk.CheckButton(label=text)
            c.set_active(bool(self.cfg.get(key, True)))

            def toggled(b, k=key):
                self.cfg[k] = b.get_active()
                self.save()
                changed()
            c.connect("toggled", toggled)
            sec.pack_start(c, False, False, 0)
        self.s_note(sec, "Changes here fit the launch bar to its icons again. Its colour and "
                         "corners: right-click it › Styling Options…")

        sec = self.s_section(box, "Line along its inner edge")
        grid = Gtk.Grid(row_spacing=8, column_spacing=10)
        sec.pack_start(grid, False, False, 0)
        width = Gtk.SpinButton.new_with_range(0, 20, 1)
        width.set_value(int(self.cfg.get("line_width", 0)))
        rgba = Gdk.RGBA()
        if not rgba.parse(self.cfg.get("line_color") or "rgba(255,255,255,0.6)"):
            rgba.parse("rgba(255,255,255,0.6)")
        colour = Gtk.ColorButton.new_with_rgba(rgba)
        colour.set_use_alpha(True)
        style = Gtk.ComboBoxText()
        for k, t in LINE_STYLES:
            style.append(k, t)
        style.set_active_id(self.cfg.get("line_style", "solid"))
        for r, (label, w) in enumerate((("Thickness (0 = no line):", width),
                                        ("Colour:", colour), ("Kind of line:", style))):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1)
            w.set_halign(Gtk.Align.START)
            grid.attach(w, 1, r, 1, 1)
        grid.attach(Gtk.Label(label="px", xalign=0), 2, 0, 1, 1)

        def line_changed(*_a):
            self.cfg["line_width"] = int(width.get_value())
            self.cfg["line_color"] = colour.get_rgba().to_string()
            self.cfg["line_style"] = style.get_active_id() or "solid"
            self.save()
            changed(place=False)
        width.connect("value-changed", line_changed)
        colour.connect("color-set", line_changed)
        style.connect("changed", line_changed)
        self.s_note(sec, "Drawn inside the bar along the side facing the middle of the "
                         "screen: the bottom of a bar at the top, the top of a bar at the "
                         "bottom.")

        sec = self.s_section(box, "Opening icons")

        def click_changed(_mode):
            for win in self.windows.values():
                win.refresh()
        self.s_combo(sec, "Open icons with:", "click_open",
                     (("bars", "One click in launch bars, a double-click elsewhere"),
                      ("single", "One click everywhere"),
                      ("double", "A double-click everywhere")), "bars", click_changed)
        self.s_note(sec, "With one click, a slow second click doesn't rename: use F2 or the "
                         "right-click menu.")
        sec = self.s_section(box, "Auto-hide")
        self.s_combo(sec, "It comes out:", "autohide_open",
                     (("hover", "When the pointer rests at the screen edge"),
                      ("click", "When I click at the screen edge")), "hover")
        self.s_combo(sec, "It goes away:", "autohide_close",
                     (("leave", "When the pointer leaves it"),
                      ("click", "When I click somewhere else or open an icon")), "leave")
        self.s_spin(sec, "Leave the corners free:", "autohide_corners", 0, 600, 100,
                    "px at each end", 10)
        self.s_note(sec, "The corners are where your windows' minimise, maximise and close "
                         "buttons are: pushing the pointer there won't bring the bar out.")
        self.s_combo(sec, "How it hides:", "autohide_anim",
                     (("slide", "Slides off the edge"), ("fade", "Fades out"),
                      ("instant", "Disappears at once")), "slide")
        self.s_spin(sec, "Comes out after the pointer rests at the edge for:", "autohide_show_ms",
                    0, 2000, 150, "ms", 50)
        self.s_spin(sec, "Hides again after the pointer leaves it for:", "autohide_hide_ms",
                    0, 5000, 600, "ms", 50)
        self.s_spin(sec, "Leave a strip showing while hidden (slide only):", "autohide_strip",
                    0, 40, 3, "px", after=lambda _v: self.pager.reposition())
        self.s_check(sec, "Come out over your windows", "autohide_on_top",
                     lambda _on: [w.ah_on_top() for w in self.windows.values()])
        self.s_note(sec, "It stays out while the pointer, one of its menus, or a file you're "
                         "dragging is on it. With a panel along the same edge, push the pointer "
                         "to the panel's inner edge (a wider strip makes that easier).")
        sec = self.s_section(box, "The page bar and the launch bar")
        self.s_combo(sec, "The page bar:", "pager_bar",
                     (("under", "Sits just under the launch bar"),
                      ("with", "Comes out together with it, just beside it"),
                      ("other", "Moves to the other edge of the screen"),
                      ("over", "Stays where it is (it may cover the launch bar)")), "under",
                     lambda _v: self.pager.reposition())
        self.s_note(sec, "“Just under”: while the launch bar is hidden, rest the "
                         "pointer just under its strip to bring out the page bar; while the "
                         "launch bar is out, the page bar stays away. Under a launch bar that "
                         "doesn't auto-hide, the page bar sits just below it. When and where "
                         "the page bar shows otherwise: Settings › Desktop Pages › "
                         "Page bar.")
        return sw

    def settings_sorting(self):
        sw, box = self.s_page("Sorting & Organising", "Where new desktop files go, and what "
                              "happens to files you add to a cubby.")
        sec = self.s_section(box, "Recent Files cubbies")
        self.s_note(sec, "A Recent Files cubby shows the files you opened lately in any app, "
                         "newest first. Each page can have one: draw it on the desktop, use the "
                         "page bar menu, or right-click a cubby \u203a Cubby Type \u203a Recent "
                         "Files. Removing an icon only takes it off the list.")
        row = Gtk.Box(spacing=8)
        row.pack_start(Gtk.Label(label="How many to show:"), False, False, 0)
        count = Gtk.SpinButton.new_with_range(1, 200, 1)
        count.set_value(self.recent_count())
        row.pack_start(count, False, False, 0)
        sec.pack_start(row, False, False, 0)

        def count_changed(b):
            self.cfg["recent_count"] = int(b.get_value())
            self.save()
            for f in self.all_cubbies():
                if is_recent(f):
                    self.refresh_cubby(f)
        count.connect("value-changed", count_changed)
        sec = self.s_section(box, "New files on the desktop go to…")
        self.s_note(sec, "Each kind of file can go to one cubby. Anything not chosen here stays "
                         "on the desktop (or goes to an Inbox Cubby under “Everything "
                         "else”). Only new files are moved, never ones already there.")
        icons = {"images": "image-x-generic", "documents": "x-office-document",
                 "music": "audio-x-generic", "videos": "video-x-generic",
                 "archives": "package-x-generic", "folders": "folder",
                 "drives": "drive-removable-media", "other": inbox_icon_name()}
        per = Gtk.CheckButton(label="Each page has its own: a new file goes to the cubby on "
                                    "the page you're on when it lands on the desktop")
        per.set_active(bool(self.setting("collect_per_page")))
        sec.pack_start(per, False, False, 4)
        prow = Gtk.Box(spacing=8)
        prow.pack_start(Gtk.Label(label="Choices for the page:"), False, False, 0)
        page_combo = Gtk.ComboBoxText()
        for i, page in enumerate(self.cfg["pages"]):
            page_combo.append(str(i), page["name"])
        page_combo.set_active_id(str(self.cfg["page"]))
        prow.pack_start(page_combo, False, False, 0)
        sec.pack_start(prow, False, False, 0)
        frow = Gtk.Box(spacing=8)
        frow.pack_start(Gtk.Label(label="Pages without their own choice:"), False, False, 0)
        fall = Gtk.ComboBoxText()
        fall.append("-", "Keep new files on the desktop")
        for page in self.cfg["pages"]:
            fall.append(self.page_id(page), f"Use the choices of \u201c{page['name']}\u201d")
        fall.set_active_id(self.cfg.get("collect_default_page") or "-")

        def fall_changed(c):
            ident = c.get_active_id()
            if ident and ident != "-":
                self.cfg["collect_default_page"] = ident
            else:
                self.cfg["collect_default_page"] = None
            self.save()
        fall.connect("changed", fall_changed)
        frow.pack_start(fall, False, False, 0)
        sec.pack_start(frow, False, False, 0)
        grid_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sec.pack_start(grid_box, False, False, 0)
        hint = self.s_note(sec, "A page with no cubby of its own for a kind uses the page "
                                "chosen above (or a cubby shown on every page that collects "
                                "that kind). So one Inbox can serve most pages while a few "
                                "pages have their own.")
        busy = [False]

        def build_grid(*_a):
            for c in grid_box.get_children():
                grid_box.remove(c)
            per_page = bool(self.setting("collect_per_page"))
            prow.set_visible(per_page)
            hint.set_visible(per_page)
            frow.set_visible(per_page)
            fall.set_active_id(self.cfg.get("collect_default_page") or "-")
            page = self.cfg["pages"][int(page_combo.get_active_id() or 0)] if per_page else None
            targets = []
            for pg in self.cfg["pages"]:
                for f in pg["cubbies"]:
                    if f.get("group") or f.get("folder") or f.get("launchbar"):
                        continue
                    if page is not None and pg is not page and not f.get("all_pages"):
                        continue
                    targets.append((f, f["title"] if page is not None
                                    else f"{pg['name']} \u203a {f['title']}"))
            grid = Gtk.Grid(row_spacing=6, column_spacing=14)
            grid.set_margin_top(4)
            grid_box.pack_start(grid, False, False, 0)

            def owner_of(kind):
                if page is None:
                    return self.collector_for(kind)
                return next((f for f, _n in targets
                             if self.page_of(f) is page and kind in f.get("collect", [])),
                            None)

            def chosen(combo, kind):
                if busy[0]:
                    return
                ident = combo.get_active_id()
                owner = owner_of(kind)
                if owner is not None:
                    self.set_collect(owner, [k for k in owner.get("collect", []) if k != kind])
                if ident and ident != "-":
                    pane = next(f for f, _n in targets if f["id"] == ident)
                    self.set_collect(pane, [k for k in pane.get("collect", []) if k != kind]
                                     + [kind])
                for win in self.windows.values():
                    win.refresh()
                self.save()

            for row, (kind, label) in enumerate(COLLECT_CHOICES):
                img = Gtk.Image.new_from_icon_name(icons.get(kind, "text-x-generic"),
                                                   Gtk.IconSize.MENU)
                grid.attach(img, 0, row, 1, 1)
                grid.attach(Gtk.Label(label=label, xalign=0), 1, row, 1, 1)
                combo = Gtk.ComboBoxText()
                combo.append("-", "Stay on the desktop")
                for f, name in targets:
                    combo.append(f["id"], name)
                owner = owner_of(kind)
                busy[0] = True
                combo.set_active_id(owner["id"] if owner is not None else "-")
                busy[0] = False
                combo.connect("changed", chosen, kind)
                grid.attach(combo, 2, row, 1, 1)
            grid_box.show_all()
            no_wheel(grid_box)

        def per_toggled(b):
            self.set_collect_per_page(b.get_active())
            build_grid()
        per.connect("toggled", per_toggled)
        page_combo.connect("changed", build_grid)
        prow.set_no_show_all(True)
        prow.show_all()
        hint.set_no_show_all(True)
        frow.set_no_show_all(True)
        frow.show_all()
        build_grid()
        sec = self.s_section(box, "Adding files")
        self.s_check(sec, "Move files and folders into the cubby folder when I add them to a "
                          "cubby (they leave the folder they came from)", "move_files")
        row = Gtk.Box(spacing=10)
        row.pack_start(Gtk.Label(label="Cubby folder:"), False, False, 0)
        where = Gtk.Label(label=self.store_dir(), xalign=0)
        where.set_selectable(True)
        where.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        row.pack_start(where, True, True, 0)
        change = Gtk.Button(label="Change\u2026")

        def change_folder(_b):
            dlg = Gtk.FileChooserDialog(title="Choose where cubby files are kept",
                                        action=Gtk.FileChooserAction.SELECT_FOLDER)
            dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Use This Folder",
                            Gtk.ResponseType.OK)
            dlg.set_create_folders(True)
            dlg.set_current_folder(os.path.dirname(self.store_dir().rstrip("/"))
                                   or os.path.expanduser("~"))
            resp = dlg.run()
            path = dlg.get_filename() if resp == Gtk.ResponseType.OK else None
            dlg.destroy()
            if not path:
                return
            problem = self.store_dir_problem(path)
            if problem:
                tell("That folder can't be used.", problem)
                return
            old = self.store_dir()
            count = len(os.listdir(old)) if os.path.isdir(old) else 0
            if count and not confirm("Move your cubby files?",
                                     f"The {count} item{'s' if count != 1 else ''} in {old} "
                                     f"will be moved to {path}, and {old} will then be removed.",
                                     "Move Them"):
                return
            n, problems = self.change_store_dir(path)
            where.set_text(self.store_dir())
            if problems:
                tell("Not everything could be moved.", "\n".join(problems[:8]))
        change.connect("clicked", change_folder)
        row.pack_start(change, False, False, 0)
        sec.pack_start(row, False, False, 0)
        self.s_note(sec, "Needed for sending new desktop files to cubbies. With it off, a cubby "
                         "only shows a link to the file where it is.")
        sec = self.s_section(box, "Removing icons")
        conf = [None]
        self.s_check(sec, "Pressing Delete removes the selected icons from their cubby",
                     "delete_key", lambda on: conf[0] and conf[0].set_sensitive(on))
        conf[0] = self.s_check(sec, "Ask me to confirm before removing", "confirm_delete")
        conf[0].set_sensitive(bool(self.setting("delete_key")))
        self.s_note(sec, "Deleting a file stored in ~/Cubbies moves it to the Trash (after "
                         "asking). Shortcuts and links only leave the cubby.")
        return sw

    def settings_cli(self):
        sw, box = self.s_page("Command Line", "Everything here can be done from a terminal, a "
                              "script, or a keyboard shortcut of your own. Type  cubbies --help  "
                              "in a terminal for the same list.")
        clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)

        def copy_button(text):
            btn = Gtk.Button.new_from_icon_name("edit-copy-symbolic", Gtk.IconSize.MENU)
            btn.set_relief(Gtk.ReliefStyle.NONE)
            btn.set_tooltip_text("Copy  " + text)
            btn.set_valign(Gtk.Align.CENTER)
            btn.connect("clicked", lambda _b: clip.set_text(text, -1))
            return btn

        # ---- saved layouts
        sec = self.s_section(box, "Saved layouts")
        self.s_note(sec, "A layout remembers where every cubby sits, its size, and whether it "
                         "is rolled up. Handy when a screen change or waking from sleep "
                         "shuffles things: restore it with one click or one command.")
        row = Gtk.Box(spacing=8)
        name_entry = Gtk.Entry()
        name_entry.set_placeholder_text("Layout name")
        name_entry.set_width_chars(22)
        save_btn = Gtk.Button(label="Save Current Layout")
        row.pack_start(name_entry, False, False, 0)
        row.pack_start(save_btn, False, False, 0)
        sec.pack_start(row, False, False, 0)
        listing = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        listing.set_margin_top(4)
        sec.pack_start(listing, False, False, 0)
        status = self.s_note(sec, "")

        def fill():
            for child in listing.get_children():
                listing.remove(child)
            found = layout_list()
            if not found:
                lbl = Gtk.Label(label="No saved layouts yet.", xalign=0)
                lbl.get_style_context().add_class("dim-label")
                listing.pack_start(lbl, False, False, 0)
            for lname, saved, screen in found:
                r = Gtk.Box(spacing=8)
                lbl = Gtk.Label(xalign=0)
                lbl.set_markup(f"<b>{GLib.markup_escape_text(lname)}</b>   "
                               f"<small>{GLib.markup_escape_text(saved)}"
                               + (f"  ·  {screen}" if screen else "") + "</small>")
                lbl.set_size_request(330, -1)
                r.pack_start(lbl, False, False, 0)
                b = Gtk.Button(label="Restore")
                b.connect("clicked", lambda _b, n=lname: (
                    self.restore_layout(n), status.set_text(f"“{n}” restored.")))
                r.pack_start(b, False, False, 0)
                d = Gtk.Button.new_from_icon_name("edit-delete-symbolic", Gtk.IconSize.MENU)
                d.set_tooltip_text("Delete this layout")
                d.set_relief(Gtk.ReliefStyle.NONE)
                d.connect("clicked", lambda _b, n=lname: (delete_layout(n), fill()))
                r.pack_start(d, False, False, 0)
                r.pack_start(copy_button(f"cubbies --restore-layout \"{lname}\""),
                             False, False, 0)
                listing.pack_start(r, False, False, 0)
            listing.show_all()

        def do_save(*_a):
            lname = name_entry.get_text().strip()
            if not lname:
                lname = time.strftime("Layout %Y-%m-%d %H.%M")
            save_layout(self.cfg, lname)
            name_entry.set_text("")
            status.set_text(f"Saved as “{lname}”.")
            fill()
        save_btn.connect("clicked", do_save)
        name_entry.connect("activate", do_save)
        fill()

        # ---- every command
        for group, cmds in CLI_COMMANDS:
            sec = self.s_section(box, group)
            grid = Gtk.Grid(column_spacing=14, row_spacing=2)
            for i, (flag, arg, text) in enumerate(cmds):
                cmd = f"cubbies {flag} {arg}".rstrip()
                c = Gtk.Label(xalign=0)
                c.set_markup(f"<tt>{GLib.markup_escape_text(cmd)}</tt>")
                c.set_selectable(True)
                c.set_size_request(290, -1)
                grid.attach(c, 0, i, 1, 1)
                d = Gtk.Label(label=text, xalign=0)
                d.set_line_wrap(True)
                d.set_max_width_chars(44)
                d.set_size_request(320, -1)      # same width in every group: buttons line up
                d.get_style_context().add_class("dim-label")
                grid.attach(d, 1, i, 1, 1)
                grid.attach(copy_button(f"cubbies {flag}" if not arg else cmd), 2, i, 1, 1)
            sec.pack_start(grid, False, False, 0)

        # ---- keyboard shortcuts
        sec = self.s_section(box, "Make a keyboard shortcut from a command")
        self.s_bullets(sec, [
            ("Open <b>Settings Manager › Keyboard › Application Shortcuts</b> and press "
             "<b>Add</b>" if IS_XFCE else
             "Open <b>Control Center › Keyboard Shortcuts</b> and press <b>Add</b>"
             if IS_MATE else
             "Open <b>System Settings › Keyboard › Shortcuts</b>, choose "
             "<b>Custom Shortcuts</b> and press <b>Add custom shortcut</b>"),
            "Give it a name, paste a command (for example <tt>cubbies --page 2</tt>), "
            "then click the empty key slot and press the keys you want",
            "A few ideas: <tt>cubbies --page 1</tt> … <tt>--page 4</tt> on Super+1…4, "
            "<tt>cubbies --refresh</tt>, or <tt>cubbies --restore-layout Work</tt>"])
        if IS_XFCE and shutil.which("xfce4-keyboard-settings"):
            self.s_link(sec, "Open Keyboard settings",
                        lambda: Cubby.spawn([shutil.which("xfce4-keyboard-settings")]))
        elif IS_MATE and shutil.which("mate-keybinding-properties"):
            self.s_link(sec, "Open Keyboard Shortcuts",
                        lambda: Cubby.spawn([shutil.which("mate-keybinding-properties")]))
        elif shutil.which("cinnamon-settings"):
            self.s_link(sec, "Open Keyboard settings",
                        lambda: Cubby.spawn([shutil.which("cinnamon-settings"), "keyboard"]))
        self.s_note(sec, "Scripts can use the same commands; for example, to put the cubbies "
                         "back after the computer wakes, run  cubbies --restore-layout NAME .")
        return sw

    def settings_about(self):
        sw, box = self.s_page("About")
        row = Gtk.Box(spacing=14)
        theme = Gtk.IconTheme.get_default()
        img = Gtk.Image.new_from_icon_name("cubbies" if theme.has_icon("cubbies")
                                           else "view-grid-symbolic", Gtk.IconSize.DIALOG)
        img.set_pixel_size(56)
        row.pack_start(img, False, False, 0)
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        n = Gtk.Label(xalign=0)
        n.set_markup("<big><b>Cubbies</b></big>")
        names.pack_start(n, False, False, 0)
        names.pack_start(Gtk.Label(label=f"Version {VERSION}", xalign=0), False, False, 0)
        row.pack_start(names, False, False, 0)
        row.set_margin_top(10)
        box.pack_start(row, False, False, 0)
        sec = self.s_section(box, "Information")
        self.s_note(sec, "A desktop organiser for Linux, on the Cinnamon, MATE and Xfce desktops (X11).", dim=False)
        self.s_note(sec, f"Running on {DESKTOP_NAME}.")
        self.s_note(sec, f"Settings are kept in {CONFIG_FILE}")
        self.s_note(sec, f"Files you add to cubbies are kept in {self.store_dir()}")
        sec = self.s_section(box, "Places")
        self.s_link(sec, "Open the folder where your cubby files are kept",
                    lambda: launch(self.store_dir()) if os.path.isdir(self.store_dir())
                    else None)
        self.s_link(sec, "Open the settings folder", lambda: launch(CONFIG_DIR))
        self.s_link(sec, "Open the Welcome Guide", lambda: GLib.idle_add(
            lambda: self.show_welcome() and False))
        return sw

    def settings_backup(self):
        sw, box = self.s_page("Backup & Restore", "One file with all your pages, cubbies, "
                              "settings and saved layouts. (The files inside your cubbies "
                              "stay where they are and aren't copied.)")
        dlg = lambda: self._settings_dlg            # noqa: E731

        # ---- now
        sec = self.s_section(box, "Back up now")
        row = Gtk.Box(spacing=8)
        b_now = Gtk.Button(label="Back Up Now")
        b_now.set_tooltip_text("A dated copy in the backups folder (listed below)")
        b_as = Gtk.Button(label="Save a Copy As\u2026")
        b_as.set_tooltip_text("A copy anywhere you like: another drive, a USB stick, the cloud")
        b_file = Gtk.Button(label="Restore from a File\u2026")
        for b in (b_now, b_as, b_file):
            row.pack_start(b, False, False, 0)
        sec.pack_start(row, False, False, 0)
        status = Gtk.Label(xalign=0)
        status.set_line_wrap(True)
        status.get_style_context().add_class("dim-label")
        sec.pack_start(status, False, False, 2)

        # ---- automatic
        sec = self.s_section(box, "Automatic backups")
        self.s_combo(sec, "Back up automatically:", "auto_backup",
                     (("off", "Never"), ("start", "Each time Cubbies starts"),
                      ("daily", "Every day"), ("weekly", "Every week")), "off",
                     lambda _m: GLib.timeout_add_seconds(
                         2, lambda: self.backup_tick(at_start=False) and False))
        self.s_spin(sec, "Keep the newest:", "backup_keep", 3, 200, BACKUP_KEEP, "backups")
        self.s_note(sec, "An automatic backup is skipped when nothing has changed since the "
                         "newest one, so the list doesn't fill up with copies. Older backups "
                         "are deleted once there are more than you keep. The command  "
                         "cubbies --backup  makes one too (for your own schedule).")

        # ---- the list
        sec = self.s_section(box, "Recent backups")
        lst = Gtk.ListBox()
        lst.set_selection_mode(Gtk.SelectionMode.NONE)
        lst.get_style_context().add_class("cb-card")
        sec.pack_start(lst, False, False, 0)
        empty = Gtk.Label(label="No backups yet.", xalign=0)
        empty.get_style_context().add_class("dim-label")
        sec.pack_start(empty, False, False, 0)
        for w in (lst, empty):           # shown by fill() only (not by Settings' show_all)
            w.set_no_show_all(True)

        def summary(path):
            try:
                c = read_backup(path)["config"]
                n_p = len(c["pages"])
                n_c = sum(1 for p in c["pages"] for f in p["cubbies"] if not f.get("tab_of"))
                return (f"{n_p} page{'s' if n_p != 1 else ''}, "
                        f"{n_c} cubb{'ies' if n_c != 1 else 'y'}")
            except Exception:
                return "can't be read"

        def when_text(st):
            day = time.strftime("%Y-%m-%d", st)
            today = time.strftime("%Y-%m-%d")
            yday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
            label = ("Today" if day == today else "Yesterday" if day == yday
                     else time.strftime("%a %b %-d, %Y", st))
            return f"{label}, {time.strftime('%-I:%M %p', st)}"

        def fill():
            for c in lst.get_children():
                lst.remove(c)
                c.destroy()
            items = list_backups()
            empty.set_visible(not items)
            lst.set_visible(bool(items))
            for b in items:
                r = Gtk.Box(spacing=10)
                r.set_border_width(6)
                txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
                head = Gtk.Label(label=when_text(b["when"]), xalign=0)
                sub = Gtk.Label(label=f"{b['kind']} \u00b7 {summary(b['path'])}", xalign=0)
                sub.get_style_context().add_class("dim-label")
                txt.pack_start(head, False, False, 0)
                txt.pack_start(sub, False, False, 0)
                r.pack_start(txt, True, True, 0)
                rb = Gtk.Button(label="Restore\u2026")
                rb.connect("clicked", lambda _b, p=b["path"]: self.restore_from_file(
                    p, parent=dlg()) and dlg() and dlg().response(Gtk.ResponseType.CLOSE))
                db = Gtk.Button.new_from_icon_name("user-trash-symbolic", Gtk.IconSize.BUTTON)
                db.set_tooltip_text("Delete this backup")
                db.set_relief(Gtk.ReliefStyle.NONE)

                def delete(_b, b=b):
                    if confirm("Delete this backup?", f"{when_text(b['when'])} "
                               f"({b['kind'].lower()}). It can't be brought back.", "Delete"):
                        try:
                            os.remove(b["path"])
                        except OSError as exc:
                            tell("Could not delete it", str(exc))
                        fill()
                db.connect("clicked", delete)
                r.pack_start(rb, False, False, 0)
                r.pack_start(db, False, False, 0)
                lst.add(r)
            for c in lst.get_children():
                c.show_all()
        fill()
        self._backup_list_refresh = fill
        lst.connect("destroy", lambda *_a: setattr(self, "_backup_list_refresh", None))
        self.s_link(sec, "Open the backups folder",
                    lambda: (os.makedirs(BACKUP_DIR, exist_ok=True), launch(BACKUP_DIR)))

        def now(_b):
            try:
                auto_backup(self.cfg)
            except Exception as exc:
                tell("Could not back up", str(exc))
                return
            status.set_text("Backed up just now.")
            fill()

        def save_as(_b):
            path = self.backup_to_file(dlg())
            if path:
                status.set_text("Saved as " + path)
        b_now.connect("clicked", now)
        b_as.connect("clicked", save_as)
        b_file.connect("clicked", lambda _b: self.restore_from_file(parent=dlg())
                       and dlg() and dlg().response(Gtk.ResponseType.CLOSE))
        return sw
