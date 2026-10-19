"""Folder Cubbies' folders, and asking what to do when a file already exists."""

import os
import shutil
import sys
import time

from gi.repository import GLib, Gtk

from ..core import undoable
from ..files import delete_permanently
from ..items import describe
from ..wallpapers import make_thumbnail


class FolderOps:
    """Folder Cubbies: a cubby that shows (and manages) the contents of a real folder.
    Needs: self.all_cubbies(), self.refresh_cubby(), self.save(), self.unique_path()."""

    @staticmethod
    def folder_of(pane):
        """The folder a Folder Cubby is showing right now: a sub-folder it was navigated into,
        or its own folder. (Navigating never changes the cubby's folder or its name.)"""
        root = pane.get("folder")
        nav = pane.get("nav")
        if root and nav and os.path.isdir(nav) and (
                os.path.abspath(nav) == os.path.abspath(root)
                or os.path.abspath(nav).startswith(os.path.abspath(root) + os.sep)):
            return nav
        return root

    @undoable("Move Into Folder")
    def drop_into_folder(self, target, paths):
        """Files dropped on a Folder Cubby are moved into its folder (read-only sources such
        as system launchers are copied instead)."""
        folder = os.path.abspath(self.folder_of(target))
        self.import_moved_map = {}
        if not os.path.isdir(folder):
            print("Cubbies: the folder", folder, "is not available.", file=sys.stderr)
            return
        asker = FileConflicts(self, len(paths))
        for path in paths:
            src = os.path.abspath(path)
            if os.path.dirname(src) == folder or folder == src or folder.startswith(src + os.sep):
                asker.left -= 1
                continue  # already there, or a folder dropped into itself
            try:
                # a name already taken there: ask, like the file manager does
                dest = asker.place(src, folder, copy=not os.access(os.path.dirname(src),
                                                                   os.W_OK))
                if dest is None:
                    continue
                self.import_moved_map[path] = dest
                for fdata in self.all_cubbies():
                    if path in fdata["items"]:
                        fdata["items"].remove(path)
                        self.refresh_cubby(fdata)
            except CancelFiles:
                break
            except Exception as exc:
                print("Cubbies: could not put", src, "into", folder, "-", exc, file=sys.stderr)
        self.refresh_cubby(target)
        self.save()

    def paste_into_folder(self, target, mode, paths):
        folder = self.folder_of(target)
        asker = FileConflicts(self, len(paths))
        for path in paths:
            try:
                if os.path.abspath(os.path.dirname(path.rstrip("/"))) == \
                        os.path.abspath(folder) and mode != "cut":
                    # pasting a copy into the folder it came from: a copy beside it
                    dest = self.unique_path(folder, os.path.basename(path.rstrip("/")))
                    if os.path.isdir(path) and not os.path.islink(path):
                        shutil.copytree(path, dest, symlinks=True)
                    else:
                        shutil.copy2(path, dest)
                    asker.left -= 1
                    continue
                asker.place(path, folder, copy=(mode != "cut"))
            except CancelFiles:
                break
            except Exception as exc:
                print("Cubbies: could not paste", path, "-", exc, file=sys.stderr)
        self.refresh_cubby(target)


class CancelFiles(Exception):
    """The person pressed Cancel in the file conflict window: stop the whole operation."""


