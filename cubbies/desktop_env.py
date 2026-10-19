"""Which desktop Cubbies runs on (Cinnamon, MATE or Xfce) and how to talk to its own
settings: wallpaper and desktop icons."""

import os
import shutil

from gi.repository import Gdk, Gio, GLib

from .core import Wnck, dbg


# ---- which desktop Cubbies runs on. Cinnamon (Nemo draws the desktop) or MATE (Caja does).
# Everything that talks to the desktop's own settings, file manager or wallpaper asks these.
def detect_desktop():
    forced = (os.environ.get("CUBBIES_DESKTOP") or "").strip().lower()
    if forced in ("cinnamon", "mate", "xfce"):
        return forced
    names = [n.strip().lower() for n in (os.environ.get("XDG_CURRENT_DESKTOP") or "").split(":")]
    if any(n in ("x-cinnamon", "cinnamon") for n in names):
        return "cinnamon"
    if "mate" in names:
        return "mate"
    if "xfce" in names:
        return "xfce"
    src = Gio.SettingsSchemaSource.get_default()

    def has(schema):
        return bool(src and src.lookup(schema, True))
    if has("org.cinnamon.desktop.background"):
        return "cinnamon"
    if has("org.mate.background"):
        return "mate"
    if shutil.which("xfdesktop"):
        return "xfce"
    return "cinnamon"


DESKTOP = detect_desktop()
IS_MATE = DESKTOP == "mate"
IS_XFCE = DESKTOP == "xfce"
DESKTOP_NAME = {"mate": "MATE", "xfce": "Xfce"}.get(DESKTOP, "Cinnamon")
FILE_MANAGER = {"mate": "caja", "xfce": "thunar"}.get(DESKTOP, "nemo")
# where people find things in their own desktop's settings (for the help texts)
SHORTCUTS_PLACE = {"mate": "Control Center \u203a Keyboard Shortcuts",
                   "xfce": "Settings Manager \u203a Keyboard \u203a Application Shortcuts"}.get(
    DESKTOP, "System Settings \u203a Keyboard \u203a Shortcuts")
SHORTCUTS_SHORT = {"mate": "Keyboard Shortcuts",
                   "xfce": "Keyboard \u203a Application Shortcuts"}.get(DESKTOP,
                                                                   "Keyboard \u203a Shortcuts")
BACKGROUNDS_PLACE = {"mate": "Control Center \u203a Appearance \u203a Background",
                     "xfce": "Settings Manager \u203a Desktop \u203a Background"}.get(
    DESKTOP, "System Settings \u203a Backgrounds")
DESKTOP_ICONS_PLACE = {"mate": "MATE Tweak \u203a Desktop",
                       "xfce": "Settings Manager \u203a Desktop \u203a Icons"}.get(
    DESKTOP, "System Settings \u203a Desktop")


def settings_schema(name):
    src = Gio.SettingsSchemaSource.get_default()
    return Gio.Settings.new(name) if src and src.lookup(name, True) else None


class MateBackground:
    """MATE's wallpaper settings (org.mate.background) answering with Cinnamon's key names and
    values, so the rest of Cubbies needn't care: picture-uri is a file path there, and the
    gradients are called "horizontal-gradient" / "vertical-gradient"."""
    SHADE_OUT = {"horizontal-gradient": "horizontal", "vertical-gradient": "vertical"}
    SHADE_IN = {"horizontal": "horizontal-gradient", "vertical": "vertical-gradient"}

    def __init__(self, settings):
        self.s = settings

    @staticmethod
    def _path(raw):
        raw = (raw or "").replace("${prefix}", "/usr")
        return raw

    def get_string(self, key):
        if key == "picture-uri":
            path = self._path(self.s.get_string("picture-filename"))
            return Gio.File.new_for_path(path).get_uri() if path else ""
        value = self.s.get_string(key)
        if key == "color-shading-type":
            return self.SHADE_OUT.get(value, value)
        return value

    def set_string(self, key, value):
        if key == "picture-uri":
            path = Gio.File.new_for_uri(value).get_path() if value else ""
            return self.s.set_string("picture-filename", path or "")
        if key == "color-shading-type":
            value = self.SHADE_IN.get(value, value)
        if key == "picture-options" and value == "none":
            return True                    # MATE has no "No picture" setting
        return self.s.set_string(key, value)

    def __getattr__(self, name):            # connect(), get_boolean() ...
        return getattr(self.s, name)


