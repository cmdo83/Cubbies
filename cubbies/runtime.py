"""Start at login, and finding / talking to a Cubbies that is already running."""

import os
import signal

from gi.repository import GLib

from .core import CONFIG_DIR, LAUNCHER


AUTOSTART_FILE = os.path.expanduser("~/.config/autostart/cubbies.desktop")


def autostart_enabled():
    return os.path.exists(AUTOSTART_FILE)


def set_autostart(enabled):
    """Start Cubbies at login (a per-user autostart entry), or stop doing so."""
    if enabled:
        os.makedirs(os.path.dirname(AUTOSTART_FILE), exist_ok=True)
        with open(AUTOSTART_FILE, "w") as fh:
            fh.write("[Desktop Entry]\nType=Application\nName=Cubbies\n"
                     f"Exec=python3 \"{LAUNCHER}\"\n"
                     "X-GNOME-Autostart-enabled=true\nX-GNOME-Autostart-Delay=3\n")
    else:
        try:
            os.remove(AUTOSTART_FILE)
        except OSError:
            pass


def install_autostart():
    set_autostart(True)
    print("Autostart entry written to", AUTOSTART_FILE)


PID_FILE = os.path.join(GLib.get_user_runtime_dir() or CONFIG_DIR, "cubbies.pid")
FLIP_FILE = os.path.join(os.path.dirname(PID_FILE), "cubbies.flip")


def running_pid():
    """PID of an already-running Cubbies, or None."""
    try:
        with open(PID_FILE) as fh:
            pid = int(fh.read().strip())
        os.kill(pid, 0)
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            if b"cubbies" not in fh.read():
                return None
        return pid
    except Exception:
        return None


def send_command(text):
    """Pass a command to the running Cubbies. Returns False when it isn't running."""
    pid = running_pid()
    if not pid:
        return False
    with open(FLIP_FILE, "a") as fh:      # queued, so quick commands in a row all arrive
        fh.write(text + "\x1e")
    os.kill(pid, signal.SIGUSR2)
    return True
