"""
Cubbies - a small desktop organizer for Linux desktops running Cinnamon, MATE or Xfce on X11.

* "Cubbies" on the desktop (see-through to solid) that hold icons (files, folders, apps, launchers)
* Several desktop "pages", each with its own cubbies and icons
* Switch pages with the mouse wheel (over a cubby title bar or the page switcher) or the arrows

Start it with  python3 cubbies.py  (or  python3 -m cubbies).
"""
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)  # GTK's override_* calls

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
