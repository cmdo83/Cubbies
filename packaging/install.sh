#!/bin/sh
# Install Cubbies on any distro (Arch, EndeavourOS, Manjaro, openSUSE, ...), from this folder.
#
#   sudo ./install.sh               install what Cubbies needs, then Cubbies itself
#   sudo ./install.sh --no-deps     only copy Cubbies in (you install the requirements)
#   sudo ./install.sh --uninstall   put every user's desktop back and remove Cubbies
#
# On Mint / Debian / Ubuntu use the .deb, and on Fedora the .rpm, instead: they update and
# uninstall through the system's own package manager.
set -e
here=$(cd "$(dirname "$0")" && pwd)
files="$here/files"
scripts="$here/scripts"
deps=1
action=install
for arg in "$@"; do
    case "$arg" in
        --no-deps) deps="" ;;
        --uninstall) action=uninstall ;;
        -h|--help) sed -n '2,/^[^#]/{/^#/s/^# \{0,1\}//p}' "$0"; exit 0 ;;
        *) echo "Unknown option: $arg (try --help)" >&2; exit 2 ;;
    esac
done

if [ "$(id -u)" -ne 0 ]; then
    echo "Run it with sudo:  sudo $0 $*" >&2
    exit 1
fi

# everything this installs, relative to /
installed_files() {
    (cd "$files" && find . -type f | sed 's#^\./#/#')
}

if [ "$action" = uninstall ]; then
    if [ ! -e /usr/lib/cubbies/cubbies.py ]; then
        echo "Cubbies is not installed."
        exit 0
    fi
    echo "Putting each user's desktop back and stopping Cubbies..."
    sh "$scripts/prerm" remove
    installed_files | while IFS= read -r f; do rm -f "$f"; done
    rm -rf /usr/lib/cubbies
    echo "Cubbies is uninstalled."
    exit 0
fi

# a copy installed by the .deb or .rpm belongs to that package manager
if command -v dpkg-query >/dev/null 2>&1 \
        && dpkg-query -W -f '${Status}' cubbies 2>/dev/null | grep -q "ok installed"; then
    echo "Cubbies is installed from the .deb. Remove it first:  sudo apt remove cubbies" >&2
    exit 1
fi
if command -v rpm >/dev/null 2>&1 && rpm -q cubbies >/dev/null 2>&1; then
    echo "Cubbies is installed from the .rpm. Remove it first:  sudo dnf remove cubbies" >&2
    exit 1
fi

if [ -n "$deps" ]; then
    echo "Installing what Cubbies needs..."
    if command -v apt-get >/dev/null 2>&1; then
        apt-get install -y python3 python3-gi python3-gi-cairo gir1.2-gtk-3.0 libx11-6
        apt-get install -y gir1.2-wnck-3.0 || true
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y python3 python3-gobject python3-cairo gtk3 libX11
        dnf install -y libwnck3 || true
    elif command -v pacman >/dev/null 2>&1; then
        pacman -S --needed --noconfirm python python-gobject python-cairo gtk3 libx11
        pacman -S --needed --noconfirm libwnck3 || true
    elif command -v zypper >/dev/null 2>&1; then
        zypper --non-interactive install python3 python3-gobject python3-gobject-cairo \
            python3-cairo typelib-1_0-Gtk-3_0 libX11-6
        zypper --non-interactive install typelib-1_0-Wnck-3_0 || true
    else
        echo "No apt, dnf, pacman or zypper here. Install Python 3 with PyGObject and pycairo," >&2
        echo "GTK 3 and libX11 yourself (libwnck 3 too, if you can), then run:" >&2
        echo "  sudo $0 --no-deps" >&2
        exit 1
    fi
fi

echo "Installing Cubbies..."
upgrade=install
[ -e /usr/lib/cubbies/cubbies.py ] && upgrade=upgrade
sh "$scripts/preinst" "$upgrade"          # stops any copy that is running
rm -rf /usr/lib/cubbies                     # no modules left over from an older version
cp -R "$files/." /
chmod 755 /usr/bin/cubbies /usr/lib/cubbies/cubbies.py /usr/lib/cubbies/cleanup.py
command -v gtk-update-icon-cache >/dev/null 2>&1 \
    && gtk-update-icon-cache -q /usr/share/icons/hicolor 2>/dev/null || true
command -v update-desktop-database >/dev/null 2>&1 \
    && update-desktop-database -q /usr/share/applications 2>/dev/null || true
sh "$scripts/postinst" configure          # starts it again for whoever had it running

if python3 -c 'import gi, cairo
gi.require_version("Gtk", "3.0"); gi.require_version("GdkX11", "3.0")
from gi.repository import Gtk, GdkX11' >/dev/null 2>&1; then
    echo "Done. Start Cubbies from the menu, or run:  cubbies"
else
    echo "Cubbies is installed, but Python can't load GTK 3 / cairo yet. Install PyGObject," >&2
    echo "pycairo and GTK 3 for your distro, then start it with:  cubbies" >&2
    exit 1
fi
