"""Cubbies: adding icons, new cubbies, default looks, moving and deleting them."""

import uuid

from gi.repository import GLib

from ..constants import BLUR_KEYS, BUTTON_KEYS, DEFAULT_BORDER_COLOR, DEFAULT_RADIUS, SHARE_PARTS
from ..core import dbg, undoable
from ..dialogs import confirm
from ..files import is_recent


class AppCubbies:
    """Cubbies. Part of App."""

    def restyle_all(self):
        for win in self.windows.values():
            win.apply_style()

    # -- cubbies
    def find_cubby_window(self, fdata):
        return self.windows.get(fdata.get("tab_of") or fdata["id"])

    def refresh_cubby(self, fdata):
        win = self.find_cubby_window(fdata)
        if win:
            win.refresh()

    @undoable("Add Icons")
    def add_items(self, target, paths, index=None):
        """Add paths to a cubby (moving them out of other cubbies); index = position, None = end."""
        if is_recent(target):
            dbg("a Recent Files cubby fills itself; nothing added")
            return
        if target.get("folder"):
            self.drop_into_folder(target, paths)
            return
        before = list(paths)
        paths = self.import_paths(paths)
        self.import_moved_map = dict(zip(before, paths))
        for path in paths:
            for fdata in self.page()["cubbies"]:
                if fdata is not target and path in fdata["items"]:
                    fdata["items"].remove(path)
                    self.refresh_cubby(fdata)
        items = target["items"]
        pos = len(items) if index is None else index
        for path in paths:
            if path in items:
                old = items.index(path)
                items.remove(path)
                if old < pos:
                    pos -= 1
            pos = min(max(pos, 0), len(items))
            items.insert(pos, path)
            pos += 1
        self.refresh_cubby(target)
        self.save()

    # -- per-desktop default look for new cubbies
    def page_of(self, fdata):
        for page in self.cfg["pages"]:
            if fdata in page["cubbies"]:
                return page
        return self.page()

    def page_index_of(self, fdata):
        page = self.page_of(fdata)
        return self.cfg["pages"].index(page)

    def new_cubby_data(self, page, title, x, y, w, h):
        """A new cubby's data, starting with the page's default look (if it has one)."""
        fdata = {"id": uuid.uuid4().hex, "title": title, "x": x, "y": y, "w": w, "h": h,
                 "items": []}
        for key, val in page.get("defaults", {}).items():
            if val not in (None, "") and key not in BLUR_KEYS:   # (blur: followed live)
                fdata[key] = val
        return fdata

    def set_page_default(self, page, key, value):
        defaults = page.setdefault("defaults", {})
        if value in (None, ""):
            defaults.pop(key, None)
        else:
            defaults[key] = value
        if not defaults:
            page.pop("defaults", None)
        self.save()

    def look_of(self, fdata):
        """A cubby's look: colour, opacity, corner roundness, and the title font/height if set."""
        look = {"color": fdata.get("color", "rgb(20,24,36)"),
                "opacity": fdata.get("opacity", 0.58),
                "radius": fdata.get("radius", DEFAULT_RADIUS)}
        for key in ("title_font", "title_height"):
            if fdata.get(key):
                look[key] = fdata[key]
        if fdata.get("border_width"):
            look["border_width"] = fdata["border_width"]
            look["border_color"] = fdata.get("border_color") or DEFAULT_BORDER_COLOR
        return look

    def clear_page_default(self, page):
        if page.pop("defaults", None) is not None:
            self.save()

    def use_cubby_style_as_default(self, fdata):
        """Make this cubby's look the default for new cubbies on its page."""
        page = self.page_of(fdata)
        defaults = self.look_of(fdata)
        page["defaults"] = defaults
        self.save()
        dbg("default look for", page["name"], "set from cubby", fdata["title"], defaults)

    @undoable("Share Look")
    def apply_look_parts(self, src, parts, pages):
        """Give the cubbies on these pages the chosen parts of src's look; everything else
        about them stays. Tabs follow their tabbed cubby; launch bars are left alone (they
        have their own settings). Returns how many cubbies changed."""
        keys = [k for key, _l, ks in SHARE_PARTS if key in parts for k in ks]
        n = 0
        for page in pages:
            for f in page["cubbies"]:
                if f is src or f.get("tab_of") or f.get("launchbar"):
                    continue
                for k in keys:
                    if k == "title_align" and f.get("group"):
                        continue
                    if k == "tab_font" and not f.get("group"):
                        continue
                    if k in src:
                        f[k] = src[k]
                    else:
                        f.pop(k, None)
                if keys:
                    n += 1
                win = self.windows.get(f["id"])
                if win is not None:
                    win.apply_style()
                    win.apply_title_size()
                    win.queue_draw()
        self.save()
        return n

    def apply_appearance_to_page(self, page, color, opacity, title_font=None, title_height=None,
                                 radius=DEFAULT_RADIUS, extra=None):
        """Give every cubby on this page the same look (other pages are not touched)."""
        for fdata in page["cubbies"]:
            fdata["color"], fdata["opacity"], fdata["radius"] = color, opacity, radius
            for key in ("border_width", "border_color") + BLUR_KEYS + BUTTON_KEYS:
                fdata.pop(key, None)
            fdata.update(extra or {})
            for key, val in (("title_font", title_font), ("title_height", title_height)):
                if val:
                    fdata[key] = val
                else:
                    fdata.pop(key, None)
            win = self.windows.get(fdata["id"])
            if win:
                win.apply_style()

    def remove_item(self, fdata, path):
        if path in fdata["items"]:
            fdata["items"].remove(path)
            self.refresh_cubby(fdata)
            self.save()

    def item_target(self, page):
        """The cubby on a page that can receive moved icons (not a group, not a Folder Cubby)."""
        return next((f for f in page["cubbies"]
                     if not f.get("group") and not f.get("folder")), None)

    @undoable("Move to Page")
    def move_item_to_page(self, path, from_cubby, page_index):
        dest = self.item_target(self.cfg["pages"][page_index])
        if dest is None:
            return
        if path in from_cubby["items"]:
            from_cubby["items"].remove(path)
            self.refresh_cubby(from_cubby)
        if path not in dest["items"]:
            dest["items"].append(path)
        self.refresh_cubby(dest)
        self.save()

    @undoable("New Cubby")
    def new_cubby(self, title=None):
        fdata = self.new_cubby_data(self.page(), title or "New Cubby", 100, 160, 300, 220)
        self.page()["cubbies"].append(fdata)
        self.show_page()
        self.save()
        win = self.windows.get(fdata["id"])
        if win is not None and not title:        # name it right in its title bar
            GLib.timeout_add(250, lambda: win.edit_title() and False)

    @undoable("Delete Cubby")
    def delete_group(self, group):
        """Delete a tabbed cubby and all its tabs (stored files go back to the Desktop)."""
        panes = self.group_panes(group)
        managed = sum(1 for p in panes for i in p["items"] if self.is_managed(i))
        note = (f"All {len(panes)} tabs are deleted. ")
        note += (f"The {managed} item{'s' if managed != 1 else ''} stored in {self.store_dir()} "
                 "will be moved back to your Desktop." if managed else
                 "Folder views and links only disappear; no files are touched.")
        names = ", ".join(p["title"] for p in panes)
        if not confirm(f"Delete the tabbed cubby \u201c{names}\u201d?", note, "Delete Cubby"):
            return
        failed = []
        for pane in panes:
            failed += self.release_cubby_files(pane)
        if failed:
            for pane in panes:
                self.refresh_cubby(pane)
            self.save()
            self.report_release_failure(failed)
            return
        page = self.page_of(group)
        for pane in panes:
            if pane in page["cubbies"]:
                page["cubbies"].remove(pane)
        page["cubbies"].remove(group)
        win = self.windows.pop(group["id"], None)
        if win:
            win.destroy()
        self.save()

    @undoable("Delete Cubby")
    def pages_showing(self, fdata):
        """Names of the pages a cubby shows on (more than one: every-page cubbies and
        launch bars shared by several pages)."""
        pages = self.cfg["pages"]
        if fdata.get("launchbar"):
            return [p["name"] for p in pages if self.bar_for_page(p) is fdata]
        if fdata.get("all_pages"):
            return [p["name"] for p in pages]
        page = self.page_of(fdata)
        return [page["name"]] if page else []

    def delete_cubby(self, fdata):
        managed = [p for p in fdata["items"] if self.is_managed(p)]
        others = len(fdata["items"]) - len(managed)
        is_tab = bool(fdata.get("tab_of"))
        if managed:
            note = (f"The {len(managed)} item{'s' if len(managed) != 1 else ''} stored in "
                    f"{self.store_dir()} will be moved back to your Desktop.")
            if others:
                note += " Links to items stored elsewhere simply leave the cubby."
        elif fdata.get("folder"):
            note = ("Only this view of the folder is removed. The folder and the files in it "
                    "are not touched.")
        elif others:
            note = "Its icons are only links, so the files themselves are not touched."
        else:
            note = "The cubby is empty."
        what = "tab" if is_tab else "cubby"
        host = next((f for f in self.all_cubbies() if f["id"] == fdata.get("tab_of")),
                    None) if is_tab else None
        shown = self.pages_showing(host or fdata)
        if len(shown) > 1:
            names = ", ".join(f"\u201c{n}\u201d" for n in shown)
            note = (f"This {what} is on {len(shown)} pages: {names}. Deleting it takes it off "
                    f"every one of them.\n\n") + note
        if not confirm(f"Delete the {what} \u201c{fdata['title']}\u201d?", note,
                       "Delete Tab" if is_tab else "Delete Cubby"):
            return
        failed = self.release_cubby_files(fdata)
        if failed:
            self.refresh_cubby(fdata)
            self.save()
            self.report_release_failure(failed)
            return
        page = self.page_of(fdata)
        group = self.remove_from_group(fdata) if is_tab else None
        page["cubbies"].remove(fdata)
        if group is not None:
            self.drop_window(group)
            group["tabs"] = [i for i in group["tabs"] if i != fdata["id"]]
            if group.get("active") == fdata["id"]:
                group["active"] = group["tabs"][0] if group["tabs"] else None
            self.fix_group(group)
            self.show_page()
        else:
            win = self.windows.pop(fdata["id"], None)
            if win:
                win.destroy()
        self.save()