class Xfconf:
    """Xfce's settings store (xfconfd), over D-Bus. Every value Cubbies changes is remembered
    first (XFCONF_REMEMBER), so uninstalling can put the desktop back exactly."""
    CH = "xfce4-desktop"
    _bus = None

    @classmethod
    def call(cls, method, params, rtype):
        if cls._bus is None:
            cls._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        return cls._bus.call_sync("org.xfce.Xfconf", "/org/xfce/Xfconf", "org.xfce.Xfconf",
                                  method, params, GLib.VariantType(rtype) if rtype else None,
                                  Gio.DBusCallFlags.NONE, 3000, None)

    @classmethod
    def raw(cls, prop, channel=None):
        """The property's value as a GLib.Variant, or None when it isn't set."""
        try:
            return cls.call("GetProperty", GLib.Variant("(ss)", (channel or cls.CH, prop)),
                            "(v)").get_child_value(0).get_variant()
        except Exception:
            return None

    @classmethod
    def get(cls, prop, default=None, channel=None):
        v = cls.raw(prop, channel)
        return default if v is None else v.unpack()

    @classmethod
    def all(cls, base, channel=None):
        try:
            res = cls.call("GetAllProperties",
                           GLib.Variant("(ss)", (channel or cls.CH, base)), "(a{sv})")
            return res.unpack()[0]
        except Exception:
            return {}

    @classmethod
    def set(cls, prop, value, channel=None):
        """value: a GLib.Variant of the right type (i, u, b, s, or av of d)."""
        hook = XFCONF_REMEMBER[0]
        if hook is not None:
            hook(prop, cls.raw(prop, channel))
        try:
            cls.call("SetProperty", GLib.Variant("(ssv)", (channel or cls.CH, prop, value)), None)
            return True
        except Exception as exc:
            dbg("xfconf: could not set", prop, "-", exc)
            return False

    @classmethod
    def watch(cls, callback, prefix="/backdrop"):
        if cls._bus is None:
            cls._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

        def on_signal(_c, _s, _o, _i, _n, params):
            ch, prop = params.unpack()[:2]
            if ch == cls.CH and prop.startswith(prefix):
                callback()
        return cls._bus.signal_subscribe(None, "org.xfce.Xfconf", "PropertyChanged",
                                         "/org/xfce/Xfconf", None, Gio.DBusSignalFlags.NONE,
                                         on_signal)


XFCONF_REMEMBER = [None]     # App.remember_xfconf, once the app is running


def variant_to_saved(v):
    """A GLib.Variant as something JSON can keep: {"t": type, "v": value} (None = not set)."""
    if v is None:
        return None
    t = v.get_type_string()
    if t == "av":
        return {"t": "ad", "v": [float(x) for x in v.unpack()]}
    return {"t": t, "v": v.unpack()}


def _hex_to_rgba(code):
    try:
        c = Gdk.RGBA()
        if c.parse(code):
            return GLib.Variant("av", [GLib.Variant("d", x) for x in
                                       (c.red, c.green, c.blue, 1.0)])
    except Exception:
        pass
    return None


