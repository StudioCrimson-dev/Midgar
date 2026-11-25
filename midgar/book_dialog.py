"""New / Edit Book dialog."""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .images import prepare_image  # noqa: E402
from .library_page import make_cover  # noqa: E402
from .store import Book  # noqa: E402
from .ui import IMAGE_FILTER, pick_files, read_file, shortcut  # noqa: E402


class BookDialog(Adw.Dialog):
    def __init__(self, win, book: Book | None, on_saved: Callable[[Book], None]):
        super().__init__(title="Edit Book" if book else "New Book", content_width=600)
        self.win, self.store, self.book, self.on_saved = win, win.store, book, on_saved
        self.cover_id = book.cover_id if book else None
        self.session_images: set[str] = set()
        self.saved = False

        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_a: self.close())
        header.pack_start(cancel)
        self.save_btn = Gtk.Button(label="Save" if book else "Create")
        self.save_btn.add_css_class("suggested-action")
        self.save_btn.connect("clicked", lambda *_a: self.save())
        header.pack_end(self.save_btn)

        # cover
        self.cover_btn = Gtk.Button(tooltip_text="Choose a cover picture", valign=Gtk.Align.START)
        self.cover_btn.add_css_class("flat")
        self.cover_btn.add_css_class("cover-picker")
        self.cover_btn.connect("clicked", lambda *_a: self.pick_cover())
        self.remove_btn = Gtk.Button(label="Remove Cover", halign=Gtk.Align.CENTER)
        self.remove_btn.add_css_class("flat")
        self.remove_btn.connect("clicked", lambda *_a: self.set_cover(None))
        change = Gtk.Button(label="Choose Cover…", halign=Gtk.Align.CENTER)
        change.connect("clicked", lambda *_a: self.pick_cover())
        cover_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        cover_col.append(self.cover_btn)
        cover_col.append(change)
        cover_col.append(self.remove_btn)

        # fields
        group = Adw.PreferencesGroup()
        self.title_row = Adw.EntryRow(title="Title")
        self.title_row.set_text(book.title if book else "")
        self.title_row.connect("entry-activated", lambda *_a: self.save())
        self.title_row.connect("changed", lambda *_a: self._validate())
        group.add(self.title_row)

        desc_group = Adw.PreferencesGroup(title="Description", description="Optional — shown in the book's sidebar")
        self.desc = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=10, bottom_margin=10,
                                 left_margin=12, right_margin=12, accepts_tab=False)
        self.desc.get_buffer().set_text(book.description if book else "")
        frame = Gtk.ScrolledWindow(child=self.desc, min_content_height=130, max_content_height=220,
                                   propagate_natural_height=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        frame.add_css_class("card")
        frame.set_overflow(Gtk.Overflow.HIDDEN)
        desc_group.add(frame)

        fields = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, hexpand=True)
        fields.append(group)
        fields.append(desc_group)

        body = Gtk.Box(spacing=24, margin_top=12, margin_bottom=24, margin_start=24, margin_end=24)
        body.append(cover_col)
        body.append(fields)

        tv = Adw.ToolbarView(content=body)
        tv.add_top_bar(header)
        self.set_child(tv)
        self.set_default_widget(self.save_btn)
        self.set_focus(self.title_row)
        shortcut(self, "<Control>Return", self.save)
        self._refresh_cover()
        self._validate()
        self.connect("closed", self._on_closed)

    def _validate(self):
        self.save_btn.set_sensitive(bool(self.title_row.get_text().strip()))

    def _refresh_cover(self):
        preview = Book("", self.title_row.get_text().strip() or "New Book", "", self.cover_id, 0, 0)
        self.cover_btn.set_child(make_cover(self.win.textures, preview, 132, 198))
        self.remove_btn.set_visible(bool(self.cover_id))

    def set_cover(self, image_id):
        self.cover_id = image_id
        self._refresh_cover()

    def pick_cover(self):
        def chosen(files):
            name, data = read_file(files[0])
            try:
                blob, mime = prepare_image(data, name, max_dim=1200)
            except ValueError:
                self.win.toast("That file couldn't be read as a picture")
                return
            iid = self.store.add_image(mime, blob)
            self.session_images.add(iid)
            self.set_cover(iid)

        pick_files(self.win, "Choose Cover", IMAGE_FILTER, chosen, multiple=False)

    def save(self):
        title = self.title_row.get_text().strip()
        if not title:
            return
        buf = self.desc.get_buffer()
        desc = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        if self.book:
            self.store.update_book(self.book.id, title, desc, self.cover_id)
            book = self.store.get_book(self.book.id)
        else:
            book = self.store.create_book(title, desc, self.cover_id)
        self.saved = True
        self.close()
        self.on_saved(book)

    def _on_closed(self, *_a):
        # release uploads from this session; GC keeps whichever one became the cover
        self.store.discard_pending(self.session_images)
