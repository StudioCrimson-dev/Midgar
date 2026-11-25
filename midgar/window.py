"""Main window: navigation between library → book → editor, plus library-wide actions."""

from __future__ import annotations

import datetime as dt

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, APP_NAME, VERSION, paths  # noqa: E402
from .book_dialog import BookDialog  # noqa: E402
from .book_page import BookPage  # noqa: E402
from .editor_page import EditorPage  # noqa: E402
from .images import TextureCache, prepare_image  # noqa: E402
from .library_page import LibraryPage  # noqa: E402
from .store import LibraryError  # noqa: E402
from .transfer import export_zip, import_markdown, import_zip, safe_name  # noqa: E402
from .ui import (BACKUP_FILTER, MARKDOWN_FILTER, ZIP_FILTER, confirm, pick_files,  # noqa: E402
                 pick_save, plural, read_file)

SHORTCUTS = [
    ("General", [("Ctrl+N", "New book"), ("Ctrl+F", "Search the library"), ("Ctrl+Q", "Quit"),
                 ("F10", "Main menu"), ("Ctrl+?", "Keyboard shortcuts")]),
    ("Reading", [("Alt+← / Alt+→", "Previous / next chapter"), ("Ctrl+E", "Edit chapter"),
                 ("Ctrl+Shift+N", "New chapter"), ("Ctrl+I", "Import Markdown"),
                 ("Alt+↑ / Alt+↓", "Move chapter up / down"), ("Ctrl+= / Ctrl+-", "Text size"),
                 ("F9", "Toggle sidebar"), ("Delete", "Delete selected chapter")]),
    ("Writing", [("Ctrl+S", "Save"), ("Ctrl+P", "Toggle preview"), ("Ctrl+B / Ctrl+I", "Bold / italic"),
                 ("Ctrl+K", "Insert link"), ("Ctrl+Shift+I", "Insert pictures"),
                 ("Esc / Ctrl+W", "Close editor")]),
]


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app, store):
        super().__init__(application=app, title=APP_NAME)
        self.store = store
        self.textures = TextureCache(store)
        self.set_size_request(360, 420)
        w = int(store.get_setting("window.width", "1180") or 1180)
        h = int(store.get_setting("window.height", "780") or 780)
        self.set_default_size(w, h)
        if store.get_setting("window.maximized") == "1":
            self.maximize()

        self.nav = Adw.NavigationView()
        self.toasts = Adw.ToastOverlay(child=self.nav)
        self.set_content(self.toasts)
        self.library = LibraryPage(self)
        self.nav.add(self.library)

        for name, cb in (("new-book", self.new_book), ("search", self.focus_search),
                         ("backup", self.backup), ("restore", self.restore),
                         ("export-library", lambda: self.export_books(None, "Midgar Library")),
                         ("import-zip", self.import_zip), ("open-data-folder", self.open_data_folder),
                         ("shortcuts", self.show_shortcuts), ("about", self.show_about)):
            act = Gio.SimpleAction(name=name)
            act.connect("activate", lambda _a, _p, cb=cb: cb())
            self.add_action(act)

        self.connect("close-request", self._on_close_request)

    # ── navigation ───────────────────────────────────────────
    def _editor(self) -> EditorPage | None:
        page = self.nav.get_visible_page()
        return page if isinstance(page, EditorPage) else None

    def _book_page(self) -> BookPage | None:
        stack = self.nav.get_navigation_stack()
        for i in range(stack.get_n_items() - 1, -1, -1):
            p = stack.get_item(i)
            if isinstance(p, BookPage):
                return p
        return None

    def open_book(self, book_id: str, chapter_id: str | None = None):
        if self._editor():
            return
        page = self._book_page()
        if page and page.book_id == book_id:
            page.current_id = chapter_id or page.current_id
            self.nav.pop_to_page(page)
            page.reload()
            return
        self.nav.pop_to_tag("library")
        self.nav.push(BookPage(self, book_id, chapter_id))

    def open_editor(self, book_id: str, chapter_id: str | None):
        if self._editor():
            return
        self.nav.push(EditorPage(self, book_id, chapter_id))

    def close_editor(self, chapter_id: str | None):
        page = self._book_page()
        if page and chapter_id:
            page.current_id = chapter_id
        self.nav.pop()

    def focus_search(self):
        if self._editor():
            return
        self.nav.pop_to_tag("library")
        self.library.focus_search()

    def toast(self, message: str, timeout: int = 3):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(message), timeout=timeout))

    def _refresh_visible(self):
        page = self.nav.get_visible_page()
        if hasattr(page, "reload"):
            page.reload()

    # ── books ────────────────────────────────────────────────
    def new_book(self):
        if self._editor():
            return
        BookDialog(self, None, lambda book: (self.library.reload(), self.open_book(book.id))).present(self)

    def edit_book(self, book_id: str):
        book = self.store.get_book(book_id)
        if book:
            BookDialog(self, book, lambda _b: self._refresh_visible()).present(self)

    def delete_book(self, book_id: str):
        book = self.store.get_book(book_id)
        if not book:
            return

        def go():
            self.store.delete_book(book_id)
            self.nav.pop_to_tag("library")
            self.library.reload()
            self.toast(f"Deleted “{book.title}”")

        what = plural(book.chapter_count, "chapter")
        confirm(self, f"Delete “{book.title}”?",
                f"The book, its {what} and all of its pictures will be removed permanently. "
                "Consider exporting it first.", "Delete Book", go)

    # ── import / export ─────────────────────────────────────
    def import_markdown(self, book_id: str):
        def chosen(files):
            payload = [read_file(f) for f in files]
            res = import_markdown(self.store, book_id, payload, prepare_image)
            if not res.chapters:
                self.toast(res.errors[0] if res.errors else "Nothing was imported")
                return
            msg = f"Imported {plural(len(res.chapters), 'chapter')}"
            if res.unmatched_images:
                msg += f" — {plural(res.unmatched_images, 'picture')} not found; select pictures together " \
                       "with the Markdown files to include them"
            elif res.errors:
                msg += f" — {plural(len(res.errors), 'file')} skipped"
            page = self._book_page()
            if page:
                page.current_id = res.chapters[0].id
                page.reload()
            self.toast(msg, timeout=6)

        pick_files(self, "Import Markdown", MARKDOWN_FILTER, chosen)

    def export_books(self, book_ids: list[str] | None, name: str):
        if not self.store.list_books():
            self.toast("There's nothing to export yet")
            return

        def chosen(f: Gio.File):
            try:
                n = export_zip(self.store, f.get_path(), book_ids)
            except OSError as err:
                self.toast(f"Export failed: {err.strerror or err}")
                return
            self.toast(f"Exported {plural(n, 'book')} to {f.get_basename()}")

        pick_save(self, "Export as Markdown", f"{safe_name(name, 'Midgar')}.zip", ZIP_FILTER, chosen)

    def import_zip(self):
        def chosen(files):
            try:
                books, res = import_zip(self.store, files[0].get_path(), prepare_image)
            except Exception as err:  # noqa: BLE001 — bad zip, etc.
                self.toast(f"Couldn't read that file: {err}")
                return
            if not books:
                self.toast(res.errors[0] if res.errors else "No books found in that file")
                return
            self.library.reload()
            self.toast(f"Imported {plural(len(books), 'book')} ({plural(len(res.chapters), 'chapter')})")

        pick_files(self, "Import Books from Export", ZIP_FILTER, chosen, multiple=False)

    # ── backup / restore ─────────────────────────────────────
    def backup(self):
        stamp = dt.date.today().isoformat()

        def chosen(f: Gio.File):
            try:
                self.store.backup_to(f.get_path())
            except Exception as err:  # noqa: BLE001
                self.toast(f"Backup failed: {err}")
                return
            self.toast(f"Library backed up to {f.get_basename()}")

        pick_save(self, "Back Up Library", f"Midgar Backup {stamp}.midgar", BACKUP_FILTER, chosen)

    def restore(self):
        if self._editor():
            return

        def chosen(files):
            path = files[0].get_path()
            try:
                self.store.validate_backup(path)
            except LibraryError as err:
                self.toast(str(err))
                return

            def go():
                try:
                    safety = self.store.restore_from(path, paths.safety_dir())
                except Exception as err:  # noqa: BLE001
                    self.toast(f"Restore failed: {err}")
                    return
                self.textures = TextureCache(self.store)
                self.nav.pop_to_tag("library")
                self.library.reload()
                self.toast(f"Library restored. Your previous library was kept as {safety.name}", timeout=8)

            confirm(self, "Replace Your Library?",
                    "Everything currently in Midgar will be replaced by the contents of this backup. "
                    "A safety copy of your current library is saved first.", "Restore", go)

        pick_files(self, "Restore from Backup", BACKUP_FILTER, chosen, multiple=False)

    def open_data_folder(self):
        launcher = Gtk.FileLauncher(file=Gio.File.new_for_path(str(paths.data_dir())))
        launcher.launch(self, None, None, None)

    # ── info dialogs ─────────────────────────────────────────
    def show_shortcuts(self):
        dlg = Adw.Dialog(title="Keyboard Shortcuts", content_width=520, content_height=640)
        page = Adw.PreferencesPage()
        for title, items in SHORTCUTS:
            group = Adw.PreferencesGroup(title=title)
            for keys, label in items:
                row = Adw.ActionRow(title=label)
                k = Gtk.Label(label=keys)
                k.add_css_class("dim-label")
                k.add_css_class("monospace")
                row.add_suffix(k)
                group.add(row)
            page.add(group)
        tv = Adw.ToolbarView(content=page)
        tv.add_top_bar(Adw.HeaderBar())
        dlg.set_child(tv)
        dlg.present(self)

    def show_about(self):
        s = self.store.stats()
        about = Adw.AboutDialog(
            application_name=APP_NAME, application_icon=APP_ID, version=VERSION,
            developer_name="Studio Crimson",
            comments="A private, offline library for writing and reading your own books.",
            issue_url="https://github.com/StudioCrimson-dev/The-Library/issues",
            website="https://github.com/StudioCrimson-dev/The-Library",
            debug_info=(f"Library: {self.store.path}\nBooks: {s['books']}\nChapters: {s['chapters']}\n"
                        f"Pictures: {s['images']}\nSize: {s['bytes'] / 1_048_576:.1f} MiB\n"
                        f"Snapshots: {paths.snapshot_dir()}\n"),
            debug_info_filename="midgar-debug-info.txt",
        )
        about.present(self)

    # ── closing ──────────────────────────────────────────────
    def _save_geometry(self):
        if not self.is_maximized():
            w, h = self.get_default_size()
            self.store.set_setting("window.width", str(w))
            self.store.set_setting("window.height", str(h))
        self.store.set_setting("window.maximized", "1" if self.is_maximized() else "0")

    def _on_close_request(self, *_a):
        editor = self.nav.find_page("editor")
        if editor is not None and editor.dirty:
            if self.nav.get_visible_page() is not editor:
                self.nav.pop_to_page(editor)
            editor.request_close(then=self.close)
            return True
        self._save_geometry()
        return False
