"""Pages: showing, adding, moving, renaming and deleting them, and Manage Pages."""

import sys
import uuid

from gi.repository import Gdk, GLib, Gtk

from ..core import dbg, undoable
from ..dialogs import ask, confirm
from ..edge_puller import EdgePuller
from ..page_order import PageOrder
from ..widgets import make_window
from ..cubby.cubby import Cubby


class AppPages:
    """Pages. Part of App."""

    def show_page(self):
        # "If hidden, show my cubbies when switching pages"
        last = getattr(self, "_shown_page", None)
        if (last is not None and last != self.cfg["page"] and self.hidden
                and self.setting("unhide_on_switch")):
            self.hidden = False
            self.cfg["hidden"] = False
        self._shown_page = self.cfg["page"]
        self.apply_title_colour()
        self.swap_page_positions()
        hosts = [f for f in self.page()["cubbies"] if not f.get("tab_of")]
        # cubbies marked "Show on Every Page" (they live on their own page, shown on all)
        hosts += [f for p in self.cfg["pages"] if p is not self.page()
                  for f in p["cubbies"] if f.get("all_pages") and not f.get("tab_of")]
        hosts = [f for f in hosts if not f.get("launchbar")]
        bar = self.bar_for_page(self.page())      # this page's launch bar (it may live on
        if bar is not None and not bar.get("tab_of"):    # another page)
            hosts.append(bar)
        visible = {f["id"] for f in hosts}
        stays = {f["id"] for f in hosts if f.get("keep_visible")}
        for fid, win in self.windows.items():
            if fid not in visible or (self.hidden and fid not in stays):
                win.hide()
        if True:
            for fdata in hosts:
                if self.hidden and fdata["id"] not in stays:
                    continue        # quick-hide leaves out the cubbies marked to stay
                win = self.windows.get(fdata["id"])
                if win is None:
                    win = Cubby(self, fdata)
                    self.windows[fdata["id"]] = win
                win.show_all()
                win.sync_roll()  # show_all() re-shows the parts a rolled-up cubby hides
                win.ah_on_top()  # its one layer: the desktop (or, auto-hiding, the top)
                win.move(*win.home_pos())
        self.autohide_start()
        self.pager.update()
        self.pager.flash()   # with auto-hide on, show the pager briefly after a page change
        self.apply_wallpaper()
        if self.puller is None:
            try:
                self.puller = EdgePuller(self)
            except Exception as exc:
                print("Cubbies: the page edges could not be set up:", exc, file=sys.stderr)
                self.puller = False
        if self.puller:
            self.puller.update()

    def open_page_order(self, mode="order", toggle=False):
        """Page bar menu › Manage Pages… (mode "order"), or Ctrl + Up: the page chooser
        (mode "pick"). With toggle, the same key closes it again."""
        po = getattr(self, "page_order", None)
        if po is not None and po.mode != mode:       # the other one is open: swap
            po.close()
            po = None
        if po is not None:
            if toggle:
                po.close()
            else:
                po.present()
            return
        self.page_order = PageOrder(self, mode)

    def settings_css(self):
        """Settings' own look (section headings with their dividing lines, cards...): loaded
        once, so pieces of Settings shown elsewhere (Manage Pages › the gear) look the same."""
        if getattr(self, "_settings_css", None) is None:
            css = Gtk.CssProvider()
            try:
                css.load_from_data(self.SETTINGS_CSS)
                Gtk.StyleContext.add_provider_for_screen(
                    Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
                self._settings_css = css
            except GLib.Error as exc:
                dbg("settings css:", exc)

    def open_page_settings(self, page=None, tab=0):
        """Manage Pages, with a page's settings open beside its picture (its gear)."""
        page = page if page is not None else self.page()
        po = getattr(self, "page_order", None)
        if po is not None:
            po.close()
        self.page_order = PageOrder(self, "order")
        po = self.page_order
        if page in po.order:
            po.settings_tab = tab
            po._settings_after_focus = True
            po.open_focus(page)

    def own_positions(self, fdata):
        """An every-page cubby that has its own place on each page."""
        return bool(fdata.get("all_pages") and not fdata.get("same_place"))

    def swap_page_positions(self):
        """An every-page cubby keeps a place per page (`page_pos` {page id: [x, y]}); its
        x and y are always its place on the page shown (`pos_page`). Switching pages puts
        the old place away and takes out the new one (a page it hasn't been moved on yet
        gets the place it had on the page before)."""
        pid = self.page_id(self.page())
        for f in self.all_cubbies():
            if f.get("tab_of") or not self.own_positions(f):
                continue
            was = f.get("pos_page")
            if was == pid:
                continue
            pos = f.setdefault("page_pos", {})
            if was:
                pos[was] = [int(f.get("x", 0)), int(f.get("y", 0))]
            if pid in pos:
                f["x"], f["y"] = pos[pid]
            f["pos_page"] = pid

    def position_on_page(self, fdata, page):
        """Where an every-page cubby is on a page (for pictures of pages)."""
        if self.own_positions(fdata):
            pid = page.get("pid")
            if pid and pid != fdata.get("pos_page") and pid in fdata.get("page_pos", {}):
                return tuple(fdata["page_pos"][pid])
        return fdata.get("x", 0), fdata.get("y", 0)

    @undoable("Re-order Pages")
    def move_page(self, src, dst):
        """Put page number src at number dst (the others shift). The page you're on stays
        the page you're on; nothing else about the pages changes."""
        pages = self.cfg["pages"]
        if not (0 <= src < len(pages)) or src == dst:
            return
        dst = max(0, min(dst, len(pages) - 1))
        here = pages[self.cfg["page"]]
        order = list(range(len(pages)))
        page = pages.pop(src)
        pages.insert(dst, page)
        order.insert(dst, order.pop(src))
        self.cfg["page"] = pages.index(here)
        pending = getattr(self, "_desk_pending", None)   # new desktop files: page numbers
        if pending:
            for path, idx in list(pending.items()):
                if isinstance(idx, int) and idx in order:
                    pending[path] = order.index(idx)
        self.save()
        self.pager.update()
        if getattr(self, "on_pages_reordered", None):
            self.on_pages_reordered()
        dbg("page moved:", src, "->", dst)

    def page_id(self, page):
        """A page's lasting id (names can change), made the first time it's needed."""
        if not page.get("pid"):
            page["pid"] = uuid.uuid4().hex[:10]
        return page["pid"]

    def change_page(self, step, force=False):
        if not self.setting("pages_enabled"):
            return
        now = GLib.get_monotonic_time()
        if not force and now - self._last_flip < 250_000:  # debounce touchpads / fast wheels
            return
        self._last_flip = now
        n = len(self.cfg["pages"])
        dest = (self.cfg["page"] + step) % n
        if dest == self.cfg["page"]:
            return
        if (self.setting("animate_pages") and self.puller
                and self.puller.slide_to(dest, "right" if step > 0 else "left")):
            return                       # slides across, then shows the page
        self.cfg["page"] = dest
        self.show_page()
        self.save()

    # -- pages
    def new_page(self):
        name = ask("Name for the new page", f"Page {len(self.cfg['pages']) + 1}")
        if not name:
            return
        page = {"name": name, "cubbies": []}
        self.cfg["pages"].append(page)
        self.cfg["page"] = len(self.cfg["pages"]) - 1
        self.show_page()
        self.save()

    _edge_win = None

    def show_edge_hint(self, side):
        """A coloured strip along the left/right screen edge while a cubby is dragged there."""
        win = self._edge_win
        if side is None:
            if win is not None and win.get_visible():
                win.hide()
            return
        if win is None:
            win = self._edge_win = make_window("edgehint")
            win.set_keep_above(True)
        scr = Gdk.Screen.get_default()
        sw, sh = scr.get_width(), scr.get_height()
        win.set_default_size(10, sh)
        win.resize(10, sh)
        win.show_all()
        win.move(0 if side == "left" else sw - 10, 0)

    def insert_page_beside(self, side, auto=False):
        """A new empty page just left or right of the current one; returns its index.
        `auto`: made by dragging a cubby to the screen edge, so it goes away again by itself
        if the cubby is taken back off it and it is left empty."""
        pages = self.cfg["pages"]
        cur = self.cfg["page"]
        idx = cur + 1 if side == "right" else cur
        page = {"name": f"Page {len(pages) + 1}", "cubbies": []}
        if auto:
            page["auto"] = True
        pages.insert(idx, page)
        return idx

    @undoable("Move to Page")
    def move_cubby_to_edge(self, host, side, carry=None):
        """A cubby was taken to the left/right screen edge: it moves to the page on that side,
        which is created (named "Page N", empty) when there is none yet. With `carry` (the
        cubby's own window, still held by the pointer) that window is kept and stays under the
        pointer; otherwise it is let go and arrives on the side it came from."""
        try:
            pages = self.cfg["pages"]
            src = self.page_of(host)
            cur = pages.index(src)
            if side == "right":
                dest_i = cur + 1
                if dest_i >= len(pages):
                    self.cfg["page"] = cur
                    dest_i = self.insert_page_beside("right", auto=True)
            else:
                dest_i = cur - 1
                if dest_i < 0:
                    self.cfg["page"] = cur
                    dest_i = self.insert_page_beside("left", auto=True)
            dest = pages[dest_i]
            if dest is src:
                return False
            entries = [host] + [f for f in src["cubbies"] if f.get("tab_of") == host["id"]]
            for entry in entries:
                src["cubbies"].remove(entry)
                dest["cubbies"].append(entry)
            if src.get("auto") and not src["cubbies"] and len(pages) > 1:
                pages.remove(src)          # a page only made by dragging, now empty again
                dest_i = pages.index(dest)
                dbg("removed the empty page made by dragging:", src["name"])
            width = Gdk.Screen.get_default().get_width()
            if carry is None:
                self.drop_window(host)
                # it arrives on the side it came from, like sliding in from the next page over
                host["x"] = 40 if side == "right" else max(0, width - host.get("w", 300) - 40)
            # (still in the hand: the caller keeps it under the pointer where it was held)
            self.cfg["page"] = dest_i
            self.show_page()
            if carry is not None:
                try:
                    carry.get_window().raise_()   # above the new page's cubbies while held
                except Exception:
                    pass
            self.save()
            dbg("moved cubby to page", dest_i, "on the", side)
        except Exception:
            import traceback
            print("Cubbies: could not move the cubby to another page:", file=sys.stderr)
            traceback.print_exc()
        return False

    def key_page_step(self, step):
        """Ctrl+Left / Ctrl+Right. Where a page exists it switches to it. At the last page in
        that direction, pressing the key twice (not holding it) makes a new empty page there.
        Ctrl+Up (step 0) opens the page chooser (or closes it again)."""
        pages = self.cfg["pages"]
        if not self.setting("pages_enabled"):
            return
        if step == 0:
            GLib.idle_add(lambda: self.open_page_order("pick", toggle=True) and False)
            return
        if 0 <= self.cfg["page"] + step < len(pages):
            self._key_dir = 0
            self.change_page(step)
            return
        if not self.setting("newpage_keys"):   # off unless ticked in Settings
            self._key_dir = 0
            self.pager.flash(1500)
            return
        now = GLib.get_monotonic_time() / 1e6
        gap = now - getattr(self, "_key_t", 0.0)
        same = getattr(self, "_key_dir", 0) == step
        self._key_dir = step
        if same and gap < 0.12:        # key held down: repeats do not count as a second press
            self._key_t = now
            return
        if same and gap <= 0.45:
            self._key_dir, self._key_t = 0, 0.0
            self.cfg["page"] = self.insert_page_beside("right" if step > 0 else "left")
            self.show_page()
            self.save()
            return
        self._key_t = now
        self.pager.flash(1500)         # nothing further that way: show the page bar as a hint

    def rename_page(self, page=None, name=None):
        """Rename a page (the one shown if none is given). Without a name, ask for one."""
        page = page if page is not None else self.page()
        if name is None:
            name = ask("Rename page", page["name"])
        name = (name or "").strip()
        if name and name != page.get("name"):
            page["name"] = name
            page.pop("auto", None)            # named by hand: it is a real page now
            self.pager.update()
            self.save()

    def delete_page_note(self, page):
        """What deleting a page does, in a line (for the question asked first)."""
        count = sum(1 for fd in page["cubbies"]
                    if not (fd.get("all_pages") or (fd.get("launchbar") and any(
                        p is not page for p in self.bar_covers(fd))))
                    for p in fd["items"] if self.is_managed(p))
        note = "All of its cubbies are deleted."
        if count:
            note += (f" The {count} item{'s' if count != 1 else ''} they store in "
                     f"{self.store_dir()} will be moved back to your Desktop.")
        return note

    @undoable("Delete Page")
    def delete_page(self, page=None, ask_first=True):
        """Delete a page (the one shown if none is given). With ask_first, a question first;
        Manage Pages asks its own question and passes ask_first=False."""
        if len(self.cfg["pages"]) <= 1:
            return False
        page = page if page is not None else self.page()
        if page not in self.cfg["pages"]:
            return False
        if ask_first and not confirm(f"Delete the page \u201c{page['name']}\u201d?",
                                     self.delete_page_note(page), "Delete Page"):
            return False
        # launch bars also shown on other pages, and cubbies shown on every page, move to
        # another page instead of going with this one
        keep = [f for f in page["cubbies"] if f.get("all_pages") or (
            f.get("launchbar") and any(p is not page for p in self.bar_covers(f)))]
        if keep:
            other = next(p for p in self.cfg["pages"] if p is not page)
            for f in keep:
                page["cubbies"].remove(f)
                other["cubbies"].append(f)
                for t in self.group_panes(f) if f.get("group") else []:
                    if t in page["cubbies"]:
                        page["cubbies"].remove(t)
                        other["cubbies"].append(t)
        failed = []
        for fdata in page["cubbies"]:
            failed += self.release_cubby_files(fdata)
        if failed:
            for fdata in page["cubbies"]:
                self.refresh_cubby(fdata)
            self.save()
            self.report_release_failure(failed)
            return False
        here = self.page()
        gone = self.cfg["pages"].index(page)
        self.cfg["pages"].remove(page)
        for f in self.launch_bars():           # forget the deleted page in bar page lists
            if page.get("pid") in f.get("bar_pages", []):
                f["bar_pages"].remove(page["pid"])
        for fdata in page["cubbies"]:
            win = self.windows.pop(fdata["id"], None)
            if win:
                win.destroy()
        if here is page:                       # the page shown: show the one before it
            self.cfg["page"] = max(0, gone - 1)
        else:                                  # another page: stay on the one shown
            self.cfg["page"] = self.cfg["pages"].index(here)
        self.show_page()
        self.save()
        return True
