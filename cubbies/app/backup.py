"""Backing up and restoring, from the running program."""

import os
import shutil
import time

from gi.repository import GLib, Gtk

from ..backups import (BACKUP_DIR, auto_backup, backup_unchanged, list_backups, make_backup,
    read_backup, write_backup_contents)
from ..core import dbg, load_config
from ..dialogs import confirm, tell
from ..cubby.cubby import Cubby


class AppBackup:
    """Backup and restore. Part of App."""

    # -- backing up and restoring everything
    BACKUP_EVERY = {"daily": 24 * 3600, "weekly": 7 * 24 * 3600}

    def backup_tick(self, at_start=True):
        """Automatic backups (Settings › Backup & Restore): when Cubbies starts, every day or
        every week; skipped when nothing has changed since the newest backup."""
        try:
            mode = self.cfg.get("auto_backup", "off")
            due = False
            if mode == "start":
                due = at_start
            elif mode in self.BACKUP_EVERY:
                autos = [b for b in list_backups() if b["tag"] == "auto"]
                last = time.mktime(autos[0]["when"]) if autos else 0
                due = time.time() - last >= self.BACKUP_EVERY[mode]
            if due and not backup_unchanged(self.cfg):
                path = auto_backup(self.cfg, "auto")
                dbg("automatic backup:", path)
                refresh = getattr(self, "_backup_list_refresh", None)
                if refresh:
                    refresh()
        except Exception as exc:          # never let the timer die
            dbg("automatic backup failed:", repr(exc))
        return False

    def backup_tick_repeat(self):
        self.backup_tick(at_start=False)
        return True

    def backup_now(self):
        try:
            path = auto_backup(self.cfg)
        except Exception as exc:
            tell("Could not back up", str(exc))
            return
        dbg("backed up to", path)
        notify = shutil.which("notify-send")
        if notify:
            Cubby.spawn([notify, "-i", "document-save", "Cubbies backed up",
                         "Saved in " + BACKUP_DIR])
        else:
            tell("Backed up", "Saved as " + path)

    def backup_to_file(self, parent=None):
        dlg = Gtk.FileChooserDialog(title="Back Up Cubbies", action=Gtk.FileChooserAction.SAVE,
                                    transient_for=parent)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Back Up", Gtk.ResponseType.OK)
        dlg.set_do_overwrite_confirmation(True)
        dlg.set_current_folder(GLib.get_home_dir())
        dlg.set_current_name(time.strftime("cubbies-backup-%Y-%m-%d.json"))
        resp = dlg.run()
        path = dlg.get_filename() if resp == Gtk.ResponseType.OK else None
        dlg.destroy()
        if not path:
            return None
        try:
            make_backup(self.cfg, path)
        except Exception as exc:
            tell("Could not back up", str(exc))
            return None
        return path

    def restore_from_file(self, path=None, parent=None, ask_first=True):
        if path is None:
            dlg = Gtk.FileChooserDialog(title="Restore Cubbies from a Backup",
                                        action=Gtk.FileChooserAction.OPEN, transient_for=parent)
            dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Restore", Gtk.ResponseType.OK)
            flt = Gtk.FileFilter()
            flt.set_name("Cubbies backups")
            flt.add_pattern("*.json")
            dlg.add_filter(flt)
            dlg.set_current_folder(BACKUP_DIR if os.path.isdir(BACKUP_DIR)
                                   else GLib.get_home_dir())
            resp = dlg.run()
            path = dlg.get_filename() if resp == Gtk.ResponseType.OK else None
            dlg.destroy()
            if not path:
                return False
        try:
            data = read_backup(path)
        except ValueError as exc:
            tell("Can't restore that file", str(exc))
            return False
        pages = len(data["config"]["pages"])
        cubbies = sum(1 for p in data["config"]["pages"] for f in p["cubbies"]
                      if not f.get("tab_of"))
        if ask_first and not confirm(
                "Restore this backup?",
                f"From {data.get('saved', 'an unknown date')}: {pages} page"
                f"{'s' if pages != 1 else ''}, {cubbies} cubb{'ies' if cubbies != 1 else 'y'}. "
                "Your cubbies, pages and settings are replaced by the backup's, and Cubbies "
                "restarts. (A copy of how things are now is kept in the backups folder first.)",
                "Restore"):
            return False
        try:
            auto_backup(self.cfg, "before-restore")
        except Exception as exc:
            dbg("could not keep a copy before restoring:", exc)
        write_backup_contents(data)
        self.cfg = load_config()
        self.bind_item_names()
        dbg("restored from", path, "- restarting")
        if "nemo_layout" in self.cfg:
            self.set_desktop_icons(True)
        GLib.idle_add(lambda: self.run_command("restart") and False)
        return True
