"""The system's own file menu items: Nemo actions, file-manager actions, Nemo scripts,
Open With and Properties."""

import os
import shutil
import sys

from gi.repository import Gio, GLib

from .core import dbg
from .desktop_env import IS_MATE, IS_XFCE


# ---- the system's own file menu items: Nemo actions, Nemo scripts, Open With, Properties
# Nemo's real right-click menu can't be borrowed by another program, so the same sources it
# builds from are read here: every machine then shows its own apps, actions and scripts.
NEMO_ACTION_DIRS = None


def load_uca_actions():
    """Thunar's custom actions (~/.config/Thunar/uca.xml, else the system's copy), as dicts
    with "kind": "uca"."""
    import xml.etree.ElementTree as ET
    path = None
    for d in [GLib.get_user_config_dir()] + list(GLib.get_system_config_dirs()):
        f = os.path.join(d, "Thunar", "uca.xml")
        if os.path.isfile(f):
            path = f
            break
    if path is None:
        return []
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return []
    langs = [lang.split(".")[0] for lang in GLib.get_language_names()]
    lang_key = "{http://www.w3.org/XML/1998/namespace}lang"
    out = []
    for a in root.iter("action"):
        def text(tag):
            best = None
            for e in a.findall(tag):
                lang = e.get(lang_key)
                if lang is None and best is None:
                    best = e.text
                elif lang in langs[:1]:
                    return (e.text or "").strip()
            return (best or "").strip()
        name, cmd = text("name"), text("command")
        if not name or not cmd:
            continue
        types = {t for t in ("directories", "audio-files", "image-files", "other-files",
                             "text-files", "video-files") if a.find(t) is not None}
        out.append({"kind": "uca", "file": path, "dir": os.path.dirname(path), "name": name,
                    "comment": text("description"), "exec": cmd, "icon": text("icon"),
                    "patterns": [x.strip() for x in (text("patterns") or "*").split(";")
                                 if x.strip()],
                    "types": types, "range": text("range"), "terminal": False})
    return out


def uca_action_visible(act, paths, mime_of=None):
    """Whether Thunar would offer this custom action for these selected files."""
    import fnmatch
    n = len(paths)
    if n == 0:
        return False
    rng = act.get("range") or ""
    if rng:
        lo, _sep, hi = rng.partition("-")
        try:
            if lo and lo != "*" and n < int(lo):
                return False
            if hi and hi != "*" and n > int(hi):
                return False
        except ValueError:
            pass
    mime_of = mime_of or file_mime
    for p in paths:
        base = os.path.basename(p).lower()
        if not any(fnmatch.fnmatch(base, g.lower()) for g in act["patterns"]):
            return False
        if os.path.isdir(p):
            if "directories" not in act["types"]:
                return False
            continue
        kind = (mime_of(p) or "").split("/")[0]
        group = {"audio": "audio-files", "image": "image-files", "text": "text-files",
                 "video": "video-files"}.get(kind, "other-files")
        if group not in act["types"] and "other-files" not in act["types"]:
            return False
    return True


def uca_action_command(act, paths):
    q = GLib.shell_quote
    first = paths[0] if paths else ""
    uris = [Gio.File.new_for_path(p).get_uri() for p in paths]
    table = {"%f": q(first), "%F": " ".join(q(p) for p in paths),
             "%u": q(uris[0]) if uris else "", "%U": " ".join(q(u) for u in uris),
             "%d": q(os.path.dirname(first)), "%D": " ".join(q(os.path.dirname(p)) for p in paths),
             "%n": q(os.path.basename(first)),
             "%N": " ".join(q(os.path.basename(p)) for p in paths), "%%": "%"}
    text, out, i = act["exec"], [], 0
    while i < len(text):
        tok = text[i:i + 2]
        if tok in table:
            out.append(table[tok])
            i += 2
        else:
            out.append(text[i])
            i += 1
    return "".join(out).strip()


def nemo_action_dirs():
    sub = ("file-manager", "actions") if IS_MATE else ("nemo", "actions")
    dirs = [os.path.join(GLib.get_user_data_dir(), *sub)]
    dirs += [os.path.join(d, *sub) for d in GLib.get_system_data_dirs()]
    out = []
    for d in dirs:
        if os.path.isdir(d) and d not in out:
            out.append(d)
    return out


