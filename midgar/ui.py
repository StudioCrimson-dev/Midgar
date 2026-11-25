"""Small shared UI helpers: dialogs, file pickers, labels."""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def counts_label(regular: int, info: int) -> str:
    text = plural(regular, "chapter")
    if info:
        text += f" · {info} info"
    return text


def confirm(parent: Gtk.Widget, heading: str, body: str, action_label: str,
            on_confirm: Callable[[], None], destructive: bool = True) -> None:
    dlg = Adw.AlertDialog(heading=heading, body=body)
    dlg.add_response("cancel", "Cancel")
    dlg.add_response("ok", action_label)
    dlg.set_response_appearance(
        "ok", Adw.ResponseAppearance.DESTRUCTIVE if destructive else Adw.ResponseAppearance.SUGGESTED)
    dlg.set_default_response("cancel")
    dlg.set_close_response("cancel")
    dlg.connect("response", lambda _d, r: on_confirm() if r == "ok" else None)
    dlg.present(parent)


def _filter(name: str, patterns: list[str] = (), mimes: list[str] = ()) -> Gtk.FileFilter:
    f = Gtk.FileFilter(name=name)
    for p in patterns:
        f.add_pattern(p)
    for m in mimes:
        f.add_mime_type(m)
    return f


def _filters(*filters: Gtk.FileFilter) -> Gio.ListStore:
    store = Gio.ListStore.new(Gtk.FileFilter)
    for f in filters:
        store.append(f)
    return store


IMAGE_FILTER = ("Images", [], ["image/png", "image/jpeg", "image/webp", "image/gif", "image/svg+xml"])
MARKDOWN_FILTER = ("Markdown and images",
                   ["*.md", "*.markdown", "*.mdown", "*.txt", "*.MD"],
                   ["text/markdown", "image/png", "image/jpeg", "image/webp", "image/gif", "image/svg+xml"])
BACKUP_FILTER = ("Midgar backups", ["*.midgar", "*.db"], [])
ZIP_FILTER = ("Zip archives", ["*.zip"], ["application/zip"])


def _cancelled(err: GLib.Error) -> bool:
    return err.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED) or \
        err.matches(Gtk.dialog_error_quark(), Gtk.DialogError.CANCELLED)


def pick_files(window: Gtk.Window, title: str, flt: tuple, callback: Callable[[list[Gio.File]], None],
               multiple: bool = True) -> None:
    dlg = Gtk.FileDialog(title=title, modal=True, filters=_filters(_filter(*flt)))

    def done(d, res):
        try:
            if multiple:
                model = d.open_multiple_finish(res)
                files = [model.get_item(i) for i in range(model.get_n_items())]
            else:
                files = [d.open_finish(res)]
        except GLib.Error as err:
            if not _cancelled(err):
                raise
            return
        if files:
            callback(files)

    (dlg.open_multiple if multiple else dlg.open)(window, None, done)


def pick_save(window: Gtk.Window, title: str, initial_name: str, flt: tuple,
              callback: Callable[[Gio.File], None]) -> None:
    dlg = Gtk.FileDialog(title=title, modal=True, initial_name=initial_name, filters=_filters(_filter(*flt)))

    def done(d, res):
        try:
            f = d.save_finish(res)
        except GLib.Error as err:
            if not _cancelled(err):
                raise
            return
        if f:
            callback(f)

    dlg.save(window, None, done)


def read_file(f: Gio.File) -> tuple[str, bytes]:
    ok, data, _etag = f.load_contents(None)
    return f.get_basename() or "file", bytes(data)


def shortcut(widget: Gtk.Widget, accel: str, handler: Callable[[], bool | None],
             scope: Gtk.ShortcutScope = Gtk.ShortcutScope.LOCAL) -> None:
    """Attach a keyboard shortcut handled while focus is inside ``widget``."""
    ctrl = getattr(widget, "_midgar_shortcuts", None)
    if ctrl is None:
        ctrl = Gtk.ShortcutController(scope=scope)
        widget.add_controller(ctrl)
        widget._midgar_shortcuts = ctrl

    def cb(*_a):
        res = handler()
        return True if res is None else bool(res)

    ctrl.add_shortcut(Gtk.Shortcut(trigger=Gtk.ShortcutTrigger.parse_string(accel),
                                   action=Gtk.CallbackAction.new(cb)))
