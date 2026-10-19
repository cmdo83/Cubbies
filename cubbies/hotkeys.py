"""Global keys, grabbed straight from X11 (page keys, peek, Delete, Undo, Find)."""

import ctypes
import ctypes.util
import os

from gi.repository import GLib

from .core import dbg
from .desktop_env import DESKTOP_NAME, SHORTCUTS_SHORT


class _XKeyEvent(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong),
                ("send_event", ctypes.c_int), ("display", ctypes.c_void_p),
                ("window", ctypes.c_ulong), ("root", ctypes.c_ulong),
                ("subwindow", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("x", ctypes.c_int), ("y", ctypes.c_int),
                ("x_root", ctypes.c_int), ("y_root", ctypes.c_int),
                ("state", ctypes.c_uint), ("keycode", ctypes.c_uint),
                ("same_screen", ctypes.c_int)]


class _XEvent(ctypes.Union):
    _fields_ = [("type", ctypes.c_int), ("xkey", _XKeyEvent), ("pad", ctypes.c_long * 24)]


_XErrorHandler = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)

HOTKEY_CHOICES = [
    ("ctrl", "Ctrl + Left / Right (and Ctrl + Up)"),
    ("super_ctrl", "Super + Ctrl + Left / Right (and Up)"),
    ("off", "Off"),
]