def nemo_disabled_actions():
    if IS_MATE:
        return set()
    try:
        src = Gio.SettingsSchemaSource.get_default()
        if src and src.lookup("org.nemo.plugins", True):
            return set(Gio.Settings.new("org.nemo.plugins").get_strv("disabled-actions"))
    except Exception:
        pass
    return set()


def load_nemo_actions(dirs=None, disabled=None):
    """Every active .nemo_action (the user's own first, like Nemo), as dicts."""
    if IS_XFCE and dirs is None:
        return load_uca_actions()
    dirs = nemo_action_dirs() if dirs is None else dirs
    disabled = nemo_disabled_actions() if disabled is None else disabled
    seen, out = set(), []
    for d in dirs:
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for name in names:
            ext = ".desktop" if IS_MATE else ".nemo_action"
            if not name.endswith(ext) or name in seen:
                continue
            seen.add(name)          # a user's copy hides the system one of the same name
            if name in disabled:
                continue
            if IS_MATE:
                act = parse_fm_action(os.path.join(d, name))
            else:
                act = parse_nemo_action(os.path.join(d, name))
            if act:
                out.append(act)
    return out


def parse_nemo_action(path):
    kf = GLib.KeyFile()
    try:
        kf.load_from_file(path, GLib.KeyFileFlags.NONE)
    except Exception:
        return None
    grp = "Nemo Action"
    if not kf.has_group(grp):
        return None

    def get(key, default=None, loc=False):
        try:
            if loc:
                return kf.get_locale_string(grp, key, None)
            return kf.get_string(grp, key)
        except Exception:
            return default

    def get_list(key):
        raw = get(key, "") or ""
        return [x.strip() for x in raw.split(";") if x.strip()]

    if (get("Active", "true") or "true").strip().lower() == "false":
        return None
    name, execl = get("Name", loc=True), get("Exec")
    if not name or not execl:
        return None
    sel = (get("Selection", "s") or "s").strip().lower()
    return {"file": path, "dir": os.path.dirname(path), "name": name,
            "comment": get("Comment", "", loc=True) or "", "exec": execl,
            "icon": get("Icon-Name", "") or "", "selection": sel,
            "extensions": [e.lower() for e in get_list("Extensions")],
            "mimetypes": get_list("Mimetypes"), "conditions": get_list("Conditions"),
            "dependencies": get_list("Dependencies"), "files": get_list("Files"),
            "locations": get_list("Locations"),
            "separator": get("Separator", None), "quote": (get("Quote", "") or "").lower(),
            "terminal": (get("Terminal", "false") or "").strip().lower() == "true",
            "uri_scheme": get("UriScheme", None)}


def parse_fm_action(path):
    """A Caja action (the caja-actions add-on's file-manager/actions/*.desktop files), as a
    dict like parse_nemo_action's, with "kind": "fm". Only the first profile is used."""
    kf = GLib.KeyFile()
    try:
        kf.load_from_file(path, GLib.KeyFileFlags.NONE)
    except Exception:
        return None
    top = "Desktop Entry"

    def get(grp, key, default=None, loc=False):
        try:
            if loc:
                return kf.get_locale_string(grp, key, None)
            return kf.get_string(grp, key)
        except Exception:
            return default

    def get_list(grp, key, default=""):
        raw = get(grp, key, default) or ""
        return [x.strip() for x in raw.split(";") if x.strip()]

    if (get(top, "Type", "Action") or "Action").strip() != "Action":
        return None                         # a menu of actions: not shown
    if (get(top, "Enabled", "true") or "true").strip().lower() == "false" or \
            (get(top, "Hidden", "false") or "").strip().lower() == "true":
        return None
    if (get(top, "TargetContext", "true") or "true").strip().lower() == "false":
        return None                         # only for the folder background, not for files
    name = get(top, "Name", loc=True)
    profiles = get_list(top, "Profiles")
    grp = next((f"X-Action-Profile {pr}" for pr in profiles
                if kf.has_group(f"X-Action-Profile {pr}")), None)
    if not name or grp is None:
        return None
    execl = get(grp, "Exec") or ""
    if not execl:
        path_, params = get(grp, "Path", ""), get(grp, "Parameters", "")
        execl = (path_ + " " + params).strip()
    if not execl:
        return None
    schemes = get_list(grp, "Schemes", "file")
    return {"kind": "fm", "file": path, "dir": os.path.dirname(path), "name": name,
            "comment": get(top, "Tooltip", "", loc=True) or "", "exec": execl,
            "icon": get(top, "Icon", "") or "",
            "count": (get(grp, "SelectionCount", "") or "").replace(" ", ""),
            "mimetypes": get_list(grp, "MimeTypes", "*"),
            "basenames": get_list(grp, "Basenames", "*"),
            "folders": get_list(grp, "Folders", "/"),
            "schemes": schemes,
            "terminal": (get(grp, "ExecutionMode", "") or "").lower().startswith("terminal")}


