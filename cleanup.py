#!/usr/bin/env python3
"""Cubbies clean-up, run for one user when the Cubbies package is removed.

Puts that user's desktop back the way it was: stops Cubbies, restores the original wallpaper,
moves the files Cubbies stored back onto the Desktop (nothing is deleted), and removes the
settings, the start-at-login entry and the leftover run files.

Standard library only, so it works without a display. Use --dry-run to only print the plan.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import time

DRY = "--dry-run" in sys.argv
HOME = os.path.expanduser("~")
CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"


def say(msg):
    print(("[dry run] " if DRY else "") + msg)


def xdg_dir(name, fallback):
    """A user folder such as DESKTOP from ~/.config/user-dirs.dirs."""
    try:
        with open(os.path.join(CONFIG_HOME, "user-dirs.dirs")) as fh:
            for line in fh:
                line = line.strip()
                if line.startswith(f"XDG_{name}_DIR="):
                    value = line.split("=", 1)[1].strip().strip('"')
                    value = value.replace("$HOME", HOME)
                    if value and os.path.realpath(value) != os.path.realpath(HOME):
                        return value
    except OSError:
        pass
    return os.path.join(HOME, fallback)


DESKTOP = xdg_dir("DESKTOP", "Desktop")


def protected_folders():
    out = {os.path.realpath("/"), os.path.realpath(HOME), os.path.realpath(DESKTOP)}
    for name, fb in (("DOCUMENTS", "Documents"), ("DOWNLOAD", "Downloads"), ("MUSIC", "Music"),
                     ("PICTURES", "Pictures"), ("VIDEOS", "Videos"), ("PUBLICSHARE", "Public"),
                     ("TEMPLATES", "Templates")):
        out.add(os.path.realpath(xdg_dir(name, fb)))
    return out


def stop_cubbies():
    """Stop this user's running Cubbies (never this process)."""
    me, uid = os.getpid(), os.getuid()
    found = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit() or int(entry) == me:
            continue
        try:
            if os.stat(f"/proc/{entry}").st_uid != uid:
                continue
            with open(f"/proc/{entry}/cmdline", "rb") as fh:
                args = [a.decode("utf-8", "replace") for a in fh.read().split(b"\0") if a]
        except OSError:
            continue
        if (args and os.path.basename(args[0]).startswith("python")
                and any(a.endswith("cubbies.py") for a in args[1:])):
            found.append(int(entry))
    if not found:
        return
    say(f"stop Cubbies (process {', '.join(map(str, found))})")
    if DRY:
        return
    for pid in found:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    for _ in range(20):
        if not any(os.path.exists(f"/proc/{p}") for p in found):
            break
        time.sleep(0.2)
    for pid in found:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def read_config():
    try:
        with open(os.path.join(CONFIG_HOME, "cubbies", "config.json")) as fh:
            return json.load(fh)
    except Exception:
        return {}


