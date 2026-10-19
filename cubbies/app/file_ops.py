"""Giving stored files back to the Desktop, and renaming."""

import os
import shutil
import sys

from gi.repository import GLib, Gtk

from .. import items
from ..core import undoable
from ..dialogs import ask
from ..items import describe, is_named_item


class AppFileOps:
    """Giving files back and renaming. Part of App."""

    # -- giving stored files back to the Desktop
    def release_to_desktop(self, path):
        desk = (GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DESKTOP)
                or os.path.expanduser("~/Desktop"))
        dest = self.unique_path(desk, os.path.basename(path.rstrip("/")))
        shutil.move(path, dest)
        self.undo_note("move", path, dest)

    def release_cubby_files(self, fdata):
        """Move every item this cubby keeps in the store back to the Desktop. Items that
        could not be moved stay in the cubby; returns their names."""
        failed = []
        for path in list(fdata["items"]):
            if not self.is_managed(path):
                continue
            try:
                self.release_to_desktop(path)
                fdata["items"].remove(path)
            except Exception as exc:
                print("Cubbies: could not move", path, "to the Desktop -", exc, file=sys.stderr)
                failed.append(os.path.basename(path))
        return failed

    def report_release_failure(self, failed):
        dlg = Gtk.MessageDialog(message_type=Gtk.MessageType.ERROR, text="Could not move everything to the Desktop",
                                secondary_text="Not moved: " + ", ".join(failed[:8])
                                + ("…" if len(failed) > 8 else "") + "\nNothing was deleted.",
                                buttons=Gtk.ButtonsType.OK)
        dlg.set_keep_above(True)
        dlg.run()
        dlg.destroy()

    def rename_item(self, path):
        """Rename a file or folder right where its name is shown (like the file manager)."""
        for win in self.windows.values():
            if win.get_visible() and path in win.item_widgets:
                win.edit_item_name(path)
                return
        name = ask("Rename", self.shown_name(path) if is_named_item(path)
                   else os.path.basename(path.rstrip("/")))
        if name:
            self.rename_path(path, name)

    def rename_path(self, path, name):
        """Rename the real file; every cubby showing it follows. Returns an error or None.
        Home, a drive or a place shortcut only gets a new name in Cubbies (an empty name
        brings the usual one back)."""
        if is_named_item(path):
            return self.rename_named_item(path, name)
        old_name = os.path.basename(path.rstrip("/"))
        name = name.strip()
        if not name or name == old_name:
            return None
        if "/" in name or name in (".", ".."):
            return "A name can't contain \u201c/\u201d."
        new = os.path.join(os.path.dirname(path), name)
        if os.path.lexists(new):
            return f"There is already something called \u201c{name}\u201d there."
        entry = self.undo_begin("Rename")
        try:
            os.rename(path, new)
        except OSError as exc:
            self.undo_end(entry)
            return str(exc)
        self.undo_note("move", path, new)
        for fdata in self.all_cubbies():
            for c in fdata.get("inbox_custom", []):       # nooks keep their icons
                if c.get("nook") and path in c.get("items", []):
                    c["items"][c["items"].index(path)] = new
            if path in fdata.get("items", []):
                fdata["items"][fdata["items"].index(path)] = new
                self.refresh_cubby(fdata)
            elif fdata.get("folder") and os.path.dirname(path) == self.folder_of(fdata):
                self.refresh_cubby(fdata)
            if fdata.get("nav", "").startswith(path + os.sep) or fdata.get("nav") == path:
                fdata["nav"] = new + fdata["nav"][len(path):]
        if self.clip and path in self.clip["paths"]:
            self.clip["paths"] = [new if p == path else p for p in self.clip["paths"]]
        self.save()
        self.undo_end(entry)
        return None

    def rename_named_item(self, path, name):
        name = name.strip()
        names = self.cfg.setdefault("item_names", {})
        names.pop(path, None)
        self.bind_item_names()
        usual = self.shown_name(path)              # the name it has without one of its own
        if name and name != usual:
            if "\n" in name:
                return "A name can't have more than one line."
            names[path] = name
        if not names:
            self.cfg.pop("item_names", None)
        self.save()
        for fdata in self.all_cubbies():
            if path in fdata.get("items", []):
                self.refresh_cubby(fdata)
        if getattr(self, "glance", None) is not None:
            try:
                self.glance._desc.pop(path, None)
            except Exception:
                pass
        return None

    @undoable("Move Back to Desktop")
    def move_back_to_desktop(self, fdata, path):
        link = self.link_name_of(path)
        if link:                         # Computer / Trash / Network: show the desktop's own
            self.show_desktop_link(link)
            if self.is_managed(path):        # the shortcut file itself isn't needed now
                self.trash_path(path)
            self.remove_item(fdata, path)
            return
        try:
            self.release_to_desktop(path)
        except Exception as exc:
            print("Cubbies: could not move back to the Desktop:", exc, file=sys.stderr)
            return
        self.remove_item(fdata, path)

    def bind_item_names(self):
        """describe() reads names from ITEM_NAMES: make it this config's own dict."""
        names = self.cfg.get("item_names")
        if names is None:
            names = {}
        items.ITEM_NAMES = names

    def can_rename(self, path):
        return is_named_item(path) or os.access(os.path.dirname(path) or "/", os.W_OK)

    def shown_name(self, path):
        return describe(path, 16, load_image=False)[0]