def fm_action_visible(act, paths, mime_of=None):
    """Whether Caja would offer this action for these selected files."""
    import fnmatch
    n = len(paths)
    if n == 0:
        return False
    cnt = act["count"]
    if cnt:
        op, num = cnt[0], cnt.lstrip("<>=")
        try:
            num = int(num)
        except ValueError:
            num = None
        if num is not None:
            if op == "<" and not n < num or op == ">" and not n > num or \
                    op == "=" and n != num:
                return False
    if not any(s in ("file", "*") for s in act["schemes"]):
        return False
    mime_of = mime_of or file_mime

    def matches(specs, test):
        allow = [x for x in specs if not x.startswith("!")]
        deny = [x[1:] for x in specs if x.startswith("!")]
        return (not allow or any(test(a) for a in allow)) and not any(test(d) for d in deny)

    for p in paths:
        base = os.path.basename(p)
        if not matches(act["basenames"], lambda g: fnmatch.fnmatch(base, g)):
            return False
        parent = os.path.dirname(p)
        if not matches(act["folders"], lambda f: f == "/" or parent == f.rstrip("/")
                       or parent.startswith(f.rstrip("/") + os.sep) or fnmatch.fnmatch(parent, f)):
            return False
        is_dir = os.path.isdir(p)

        def mime_ok(m, p=p, is_dir=is_dir):
            if m in ("*", "*/*", "all/all"):
                return True
            if m == "all/allfiles":
                return not is_dir
            if m == "inode/directory":
                return is_dir
            return _mime_is(mime_of(p), m)
        if not matches(act["mimetypes"], mime_ok):
            return False
    return True


def fm_action_command(act, paths):
    """The command line for a Caja action, with its % codes filled in."""
    q = GLib.shell_quote
    uris = [Gio.File.new_for_path(p).get_uri() for p in paths]
    first = paths[0] if paths else ""
    base = os.path.basename(first)
    table = {
        "%f": q(first), "%F": " ".join(q(p) for p in paths),
        "%u": q(uris[0]) if uris else "", "%U": " ".join(q(u) for u in uris),
        "%b": q(base), "%B": " ".join(q(os.path.basename(p)) for p in paths),
        "%d": q(os.path.dirname(first)),
        "%D": " ".join(q(os.path.dirname(p)) for p in paths),
        "%w": q(os.path.splitext(base)[0]),
        "%W": " ".join(q(os.path.splitext(os.path.basename(p))[0]) for p in paths),
        "%x": q(os.path.splitext(base)[1].lstrip(".")),
        "%c": str(len(paths)), "%s": "file", "%h": "", "%n": "", "%p": "", "%%": "%",
        "%m": q(file_mime(first)) if first else "",
    }
    text, out, i = act["exec"], [], 0
    while i < len(text):
        tok = text[i:i + 2]
        if tok in table:
            out.append(table[tok])
            i += 2
        else:
            out.append(text[i])
            i += 1
    return "".join(out).strip()


def _dep_ok(dep):
    neg = dep.startswith("!")
    dep = dep.lstrip("!").strip()
    have = os.path.exists(dep) if dep.startswith("/") else bool(shutil.which(dep))
    return have != neg


def _dbus_has(name):
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        res = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
                            "org.freedesktop.DBus", "NameHasOwner",
                            GLib.Variant("(s)", (name,)), GLib.VariantType("(b)"),
                            Gio.DBusCallFlags.NONE, 300, None)
        return bool(res.unpack()[0])
    except Exception:
        return False


def _pattern_ok(specs, paths, use_parent=False):
    """Nemo's Files= / Locations= keys: ;-separated names or globs, "!" forbids."""
    if not specs:
        return True
    import fnmatch
    allow = [x for x in specs if not x.startswith("!")]
    deny = [x[1:] for x in specs if x.startswith("!")]
    for p in paths:
        p = os.path.dirname(p) if use_parent else p
        name = os.path.basename(p)

        def hit(spec):
            test = p if spec.startswith("/") else name
            if any(c in spec for c in "*?["):
                return fnmatch.fnmatchcase(test, spec)
            return test.endswith(spec) or p == spec
        if allow and not any(hit(a) for a in allow):
            return False
        if any(hit(d) for d in deny):
            return False
    return True


