"""Small ready-made dialogs: ask for a line of text, confirm, tell."""

from gi.repository import Gtk


def ask(title, default=""):
    dlg = Gtk.Dialog(title=title)
    dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "OK", Gtk.ResponseType.OK)
    dlg.set_default_response(Gtk.ResponseType.OK)
    entry = Gtk.Entry(text=default)
    entry.set_activates_default(True)
    area = dlg.get_content_area()
    area.set_border_width(12)
    area.add(entry)
    dlg.show_all()
    resp = dlg.run()
    text = entry.get_text().strip()
    dlg.destroy()
    return text if resp == Gtk.ResponseType.OK and text else None


def confirm(title, secondary, ok_label):
    dlg = Gtk.MessageDialog(message_type=Gtk.MessageType.QUESTION, text=title,
                            secondary_text=secondary)
    dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, ok_label, Gtk.ResponseType.OK)
    if "Permanently" in ok_label:
        btn = dlg.get_widget_for_response(Gtk.ResponseType.OK)
        if btn is not None:
            btn.get_style_context().add_class("destructive-action")
    dlg.set_default_response(Gtk.ResponseType.CANCEL)
    dlg.set_keep_above(True)
    resp = dlg.run()
    dlg.destroy()
    return resp == Gtk.ResponseType.OK


def tell(title, secondary):
    """A message with just an OK button."""
    dlg = Gtk.MessageDialog(message_type=Gtk.MessageType.WARNING, text=title,
                            secondary_text=secondary, buttons=Gtk.ButtonsType.OK)
    dlg.set_keep_above(True)
    dlg.run()
    dlg.destroy()
