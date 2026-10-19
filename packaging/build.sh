#!/bin/sh
# Build the installers into dist/:
#   cubbies_VERSION_all.deb        Mint, LMDE, Debian, Ubuntu (needs dpkg-deb)
#   cubbies-VERSION-1.noarch.rpm   Fedora                     (needs rpmbuild; skipped if missing)
#   cubbies-VERSION.tar.gz         anything else, with install.sh
#
# Run from anywhere:  sh packaging/build.sh
# The version comes from cubbies/constants.py (VERSION = "...").
set -e
root=$(cd "$(dirname "$0")/.." && pwd)
pk="$root/packaging"
version=$(sed -n 's/^VERSION = "\(.*\)"$/\1/p' "$root/cubbies/constants.py")
[ -n "$version" ] || { echo "No VERSION in cubbies/constants.py" >&2; exit 1; }
dist="$root/dist"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$dist"

# ---- the installed files, laid out as they go under /
stage="$work/stage"
install -Dm755 "$root/data/cubbies" "$stage/usr/bin/cubbies"
install -Dm755 "$root/cubbies.py" "$stage/usr/lib/cubbies/cubbies.py"
install -Dm755 "$root/cleanup.py" "$stage/usr/lib/cubbies/cleanup.py"
(cd "$root" && find cubbies -name '*.py' -type f) | sort | while IFS= read -r f; do
    install -Dm644 "$root/$f" "$stage/usr/lib/cubbies/$f"
done
install -Dm644 "$root/data/cubbies.desktop" "$stage/usr/share/applications/cubbies.desktop"
install -Dm644 "$root/data/cubbies.svg" "$stage/usr/share/icons/hicolor/scalable/apps/cubbies.svg"
install -Dm644 "$root/data/cubbies-show-folder.nemo_action" \
    "$stage/usr/share/nemo/actions/cubbies-show-folder.nemo_action"
install -Dm644 "$root/data/cubbies-show-folder.fm-action.desktop" \
    "$stage/usr/share/file-manager/actions/cubbies-show-folder.desktop"
install -Dm644 "$root/data/cubbies-folder.thunar-sendto.desktop" \
    "$stage/usr/share/Thunar/sendto/cubbies-folder.desktop"
find "$stage" -type d -exec chmod 755 {} +

# ---- .deb
deb="$work/deb"
cp -a "$stage" "$deb"
mkdir -p "$deb/DEBIAN"
size=$(du -sk --exclude=DEBIAN "$deb" | cut -f1)
sed -e "s/@VERSION@/$version/" -e "s/@SIZE@/$size/" "$pk/debian/control.in" > "$deb/DEBIAN/control"
for s in preinst postinst prerm; do
    install -m755 "$pk/debian/$s" "$deb/DEBIAN/$s"
done
dpkg-deb --root-owner-group -Zxz -b "$deb" "$dist/cubbies_${version}_all.deb" >/dev/null
echo "built dist/cubbies_${version}_all.deb"

# ---- .rpm (the scriptlets are the .deb's scripts; % is doubled so rpm leaves it alone)
if command -v rpmbuild >/dev/null 2>&1; then
    body() { sed -e '1{/^#!/d}' -e 's/%/%%/g' "$pk/debian/$1"; }
    spec="$work/cubbies.spec"
    while IFS= read -r line; do
        case "$line" in
            @PREINST@) body preinst ;;
            @POSTINST@) body postinst ;;
            @PRERM@) body prerm ;;
            *) printf '%s\n' "$line" ;;
        esac
    done < "$pk/rpm/cubbies.spec.in" \
        | sed -e "s/@VERSION@/$version/" -e "s#@STAGE@#$stage#" > "$spec"
    rpmbuild -bb --quiet --define "_topdir $work/rpm" "$spec" >/dev/null
    cp "$work/rpm/RPMS/noarch/cubbies-$version-1.noarch.rpm" "$dist/"
    echo "built dist/cubbies-$version-1.noarch.rpm"
else
    echo "rpmbuild not found: skipped the .rpm"
fi

# ---- tar.gz with install.sh
tdir="$work/cubbies-$version"
mkdir -p "$tdir/scripts"
cp -a "$stage" "$tdir/files"
install -m755 "$pk/install.sh" "$tdir/install.sh"
for s in preinst postinst prerm; do
    install -m755 "$pk/debian/$s" "$tdir/scripts/$s"
done
tar -C "$work" --owner=0 --group=0 -czf "$dist/cubbies-$version.tar.gz" "cubbies-$version"
echo "built dist/cubbies-$version.tar.gz"
