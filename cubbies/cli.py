"""The command line: one table drives  cubbies --help  and the Settings page."""

from .constants import VERSION
from .desktop_env import IS_MATE, IS_XFCE


# ---- the command line: one table drives  cubbies --help  and the Settings page
CLI_COMMANDS = [
    ("Showing and hiding", [
        ("--toggle", "", "Hide or show all cubbies (Quick-hide)"),
        ("--hide", "", "Hide all cubbies"),
        ("--show", "", "Show all cubbies"),
        ("--glance", "", "Open the Glance panel (your cubbies' icons over your windows)"),
        ("--manage-pages", "", "Open (or close) Manage Pages: rename, delete and re-order"),
        ("--refresh", "", "Refresh every cubby (the same as F5 on the desktop)"),
    ]),
    ("Pages", [
        ("--next-page", "", "Go to the next page"),
        ("--prev-page", "", "Go to the previous page"),
        ("--page", "NUMBER|NAME", "Go to a page by its number (1 is the first) or its name"),
        ("--list", "", "List the pages and the cubbies on each"),
        ("--page-bar", "", "Show the page bar (or hide it again)"),
    ]),
    ("Cubbies", [
        ("--new-cubby", "[TITLE]", "Make a new cubby on the current page"),
        ("--new-launch-bar", "", "Make a Launch Bar Cubby (if this page has none yet)"),
        ("--add-folder", "FOLDER…", "Show folders as Folder Cubbies (starts Cubbies if needed)"),
        ("--lock-all", "", "Lock every cubby in place"),
        ("--unlock-all", "", "Unlock them again"),
    ]),
    ("Layouts", [
        ("--save-layout", "NAME", "Remember where every cubby is, under a name"),
        ("--restore-layout", "NAME", "Put every cubby back where that layout had it"),
        ("--list-layouts", "", "List the saved layouts"),
        ("--delete-layout", "NAME", "Forget a saved layout"),
    ]),
    ("Backups", [
        ("--backup", "[FILE]", "Back up everything (to the backups folder if no file is given)"),
        ("--restore", "FILE", "Restore a backup (Cubbies restarts)"),
    ]),
    ("The program", [
        ("--settings", "", "Open the Settings window"),
        ("--restart", "", "Restart Cubbies"),
        ("--quit", "", "Close Cubbies"),
        ("--install-autostart", "", "Start Cubbies when you log in"),
        ("--remove-autostart", "", "Stop starting it at login"),
        ("--version", "", "Show the version number"),
        ("--help", "", "Show this list"),
    ]),
]


def cli_help():
    lines = [f"Cubbies {VERSION} - a desktop organiser", "",
             "Usage: cubbies [COMMAND]", "Run with no command to start Cubbies.", ""]
    for group, cmds in CLI_COMMANDS:
        lines.append(group + ":")
        for flag, arg, text in cmds:
            left = f"  {flag} {arg}".rstrip()
            lines.append(f"{left:<34}{text}")
        lines.append("")
    lines += ["Most commands talk to the running Cubbies. Bind them to keys in",
              ("Settings Manager > Keyboard > Application Shortcuts." if IS_XFCE else
               "Control Center > Keyboard Shortcuts." if IS_MATE else
               "System Settings > Keyboard > Shortcuts > Custom Shortcuts."), "",
              "Debug output:  CUBBIES_DEBUG=1 cubbies"]
    return "\n".join(lines)


def cli_list(cfg):
    lines = []
    for i, page in enumerate(cfg["pages"], 1):
        cur = "  (current)" if i - 1 == cfg.get("page", 0) else ""
        lines.append(f"{i}. {page['name']}{cur}")
        for f in page["cubbies"]:
            if f.get("tab_of"):
                continue
            panes = ([t for t in page["cubbies"] if t.get("tab_of") == f["id"]]
                     if f.get("group") else [f])
            for t in panes:
                kind = ("folder " + t["folder"] if t.get("folder")
                        else "inbox" if "other" in t.get("collect", [])
                        else f"{len(t.get('items', []))} items")
                extra = [w for w, k in (("tab", f.get("group")), ("rolled up", f.get("rolled")),
                                        ("locked", f.get("locked")),
                                        ("every page", f.get("all_pages"))) if k]
                lines.append(f"   - {t['title']}  [{kind}]"
                             + (f"  ({', '.join(extra)})" if extra else ""))
        if not page["cubbies"]:
            lines.append("   (no cubbies)")
    return "\n".join(lines)
