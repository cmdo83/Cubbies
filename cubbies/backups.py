"""Backing up and restoring everything (dated copies, automatic backups)."""

import json
import os
import shutil
import sys
import time

from gi.repository import GLib

from .constants import VERSION
from .core import CONFIG_DIR, dbg, load_config, save_config
from .items import place_of
from .layouts import LAYOUT_DIR, _layout_file, layout_list, load_layout


BACKUP_DIR = os.path.join(CONFIG_DIR, "backups")


def make_backup(cfg, path):
    """Everything about your cubbies in one file: pages, cubbies, settings and saved layouts.
    (The files kept in the cubbies' folder are not copied; they stay where they are.)"""
    layouts = {}
    for name, _saved, _screen in layout_list():
        snap = load_layout(name)
        if snap is not None:
            layouts[name] = snap
    data = {"cubbies_backup": 1, "version": VERSION, "saved": time.strftime("%Y-%m-%d %H:%M"),
            "config": cfg, "layouts": layouts}
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path + ".tmp", "w") as fh:
        json.dump(data, fh, indent=1)
    os.replace(path + ".tmp", path)
    return path


def read_backup(path):
    """The backup's contents, or raise ValueError with a reason."""
    try:
        with open(path) as fh:
            data = json.load(fh)
    except Exception as exc:
        raise ValueError(f"It could not be read ({exc}).")
    if not isinstance(data, dict) or data.get("cubbies_backup") != 1 \
            or not isinstance(data.get("config"), dict) or not data["config"].get("pages"):
        raise ValueError("It isn't a Cubbies backup.")
    return data


def write_backup_contents(data):
    """Put a backup's settings and layouts in place (the caller restarts Cubbies)."""
    try:
        reconcile_restored_files(load_config(), data["config"])
    except Exception as exc:
        print("Cubbies: could not tidy the files for the restore -", exc, file=sys.stderr)
    cfg = data["config"]
    cfg["page"] = min(max(int(cfg.get("page", 0)), 0), len(cfg["pages"]) - 1)
    for name, snap in (data.get("layouts") or {}).items():
        try:
            os.makedirs(LAYOUT_DIR, exist_ok=True)
            with open(_layout_file(name), "w") as fh:
                json.dump(snap, fh, indent=1)
        except Exception as exc:
            print("Cubbies: could not restore layout", name, "-", exc, file=sys.stderr)
    save_config(cfg)
    return cfg


def reconcile_restored_files(old, new):
    """A backup holds the cubbies' layout, not the files. Files that went into the Cubbies
    folder after the backup was made would be held by no cubby once it's restored, so they go
    back on the Desktop (Cubbies' own place shortcuts are just removed). A file the backup's
    cubbies hold that has since gone back to the Desktop is fetched into the Cubbies folder.
    The desktop's own Computer / Home / Trash icons that either layout hid are shown again
    unless the restored cubbies hold them."""
    home = os.path.expanduser("~")
    desk = (GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DESKTOP)
            or os.path.join(home, "Desktop"))
    held = {p for page in new.get("pages", []) for f in page.get("cubbies", [])
            for p in f.get("items", [])}
    stores = []
    for c in (new, old):
        st = os.path.realpath(c.get("store_dir") or os.path.join(home, "Cubbies"))
        if st not in stores:
            stores.append(st)

    def free_name(folder, name):
        stem, ext = os.path.splitext(name)
        cand, k = os.path.join(folder, name), 2
        while os.path.lexists(cand):
            cand, k = os.path.join(folder, f"{stem} ({k}){ext}"), k + 1
        return cand
    held_real = {os.path.realpath(p) for p in held}
    for store in stores:
        try:
            names = os.listdir(store)
        except OSError:
            continue
        for name in names:
            if name.startswith("."):
                continue
            path = os.path.join(store, name)
            if path in held or os.path.realpath(path) in held_real:
                continue
            if place_of(path):
                os.remove(path)          # a Computer / Trash / Network shortcut of Cubbies'
                continue
            os.makedirs(desk, exist_ok=True)
            dest = free_name(desk, name)
            shutil.move(path, dest)
            dbg("restore: gave back", path, "->", dest)
    for p in held:
        if os.path.lexists(p) or os.path.realpath(os.path.dirname(p)) not in stores:
            continue
        back = os.path.join(desk, os.path.basename(p))
        if os.path.lexists(back):
            shutil.move(back, p)         # it went back to the Desktop since: fetch it
            dbg("restore: fetched", back, "->", p)
    hidden = list(new.get("hidden_links") or [])
    for n in old.get("hidden_links") or []:
        if n not in hidden:              # (the next start shows the ones no cubby holds)
            hidden.append(n)
    if hidden:
        new["hidden_links"] = hidden


BACKUP_KEEP = 20          # how many dated copies are kept, unless Settings says otherwise
BACKUP_KINDS = {"": "Backed up", "auto": "Automatic", "before-restore": "Before a restore"}


def backup_keep(cfg):
    try:
        return max(3, min(200, int(cfg.get("backup_keep", BACKUP_KEEP))))
    except (TypeError, ValueError):
        return BACKUP_KEEP


def auto_backup(cfg, tag=""):
    """A dated copy in the backups folder; only the newest few are kept (Settings › Backup
    & Restore says how many, 20 at first)."""
    base = time.strftime("cubbies-%Y-%m-%d-%H%M%S") + (f"-{tag}" if tag else "")
    name, n = base + ".json", 2
    while os.path.exists(os.path.join(BACKUP_DIR, name)):    # two in the same second
        name, n = f"{base}-{n}.json", n + 1
    path = make_backup(cfg, os.path.join(BACKUP_DIR, name))
    try:
        old = sorted(f for f in os.listdir(BACKUP_DIR) if f.endswith(".json"))
        for f in old[:-backup_keep(cfg)]:
            os.remove(os.path.join(BACKUP_DIR, f))
    except OSError:
        pass
    return path


def list_backups():
    """The dated copies in the backups folder, newest first:
    [{"path", "when" (time.struct_time), "kind" (a word for people), "tag"}]."""
    out = []
    try:
        names = os.listdir(BACKUP_DIR)
    except OSError:
        return out
    for fn in names:
        if not (fn.startswith("cubbies-") and fn.endswith(".json")):
            continue
        stem = fn[len("cubbies-"):-len(".json")]
        try:
            when = time.strptime(stem[:17], "%Y-%m-%d-%H%M%S")
        except ValueError:
            continue
        tag = stem[18:]
        while tag[-1:].isdigit() and "-" in tag:            # (-2, -3: same-second copies)
            tag = tag.rsplit("-", 1)[0]
        if tag.isdigit():
            tag = ""
        out.append({"path": os.path.join(BACKUP_DIR, fn), "when": when, "tag": tag,
                    "kind": BACKUP_KINDS.get(tag, tag.replace("-", " ").capitalize())})
    out.sort(key=lambda b: time.mktime(b["when"]), reverse=True)
    return out


def backup_unchanged(cfg):
    """True when the newest backup already holds exactly these settings (an automatic
    backup then has nothing new to keep)."""
    newest = list_backups()
    if not newest:
        return False
    try:
        with open(newest[0]["path"]) as fh:
            old = json.load(fh).get("config")
        return json.dumps(old, sort_keys=True) == json.dumps(cfg, sort_keys=True)
    except Exception:
        return False
