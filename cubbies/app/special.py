"""Recent Files, Inbox and Folder Cubbies: making and changing them."""

import os

from gi.repository import Gtk

from ..core import dbg, undoable
from ..dialogs import confirm, tell
from ..files import is_recent


class AppSpecialCubbies:
    """Recent Files, Inbox and Folder Cubbies. Part of App."""

    # -- Recent Files cubbies (one per page)
    def recent_count(self):
        try:
            return max(1, min(200, int(self.cfg.get("recent_count", 20))))
        except (TypeError, ValueError):
            return 20

    def page_recent(self, page):
        return next((f for f in page["cubbies"] if is_recent(f)), None)

    def show_one_recent_only(self, have):
        tell("This page already has a Recent Files cubby",
             f"\u201c{have['title']}\u201d already shows your recent files. Each page can "
             "have one.")

    @undoable("New Recent Files Cubby")
    def new_recent_cubby(self):
        have = self.page_recent(self.page())
        if have is not None:
            self.show_one_recent_only(have)
            return
        fdata = self.new_cubby_data(self.page(), "Recent Files", 100, 160, 320, 240)
        fdata["recent"] = True
        self.page()["cubbies"].append(fdata)
        if self.hidden:
            self.toggle_hidden()
        self.show_page()
        self.save()

    @undoable("Make Recent Files Cubby")
    def make_recent(self, pane):
        """Turn a cubby into the page's Recent Files cubby. Its own stored files go back to
        the Desktop first (after asking), since a Recent Files cubby fills itself."""
        page = self.page_of(pane)
        have = self.page_recent(page)
        if have is not None and have is not pane:
            self.show_one_recent_only(have)
            return
        if pane.get("items"):
            if not confirm("Make this a Recent Files cubby?",
                           "Its icons go back to your Desktop (links simply leave it), and "
                           "from then on it shows the files you opened lately.",
                           "Make It Recent Files"):
                return
            failed = self.release_cubby_files(pane)
            if failed:
                self.report_release_failure(failed)
                return
            pane["items"] = []
        if pane.get("folder"):
            self.stop_pane_folder(pane)
        self.set_collect(pane, [])
        pane["recent"] = True
        pane["sort"] = "manual"
        self.refresh_cubby(pane)
        win = self.find_cubby_window(pane)
        if win is not None:
            win.update_title()
        self.save()

    def clear_recent(self):
        if not confirm("Clear the recent files list?",
                       "This empties the list of recently opened files for every app (the "
                       "files themselves are not touched).", "Clear List"):
            return
        try:
            Gtk.RecentManager.get_default().purge_items()
        except Exception as exc:
            dbg("could not clear recent files:", exc)

    def watch_recent(self):
        try:
            mgr = Gtk.RecentManager.get_default()
            if not getattr(self, "_recent_watch", False):
                self._recent_watch = True

                def changed(*_a):
                    for f in self.all_cubbies():
                        if is_recent(f):
                            self.refresh_cubby(f)
                mgr.connect("changed", changed)
        except Exception as exc:
            dbg("recent files can't be watched:", exc)

    def new_inbox_cubby(self):
        """A cubby that receives every new file that lands on the Desktop (unless another
        cubby collects that kind of file)."""
        fdata = self.new_cubby_data(self.page(), "Inbox", 100, 160, 300, 220)
        self.page()["cubbies"].append(fdata)
        self.set_collect(fdata, ["other"])
        self.show_page()
        self.save()

    def new_folder_cubby(self, path=None):
        """A new cubby that shows the contents of a real folder (asks for one if none given)."""
        if path is None:
            dlg = Gtk.FileChooserDialog(title="Choose a folder to show in a new cubby",
                                        action=Gtk.FileChooserAction.SELECT_FOLDER)
            dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Show Folder", Gtk.ResponseType.OK)
            dlg.set_current_folder(os.path.expanduser("~"))
            resp = dlg.run()
            path = dlg.get_filename() if resp == Gtk.ResponseType.OK else None
            dlg.destroy()
        if not path or not os.path.isdir(path):
            return
        path = os.path.abspath(path)
        n = len([f for f in self.page()["cubbies"] if not f.get("tab_of")])
        fdata = self.new_cubby_data(self.page(), os.path.basename(path) or path,
                                    120 + 30 * (n % 6), 180 + 30 * (n % 6), 340, 260)
        fdata["folder"] = path
        fdata["sort"] = "name"
        self.page()["cubbies"].append(fdata)
        self.show_page()
        self.save()

    def set_pane_folder(self, pane, path):
        """Make an existing cubby show a folder. Its own icons are kept, just hidden."""
        if not os.path.isdir(path):
            return
        if pane["items"] and not pane.get("folder"):
            n = len(pane["items"])
            if not confirm("Show this folder in the cubby?",
                           f"The {n} icon{'s' if n != 1 else ''} in this cubby are kept, but stay "
                           "hidden while the folder is shown. \u201cCubby Type \u203a Regular Cubby\u201d "
                           "brings them back.", "Show Folder"):
                return
        pane["folder"] = path
        pane.pop("nav", None)
        if pane.get("collect"):      # a Folder Cubby is not an inbox, nor does it collect files
            self.set_collect(pane, [])
        if pane.get("sort", "manual") == "manual":
            pane["sort"] = "name"
        self.refresh_cubby(pane)
        self.save()

    def stop_pane_folder(self, pane):
        pane.pop("folder", None)
        pane.pop("nav", None)
        self.refresh_cubby(pane)
        self.save()