def nemo_action_visible(act, paths, mime_of=None):
    """Whether Nemo would show this action for these selected files (not on the desktop)."""
    if act.get("kind") == "fm":
        return fm_action_visible(act, paths, mime_of)
    if act.get("kind") == "uca":
        return uca_action_visible(act, paths, mime_of)
    n = len(paths)
    sel = act["selection"]
    ok = {"s": n == 1, "single": n == 1, "m": n > 1, "multiple": n > 1,
          "notnone": n > 0, "any": True, "none": n == 0}.get(sel)
    if ok is None:
        ok = sel.isdigit() and n == int(sel)
    if not ok or n == 0:
        return False
    if not all(_dep_ok(d) for d in act["dependencies"]):
        return False
    for cond in act["conditions"]:
        if cond == "desktop" or cond == "removable":
            return False           # only shown for the desktop itself / removable drives
        if cond.startswith("dbus "):
            if not _dbus_has(cond.split(None, 1)[1].strip()):
                return False
        elif cond.startswith("exec "):
            if not _exec_condition(act, cond.split(None, 1)[1], paths):
                return False
        else:
            return False           # gsettings and anything else: not checked here, so hidden
    if act.get("uri_scheme") and act["uri_scheme"].strip() != "file":
        return False
    if not _pattern_ok(act["locations"], paths, use_parent=True):
        return False
    if not _pattern_ok(act["files"], paths):
        return False
    exts, mimes = act["extensions"], act["mimetypes"]
    if exts == ["any"]:
        return True
    mime_of = mime_of or file_mime
    for p in paths:
        fn = os.path.basename(p).lower()
        is_dir = os.path.isdir(p)
        match = False
        for e in exts:
            if (e == "dir" and is_dir) or (e == "none" and "." not in fn) \
                    or (e == "nodirs" and not is_dir) \
                    or (e not in ("dir", "none", "nodirs") and fn.endswith(e)):
                match = True
                break
        if not match and mimes:
            ctype = mime_of(p)
            match = any(_mime_is(ctype, m) for m in mimes)
        if not match:
            return False
    return True


def _mime_is(ctype, want):
    if not ctype:
        return False
    if want in ("*", "*/*"):
        return True
    if want.endswith("/*"):
        return ctype.split("/")[0] == want[:-2] or Gio.content_type_is_a(ctype, want)
    return ctype == want or Gio.content_type_is_a(ctype, want)


def file_mime(path):
    try:
        info = Gio.File.new_for_path(path).query_info("standard::content-type", 0, None)
        return info.get_content_type() or ""
    except Exception:
        return ""


def _shell_escape(text):
    """Like Nemo's eel_str_escape_shell_characters: a backslash before shell specials."""
    out = []
    for ch in text:
        if ch in " \t\n'\"`$\\!*?&;|<>()[]{}#~":
            out.append("\\")
        out.append(ch)
    return "".join(out)


def nemo_action_command(act, paths, exec_str=None):
    """The command line Nemo would run for this action (tokens filled in)."""
    if act.get("kind") == "fm" and exec_str is None:
        return fm_action_command(act, paths)
    if act.get("kind") == "uca" and exec_str is None:
        return uca_action_command(act, paths)
    quote = {"single": "'", "double": '"', "backtick": "`"}.get(act.get("quote"), "")

    def esc(text):
        if quote == '"':
            return text.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
        if quote == "'":
            return text.replace("'", "'\\''")
        return _shell_escape(text)

    sep = act.get("separator") if act.get("separator") is not None else " "
    parent = os.path.dirname(paths[0]) if paths else os.path.expanduser("~")
    uris = [Gio.File.new_for_path(p).get_uri() for p in paths]
    first = os.path.basename(paths[0]) if paths else ""
    table = {
        "%F": sep.join(quote + esc(p) + quote for p in paths),
        "%U": sep.join(quote + u + quote for u in uris),
        "%P": quote + esc(parent) + quote,
        "%R": quote + Gio.File.new_for_path(parent).get_uri() + quote,
        "%f": first, "%N": first, "%p": os.path.basename(parent),
        "%e": os.path.splitext(first)[0], "%D": "", "%X": "0", "%%": "%",
    }
    text = act["exec"] if exec_str is None else exec_str
    out, i = [], 0
    while i < len(text):
        tok = text[i:i + 2]
        if tok in table:
            out.append(table[tok])
            i += 2
        else:
            out.append(text[i])
            i += 1
    cmd = "".join(out).strip()
    if cmd.startswith("<") and cmd.endswith(">"):       # a script next to the action file
        cmd = act["dir"] + os.sep + cmd[1:-1]
    return cmd