def gsettings_set(schema, key, value):
    """Set a desktop setting for this user. Someone who isn't logged in right now has no
    session bus, and without one the change would be silently lost, so a short private one
    is started for it (dbus-run-session)."""
    if DRY:
        return
    env = dict(os.environ)
    bus = os.path.join(RUNTIME, "bus")
    cmd = ["gsettings", "set", schema, key, value]
    if not env.get("DBUS_SESSION_BUS_ADDRESS"):
        if os.path.exists(bus):
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus}"
        elif shutil.which("dbus-run-session"):
            cmd = ["dbus-run-session", "--"] + cmd
    try:
        subprocess.run(cmd, env=env, timeout=20, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:
        print(f"could not set {schema} {key}:", exc, file=sys.stderr)


# Cubbies keeps the background values with Cinnamon's names and formats; MATE's own:
SHADE_MATE = {"horizontal": "horizontal-gradient", "vertical": "vertical-gradient"}


def uri_to_path(uri):
    from urllib.parse import unquote, urlparse
    if uri.startswith("file://"):
        return unquote(urlparse(uri).path)
    return uri


def restore_wallpaper(uri, aspect=None, desktop="cinnamon"):
    if not uri:
        return
    say(f"put your original wallpaper back ({desktop}): {uri}")
    if desktop == "mate":
        gsettings_set("org.mate.background", "picture-filename", uri_to_path(uri))
        if aspect and aspect != "none":
            gsettings_set("org.mate.background", "picture-options", aspect)
        return
    gsettings_set("org.cinnamon.desktop.background", "picture-uri", uri)
    if aspect:
        gsettings_set("org.cinnamon.desktop.background", "picture-options", aspect)


def restore_background(values, desktop="cinnamon"):
    """Put back the desktop's background colours (and shading) Cubbies' pages changed."""
    schema = "org.mate.background" if desktop == "mate" else "org.cinnamon.desktop.background"
    for key in ("primary-color", "secondary-color", "color-shading-type"):
        value = values.get(key)
        if value:
            if desktop == "mate" and key == "color-shading-type":
                value = SHADE_MATE.get(value, value)
            say(f"put the background setting {key} back ({desktop}): {value}")
            gsettings_set(schema, key, value)


def restore_desktop_links(names, desktop="cinnamon"):
    """Show again the desktop's Computer / Home / Trash / Network icons Cubbies hid."""
    keys = {"computer": "computer-icon-visible", "home": "home-icon-visible",
            "trash": "trash-icon-visible", "network": "network-icon-visible"}
    schema = "org.mate.caja.desktop" if desktop == "mate" else "org.nemo.desktop"
    for name in names:
        if name in keys:
            say(f"show the desktop's {name} icon again ({desktop})")
            gsettings_set(schema, keys[name], "true")


def restore_desktop_icons(layout, desktop="cinnamon"):
    """Quick-hide can hide the desktop icons; Cubbies puts them back when it quits, but if it
    wasn't running cleanly, do it here."""
    if layout is None:
        return
    layout = str(layout or "")
    say(f"show the desktop icons again ({desktop})")
    if desktop == "mate":
        gsettings_set("org.mate.background", "show-desktop-icons",
                      "false" if layout == "mate:false" else "true")
    else:
        gsettings_set("org.nemo.desktop", "desktop-layout",
                      "true::false" if not layout or layout.startswith("mate:") else layout)


def run_in_session(cmd):
    """Run a settings command for this user, with a session bus (a short private one when
    they aren't logged in), like gsettings_set."""
    if DRY:
        return
    env = dict(os.environ)
    bus = os.path.join(RUNTIME, "bus")
    if not env.get("DBUS_SESSION_BUS_ADDRESS"):
        if os.path.exists(bus):
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus}"
        elif shutil.which("dbus-run-session"):
            cmd = ["dbus-run-session", "--"] + cmd
    try:
        subprocess.run(cmd, env=env, timeout=20, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:
        print("could not run", cmd[0], "-", exc, file=sys.stderr)


XF_TYPES = {"s": "string", "i": "int", "u": "uint", "b": "bool", "d": "double",
            "x": "int64", "t": "uint64"}


def restore_xfce(saved):
    """Xfce: put back every xfce4-desktop value Cubbies changed (it kept the originals: a
    {"t": type, "v": value} each, or None when the property wasn't set before)."""
    if not shutil.which("xfconf-query"):
        return
    for prop, old in sorted((saved or {}).items()):
        base = ["xfconf-query", "-c", "xfce4-desktop", "-p", prop]
        if old is None:
            say(f"remove the Xfce setting {prop} again")
            run_in_session(base + ["-r"])
            continue
        t, v = old.get("t"), old.get("v")
        say(f"put the Xfce setting {prop} back: {v}")
        if t == "ad":
            cmd = base + ["-n", "-a"]
            for x in v or []:
                cmd += ["-t", "double", "-s", repr(float(x))]
            run_in_session(cmd)
        elif t in XF_TYPES:
            val = ("true" if v else "false") if t == "b" else str(v)
            run_in_session(base + ["-n", "-t", XF_TYPES[t], "-s", val])


def unique_path(folder, name):
    stem, ext = os.path.splitext(name)
    cand, n = os.path.join(folder, name), 2
    while os.path.lexists(cand):
        cand = os.path.join(folder, f"{stem} ({n}){ext}")
        n += 1
    return cand


STORE_MARK = ".cubbies-store"     # in a store folder Cubbies made itself


def made_by_cubbies(path):
    """A Computer / Trash / Network ... shortcut Cubbies wrote (not one of your files)."""
    if not path.endswith(".desktop") or not os.path.isfile(path):
        return False
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return any(line.startswith("X-Cubbies-Place=") for line in fh)
    except OSError:
        return False


def give_back_files(store, cfg, own):
    """Move the files Cubbies kept in the store folder back onto the Desktop, then remove the
    folder if it's left empty. A folder Cubbies made itself (own) gives back everything in
    it; a folder you chose that already existed gives back only what your cubbies hold, so
    nothing else of yours is moved."""
    if not os.path.isdir(store):
        return
    if os.path.realpath(store) in protected_folders():
        say(f"leave {store} alone (not a safe folder to clear)")
        return
    real = os.path.realpath(store)
    held = set()
    for page in cfg.get("pages", []):
        for f in page.get("cubbies", []):
            for p in f.get("items", []):
                rp = os.path.realpath(p)
                if os.path.dirname(rp) == real:
                    held.add(os.path.basename(rp))
    own = own or os.path.exists(os.path.join(store, STORE_MARK))
    names = sorted(n for n in os.listdir(store) if n != STORE_MARK and (own or n in held))
    say(f"move the {len(names)} item(s) Cubbies kept in {store} back to {DESKTOP}")
    if DRY:
        return
    os.makedirs(DESKTOP, exist_ok=True)
    left = 0
    for name in names:
        src = os.path.join(store, name)
        try:
            if made_by_cubbies(src):
                os.remove(src)                 # its own shortcut, not a file of yours
                continue
            shutil.move(src, unique_path(DESKTOP, name.rstrip("/")))
        except Exception as exc:
            print(f"could not move {name}: {exc}", file=sys.stderr)
            left += 1
    if left:
        print(f"left {store} in place because {left} item(s) could not be moved", file=sys.stderr)
        return
    try:
        if os.path.exists(os.path.join(store, STORE_MARK)):
            os.remove(os.path.join(store, STORE_MARK))
        os.rmdir(store)                        # only when nothing else is in it
    except OSError:
        pass


def remove(path):
    if not os.path.lexists(path):
        return
    say(f"delete {path}")
    if DRY:
        return
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
    except OSError as exc:
        print(f"could not delete {path}: {exc}", file=sys.stderr)


def main():
    stop_cubbies()
    remove(os.path.join(CONFIG_HOME, "autostart", "cubbies.desktop"))
    remove(os.path.join(RUNTIME, "cubbies.pid"))
    remove(os.path.join(RUNTIME, "cubbies.flip"))
    if not os.path.exists(os.path.join(CONFIG_HOME, "cubbies", "config.json")):
        return                  # this user never used Cubbies: nothing of theirs is touched
    cfg = read_config()
    if not isinstance(cfg, dict) or not cfg.get("pages"):
        say("the Cubbies settings can't be read: your files are left where they are")
        return
    base = dict(cfg.get("base_bg") or {})
    if cfg.get("base_wallpaper_aspect"):
        base.setdefault("picture-options", cfg["base_wallpaper_aspect"])
    aspect = base.pop("picture-options", None)
    known = [d for d in (cfg.get("desktops") or ["cinnamon"])]
    if "xfce" in known or cfg.get("xfce_base"):
        restore_xfce(cfg.get("xfce_base"))       # (holds the desktop icons' switches too)
    desktops = [d for d in known if d in ("cinnamon", "mate")]
    if "xfce" in known and not desktops:
        desktops = []
    elif not desktops:
        desktops = ["cinnamon"]
    for desktop in desktops:                     # each desktop this user ran Cubbies on
        restore_wallpaper(cfg.get("base_wallpaper"), aspect, desktop)
        restore_background(base, desktop)
        restore_desktop_links(cfg.get("hidden_links") or [], desktop)
        if "nemo_layout" in cfg:
            restore_desktop_icons(cfg.get("nemo_layout"), desktop)
    default = os.path.join(HOME, "Cubbies")
    store = cfg.get("store_dir") or default
    give_back_files(store, cfg, own=os.path.realpath(store) == os.path.realpath(default))
    if os.path.realpath(store) != os.path.realpath(default):
        give_back_files(default, cfg, own=False)  # (one left from before a move: what's held)
    remove(os.path.join(CONFIG_HOME, "cubbies"))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # never block a package removal
        print("Cubbies clean-up problem:", exc, file=sys.stderr)
    sys.exit(0)
