"""The welcome guide (first start, and from Settings)."""

from gi.repository import Gdk, GLib, Gtk

from ..core import dbg


class AppWelcome:
    """The welcome guide. Part of App."""

    # -- welcome guide (first start, and from Settings)
    def maybe_show_welcome(self):
        if self.cfg.get("welcome_shown") is False:
            self.cfg["welcome_shown"] = True
            self.save()
            self.show_welcome()
        return False

    WELCOME_TOPICS = (
        ("welcome", "Welcome"),
        ("make", "Making Cubbies"),
        ("use", "Filling and Using Them"),
        ("arrange", "Moving and Arranging"),
        ("pages", "Pages"),
        ("launch", "Launch Bar Cubbies"),
        ("sort", "Sorting New Files"),
        ("tabs", "Tabs"),
        ("hide", "Hiding and Glance"),
        ("more", "Handy Extras"),
    )

    def welcome_page(self, key):
        """One topic of the Welcome Guide: a picture, a line about it, and the basics."""
        k = "<b>{}</b>".format
        if key == "welcome":
            sw, box = self.s_page("Welcome to Cubbies", "Cubbies keeps your desktop tidy. A "
                                  "cubby is a box on your desktop that holds icons for your "
                                  "files, folders and apps, styled however you like.",
                                  self.s_preview("cubby"))
            sec = self.s_section(box, "The ideas")
            self.s_bullets(sec, [
                k("Cubbies") + " hold your icons. Name them, colour them, roll them up.",
                k("Pages") + " are separate desktops, each with its own cubbies (and wallpaper, "
                "if you like).",
                "A " + k("Launch Bar Cubby") + " keeps your favourite apps along the edge of "
                "the screen, out of sight until you want them.",
                "Files you put in a cubby are kept in the " + k("Cubbies") + " folder in your "
                "home folder, so your Desktop folder stays clean."])
            sec = self.s_section(box, "Your first minute")
            self.s_bullets(sec, [
                "Hold the left mouse button on the empty desktop and drag a box: choose "
                + k("Create Cubby Here") + ". Icons inside the box go straight into it.",
                "Drag files onto the cubby to add more.",
                "Double-click the empty desktop to hide every cubby; again to bring them back."])
            self.s_note(sec, "Use the topics on the left (or Next) for a quick tour. You can "
                             "open this guide again from Settings \u203a Home.")
        elif key == "make":
            sw, box = self.s_page("Making Cubbies", "Five kinds, made in a few ways.",
                                  self.s_preview("folder", title="Projects"))
            sec = self.s_section(box, "Ways to make one")
            self.s_bullets(sec, [
                "Draw a box on the empty desktop (hold the left button and drag). Desktop icons "
                "inside it move in, Computer, Home, Trash and Network too (they then leave the "
                "desktop, and come back when no cubby holds them).",
                "Right-click the page bar › " + k("New Cubby") + " and pick the kind.",
                "Type its name straight away, then press Enter."])
            sec = self.s_section(box, "Kinds of cubby")
            self.s_bullets(sec, [
                k("Cubby") + ": holds whatever you drop on it.",
                k("Folder Cubby") + ": shows a real folder, always up to date. Double-click a "
                "folder in it to look inside; ↑ goes back up. Also: right-click a folder "
                "in the file manager › Show as a Folder Cubby on the Desktop.",
                k("Inbox Cubby") + ": new files that land on your desktop (downloads, "
                "screenshots) are moved into it.",
                k("Recent Files") + ": the files you opened lately, in any app.",
                k("Launch Bar Cubby") + ": a bar of apps along the screen edge (see Launch "
                "Bar Cubbies)."])
            self.s_note(sec, "Right-click a cubby › Cubby Type to change what kind it is.")
        elif key == "use":
            sw, box = self.s_page("Filling and Using Them", "Icons in a cubby work like icons "
                                  "on the desktop.", self.s_preview("cubby", title="Documents"))
            sec = self.s_section(box, "Icons")
            self.s_bullets(sec, [
                "Double-click to open. Right-click for the same menu the file manager has.",
                "Click a name again (slowly), or press F2, to rename it right there.",
                "Ctrl + click picks several icons; Shift + click picks a range; Shift + drag "
                "draws a selection box.",
                "Cut, Copy and Paste work with the file manager both ways.",
                "Right-click › " + k("Add System Places") + " adds Computer, Home, Trash, "
                "Network or a drive. Files dropped on a Trash icon go to the Trash. You can "
                "rename these too (only in Cubbies: the real folder keeps its name)."])
            sec = self.s_section(box, "The cubby")
            self.s_bullets(sec, [
                "The ☰ button (on the title bar) sorts the icons and changes the view: "
                "Icons, List or Details, and its scroll bars (down, sideways or both).",
                "Ctrl + mouse wheel over the icons makes them bigger or smaller.",
                "Right-click › " + k("Filter Tabs…") + " adds tabs that show just "
                "pictures, documents, and so on, or " + k("Nooks") + ": tabs for the icons "
                "you choose (drag icons onto a nook).",
                "Ctrl + F over a cubby searches it: a strip slides down and the icons narrow "
                "as you type. Enter opens the first one.",
                "Rest the pointer on a folder to see what's inside it.",
                "Right-click › " + k("Style") + " › Styling Options… for colour, "
                "transparency (see-through to solid), corners, border, blur and font. Its "
                + k("Share this look") + " copies just the parts you tick to other cubbies, "
                "on any pages."])
        elif key == "arrange":
            sw, box = self.s_page("Moving and Arranging", "Put cubbies exactly where you want "
                                  "them.", self.s_preview("rollup"))
            sec = self.s_section(box, "Moving and sizing")
            self.s_bullets(sec, [
                "Drag a title bar to move a cubby; drag any edge or corner to resize it. The "
                "icons stay put while you resize.",
                "Cubbies snap to each other (with the gap you choose) and to the edges of the "
                "screen. Hold Shift to place freely.",
                "To move several: draw a box around them on the desktop, or Ctrl + click their "
                "title bars, then drag one of them."])
            sec = self.s_section(box, "Tidy touches")
            self.s_bullets(sec, [
                "Double-click a title bar to roll the cubby up to just its title.",
                "Right-click › " + k("Options") + " › Lock Position and Size keeps a "
                "cubby from moving.",
                "Right-click › " + k("Options") + " › Title Bar puts the title at the "
                "top or the bottom, or takes it away (then drag the empty space to move it).",
                "Options also has Show on Every Page (it can sit in its own place on each "
                "page), and Stay Visible for when cubbies are hidden."])
        elif key == "pages":
            sw, box = self.s_page("Pages", "Keep work, home and projects on separate desktops.",
                                  self.s_preview("pages", title="General"))
            sec = self.s_section(box, "Getting around")
            self.s_bullets(sec, [
                "The page bar hides at the top middle of the screen: rest the pointer there to "
                "see it. Right-click it for the menu (" + k("New Page…") + ", Settings).",
                "Switch pages with Ctrl + Left / Right (while the desktop is in front), the mouse "
                "wheel over a title bar, a sideways touchpad swipe, or by pulling the left or "
                "right screen edge.",
                k("Ctrl + Up") + " shows all your pages: click one or press its number.",
                "Page bar menu › " + k("Manage Pages…") + " (or " + k("Ctrl + Super + M") +
                " from any window): click a page to rename or delete it, or drag the pages "
                "into the order you want.",
                "Click a dot on the page bar to go to that page; double-click the page name "
                "for Manage Pages.",
                "Drag a cubby against the left or right edge to carry it to the next page."])
            sec = self.s_section(box, "The page bar your way")
            self.s_bullets(sec, [
                "Drag it by its name to put it anywhere, or move it to the bottom of the "
                "screen.",
                "Keep it always showing, or hidden until you press a key (Ctrl + Alt + P).",
                "All in Settings › Desktop Pages › Page bar. Each page's wallpaper, picture "
                "aspect, background colour and default cubby look: Manage Pages › click "
                "the page › its gear."])
        elif key == "launch":
            sw, box = self.s_page("Launch Bar Cubbies", "Your favourite apps along the edge of "
                                  "the screen, out of sight until you want them.",
                                  self.s_preview("launchbar"))
            sec = self.s_section(box, "Making and filling one")
            self.s_bullets(sec, [
                "Right-click the page bar › " + k("New Cubby") + " › "
                + k("Launch Bar Cubby") + " (or Settings › Launch Bar Cubbies).",
                "Drag apps from the menu onto it, or right-click it › Add Applications…",
                "One click opens an app."])
            sec = self.s_section(box, "Using it")
            self.s_bullets(sec, [
                "Push the pointer against the top of the screen and it slides out; move away "
                "and it slides back. Or set it to come out when you click the edge.",
                "The corners stay free, so it won't pop out when you go for a window's close "
                "button.",
                "Pages can share a launch bar or have their own: work apps on one page, media "
                "on another."])
            self.s_note(sec, "Its size, icons, edge and hiding: Settings › Launch Bar "
                             "Cubbies.")
        elif key == "sort":
            sw, box = self.s_page("Sorting New Files", "New files that land on the desktop go "
                                  "straight into the right cubby.",
                                  self.s_preview("cubby", title="Inbox"))
            sec = self.s_section(box, "How it works")
            self.s_bullets(sec, [
                "Right-click a cubby › " + k("Collect Certain Kinds of Files…") + " "
                "and tick what it takes: images, documents, music, videos, archives, folders "
                "or everything else.",
                "An " + k("Inbox Cubby") + " takes everything no other cubby collects.",
                "Tick " + k("Mounted drives") + " and USB sticks, discs and network shares "
                "appear in that cubby while they're plugged in."])
            sec = self.s_section(box, "Page by page")
            self.s_bullets(sec, [
                "Each page can have its own Inbox: a file goes to the one on the page you're "
                "on.",
                "Pages without their own can use another page's, so one Inbox can serve most "
                "pages."])
            self.s_note(sec, "All of it in Settings › Sorting & Organising.")
        elif key == "tabs":
            sw, box = self.s_page("Tabs", "Combine cubbies into one, with a tab for each.",
                                  self.s_preview("tabs"))
            sec = self.s_section(box, "Using tabs")
            self.s_bullets(sec, [
                "Drag a cubby's title bar onto another cubby's title bar to combine them.",
                "Drag a tab to move the whole cubby. " + k("Ctrl") + " + drag a tab to put it "
                "in another place in the row, or out of the row to make it a cubby of its own.",
                "Click the shown tab again (slowly) to rename it.",
                "Right-click a tab › " + k("Tab Colour…") + " gives it its own colour (the "
                "cubby takes it while that tab is shown), or " + k("Tab Font…") + ".",
                "Tabs share the title bar's width and always show their whole names "
                "(Settings › Tabbed Cubbies › Tab widths)."])
        elif key == "hide":
            sw, box = self.s_page("Hiding and Glance", "Out of the way when you need room; "
                                  "within reach when your windows cover them.",
                                  self.s_preview("hide"))
            sec = self.s_section(box, "Two quick moves")
            self.s_bullets(sec, [
                k("Quick-hide") + ": double-click the empty desktop to hide every cubby. "
                "Double-click again to bring them back.",
                k("Glance") + ": press Super + Space for a panel over your windows with "
                "the icons of all your cubbies: click one to open it, or drag it into an "
                "app. Press it again, Escape, or click elsewhere to close it."])
        else:
            sw, box = self.s_page("Handy Extras", "A few things worth knowing.",
                                  self.s_preview("cubby", title="Extras"))
            sec = self.s_section(box, "Good to know")
            self.s_bullets(sec, [
                "Made a mistake? Ctrl + Z over a cubby (or Undo in its menu) takes back the "
                "last move, rename or delete.",
                "Dropping a file into a Folder Cubby where one of the same name exists asks "
                "first: Replace, Keep Both, Rename or Skip.",
                "Settings › " + k("Backup & Restore") + " keeps copies of everything (now, "
                "or automatically every day or week) and restores any of them.",
                "Press F5 on the desktop to refresh the cubbies too.",
                "Save where everything sits as a " + k("layout") + " and put it back in one "
                "click (Settings › Command Line).",
                "Everything can be done from a terminal or your own keyboard shortcuts: "
                "<tt>cubbies --help</tt> lists the commands.",
                "Deleting files from a network folder deletes them for good (there is no "
                "Trash there); Cubbies always asks first."])
            sec = self.s_section(box, "Where things are")
            self.s_bullets(sec, [
                "Settings: right-click the page bar › Settings.",
                "This guide: Settings › Home › Open the Welcome Guide."])
        return sw

    def show_welcome(self):
        """The Welcome Guide: the basics in short topics, laid out like Settings."""
        css = Gtk.CssProvider()
        try:
            css.load_from_data(self.SETTINGS_CSS)
            Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css,
                                                     Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        except GLib.Error as exc:
            dbg("welcome css:", exc)
        dlg = Gtk.Dialog(title="Welcome to Cubbies")
        dlg.set_position(Gtk.WindowPosition.CENTER)
        dlg.set_keep_above(True)
        dlg.set_resizable(False)
        dlg.set_size_request(880, 600)
        area = dlg.get_content_area()
        area.set_border_width(0)
        area.set_spacing(0)
        body = Gtk.Box()
        area.pack_start(body, True, True, 0)
        side = Gtk.ListBox()
        side.get_style_context().add_class("cb-settings-side")
        side.set_size_request(220, -1)
        body.pack_start(side, False, False, 0)
        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        stack.set_transition_duration(120)
        stack.get_style_context().add_class("cb-settings-body")
        body.pack_start(stack, True, True, 0)
        rows = []
        for n, (key, label) in enumerate(self.WELCOME_TOPICS, 1):
            row = Gtk.ListBoxRow()
            lbl = Gtk.Label(label=f"{n}.  {label}", xalign=0)
            row.add(lbl)
            row.key = key
            side.add(row)
            rows.append(row)
            try:
                stack.add_named(self.welcome_page(key), key)
            except Exception:
                import traceback
                traceback.print_exc()
                stack.add_named(Gtk.Label(label="(could not show this topic)"), key)

        # the buttons along the bottom
        foot = Gtk.Box(spacing=8)
        foot.set_border_width(10)
        back = Gtk.Button(label="\u2039 Back")
        nxt = Gtk.Button(label="Next \u203a")
        make = Gtk.Button(label="Create My First Cubby")
        settings = Gtk.Button(label="Settings")
        close = Gtk.Button(label="Close")
        foot.pack_start(back, False, False, 0)
        foot.pack_start(nxt, False, False, 0)
        foot.pack_end(close, False, False, 0)
        foot.pack_end(settings, False, False, 0)
        foot.pack_end(make, False, False, 0)
        make.get_style_context().add_class("suggested-action")
        area.pack_start(Gtk.Separator(), False, False, 0)
        area.pack_start(foot, False, False, 0)

        def current():
            row = side.get_selected_row()
            return rows.index(row) if row in rows else 0

        def selected(_l, row):
            if row is None:
                return
            stack.set_visible_child_name(row.key)
            i = rows.index(row)
            back.set_sensitive(i > 0)
            nxt.set_sensitive(i < len(rows) - 1)
        side.connect("row-selected", selected)
        back.connect("clicked", lambda _b: side.select_row(rows[max(0, current() - 1)]))
        nxt.connect("clicked", lambda _b: side.select_row(rows[min(len(rows) - 1, current() + 1)]))
        make.connect("clicked", lambda _b: dlg.response(Gtk.ResponseType.YES))
        settings.connect("clicked", lambda _b: dlg.response(Gtk.ResponseType.APPLY))
        close.connect("clicked", lambda _b: dlg.response(Gtk.ResponseType.OK))
        dlg.show_all()
        side.select_row(rows[0])
        self._welcome_dlg = dlg
        self.pager.flash(120000)   # keep the page bar showing while this is open
        resp = dlg.run()
        dlg.destroy()
        self._welcome_dlg = None
        Gtk.StyleContext.remove_provider_for_screen(Gdk.Screen.get_default(), css)
        self.pager._reveal_until = GLib.get_monotonic_time() // 1000 + 4000
        if resp == Gtk.ResponseType.YES:
            self.new_cubby()
        elif resp == Gtk.ResponseType.APPLY:
            GLib.idle_add(lambda: self.open_settings() and False)