def _exec_condition(act, cond, paths):
    try:
        import subprocess
        cmd = nemo_action_command(act, paths, exec_str=cond)
        return subprocess.run(GLib.shell_parse_argv(cmd)[1], timeout=2,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    except Exception:
        return False


def run_nemo_action(act, paths):
    cmd = nemo_action_command(act, paths)
    dbg("action:", act["name"], "->", cmd)
    try:
        if act.get("terminal"):
            argv = GLib.shell_parse_argv(cmd)[1]
            term = shutil.which("x-terminal-emulator") or shutil.which("gnome-terminal")
            if term:
                GLib.spawn_async([term, "-e"] + [" ".join(GLib.shell_quote(a) for a in argv)],
                                 flags=GLib.SpawnFlags.DEFAULT)
                return
        GLib.spawn_command_line_async(cmd)
    except Exception as exc:
        print("Cubbies: could not run the action", act["name"], "-", exc, file=sys.stderr)


def nemo_scripts(folder=None):
    """[(name, path, children)] from ~/.local/share/nemo/scripts, or Caja's ~/.config/caja/
    scripts (folders become submenus)."""
    if IS_XFCE and folder is None:
        return []                  # Thunar has no scripts folder (custom actions instead)
    folder = folder or (os.path.join(GLib.get_user_config_dir(), "caja", "scripts") if IS_MATE
                        else os.path.join(GLib.get_user_data_dir(), "nemo", "scripts"))
    out = []
    try:
        names = sorted(os.listdir(folder), key=str.casefold)
    except OSError:
        return out
    for name in names:
        if name.startswith("."):
            continue
        full = os.path.join(folder, name)
        if os.path.isdir(full):
            kids = nemo_scripts(full)
            if kids:
                out.append((name, full, kids))
        elif os.access(full, os.X_OK):
            out.append((name, full, None))
    return out


def run_nemo_script(script, paths):
    env = dict(os.environ)
    pre = "CAJA" if IS_MATE else "NEMO"
    env[pre + "_SCRIPT_SELECTED_FILE_PATHS"] = "".join(p + "\n" for p in paths)
    env[pre + "_SCRIPT_SELECTED_URIS"] = "".join(Gio.File.new_for_path(p).get_uri() + "\n"
                                                 for p in paths)
    env[pre + "_SCRIPT_CURRENT_URI"] = Gio.File.new_for_path(
        os.path.dirname(paths[0]) if paths else os.path.expanduser("~")).get_uri()
    try:
        import subprocess
        subprocess.Popen([script] + paths, cwd=os.path.dirname(paths[0]) if paths else None,
                         env=env, start_new_session=True)
    except Exception as exc:
        print("Cubbies: could not run the script", script, "-", exc, file=sys.stderr)


def show_properties(paths):
    """The file manager's own Properties window (Nemo answers this standard request)."""
    uris = [Gio.File.new_for_path(p).get_uri() for p in paths]
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call("org.freedesktop.FileManager1", "/org/freedesktop/FileManager1",
                 "org.freedesktop.FileManager1", "ShowItemProperties",
                 GLib.Variant("(ass)", (uris, "")), None, Gio.DBusCallFlags.NONE, 5000,
                 None, None, None)
    except Exception as exc:
        print("Cubbies: could not open Properties:", exc, file=sys.stderr)


def show_in_folder(paths):
    uris = [Gio.File.new_for_path(p).get_uri() for p in paths]
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call("org.freedesktop.FileManager1", "/org/freedesktop/FileManager1",
                 "org.freedesktop.FileManager1", "ShowItems",
                 GLib.Variant("(ass)", (uris, "")), None, Gio.DBusCallFlags.NONE, 5000,
                 None, None, None)
    except Exception as exc:
        print("Cubbies: could not show the folder:", exc, file=sys.stderr)
