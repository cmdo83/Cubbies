#!/usr/bin/env python3
"""
Cubbies - a small desktop organizer for Linux desktops running Cinnamon, MATE or Xfce on X11.

Run:      python3 cubbies.py
Autostart: python3 cubbies.py --install-autostart

The program itself is the cubbies/ package beside this file. This launcher keeps the name
cubbies.py because autostart entries, restarts and the installer all look for it.
"""
import os
import sys

if __name__ == "__main__":
    here = os.path.dirname(os.path.realpath(__file__))
    if sys.path[0] != here:
        sys.path.insert(0, here)
    from cubbies.main import main
    main()
