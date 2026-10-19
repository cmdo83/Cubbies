"""Per-page wallpaper and the blurred wallpaper behind cubbies."""

import os
import sys

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango

from ..core import dbg
from ..desktop_env import DESKTOP_NAME, background_settings
from ..wallpapers import (PAGE_BG, folder_wallpapers, framed_thumbnail, make_blurred_wallpaper,
    make_thumbnail, save_wallpaper_folders, thumb_pool, wallpaper_collections, wallpaper_folders)


class AppWallpaper:
    """Wallpapers and blur. Part of App."""

    def set_wallpaper_for(self, page, path):
        bg = self.bg_settings()
        if "base_wallpaper" not in self.cfg and bg is not None:
            self.cfg["base_wallpaper"] = bg.get_string("picture-uri")
        if path:
            page["wallpaper"] = path
            page.pop("auto", None)          # given its own wallpaper: keep it
        else:
            page.pop("wallpaper", None)
        self.save()
        self._applied_wp = None
        self.apply_wallpaper()

    def set_wallpaper_aspect(self, page, aspect):
        self.set_page_bg(page, "wallpaper_aspect", aspect)

    def base_bg(self):
        """The desktop's own background settings from before Cubbies changed any (so pages
        without their own choice, and uninstalling, put them back)."""
        base = self.cfg.setdefault("base_bg", {})
        if "base_wallpaper_aspect" in self.cfg:          # (kept by 1.18.4 – 1.18.13)
            base.setdefault("picture-options", self.cfg.pop("base_wallpaper_aspect"))
        return base

    def set_page_bg(self, page, key, value):
        """One of a page's background settings (PAGE_BG); None = as the desktop has it."""
        gkey = dict(PAGE_BG)[key]
        bg = self.bg_settings()
        base = self.base_bg()
        if gkey not in base and bg is not None:
            base[gkey] = bg.get_string(gkey)
        if value:
            page[key] = value
        else:
            page.pop(key, None)
        self.save()
        self._applied_wp = None
        self.apply_wallpaper()

    def choose_wallpaper(self, page, changed=None, parent=None):
        """The wallpaper chooser for one page in its own window, laid out like Mint's
        Backgrounds. A click on a picture uses it straight away; Close when done."""
        parent = parent or getattr(self, "_settings_dlg", None)
        dlg = Gtk.Dialog(title=f"Wallpaper for \u201c{page['name']}\u201d",
                         transient_for=parent, modal=True)
        dlg.set_default_size(800, 540)
        dlg.add_button("Close", Gtk.ResponseType.CLOSE)
        area = dlg.get_content_area()
        area.set_border_width(10)
        picker = self.build_wallpaper_picker(page, changed)
        area.pack_start(picker, True, True, 0)
        dlg.show_all()
        dlg.run()
        dlg.destroy()
        if changed:
            changed()

    def build_wallpaper_picker(self, page, changed=None):
        """A page's wallpaper chooser, laid out like Mint's Backgrounds: Images (the wallpaper
        sets and your folders on the left, the pictures on the right; one click uses it).
        The background settings (aspect, colours) sit with the wallpaper in Settings itself.
        changed() runs after the page's wallpaper changes."""
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        outer.pack_start(stack, True, True, 0)    # (the page's tab in Settings has the rest)

        # ---- Images: collections | pictures
        images = Gtk.Box(spacing=8)
        images.set_size_request(-1, 340)
        stack.add_titled(images, "images", "Images")
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        left.set_size_request(170, -1)
        images.pack_start(left, False, False, 0)
        lsw = Gtk.ScrolledWindow()
        lsw.set_shadow_type(Gtk.ShadowType.IN)
        lsw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        left.pack_start(lsw, True, True, 0)
        # kind: "sys", "sep" or "user"; key: index into the system sets, or the folder path
        coll_store = Gtk.ListStore(str, str, str, str)     # icon, name, kind, key
        tree = Gtk.TreeView(model=coll_store)
        tree.set_headers_visible(False)
        tree.set_row_separator_func(lambda m, it: m[it][2] == "sep")
        col = Gtk.TreeViewColumn()
        cell = Gtk.CellRendererPixbuf()
        cell.set_padding(4, 4)
        col.pack_start(cell, False)
        col.add_attribute(cell, "icon-name", 0)
        cell = Gtk.CellRendererText()
        cell.set_property("ellipsize", Pango.EllipsizeMode.END)
        col.pack_start(cell, True)
        col.add_attribute(cell, "text", 1)
        tree.append_column(col)
        lsw.add(tree)
        bar = Gtk.Toolbar()
        bar.set_icon_size(Gtk.IconSize.MENU)
        bar.get_style_context().add_class("inline-toolbar")
        theme = Gtk.IconTheme.get_default()

        def icon_of(names):
            return next((n for n in names if theme.has_icon(n)), names[-1])
        add_btn = Gtk.ToolButton()
        add_btn.set_icon_name(icon_of(("xsi-list-add-symbolic", "list-add-symbolic")))
        add_btn.set_tooltip_text("Add new folder")
        rem_btn = Gtk.ToolButton()
        rem_btn.set_icon_name(icon_of(("xsi-list-remove-symbolic", "list-remove-symbolic")))
        rem_btn.set_tooltip_text("Remove selected folder")
        bar.insert(add_btn, -1)
        bar.insert(rem_btn, -1)
        left.pack_start(bar, False, False, 0)

        rsw = Gtk.ScrolledWindow()
        rsw.set_shadow_type(Gtk.ShadowType.IN)
        rsw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        images.pack_start(rsw, True, True, 0)
        pic_store = Gtk.ListStore(GdkPixbuf.Pixbuf, str, str)     # thumbnail, label, path
        view = Gtk.IconView(model=pic_store)
        # own cells: with set_markup_column GTK makes every item far wider than item_width
        pcell = Gtk.CellRendererPixbuf()
        view.pack_start(pcell, False)
        view.add_attribute(pcell, "pixbuf", 0)
        tcell = Gtk.CellRendererText()
        tcell.set_property("wrap-width", 104)
        tcell.set_property("wrap-mode", Pango.WrapMode.WORD_CHAR)
        tcell.set_property("xalign", 0.5)
        tcell.set_property("alignment", Pango.Alignment.CENTER)
        view.pack_start(tcell, False)
        view.add_attribute(tcell, "markup", 1)
        view.set_item_width(110)
        view.set_column_spacing(4)
        view.set_row_spacing(6)
        view.set_selection_mode(Gtk.SelectionMode.SINGLE)
        rsw.add(view)
        empty = Gtk.Label(label="No pictures here.")
        empty.get_style_context().add_class("dim-label")

        systems = wallpaper_collections()
        st = {"gen": 0, "loading": False}
        try:
            blank = theme.load_icon(icon_of(("image-x-generic", "image-x-generic-symbolic")),
                                    48, 0)
        except Exception:
            blank = None

        def fill_collections(select=None):
            coll_store.clear()
            for i, (name, icons, _pics) in enumerate(systems):
                coll_store.append([icon_of(icons), name, "sys", str(i)])
            if systems:
                coll_store.append(["", "", "sep", ""])
            pics_dir = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES) or ""
            for folder in wallpaper_folders():
                icons = (("xsi-folder-pictures-symbolic", "folder-pictures-symbolic",
                          "folder-pictures") if os.path.normpath(folder) ==
                         os.path.normpath(pics_dir or "/-") else
                         ("xsi-folder-symbolic", "folder-symbolic", "folder"))
                coll_store.append([icon_of(icons), os.path.basename(folder.rstrip("/")) or folder,
                                   "user", folder])
            # start on the set that holds this page's wallpaper
            want = select
            cur = page.get("wallpaper")
            if want is None and cur:
                for row in coll_store:
                    pics = (systems[int(row[3])][2] if row[2] == "sys" else
                            [(os.path.join(row[3], "x"), "")] if row[2] == "user" else [])
                    if row[2] == "sys" and any(p == cur for p, _t in pics):
                        want = row[3]
                        break
                    if row[2] == "user" and os.path.dirname(cur) == os.path.normpath(row[3]):
                        want = row[3]
                        break
            for row in coll_store:
                if row[2] != "sep" and (want is None or row[3] == want):
                    tree.get_selection().select_iter(row.iter)
                    tree.scroll_to_cell(row.path, None, False, 0, 0)
                    break

        def label_for(title, size=None):
            title = title if len(title) <= 30 else title[:28] + "\u2026"
            return "<b>" + GLib.markup_escape_text(title) + "</b>" + (
                "\n<small>{} \u00d7 {}</small>".format(*size) if size else "")

        def show_pictures(pics):
            st["gen"] += 1
            gen = st["gen"]
            st["loading"] = True
            pic_store.clear()
            cur = page.get("wallpaper")
            rows = {}
            for path, title in pics:
                rows[path] = pic_store.append([blank, label_for(title), path])
            if cur in rows:
                view.select_path(pic_store.get_path(rows[cur]))
                view.scroll_to_path(pic_store.get_path(rows[cur]), False, 0, 0)
            st["loading"] = False
            if not pics:
                rsw.remove(rsw.get_child())
                rsw.add(empty)
                empty.show()
            elif rsw.get_child() is not view:
                rsw.remove(rsw.get_child())
                rsw.add(view)
                view.show()

            def work(path, title):
                if st["gen"] != gen:
                    return
                pb = make_thumbnail(path, 100)
                try:
                    info = GdkPixbuf.Pixbuf.get_file_info(path)
                    size = (info[1], info[2]) if info and info[0] else None
                except Exception:
                    size = None
                GLib.idle_add(lambda: put(path, title, pb, size) and False)

            def put(path, title, pb, size):
                it = rows.get(path)
                if st["gen"] != gen or it is None or not pic_store.iter_is_valid(it):
                    return False
                if pb is not None:
                    try:
                        pb = framed_thumbnail(pb)
                    except Exception:
                        pass
                    pic_store[it][0] = pb
                pic_store[it][1] = label_for(title, size)
                return False
            for path, title in pics:
                thumb_pool().submit(work, path, title)

        def collection_changed(sel):
            model, it = sel.get_selected()
            if it is None:
                rem_btn.set_sensitive(False)
                return
            kind, key = model[it][2], model[it][3]
            rem_btn.set_sensitive(kind == "user")
            show_pictures(systems[int(key)][2] if kind == "sys" else folder_wallpapers(key))
        tree.get_selection().connect("changed", collection_changed)

        def picture_chosen(_v):
            if st["loading"]:
                return
            sel = view.get_selected_items()
            if not sel:
                return
            path = pic_store[sel[0]][2]
            if path != page.get("wallpaper"):
                self.set_wallpaper_for(page, path)
                if changed:
                    changed()
        view.connect("selection-changed", picture_chosen)

        def add_folder(_b):
            dlg = Gtk.FileChooserDialog(title="Add a Folder of Wallpapers",
                                        action=Gtk.FileChooserAction.SELECT_FOLDER,
                                        transient_for=outer.get_toplevel()
                                        if isinstance(outer.get_toplevel(), Gtk.Window) else None)
            dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Add", Gtk.ResponseType.OK)
            folder = dlg.get_filename() if dlg.run() == Gtk.ResponseType.OK else None
            dlg.destroy()
            if folder:
                folders = wallpaper_folders()
                if folder not in folders:
                    folders.append(folder)
                    save_wallpaper_folders(folders)
                fill_collections(select=folder)

        def remove_folder(_b):
            model, it = tree.get_selection().get_selected()
            if it is None or model[it][2] != "user":
                return
            save_wallpaper_folders([f for f in wallpaper_folders() if f != model[it][3]])
            fill_collections(select=None if not systems else "0")
        add_btn.connect("clicked", add_folder)
        rem_btn.connect("clicked", remove_folder)

        def refresh():
            """The page's wallpaper was cleared elsewhere: drop the highlight."""
            st["loading"] = True
            view.unselect_all()
            st["loading"] = False
        outer.refresh = refresh
        fill_collections()
        return outer

    # -- per-page wallpaper (Cinnamon: org.cinnamon.desktop.background)
    # -- the wallpaper behind cubbies, blurred (Cinnamon can't blur behind windows itself,
    #    so each cubby paints the blurred part of the wallpaper that is behind it)
    _blur = None            # (key, screen-sized blurred pixbuf)
    _blur_busy = None

    def blur_of(self, data):
        """(blurred?, blur amount, glass strength) for a cubby: its own choice, else its
        page's default (Manage Pages › the gear › Cubby Defaults), else Settings'."""
        page_d = {}
        for page in self.cfg["pages"]:
            if any(f is data for f in page["cubbies"]):
                page_d = page.get("defaults") or {}
                break

        def pick(key, usual):
            v = data.get(key)
            if v is None:
                v = page_d.get(key)
            return usual if v is None else v
        try:
            level = int(pick("blur_level", self.cfg.get("blur_level", 18)))
            strength = float(pick("blur_strength", self.cfg.get("blur_strength", 1.0)))
        except (TypeError, ValueError):
            level, strength = 18, 1.0
        return (bool(pick("blur", self.setting("blur_bg"))), max(6, min(40, level)),
                max(0.1, min(1.0, strength)))

    def cubby_blur(self, data):
        """Is the wallpaper blurred behind this cubby? Its own choice, else its page's
        default, else Settings'."""
        return self.blur_of(data)[0]

    def blurred_wallpaper(self, level=None):
        """The screen-sized wallpaper blurred by `level` (a cubby's blur amount), or None
        (made in the background). A few amounts are kept at once."""
        if not any(self.cubby_blur(f) for f in self.all_cubbies() if not f.get("tab_of")):
            return None
        if level is None:
            level = int(self.cfg.get("blur_level", 18))
        bg = self.bg_settings()
        if bg is None:
            return None
        try:
            uri = bg.get_string("picture-uri")
            options = bg.get_string("picture-options")
            colours = (bg.get_string("color-shading-type"), bg.get_string("primary-color"),
                       bg.get_string("secondary-color"))
        except Exception as exc:
            self._blur_status = f"Can't read the background settings ({exc!r})"
            return None
        path = Gio.File.new_for_uri(uri).get_path() if uri else None
        mtime = 0
        if options == "none":
            path = None
        if path:
            try:
                mtime = int(os.stat(path).st_mtime)
            except OSError:
                path = None                  # (a missing picture: the colour alone)
        scr = Gdk.Screen.get_default()
        display = Gdk.Display.get_default()
        mons = []
        for i in range(display.get_n_monitors()):
            g = display.get_monitor(i).get_geometry()
            mons.append((g.x, g.y, g.width, g.height))
        key = (path, mtime, options, level, scr.get_width(), scr.get_height(),
               tuple(mons), colours)
        blurs = self.__dict__.setdefault("_blurs", {})
        busy = self.__dict__.setdefault("_blurs_busy", set())
        if key in blurs:
            return blurs[key]
        if key not in busy:
            busy.add(key)

            dbg(f"making the blurred wallpaper: {path} ({options}), desktop "
                f"{key[4]}x{key[5]}, screens {mons}, blur {level}")

            def work():
                return key, make_blurred_wallpaper(path, options, key[4], key[5], level, mons,
                                                   colours)

            def done(fut):
                try:
                    k, pb = fut.result()
                except Exception as exc:
                    busy.discard(key)
                    dbg("blur failed:", exc)
                    self._blur_status = f"Blurring failed: {exc}"
                    return
                self._blur_status = f"Blurring {path} ({options})"
                def apply():
                    busy.discard(k)
                    if pb is not None:
                        for old in [o for o in blurs if o[:3] != k[:3] or o[4:] != k[4:]]:
                            blurs.pop(old, None)      # another wallpaper or screen: gone
                        while len(blurs) >= 4:        # a few amounts at a time
                            blurs.pop(next(iter(blurs)))
                        blurs[k] = pb
                        for win in self.windows.values():
                            win.queue_draw()
                    return False
                GLib.idle_add(apply)
            thumb_pool().submit(work).add_done_callback(done)
        return None          # not ready yet (an old picture would be the wrong one)

    def watch_background(self):
        bg = self.bg_settings()
        if bg is not None and not getattr(self, "_bg_watch", None):
            self._bg_watch = bg
            bg.connect("changed", lambda *_a: [w.queue_draw() for w in self.windows.values()])

    def bg_settings(self):
        return background_settings()

    def apply_wallpaper(self):
        if not self.setting("page_wallpapers"):
            return
        wp = self.page().get("wallpaper")
        if wp and os.path.exists(wp):
            uri = Gio.File.new_for_path(wp).get_uri()
        else:
            uri = self.cfg.get("base_wallpaper")  # the wallpaper you had before using this
        base = self.base_bg() if self.cfg.get("base_bg") or "base_wallpaper_aspect" in self.cfg \
            else {}
        want = {gkey: self.page().get(key) or base.get(gkey) for key, gkey in PAGE_BG}
        if want.get("picture-options") == "none":
            uri = ""                  # "No picture": the colour only (an empty picture setting
            #                           is what every desktop honours)
        key = (uri, tuple(sorted(want.items(), key=lambda kv: kv[0])))
        if key == self._applied_wp:
            return
        bg = self.bg_settings()
        if bg is not None and "base_wallpaper" not in self.cfg:
            self.cfg["base_wallpaper"] = bg.get_string("picture-uri")   # (for uninstalling)
        if bg is None:
            dbg("no", DESKTOP_NAME, "background settings found; wallpaper not changed")
            return
        try:
            for gkey, value in want.items():      # aspect and colours first, then the picture
                if value and bg.get_string(gkey) != value:
                    bg.set_string(gkey, value)
            if uri is not None and bg.get_string("picture-uri") != uri:
                if not bg.set_string("picture-uri", uri):
                    raise RuntimeError(DESKTOP_NAME + " refused the wallpaper setting")
            Gio.Settings.sync()
            self._applied_wp = key
            dbg("wallpaper ->", uri, want)
            try:
                src = Gio.SettingsSchemaSource.get_default()
                if src.lookup("org.cinnamon.desktop.background.slideshow", True):
                    show = Gio.Settings.new("org.cinnamon.desktop.background.slideshow")
                    if show.get_boolean("slideshow-enabled"):
                        print("Cubbies: Cinnamon's wallpaper slideshow is on and will "
                              "override page wallpapers; turn it off in Backgrounds.",
                              file=sys.stderr)
            except Exception:
                pass
        except Exception as exc:
            print("Cubbies: could not change the wallpaper:", exc, file=sys.stderr)
