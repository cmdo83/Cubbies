"""Saved layouts: where every cubby sits, for the menu, Settings and the command line."""

import json
import os
import time

from gi.repository import Gdk

from .core import CONFIG_DIR


# ---- saved layouts (where every cubby sits), for the menu, Settings and the command line
LAYOUT_DIR = os.path.join(CONFIG_DIR, "layouts")
LAYOUT_KEYS = ("x", "y", "w", "h", "rolled", "flip", "docked")


def _layout_file(name):
    safe = "".join(c if (c.isalnum() or c in " -_.") else "_" for c in name.strip())[:80]
    return os.path.join(LAYOUT_DIR, (safe or "layout") + ".json")


def layout_list():
    """[(name, saved time text, screen size text)], newest first."""
    out = []
    try:
        files = os.listdir(LAYOUT_DIR)
    except OSError:
        return out
    for fn in files:
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(LAYOUT_DIR, fn)) as fh:
                d = json.load(fh)
            out.append((d.get("name") or fn[:-5], d.get("saved", ""), d.get("screen", ""),
                        d.get("stamp", 0)))
        except Exception:
            continue
    out.sort(key=lambda t: t[3], reverse=True)
    return [t[:3] for t in out]


def screen_size_text():
    try:
        scr = Gdk.Screen.get_default()
        return f"{scr.get_width()}x{scr.get_height()}"
    except Exception:
        return ""


def save_layout(cfg, name):
    """Remember where every cubby is (and its size, roll-up and docking) under a name."""
    name = name.strip()
    if not name:
        raise ValueError("a layout needs a name")
    spots = {}
    for page in cfg["pages"]:
        for f in page["cubbies"]:
            spots[f["id"]] = {k: f[k] for k in LAYOUT_KEYS if k in f}
    snap = {"name": name, "saved": time.strftime("%Y-%m-%d %H:%M"), "stamp": time.time(),
            "screen": screen_size_text(), "cubbies": spots}
    os.makedirs(LAYOUT_DIR, exist_ok=True)
    path = _layout_file(name)
    with open(path + ".tmp", "w") as fh:
        json.dump(snap, fh, indent=1)
    os.replace(path + ".tmp", path)
    return path


def load_layout(name):
    for path in (_layout_file(name),):
        try:
            with open(path) as fh:
                return json.load(fh)
        except Exception:
            pass
    # match without caring about upper/lower case
    for n, _t, _s in layout_list():
        if n.casefold() == name.strip().casefold():
            try:
                with open(_layout_file(n)) as fh:
                    return json.load(fh)
            except Exception:
                pass
    return None


def apply_layout(cfg, snap):
    """Put the cubbies back where the saved layout had them. Returns how many moved.
    Cubbies made after the layout was saved are left where they are."""
    spots = snap.get("cubbies", {})
    n = 0
    for page in cfg["pages"]:
        for f in page["cubbies"]:
            spot = spots.get(f["id"])
            if not spot:
                continue
            for k in LAYOUT_KEYS:
                if k in spot:
                    f[k] = spot[k]
                elif k in ("rolled", "flip", "docked"):
                    f.pop(k, None)
            n += 1
    return n


def delete_layout(name):
    snap = load_layout(name)
    if snap is None:
        return False
    try:
        os.remove(_layout_file(snap.get("name", name)))
        return True
    except OSError:
        return False