class XfceBackground:
    """Xfce's wallpaper settings (xfconf channel xfce4-desktop, one set per monitor and
    workspace under /backdrop/screen0/monitorNAME/workspaceN/) answering with Cinnamon's key
    names and values. Cubbies' pages aren't workspaces, so a page's wallpaper goes to every
    monitor and every workspace xfdesktop keeps."""
    ASPECT = {"none": 0, "centered": 1, "wallpaper": 2, "stretched": 3, "scaled": 4, "zoom": 5,
              "spanned": 6}
    SHADE = {"solid": 0, "horizontal": 1, "vertical": 2}
    KEYS = {"picture-uri": "last-image", "picture-options": "image-style",
            "color-shading-type": "color-style", "primary-color": "rgba1",
            "secondary-color": "rgba2"}

    @staticmethod
    def monitor_names():
        """The monitors' output names (Virtual-1, HDMI-1 ...), as xfdesktop names them."""
        out = []
        display = Gdk.Display.get_default()
        for i in range(display.get_n_monitors() if display else 0):
            m = display.get_monitor(i)
            name = m.get_model() or ""
            try:
                scr = Gdk.Screen.get_default()
                plug = scr.get_monitor_plug_name(i)
                if plug:
                    name = plug
            except Exception:
                pass
            if name and name not in out:
                out.append(name)
        return out

    @classmethod
    def targets(cls):
        """Every monitor + workspace folder xfdesktop could be reading the wallpaper from:
        the ones already set, and each connected monitor on each workspace (a system's
        default settings may only name monitors that aren't there, like "monitor0")."""
        props = Xfconf.all("/backdrop")
        dirs = {k.rsplit("/", 1)[0] for k in props if k.endswith("/last-image")}
        n_ws = 1
        try:
            if Wnck is not None:
                scr = Wnck.Screen.get_default()
                scr.force_update()
                n_ws = max(1, scr.get_workspace_count())
        except Exception:
            pass
        for name in cls.monitor_names():
            for ws in range(n_ws):
                dirs.add(f"/backdrop/screen0/monitor{name}/workspace{ws}")
        return sorted(dirs) or ["/backdrop/screen0/monitor0/workspace0"]

    def main_dir(self):
        dirs = self.targets()
        names = self.monitor_names()
        for name in names[:1]:
            want = f"/backdrop/screen0/monitor{name}/workspace0"
            if Xfconf.raw(want + "/last-image") is not None:
                return want
        props = Xfconf.all("/backdrop")
        for d in dirs:
            if d + "/last-image" in props:
                return d
        return dirs[0]

    def get_string(self, key):
        prop = self.main_dir() + "/" + self.KEYS.get(key, key)
        v = Xfconf.get(prop)
        if key == "picture-uri":
            return Gio.File.new_for_path(v).get_uri() if v else ""
        if key == "picture-options":
            return next((k for k, n in self.ASPECT.items() if n == v), "zoom")
        if key == "color-shading-type":
            return next((k for k, n in self.SHADE.items() if n == v), "solid")
        if key in ("primary-color", "secondary-color"):
            try:
                r, g, b = (max(0, min(255, int(round(float(x) * 255)))) for x in v[:3])
                return "#{:02x}{:02x}{:02x}".format(r, g, b)
            except Exception:
                return "#000000"
        return v if isinstance(v, str) else ""

    def set_string(self, key, value):
        if key == "picture-uri":
            path = Gio.File.new_for_uri(value).get_path() if value else ""
            var = GLib.Variant("s", path or "")
        elif key == "picture-options":
            var = GLib.Variant("i", self.ASPECT.get(value, 5))
        elif key == "color-shading-type":
            var = GLib.Variant("i", self.SHADE.get(value, 0))
        elif key in ("primary-color", "secondary-color"):
            var = _hex_to_rgba(value)
            if var is None:
                return False
        else:
            return False
        ok = True
        for d in self.targets():
            prop = d + "/" + self.KEYS[key]
            old = Xfconf.raw(prop)
            if old is not None and old.unpack() == var.unpack():
                continue
            ok = Xfconf.set(prop, var) and ok
            if key == "primary-color" and Xfconf.raw(d + "/color-style") is None:
                # with no colour style set xfdesktop shows no colour at all (black)
                Xfconf.set(d + "/color-style", GLib.Variant("i", 0))
        return ok

    def connect(self, _signal, callback):
        return Xfconf.watch(lambda: callback(self, ""))


class XfceDesktopIcons:
    """Xfce's switches for the desktop's own Home / Trash / File System icons, answering to
    Nemo's key names. Xfce has no Network icon."""
    KEYS = {"computer-icon-visible": "/desktop-icons/file-icons/show-filesystem",
            "home-icon-visible": "/desktop-icons/file-icons/show-home",
            "trash-icon-visible": "/desktop-icons/file-icons/show-trash"}

    def get_boolean(self, key):
        prop = self.KEYS.get(key)
        return bool(Xfconf.get(prop, True)) if prop else False

    def set_boolean(self, key, value):
        prop = self.KEYS.get(key)
        if prop:
            Xfconf.set(prop, GLib.Variant("b", bool(value)))
        return True


def background_settings():
    """The desktop's wallpaper settings, with Cinnamon's key names (see MateBackground)."""
    if IS_XFCE:
        return XfceBackground()
    if IS_MATE:
        s = settings_schema("org.mate.background")
        return MateBackground(s) if s is not None else None
    return settings_schema("org.cinnamon.desktop.background")
