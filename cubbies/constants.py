"""Fixed values shared across Cubbies: the version, style keys, views, file kinds."""


DEFAULT_RADIUS = 10
MAX_RADIUS = 30
# Styling Options › Share this look: the parts that can be copied to other cubbies
SHARE_PARTS = (("color", "Background colour", ("color",)),
               ("opacity", "Transparency", ("opacity",)),
               ("radius", "Corner roundness", ("radius",)),
               ("border_width", "Border width", ("border_width",)),
               ("border_color", "Border colour", ("border_color",)),
               ("blur", "Background blur", ("blur", "blur_level", "blur_strength")),
               ("title_font", "Title font and size", ("title_font",)),
               ("title_height", "Title bar height", ("title_height",)),
               ("title_align", "Title alignment", ("title_align",)),
               ("tab_font", "Tab font", ("tab_font",)))
STYLE_KEYS = ("color", "opacity", "radius", "title_font", "title_height",
              "border_width", "border_color", "show_buttons", "show_add", "show_gear",
              "blur", "blur_level", "blur_strength")
BLUR_KEYS = ("blur", "blur_level", "blur_strength")   # a cubby's own, else its page's, else
BUTTON_KEYS = ("show_buttons", "show_add", "show_gear")   # show_buttons: older, both at once
MAX_BORDER = 8
DEFAULT_BORDER_COLOR = "rgba(255,255,255,0.75)"
TITLE_ALIGNS = {"left": 0.0, "center": 0.5, "right": 1.0}
GEOMETRY_KEYS = ("x", "y", "w", "h", "rolled")
MAX_FOLDER_ITEMS = 400
VERSION = "1.20.4"
MIN_ICON, MAX_ICON, DEFAULT_ICON = 24, 256, 48
ICON_GAP = 6          # px between columns of icons
# a line along the inner edge of a launch bar (its bottom, or its top at the screen bottom)
LINE_KEYS = ("line_width", "line_color", "line_style")
LINE_STYLES = (("solid", "Solid"), ("dashed", "Dashed"), ("dotted", "Dotted"),
               ("dashdot", "Dash and dot"), ("double", "Double"))
VIEWS = (("icons", "Icons"), ("list", "List"), ("details", "Details"))
CATEGORY_EXTS = {
    "images": "png jpg jpeg gif bmp webp svg tif tiff ico heic avif xcf psd raw cr2 nef",
    "documents": "pdf doc docx odt rtf txt md epub xls xlsx ods csv ppt pptx odp tex "
                 "pages numbers key",
    "music": "mp3 flac ogg oga opus wav m4a aac wma aiff mid midi",
    "videos": "mp4 mkv avi mov wmv webm flv m4v mpg mpeg ogv 3gp",
    "archives": "zip tar gz tgz bz2 xz 7z rar zst iso deb rpm appimage",
}
CATEGORY_EXTS = {k: set(v.split()) for k, v in CATEGORY_EXTS.items()}
COLLECT_CHOICES = (("images", "Images"), ("documents", "Documents"), ("music", "Music"),
                   ("videos", "Videos"), ("archives", "Archives and installers"),
                   ("folders", "Folders"), ("drives", "Mounted drives (USB, discs, network)"),
                   ("other", "Everything else"))
# Short names for the tabs any cubby can show under its title bar.
KIND_LABELS = {"images": "Images", "documents": "Documents", "music": "Music",
               "videos": "Videos", "archives": "Archives", "folders": "Folders",
               "drives": "Drives", "other": "Other"}
INBOX_ICONS = ("mail-inbox", "folder-download", "emblem-downloads", "go-down")
IGNORED_SUFFIXES = (".part", ".crdownload", ".tmp", ".download", ".partial", ".swp", "~")


NETWORK_FS = {"cifs", "smb3", "smbfs", "nfs", "nfs4", "afs", "ncpfs", "9p", "ceph", "glusterfs",
              "davfs", "fuse.gvfsd-fuse", "fuse.sshfs", "fuse.rclone", "fuse.davfs2",
              "fuse.smbnetfs", "fuse.curlftpfs", "fuse.s3fs"}
