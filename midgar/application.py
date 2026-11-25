"""Application entry point."""

from __future__ import annotations

import sys
from importlib import resources

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, APP_NAME, paths  # noqa: E402
from .store import LibraryError, Store  # noqa: E402


class MidgarApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        GLib.set_application_name(APP_NAME)
        self.store: Store | None = None
        self.window = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        provider = Gtk.CssProvider()
        css = resources.files("midgar").joinpath("style.css").read_text(encoding="utf-8")
        provider.load_from_string(css) if hasattr(provider, "load_from_string") else provider.load_from_data(css, -1)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._install_icon_path()

        quit_action = Gio.SimpleAction(name="quit")
        quit_action.connect("activate", lambda *_a: self.window.close() if self.window else self.quit())
        self.add_action(quit_action)
        for action, accels in (("app.quit", ["<Control>q"]), ("win.new-book", ["<Control>n"]),
                               ("win.search", ["<Control>f"]), ("win.shortcuts", ["<Control>question"]),
                               ("win.backup", ["<Control><Shift>b"])):
            self.set_accels_for_action(action, accels)

    def _install_icon_path(self):
        """When running from a source checkout, make the bundled icons resolvable."""
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        try:
            src_icons = resources.files("midgar").joinpath("..", "data", "icons")
            if src_icons.is_dir():
                theme.add_search_path(str(src_icons))
        except (OSError, TypeError, ValueError):
            pass

    def do_activate(self):
        if self.window:
            self.window.present()
            return
        try:
            self.store = Store(paths.library_path())
        except LibraryError as err:
            self._fatal(str(err))
            return
        try:
            self.store.gc_images()
            self.store.snapshot(paths.snapshot_dir(), keep=7)
        except Exception as err:  # noqa: BLE001 — never block startup on housekeeping
            print(f"midgar: housekeeping skipped: {err}", file=sys.stderr)
        from .window import MainWindow
        self.window = MainWindow(self, self.store)
        self.window.present()

    def _fatal(self, message: str):
        win = Adw.ApplicationWindow(application=self, default_width=480, default_height=320)
        page = Adw.StatusPage(icon_name="dialog-error-symbolic", title="Library Unavailable", description=message)
        win.set_content(page)
        win.present()

    def do_shutdown(self):
        if self.store:
            self.store.close()
        Adw.Application.do_shutdown(self)


def main() -> int:
    return MidgarApp().run(sys.argv)