class FileConflicts:
    """Asks what to do when a file of the same name is already in the folder (like the file
    manager's own window): Replace (or Merge, for two folders), Keep Both, a new name, Skip
    or Cancel, optionally for all the remaining files at once."""

    def __init__(self, app, total=1):
        self.app, self.left, self.always = app, total, None

    def place(self, src, folder, copy=False):
        """Move (or copy) src into folder, asking first if the name is taken. Returns the
        new path, or None if skipped. Raises CancelFiles."""
        self.left -= 1
        name = os.path.basename(src.rstrip("/"))
        dest = os.path.join(folder, name)
        how = None
        if os.path.lexists(dest):
            if os.path.abspath(src) == os.path.abspath(dest):
                return None
            choice = self.always or self.ask(src, dest)
            kind = choice[0]
            if kind == "cancel":
                raise CancelFiles()
            if kind == "skip":
                return None
            if kind == "both":
                dest = self.app.unique_path(folder, name)
            elif kind == "rename":
                dest = os.path.join(folder, choice[1])
                if os.path.lexists(dest):
                    dest = self.app.unique_path(folder, choice[1])
            else:
                how = kind                    # "replace" or "merge"
                if how == "merge" and not (os.path.isdir(src) and os.path.isdir(dest)
                                           and not os.path.islink(dest)):
                    how = "replace"           # (only two folders can be merged)
        app = self.app
        if how == "merge" and os.path.isdir(src) and os.path.isdir(dest) \
                and not os.path.islink(dest):
            shutil.copytree(src, dest, symlinks=True, dirs_exist_ok=True)
            app.undo_forbid()                 # (a merge can't be taken apart again)
            if not copy:
                shutil.rmtree(src)
            return dest
        if how == "replace":
            if not app.trash_path(dest):      # the old one goes to the Trash, not lost
                err = delete_permanently(dest)
                if err:
                    raise OSError(err)
                app.undo_forbid()
        if copy:
            if os.path.isdir(src) and not os.path.islink(src):
                shutil.copytree(src, dest, symlinks=True)
            else:
                shutil.copy2(src, dest)
            app.undo_note("made", dest)
        else:
            shutil.move(src, dest)
            app.undo_note("move", src, dest)
        return dest

    def ask(self, src, dest):
        folder_both = os.path.isdir(src) and os.path.isdir(dest) and not os.path.islink(dest)
        name = os.path.basename(dest)
        where = os.path.basename(os.path.dirname(dest)) or os.path.dirname(dest)
        dlg = Gtk.Dialog(title="File Conflict")
        dlg.set_resizable(False)
        dlg.set_keep_above(True)
        area = dlg.get_content_area()
        area.set_border_width(16)
        area.set_spacing(10)
        head = Gtk.Label(xalign=0)
        head.set_markup("<big><b>" + GLib.markup_escape_text(
            (f"Merge folder “{name}”?" if folder_both
             else f"Replace file “{name}”?")) + "</b></big>")
        area.pack_start(head, False, False, 0)
        sub = Gtk.Label(xalign=0)
        sub.set_line_wrap(True)
        sub.set_max_width_chars(60)
        sub.set_text((f"A folder with the same name already exists in “{where}”. "
                      "Merging puts the contents of both in one folder; files inside with "
                      "the same name are replaced.") if folder_both else
                     (f"Another file with the same name already exists in “{where}”. "
                      "Replacing it moves the old one to the Trash."))
        area.pack_start(sub, False, False, 0)
        grid = Gtk.Grid(row_spacing=10, column_spacing=12)
        grid.set_margin_top(6)
        area.pack_start(grid, False, False, 0)
        for row, (title, path) in enumerate((("Original " + ("folder" if folder_both else
                                                             "file"), dest),
                                             ("Replace with", src))):
            label, gicon, pix = describe(path, 64)
            pb = None
            if not os.path.isdir(path):
                try:
                    pb = make_thumbnail(path, 64)
                except Exception:
                    pb = None
            img = Gtk.Image.new_from_pixbuf(pb or pix) if (pb or pix) else \
                Gtk.Image.new_from_gicon(gicon, Gtk.IconSize.DIALOG)
            img.set_pixel_size(64)
            grid.attach(img, 0, row, 1, 1)
            try:
                st = os.stat(path)
                size = (f"{len(os.listdir(path))} items" if os.path.isdir(path)
                        else GLib.format_size(st.st_size))
                when = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))
            except OSError:
                size, when = "", ""
            info = Gtk.Label(xalign=0)
            info.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>\n"
                            f"Size: {GLib.markup_escape_text(size)}\n"
                            f"Last modified: {GLib.markup_escape_text(when)}")
            grid.attach(info, 1, row, 1, 1)
        nrow = Gtk.Box(spacing=8)
        nrow.pack_start(Gtk.Label(label="New name:"), False, False, 0)
        suggested = os.path.basename(self.app.unique_path(os.path.dirname(dest), name))
        entry = Gtk.Entry()
        entry.set_text(suggested)
        entry.set_width_chars(34)
        nrow.pack_start(entry, True, True, 0)
        reset = Gtk.Button(label="Reset")
        nrow.pack_start(reset, False, False, 0)
        area.pack_start(nrow, False, False, 4)
        every = Gtk.CheckButton(label="Do the same for the other conflicts")
        if self.left > 0:
            area.pack_start(every, False, False, 0)
        dlg.add_button("Cancel", 1)
        dlg.add_button("Skip", 2)
        both = dlg.add_button("Keep Both", 3)
        rep = dlg.add_button("Merge" if folder_both else "Replace", 4)
        rep.get_style_context().add_class("suggested-action")
        dlg.set_default_response(4)

        def name_changed(_e):
            typed = entry.get_text().strip()
            both.set_label("Keep Both" if typed in ("", suggested) else "Rename")
            both.set_sensitive(bool(typed) and "/" not in typed and typed != name)
        entry.connect("changed", name_changed)
        reset.connect("clicked", lambda _b: entry.set_text(suggested))
        dlg.show_all()
        resp = dlg.run()
        typed = entry.get_text().strip()
        apply_all = every.get_active()
        dlg.destroy()
        if resp == 4:
            choice = ("merge" if folder_both else "replace", None)
        elif resp == 3:
            choice = ("both", None) if typed in ("", suggested) else ("rename", typed)
        elif resp == 2:
            choice = ("skip", None)
        else:
            choice = ("cancel", None)
        if apply_all and choice[0] != "cancel":
            # (a typed name only fits this file: for the others it means "keep both")
            self.always = ("both", None) if choice[0] == "rename" else choice
        return choice
