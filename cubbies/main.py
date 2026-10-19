"""Starting Cubbies, or passing a command-line command to the copy already running."""

import os
import signal
import sys
import time

from gi.repository import Gdk, GLib, Gtk

from .backups import auto_backup, make_backup, read_backup, write_backup_contents
from .cli import cli_help, cli_list
from .constants import VERSION
from .core import CSS, dbg, load_config, save_config
from .layouts import apply_layout, delete_layout, layout_list, load_layout, save_layout
from .runtime import (FLIP_FILE, PID_FILE, install_autostart, running_pid, send_command,
    set_autostart)
from .app.app import App


def main():
    argv = sys.argv[1:]

    def arg_after(flag):
        i = argv.index(flag)
        rest = [a for a in argv[i + 1:] if not a.startswith("--")]
        return " ".join(rest).strip()

    def need_running(text):
        if not send_command(text):
            print("Cubbies is not running. Start it with:  cubbies")
            sys.exit(1)

    if "--help" in argv or "-h" in argv:
        print(cli_help())
        return
    if "--version" in argv:
        print("Cubbies", VERSION)
        return
    if "--install-autostart" in argv:
        install_autostart()
        return
    if "--remove-autostart" in argv:
        set_autostart(False)
        print("Autostart entry removed.")
        return
    if "--list" in argv:
        print(cli_list(load_config()))
        return
    if "--list-layouts" in argv:
        found = layout_list()
        if not found:
            print("No saved layouts yet. Save one with:  cubbies --save-layout NAME")
        for name, saved, screen in found:
            print(f"{name:<28}{saved}" + (f"   ({screen})" if screen else ""))
        return
    if "--toggle" in argv:  # hide/show all cubbies in the running instance
        pid = running_pid()
        if not pid:
            print("Cubbies is not running.")
            sys.exit(1)
        os.kill(pid, signal.SIGUSR1)
        return
    simple = {"--next-page": "next", "--prev-page": "prev", "--glance": "peek",
              "--peek": "peek",           # the old name still works
              "--hide": "cmd:hide", "--show": "cmd:show", "--refresh": "cmd:refresh",
              "--lock-all": "cmd:lock-all", "--unlock-all": "cmd:unlock-all",
              "--new-launch-bar": "cmd:new-launch-bar", "--page-bar": "cmd:page-bar",
              "--manage-pages": "cmd:manage-pages",
              "--settings": "cmd:settings", "--restart": "cmd:restart", "--quit": "cmd:quit"}
    for flag, word in simple.items():
        if flag in argv:
            if flag == "--quit" and not running_pid():
                print("Cubbies is not running.")
                return
            need_running(word)
            return
    if "--page" in argv:
        which = arg_after("--page")
        if not which:
            print("Usage: cubbies --page NUMBER|NAME")
            sys.exit(1)
        need_running("cmd:page\n" + which)
        return
    if "--new-cubby" in argv:
        need_running("cmd:new-cubby\n" + arg_after("--new-cubby"))
        return
    for flag in ("--save-layout", "--restore-layout", "--delete-layout"):
        if flag not in argv:
            continue
        name = arg_after(flag)
        if not name:
            print(f"Usage: cubbies {flag} NAME")
            sys.exit(1)
        if flag == "--delete-layout":
            if delete_layout(name):
                print(f"Layout “{name}” deleted.")
                return
            print(f"There is no layout called “{name}”.")
            sys.exit(1)
        if flag == "--restore-layout" and load_layout(name) is None:
            print(f"There is no layout called “{name}”. Saved layouts:")
            for n, saved, _s in layout_list():
                print("  ", n, " ", saved)
            sys.exit(1)
        word = "save" if flag == "--save-layout" else "restore"
        if send_command(f"cmd:{word}-layout\n{name}"):
            print(f"Layout “{name}” {'saved' if word == 'save' else 'restored'}.")
            return
        # not running: work on the saved settings directly
        cfg = load_config()
        if word == "save":
            save_layout(cfg, name)
            print(f"Layout “{name}” saved.")
        else:
            n = apply_layout(cfg, load_layout(name))
            save_config(cfg)
            print(f"Layout “{name}” restored ({n} cubbies); you'll see it when "
                  "Cubbies starts.")
        return
    if "--backup" in argv:
        dest = arg_after("--backup")
        cfg = load_config()
        if running_pid():
            # the running Cubbies saves as it goes, so its settings file is up to date
            time.sleep(0.2)
            cfg = load_config()
        try:
            path = make_backup(cfg, os.path.abspath(os.path.expanduser(dest))) if dest \
                else auto_backup(cfg)
        except Exception as exc:
            print("Could not back up:", exc)
            sys.exit(1)
        print("Backed up to", path)
        return
    if "--restore" in argv:
        src = os.path.abspath(os.path.expanduser(arg_after("--restore") or ""))
        try:
            read_backup(src)
        except ValueError as exc:
            print("Can't restore that file:", exc)
            sys.exit(1)
        if send_command("cmd:restore\n" + src):
            print("Restoring; Cubbies restarts.")
            return
        auto_backup(load_config(), "before-restore")
        write_backup_contents(read_backup(src))
        print("Restored. Start Cubbies to see it.")
        return
    pending_folders = []
    if "--add-folder" in argv:  # show folders as Folder Cubbies (used by the Nemo action)
        args = argv[argv.index("--add-folder") + 1:]
        pending_folders = [os.path.abspath(p) for p in args if os.path.isdir(p)]
        if not pending_folders:
            print("Usage: cubbies --add-folder FOLDER [FOLDER...]")
            sys.exit(1)
        if send_command("folder:" + "\n".join(pending_folders)):
            return
    unknown = [a for a in argv if a.startswith("-") and a != "--add-folder"]
    if unknown:
        print(f"Unknown command: {unknown[0]}\n")
        print(cli_help())
        sys.exit(2)
    pid = running_pid()
    if pid and pid != os.getpid():   # (after an update restart the pid is our own)
        print(f"Cubbies is already running (pid {pid}). "
              "See  cubbies --help  for what you can tell it to do.")
        return

    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    app = App()
    GLib.timeout_add(700, app.maybe_show_welcome)
    for folder in pending_folders:
        GLib.idle_add(lambda f=folder: app.new_folder_cubby(f) and False)

    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    with open(PID_FILE, "w") as fh:
        fh.write(str(os.getpid()))

    def toggle():
        app.toggle_hidden()
        return True  # keep the handler installed

    def flip():
        try:
            with open(FLIP_FILE) as fh:
                queued = fh.read()
            os.remove(FLIP_FILE)
        except OSError:
            queued = ""          # already handled with an earlier signal
        for text in queued.split("\x1e"):
            text = text.strip()
            if text:
                handle(text)
        return True

    def handle(text):
        if text.startswith("folder:"):
            for folder in text[len("folder:"):].split("\n"):
                app.new_folder_cubby(folder)
            return
        if text == "peek":
            app.toggle_on_top()
            return
        if text.startswith("cmd:"):
            name, _nl, rest = text[4:].partition("\n")
            try:
                app.run_command(name.strip(), rest.strip())
            except Exception:
                import traceback
                traceback.print_exc()
            return
        step = -1 if text == "prev" else 1
        dbg("page switch requested from the command line:", step)
        app.change_page(step, force=True)
        return

    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, toggle)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR2, flip)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, Gtk.main_quit)  # Ctrl+C works
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, Gtk.main_quit)
    try:
        Gtk.main()
    finally:
        if "nemo_layout" in app.cfg:            # never leave the desktop icons hidden
            app.set_desktop_icons(True)
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
