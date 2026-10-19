"""Basics everything else uses: debug output, where the settings live, the window type
for cubbies, the shared CSS, loading and saving the config, and Undo steps."""

import functools
import gi
import json
import os

from gi.repository import Gdk, GLib


try:  # optional: lets the desktop double-click detection ask the window manager about windows
    gi.require_version("Wnck", "3.0")
    from gi.repository import Wnck  # noqa: E402
except (ValueError, ImportError):
    Wnck = None

# Set CUBBIES_DEBUG=1 to print what the desktop double-click detector is seeing.
DEBUG = bool(os.environ.get("CUBBIES_DEBUG"))


def dbg(*args):
    if DEBUG:
        print("[cubbies]", *args, flush=True)


# Cubbies' own code: the package, and the cubbies.py launcher beside it (what autostart and a
# restart run, and what the installer looks for when it stops a running copy).
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
LAUNCHER = os.path.join(os.path.dirname(PACKAGE_DIR), "cubbies.py")


def code_stamp():
    """When Cubbies' code last changed: the newest of the launcher and every module. Installing
    a new version changes it, which is how a running copy knows to restart on the new code."""
    newest = os.stat(LAUNCHER).st_mtime_ns
    for folder, _dirs, files in os.walk(PACKAGE_DIR):
        for name in files:
            if name.endswith(".py"):
                newest = max(newest, os.stat(os.path.join(folder, name)).st_mtime_ns)
    return newest


CONFIG_DIR = os.path.join(GLib.get_user_config_dir(), "cubbies")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# Window type for the cubbies. "dock" + the "keep below" state puts them in the layer just
# above the Cinnamon desktop (so clicking the desktop never buries them) and under normal
# windows, while the window manager treats them like panels, which "Show Desktop" leaves alone.
# Alternatives if your setup misbehaves:  CUBBIES_HINT=utility  or  CUBBIES_HINT=desktop
_HINTS = {
    "dock": Gdk.WindowTypeHint.DOCK,
    "utility": Gdk.WindowTypeHint.UTILITY,
    "desktop": Gdk.WindowTypeHint.DESKTOP,
}
HINT = _HINTS.get(os.environ.get("CUBBIES_HINT", "dock").lower(), Gdk.WindowTypeHint.DOCK)

CSS = b"""
window.cubbywin { background: transparent; }
.cubby-preview { background: rgba(28, 30, 38, 0.96); border-radius: 8px;
                 border: 1px solid rgba(255, 255, 255, 0.18); }
.cubby-preview label { color: white; }
.cubby-preview .head { font-weight: bold; }
.cubby-preview .dim { color: rgba(255, 255, 255, 0.6); }
.cubby-preview-row { border-radius: 4px; }
.cubby-preview-row:hover { background: rgba(255, 255, 255, 0.12); }
.cubby { background: rgba(20, 24, 36, 0.58); border-radius: 10px;
         border: 1px solid rgba(255, 255, 255, 0.20); }
.cubby-title { background: rgba(255, 255, 255, 0.14); border-radius: 10px 10px 0 0; }
.cubby-title.flipped { border-radius: 0 0 10px 10px; }
.cubby-title label { color: white; font-weight: bold; padding: 4px 10px; }
.cubby-title button { background: transparent; border: none; box-shadow: none; color: white;
                      font-weight: bold; padding: 0 10px; min-height: 0; min-width: 0; }
.cubby-title button:hover { background: rgba(255, 255, 255, 0.25); }
.cubby-title button.cubby-hover-btn { font-weight: normal; }
.cubby-title button.cubby-tab-btn { padding: 0 3px; min-height: 0; min-width: 0;
                                    font-weight: normal; font-size: 90%; }
.cubby-title button { padding: 0 6px; }
.cubby-item { border-radius: 6px; padding: 3px; border: 1px solid transparent; }
.cubby-item label { color: white; text-shadow: 1px 1px 2px black; padding: 1px 4px;
                    border-radius: 3px; }
.cubby-tab { border-radius: 6px 6px 0 0; }
.cubby-tab:hover { background: rgba(255, 255, 255, 0.15); }
.cubby-kinds-sw, .cubby-kinds-sw viewport { background: transparent; border: none;
                                           box-shadow: none; }
.cubby-kinds-sw undershoot, .cubby-kinds-sw overshoot { background: none; box-shadow: none; }
.cubby-kind { border-radius: 5px; background: rgba(255, 255, 255, 0.07); }
.cubby-kind label { font-size: 90%; }
.cubby-kind-arrow label { font-weight: bold; }
.cubby-size-panel { background-color: @theme_bg_color; border: 1px solid alpha(@theme_fg_color, 0.25);
                    border-radius: 6px; }
.cubby-heads { padding: 6px 8px 2px 8px; border-bottom: 1px solid rgba(255, 255, 255, 0.18); }
.cubby-heads label { color: white; opacity: 0.8; }
.cubby-kind:hover { background: rgba(255, 255, 255, 0.15); }
.edgehint { background: rgba(53, 132, 228, 0.60); }
window.pullstrip-win { background: transparent; }
.pullstrip { background: rgba(0, 0, 0, 0.004); }
window.newband-win { background: transparent; }
.newband { background: rgba(53, 132, 228, 0.18); border: 2px dashed rgba(255, 255, 255, 0.7);
           border-radius: 8px; }
.newband.big-enough { background: rgba(53, 132, 228, 0.35); border-style: solid; }
.newband label { color: white; font-weight: bold; text-shadow: 1px 1px 2px black; }
.cubby-grip { color: rgba(255, 255, 255, 0.6); padding: 0 4px; }
.pager { background: rgba(20, 24, 36, 0.70); border-radius: 16px;
         border: 1px solid rgba(255, 255, 255, 0.22); }
.pager label { color: white; font-weight: bold; }
.pager button { background: transparent; border: none; color: white; box-shadow: none; }
"""


def default_config():
    return {
        "page": 0,
        "welcome_shown": False,
        "pages": [{"name": "Main", "cubbies": []}],
    }


def load_config():
    try:
        with open(CONFIG_FILE) as fh:
            cfg = json.load(fh)
        if cfg.get("pages"):
            cfg["page"] = min(max(int(cfg.get("page", 0)), 0), len(cfg["pages"]) - 1)
            return cfg
    except Exception:
        pass
    return default_config()


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(cfg, fh, indent=2)
    os.replace(tmp, CONFIG_FILE)


def undoable(label):
    """Make a method one step of Undo: a snapshot of the cubbies is taken first, and the
    step is kept only if something actually changed. Steps inside steps count as one."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(self, *a, **k):
            app = self if hasattr(self, "undo_begin") else self.app
            entry = app.undo_begin(label)
            try:
                return fn(self, *a, **k)
            finally:
                app.undo_end(entry)
        return wrapper
    return deco
