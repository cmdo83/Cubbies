"""Combining cubbies as tabs."""

import uuid

from ..constants import GEOMETRY_KEYS, STYLE_KEYS
from ..core import undoable


class GroupOps:
    """Combining cubbies as tabs. A cubby window ("host") is either one ordinary cubby, or a
    "group" entry that stands in for several cubbies shown as tabs. The tabs are ordinary
    cubby entries carrying `tab_of` = the group's id, so every part of the program that walks
    all cubbies (files, deleting, the store) keeps working unchanged. Needs: self.cfg,
    self.windows, self.page_of(), self.show_page(), self.save()."""

    def group_panes(self, host):
        if not host.get("group"):
            return [host]
        byid = {f["id"]: f for f in self.page_of(host)["cubbies"]}
        return [byid[i] for i in host.get("tabs", []) if i in byid]

    def active_pane(self, host):
        if not host.get("group"):
            return host
        panes = self.group_panes(host)
        for pane in panes:
            if pane["id"] == host.get("active"):
                return pane
        return panes[0] if panes else host

    def drop_window(self, host):
        win = self.windows.pop(host["id"], None)
        if win is not None:
            win.destroy()

    def merge_target_at(self, dragged, x, y):
        """The cubby whose title bar the pointer is over (ignoring the one being dragged)."""
        for win in self.windows.values():
            if win is dragged or not win.get_visible() or not win.has_title():
                continue
            wx, wy = win.get_position()
            ww, _wh = win.get_size()
            th = max(win.title_ev.get_allocated_height(), 20)
            if wx <= x < wx + ww and wy <= y < wy + th:
                return win
        return None

    def fix_group(self, group):
        """Keep a group tidy: with fewer than two tabs left it dissolves, and the last cubby
        takes over the group's place, size and look."""
        page = self.page_of(group)
        panes = self.group_panes(group)
        if len(panes) >= 2:
            group["tabs"] = [p["id"] for p in panes]
            if group.get("active") not in group["tabs"]:
                group["active"] = group["tabs"][0]
            return
        self.drop_window(group)
        if panes:
            last = panes[0]
            for key in GEOMETRY_KEYS + STYLE_KEYS:
                if key in group:
                    last[key] = group[key]
            last.pop("tab_of", None)
        page["cubbies"].remove(group)

    def repair_groups(self):
        """At start-up: drop tabs that point at nothing and groups that fell apart."""
        for page in self.cfg["pages"]:
            ids = {f["id"] for f in page["cubbies"]}
            for f in page["cubbies"]:
                if f.get("tab_of") and f["tab_of"] not in ids:
                    f.pop("tab_of")
            for group in [f for f in page["cubbies"] if f.get("group")]:
                for p in page["cubbies"]:
                    if p.get("tab_of") == group["id"] and p["id"] not in group.get("tabs", []):
                        group.setdefault("tabs", []).append(p["id"])
                group["tabs"] = [i for i in group.get("tabs", []) if i in ids]
                self.fix_group(group)

    @undoable("Combine Cubbies")
    def merge_cubbies(self, src, dst):
        """Drop cubby `src` onto cubby `dst`: they become tabs of one cubby."""
        if src is dst or src.get("tab_of") or dst.get("tab_of"):
            return
        page = self.page_of(dst)
        if dst.get("group"):
            group = dst
        else:
            group = {"id": uuid.uuid4().hex, "group": True, "title": "", "items": [],
                     "tabs": [dst["id"]], "active": dst["id"]}
            for key in GEOMETRY_KEYS + STYLE_KEYS:
                if key in dst:
                    group[key] = dst[key]
            page["cubbies"].insert(page["cubbies"].index(dst), group)
            dst["tab_of"] = group["id"]
        moved = self.group_panes(src)
        for pane in moved:
            pane["tab_of"] = group["id"]
            group["tabs"].append(pane["id"])
        if src.get("group"):
            page["cubbies"].remove(src)
        group["active"] = moved[0]["id"]
        self.drop_window(src)
        self.drop_window(dst)
        self.show_page()
        self.save()

    @undoable("Move Tab Out")
    def detach_pane(self, pane, x=None, y=None):
        """Turn a tab back into a cubby of its own (at x, y if given)."""
        gid = pane.get("tab_of")
        if not gid:
            return
        page = self.page_of(pane)
        group = next((f for f in page["cubbies"] if f["id"] == gid), None)
        if group is None:
            pane.pop("tab_of", None)
            self.show_page()
            return
        self.drop_window(group)
        group["tabs"] = [i for i in group["tabs"] if i != pane["id"]]
        if group.get("active") == pane["id"]:
            group["active"] = group["tabs"][0] if group["tabs"] else None
        gx, gy = group.get("x", 100), group.get("y", 160)
        pane["x"], pane["y"] = (gx + 30, gy + 30) if x is None else (max(0, x), max(0, y))
        pane["w"], pane["h"] = group.get("w", 300), group.get("h", 220)
        pane.pop("tab_of", None)
        pane.pop("rolled", None)
        for key in STYLE_KEYS:
            if key in group:
                pane[key] = group[key]
        if pane.get("tab_color"):           # its own tab colour becomes the cubby's colour
            pane["color"] = pane.pop("tab_color")
            pane["opacity"] = pane.pop("tab_opacity", pane.get("opacity", 0.58))
        self.fix_group(group)
        self.show_page()
        self.save()

    def remove_from_group(self, pane):
        """A tab is being deleted: take it out of its group (the caller removes the entry)."""
        gid = pane.get("tab_of")
        group = next((f for f in self.page_of(pane)["cubbies"] if f["id"] == gid), None)
        return group