class HotkeyGrabber:
    """System-wide keys without any Cinnamon shortcut entries.

    A program normally only sees keys typed into its own windows. This asks the X server to
    send a few specific key combinations to us no matter which window has focus (an X "key
    grab"), over a private second connection that is polled from the GTK main loop. The grabbed
    keys are not passed on to the other program, so Ctrl+Left stops word-jumping elsewhere.
    Delete is only grabbed while the pointer is over a cubby that has selected icons."""

    KEYSYMS = {"Left": 0xFF51, "Right": 0xFF53, "Up": 0xFF52, "Delete": 0xFFFF, "F2": 0xFFBF,
               "space": 0x20, "Escape": 0xFF1B}
    SHIFT, LOCK, CONTROL, ALT, MOD2, SUPER = 1, 2, 4, 8, 0x10, 0x40
    KEY_PRESS = 2

    def __init__(self, on_step, on_delete, want_delete):
        self.on_step, self.on_delete, self.want_delete = on_step, on_delete, want_delete
        x = self.x = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        c_void_p, c_int, c_uint, c_ulong = (ctypes.c_void_p, ctypes.c_int,
                                            ctypes.c_uint, ctypes.c_ulong)
        x.XOpenDisplay.restype, x.XOpenDisplay.argtypes = c_void_p, [ctypes.c_char_p]
        x.XDefaultRootWindow.restype, x.XDefaultRootWindow.argtypes = c_ulong, [c_void_p]
        x.XKeysymToKeycode.restype, x.XKeysymToKeycode.argtypes = ctypes.c_ubyte, [c_void_p, c_ulong]
        x.XGrabKey.argtypes = [c_void_p, c_int, c_uint, c_ulong, c_int, c_int, c_int]
        x.XUngrabKey.argtypes = [c_void_p, c_int, c_uint, c_ulong]
        x.XSync.argtypes = [c_void_p, c_int]
        x.XFlush.argtypes = [c_void_p]
        x.XPending.restype, x.XPending.argtypes = c_int, [c_void_p]
        x.XNextEvent.argtypes = [c_void_p, ctypes.c_void_p]
        x.XSetErrorHandler.restype, x.XSetErrorHandler.argtypes = c_void_p, [c_void_p]
        self.dpy = x.XOpenDisplay(None)
        if not self.dpy:
            raise RuntimeError("could not open a second X connection")
        self.root = x.XDefaultRootWindow(self.dpy)
        self._handler = _XErrorHandler(self._on_error)  # keep a reference alive
        self._error = False
        self.event = _XEvent()
        self.page_grabs = []       # (keycode, modifiers, step); step 0 = the page chooser
        self.page_held = False     # are they grabbed right now?
        self.page_keys_when = lambda: True   # False: leave them to the program in front
        self.delete_kc = None
        self.f2_kc = None
        self.on_rename = lambda: None
        self.peek_grab = None              # (keycode, modifiers) of the Glance key
        self.on_peek = lambda: None
        self.esc_kc = None                 # Escape, caught only while it's needed
        self.want_escape = lambda: False
        self.on_escape = lambda: None
        self.delete_retry_at = 0
        # F5 is only watched, never grabbed: the desktop still refreshes its own icons and
        # every other program keeps its F5. Cubbies refreshes too when the desktop (or a
        # cubby) is what F5 was pressed on.
        x.XQueryKeymap.argtypes = [c_void_p, ctypes.c_char_p]
        self.f5_kc = x.XKeysymToKeycode(self.dpy, 0xFFC2)
        self._keymap = ctypes.create_string_buffer(32)
        self._f5_down = False
        self.on_refresh_key = lambda: None
        self.conditional = []       # keys grabbed only while wanted (Ctrl+Z over a cubby...)

    def add_conditional(self, keysym, mods, want, act):
        """Grab keysym+mods only while want() says so, and call act() when it's pressed."""
        self.conditional.append({"keysym": keysym, "mods": mods, "want": want, "act": act,
                                 "kc": None, "retry": 0})

    def f5_pressed_now(self):
        """True once each time F5 goes down (checked by looking at the keyboard)."""
        if not self.f5_kc:
            return False
        self.x.XQueryKeymap(self.dpy, self._keymap)
        kc = self.f5_kc
        down = bool(self._keymap.raw[kc // 8] & (1 << (kc % 8)))
        fresh = down and not self._f5_down
        self._f5_down = down
        return fresh

    def _on_error(self, _dpy, _event):
        self._error = True
        return 0

    def _combos(self, mods):
        return [mods | extra for extra in (0, self.LOCK, self.MOD2, self.LOCK | self.MOD2)]

    def grab(self, keysym, mods):
        """Grab keysym+mods (also with Caps/Num Lock on). Returns the keycode or None."""
        x = self.x
        keycode = x.XKeysymToKeycode(self.dpy, keysym)
        if not keycode:
            return None
        self._error = False
        old = x.XSetErrorHandler(ctypes.cast(self._handler, ctypes.c_void_p))
        for combo in self._combos(mods):
            x.XGrabKey(self.dpy, keycode, combo, self.root, 1, 1, 1)
        x.XSync(self.dpy, 0)
        x.XSetErrorHandler(old)
        if self._error:
            self.ungrab(keycode, mods)
            return None
        return keycode

    def ungrab(self, keycode, mods):
        for combo in self._combos(mods):
            self.x.XUngrabKey(self.dpy, keycode, combo, self.root)
        self.x.XFlush(self.dpy)

    PEEK_KEYS = {"super_space": ("space", 0x40), "ctrl_alt_space": ("space", 4 | 8),
                 "ctrl_super_space": ("space", 4 | 0x40)}

    def set_peek_key(self, mode):
        """The key that opens the Glance panel. Returns (ok, message)."""
        if self.peek_grab is not None:
            self.ungrab(*self.peek_grab)
            self.peek_grab = None
        if mode == "off" or mode not in self.PEEK_KEYS:
            return True, "No key: use the command  cubbies --glance  for your own shortcut."
        name, mods = self.PEEK_KEYS[mode]
        kc = self.grab(self.KEYSYMS[name], mods)
        if kc is None:
            return False, (f"Another program (probably {DESKTOP_NAME}) already uses that "
                           f"key. Pick another one, or free it in {SHORTCUTS_SHORT}.")
        self.peek_grab = (kc, mods)
        return True, "Active now - works in any window."

    def set_page_keys(self, mode):
        """Left / Right (pages) and Up (the page chooser) with Ctrl or Super+Ctrl. They are
        tried at once (to find keys another program already has), then held only while
        page_keys_when() says so. Returns (ok, message)."""
        if self.page_held:
            for keycode, mods, _step in self.page_grabs:
                self.ungrab(keycode, mods)
        self.page_grabs = []
        self.page_held = False
        if mode == "off":
            return True, "Page keys are off."
        mods = self.CONTROL | (self.SUPER if mode == "super_ctrl" else 0)
        for name, step in (("Left", -1), ("Right", 1), ("Up", 0)):
            keycode = self.grab(self.KEYSYMS[name], mods)
            if keycode is None:
                for kc, m, _s in self.page_grabs:
                    self.ungrab(kc, m)
                self.page_grabs = []
                return False, (f"Another program (probably {DESKTOP_NAME}) already uses "
                               "those keys. Pick another combination, or free them in "
                               f"{SHORTCUTS_SHORT}.")
            self.page_grabs.append((keycode, mods, step))
        self.page_held = True
        self.sync_page_keys()
        return True, "Active now."

    def sync_page_keys(self):
        """Hold the page keys only while they are wanted (see page_keys_when)."""
        if not self.page_grabs:
            return
        want = bool(self.page_keys_when())
        if want == self.page_held:
            return
        if want:
            for keycode, mods, _step in self.page_grabs:
                self._error = False
                old = self.x.XSetErrorHandler(ctypes.cast(self._handler, ctypes.c_void_p))
                for combo in self._combos(mods):
                    self.x.XGrabKey(self.dpy, keycode, combo, self.root, 1, 1, 1)
                self.x.XSync(self.dpy, 0)
                self.x.XSetErrorHandler(old)
        else:
            for keycode, mods, _step in self.page_grabs:
                self.ungrab(keycode, mods)
        self.page_held = want

    def set_delete(self, wanted):
        """Delete and F2 (rename) are caught only while the pointer is over a cubby with
        selected icons, so they keep working everywhere else."""
        now = GLib.get_monotonic_time() // 1000
        if wanted and self.delete_kc is None and now >= self.delete_retry_at:
            self.delete_kc = self.grab(self.KEYSYMS["Delete"], 0)
            self.f2_kc = self.grab(self.KEYSYMS["F2"], 0)
            if self.delete_kc is None:
                self.delete_retry_at = now + 2000
        elif not wanted and self.delete_kc is not None:
            self.ungrab(self.delete_kc, 0)
            self.delete_kc = None
            if self.f2_kc is not None:
                self.ungrab(self.f2_kc, 0)
                self.f2_kc = None

    def poll(self):
        try:
            if self.f5_pressed_now():
                self.on_refresh_key()
            self.set_delete(bool(self.want_delete()))
            self.sync_page_keys()
            want_esc = bool(self.want_escape())
            if want_esc and self.esc_kc is None:
                self.esc_kc = self.grab(self.KEYSYMS["Escape"], 0)
            elif not want_esc and self.esc_kc is not None:
                self.ungrab(self.esc_kc, 0)
                self.esc_kc = None
            now = GLib.get_monotonic_time() // 1000
            for c in self.conditional:
                w = bool(c["want"]())
                if w and c["kc"] is None and now >= c["retry"]:
                    c["kc"] = self.grab(c["keysym"], c["mods"])
                    if c["kc"] is None:
                        c["retry"] = now + 2000
                elif not w and c["kc"] is not None:
                    self.ungrab(c["kc"], c["mods"])
                    c["kc"] = None
            while self.x.XPending(self.dpy):
                self.x.XNextEvent(self.dpy, ctypes.byref(self.event))
                if self.event.type != self.KEY_PRESS:
                    continue
                keycode = self.event.xkey.keycode
                state = self.event.xkey.state & 0xFF & ~(self.LOCK | self.MOD2)
                for c in self.conditional:
                    if c["kc"] is not None and keycode == c["kc"] and state == c["mods"]:
                        c["act"]()
                if keycode == self.delete_kc and state == 0:
                    self.on_delete()
                elif keycode == self.f2_kc and state == 0:
                    self.on_rename()
                elif self.peek_grab and keycode == self.peek_grab[0] and state == self.peek_grab[1]:
                    self.on_peek()
                elif keycode == self.esc_kc and state == 0:
                    self.on_escape()
                for kc, mods, step in self.page_grabs:
                    if self.page_held and keycode == kc and state == mods:
                        self.on_step(step)
        except Exception as exc:  # never let a hiccup stop the polling
            dbg("hotkey poll error:", repr(exc))
        return True


def selection_owner_info(selection="CLIPBOARD"):
    """For debugging: which program owns an X selection now ("pid 123 csd-clipboard", ...)."""
    try:
        x = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        vp, ul = ctypes.c_void_p, ctypes.c_ulong
        x.XOpenDisplay.restype, x.XOpenDisplay.argtypes = vp, [ctypes.c_char_p]
        x.XInternAtom.restype, x.XInternAtom.argtypes = ul, [vp, ctypes.c_char_p, ctypes.c_int]
        x.XGetSelectionOwner.restype, x.XGetSelectionOwner.argtypes = ul, [vp, ul]
        x.XGetWindowProperty.argtypes = [vp, ul, ul, ctypes.c_long, ctypes.c_long, ctypes.c_int,
                                         ul, ctypes.POINTER(ul), ctypes.POINTER(ctypes.c_int),
                                         ctypes.POINTER(ul), ctypes.POINTER(ul),
                                         ctypes.POINTER(ctypes.c_void_p)]
        x.XFree.argtypes = [vp]
        x.XCloseDisplay.argtypes = [vp]
        dpy = x.XOpenDisplay(None)
        if not dpy:
            return "?"
        try:
            owner = x.XGetSelectionOwner(dpy, x.XInternAtom(dpy, selection.encode(), 0))
            if not owner:
                return "nobody"
            atom = x.XInternAtom(dpy, b"_NET_WM_PID", 0)
            at, fmt, n, after = ul(), ctypes.c_int(), ul(), ul()
            data = ctypes.c_void_p()
            pid = None
            if x.XGetWindowProperty(dpy, owner, atom, 0, 1, 0, 0, ctypes.byref(at),
                                    ctypes.byref(fmt), ctypes.byref(n), ctypes.byref(after),
                                    ctypes.byref(data)) == 0 and data.value:
                if n.value:
                    pid = ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))[0]
                x.XFree(data)
            name = ""
            if pid:
                try:
                    with open(f"/proc/{pid}/comm") as fh:
                        name = fh.read().strip()
                except OSError:
                    pass
            me = " (Cubbies)" if pid == os.getpid() else ""
            return f"window 0x{owner:x}" + (f", pid {pid} {name}{me}" if pid else "")
        finally:
            x.XCloseDisplay(dpy)
    except Exception as exc:
        return f"? ({exc!r})"
