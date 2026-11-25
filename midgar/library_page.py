"""The library: a grid of book covers, library-wide search, drag-to-reorder."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Graphene, Gsk, Gtk, Pango  # noqa: E402

from .ui import counts_label, plural  # noqa: E402

COVER_W, COVER_H = 156, 234


def initials(title: str) -> str:
    words = [w for w in title.split() if w[:1].isalnum()]
    return ("".join(w[0] for w in words[:2]) or title[:1] or "?").upper()


class CoverPicture(Gtk.Widget):
    """Draws a texture at a fixed size, cropped to fill (like CSS object-fit: cover)."""

    def __init__(self, texture: Gdk.Texture, width: int, height: int):
        super().__init__()
        self.texture, self.w, self.h = texture, width, height
        self.set_overflow(Gtk.Overflow.HIDDEN)

    def do_measure(self, orientation, _for_size):
        size = self.w if orientation == Gtk.Orientation.HORIZONTAL else self.h
        return size, size, -1, -1

    def do_snapshot(self, snapshot):
        w, h = self.get_width(), self.get_height()
        tw, th = self.texture.get_width(), self.texture.get_height()
        scale = max(w / tw, h / th)
        dw, dh = tw * scale, th * scale
        snapshot.push_clip(Graphene.Rect().init(0, 0, w, h))
        snapshot.append_scaled_texture(self.texture, Gsk.ScalingFilter.TRILINEAR,
                                       Graphene.Rect().init((w - dw) / 2, (h - dh) / 2, dw, dh))
        snapshot.pop()


def make_cover(textures, book, width=COVER_W, height=COVER_H, small=False) -> Gtk.Widget:
    """A book cover: the cover image, or a typographic placeholder."""
    tex = textures.get(book.cover_id)
    if tex:
        frame = Gtk.Box()
        frame.append(CoverPicture(tex, width, height))
    else:
        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.FILL)
        frame.set_size_request(width, height)
        frame.add_css_class("placeholder")
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, vexpand=True,
                        valign=Gtk.Align.CENTER, margin_start=10, margin_end=10)
        lbl = Gtk.Label(label=initials(book.title))
        lbl.add_css_class("cover-initials")
        inner.append(lbl)
        if not small:
            t = Gtk.Label(label=book.title, wrap=True, justify=Gtk.Justification.CENTER, lines=3,
                          ellipsize=Pango.EllipsizeMode.END, max_width_chars=14)
            t.add_css_class("cover-title")
            inner.append(t)
        frame.append(inner)
    frame.add_css_class("book-cover")
    if small:
        frame.add_css_class("small")
    frame.set_overflow(Gtk.Overflow.HIDDEN)
    frame.set_halign(Gtk.Align.CENTER)
    frame.set_valign(Gtk.Align.START)
    return frame


class BookCard(Gtk.Box):
    def __init__(self, page: "LibraryPage", book):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.page, self.book = page, book
        self.add_css_class("book-card")
        self.append(make_cover(page.win.textures, book))

        row = Gtk.Box(spacing=4)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        title = Gtk.Label(label=book.title, xalign=0, ellipsize=Pango.EllipsizeMode.END,
                          max_width_chars=16, tooltip_text=book.title)
        title.add_css_class("card-title")
        meta = Gtk.Label(label=counts_label(book.regular_count, book.info_count), xalign=0,
                         ellipsize=Pango.EllipsizeMode.END)
        meta.add_css_class("card-meta")
        meta.add_css_class("dim-label")
        text.append(title)
        text.append(meta)
        row.append(text)

        menu = Gio.Menu()
        s1 = Gio.Menu()
        s1.append("Open", "card.open")
        s1.append("Edit Details…", "card.edit")
        s1.append("Export as Markdown…", "card.export")
        s2 = Gio.Menu()
        s2.append("Move Earlier", "card.earlier")
        s2.append("Move Later", "card.later")
        s3 = Gio.Menu()
        s3.append("Delete Book…", "card.delete")
        for s in (s1, s2, s3):
            menu.append_section(None, s)
        btn = Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=menu, valign=Gtk.Align.CENTER,
                             tooltip_text="Book options")
        btn.add_css_class("flat")
        btn.add_css_class("circular")
        row.append(btn)
        self.append(row)
        self.set_size_request(COVER_W + 12, -1)
        self.set_halign(Gtk.Align.CENTER)

        group = Gio.SimpleActionGroup()
        for name, cb in (("open", lambda: page.win.open_book(book.id)),
                         ("edit", lambda: page.win.edit_book(book.id)),
                         ("export", lambda: page.win.export_books([book.id], book.title)),
                         ("earlier", lambda: page.move_book(book.id, -1)),
                         ("later", lambda: page.move_book(book.id, +1)),
                         ("delete", lambda: page.win.delete_book(book.id))):
            act = Gio.SimpleAction(name=name)
            act.connect("activate", lambda _a, _p, cb=cb: cb())
            group.add_action(act)
        self.insert_action_group("card", group)

        # right-click / long-press → the same menu
        self._popover = Gtk.PopoverMenu(menu_model=menu, has_arrow=False)
        self._popover.set_parent(self)
        click = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        click.connect("pressed", self._on_context)
        self.add_controller(click)
        longp = Gtk.GestureLongPress()
        longp.connect("pressed", lambda _g, x, y: self._on_context(None, 1, x, y))
        self.add_controller(longp)

        # drag-and-drop reordering
        src = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        src.connect("prepare", lambda *_a: Gdk.ContentProvider.new_for_value(book.id))
        src.connect("drag-begin", self._on_drag_begin)
        src.connect("drag-end", lambda *_a: self.remove_css_class("dragging"))
        self.add_controller(src)
        tgt = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
        tgt.connect("motion", self._on_motion)
        tgt.connect("leave", lambda *_a: self._clear_drop())
        tgt.connect("drop", self._on_drop)
        self.add_controller(tgt)

    def _on_context(self, _g, _n, x, y):
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        self._popover.set_pointing_to(rect)
        self._popover.popup()

    def _on_drag_begin(self, source, _drag):
        source.set_icon(Gtk.WidgetPaintable(widget=self), COVER_W // 2, COVER_H // 2)
        self.add_css_class("dragging")

    def _after(self, x) -> bool:
        return x > self.get_width() / 2

    def _clear_drop(self):
        self.remove_css_class("drop-before")
        self.remove_css_class("drop-after")

    def _on_motion(self, _t, x, _y):
        self._clear_drop()
        self.add_css_class("drop-after" if self._after(x) else "drop-before")
        return Gdk.DragAction.MOVE

    def _on_drop(self, _t, value, x, _y):
        self._clear_drop()
        if value and value != self.book.id:
            self.page.drop_book(value, self.book.id, self._after(x))
            return True
        return False


class LibraryPage(Adw.NavigationPage):
    def __init__(self, win):
        super().__init__(title="Library", tag="library")
        self.win = win
        self.store = win.store
        self.books = []

        header = Adw.HeaderBar()
        self.window_title = Adw.WindowTitle(title="Midgar")
        header.set_title_widget(self.window_title)
        new_btn = Gtk.Button(child=Adw.ButtonContent(icon_name="list-add-symbolic", label="New Book"),
                             action_name="win.new-book", tooltip_text="New Book (Ctrl+N)")
        new_btn.add_css_class("suggested-action")
        header.pack_start(new_btn)

        main_menu = Gio.Menu()
        sec = Gio.Menu()
        sec.append("Import Books from Export…", "win.import-zip")
        sec.append("Export Library as Markdown…", "win.export-library")
        main_menu.append_section(None, sec)
        sec = Gio.Menu()
        sec.append("Back Up Library…", "win.backup")
        sec.append("Restore from Backup…", "win.restore")
        sec.append("Open Data Folder", "win.open-data-folder")
        main_menu.append_section(None, sec)
        sec = Gio.Menu()
        sec.append("Keyboard Shortcuts", "win.shortcuts")
        sec.append("About Midgar", "win.about")
        main_menu.append_section(None, sec)
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=main_menu,
                                  tooltip_text="Main Menu (F10)", primary=True)
        header.pack_end(menu_btn)
        self.search_btn = Gtk.ToggleButton(icon_name="edit-find-symbolic", tooltip_text="Search Library (Ctrl+F)")
        header.pack_end(self.search_btn)

        self.search_entry = Gtk.SearchEntry(placeholder_text="Search books and chapters", hexpand=True)
        self.search_entry.connect("search-changed", lambda *_a: self.run_search())
        self.search_entry.connect("stop-search", lambda *_a: self.search_btn.set_active(False))
        self.search_entry.connect("activate", lambda *_a: self._activate_first_result())
        clamp = Adw.Clamp(maximum_size=640, child=self.search_entry)
        self.search_bar = Gtk.SearchBar(child=clamp, show_close_button=False)
        self.search_bar.connect_entry(self.search_entry)
        self.search_btn.bind_property("active", self.search_bar, "search-mode-enabled",
                                      GObject.BindingFlags.BIDIRECTIONAL)
        self.search_bar.connect("notify::search-mode-enabled", lambda *_a: self.run_search())

        # content states
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vexpand=True)
        empty = Adw.StatusPage(icon_name="io.github.studiocrimson_dev.Midgar-symbolic",
                               title="Your Library Is Empty",
                               description="Create a book to start writing. Everything stays on this device.")
        empty_btn = Gtk.Button(label="New Book", halign=Gtk.Align.CENTER, action_name="win.new-book")
        empty_btn.add_css_class("pill")
        empty_btn.add_css_class("suggested-action")
        empty.set_child(empty_btn)
        self.stack.add_named(empty, "empty")

        self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                                column_spacing=18, row_spacing=26, max_children_per_line=12,
                                min_children_per_line=1, valign=Gtk.Align.START,
                                margin_top=24, margin_bottom=36, margin_start=24, margin_end=24,
                                activate_on_single_click=True)
        self.flow.connect("child-activated", lambda _f, child: win.open_book(child.get_child().book.id))
        self.stack.add_named(Gtk.ScrolledWindow(child=self.flow, hscrollbar_policy=Gtk.PolicyType.NEVER), "grid")

        self.results = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, valign=Gtk.Align.START)
        self.results.add_css_class("boxed-list")
        self.results.connect("row-activated", lambda _l, row: self._open_hit(row.hit))
        res_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18, margin_bottom=24,
                          margin_start=12, margin_end=12)
        self.results_label = Gtk.Label(xalign=0)
        self.results_label.add_css_class("heading")
        res_box.append(self.results_label)
        res_box.append(self.results)
        self.stack.add_named(Gtk.ScrolledWindow(child=Adw.Clamp(maximum_size=760, child=res_box)), "results")
        self.stack.add_named(Adw.StatusPage(icon_name="edit-find-symbolic", title="No Results",
                                            description="Try a different word or phrase."), "no-results")

        view = Adw.ToolbarView(content=self.stack)
        view.add_top_bar(header)
        view.add_top_bar(self.search_bar)
        self.set_child(view)
        self.connect("showing", lambda *_a: self.reload())
        self.search_bar.set_key_capture_widget(self)

    # ── data ─────────────────────────────────────────────────
    def reload(self) -> None:
        self.books = self.store.list_books()
        self.flow.remove_all()
        for b in self.books:
            self.flow.append(BookCard(self, b))
        n = len(self.books)
        self.window_title.set_subtitle(plural(n, "book") if n else "")
        self.run_search()

    def run_search(self) -> None:
        q = self.search_entry.get_text().strip() if self.search_bar.get_search_mode() else ""
        if not q:
            self.stack.set_visible_child_name("grid" if self.books else "empty")
            return
        hits = self.store.search(q)
        self.results.remove_all()
        if not hits:
            self.stack.set_visible_child_name("no-results")
            return
        self.results_label.set_label(plural(len(hits), "result"))
        for hit in hits:
            row = Adw.ActionRow(activatable=True, title_lines=1, subtitle_lines=2)
            row.set_title(GLib.markup_escape_text(hit.title))
            if hit.kind == "book":
                row.set_subtitle(GLib.markup_escape_text(hit.snippet or "Book"))
                row.add_prefix(Gtk.Image(icon_name="x-office-document-symbolic"))
            else:
                row.set_subtitle(GLib.markup_escape_text(f"{hit.book_title} — {hit.snippet}"))
                row.add_prefix(Gtk.Image(icon_name="document-edit-symbolic"))
            row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            row.hit = hit
            self.results.append(row)
        self.stack.set_visible_child_name("results")

    def _open_hit(self, hit) -> None:
        self.win.open_book(hit.book_id, hit.chapter_id)

    def _activate_first_result(self) -> None:
        row = self.results.get_row_at_index(0)
        if row is not None and self.stack.get_visible_child_name() == "results":
            self._open_hit(row.hit)

    def focus_search(self) -> None:
        self.search_btn.set_active(True)
        self.search_entry.grab_focus()

    # ── ordering ─────────────────────────────────────────────
    def _apply_order(self, ids: list[str]) -> None:
        self.store.reorder_books(ids)
        self.reload()

    def move_book(self, book_id: str, delta: int) -> None:
        ids = [b.id for b in self.books]
        i = ids.index(book_id)
        j = max(0, min(len(ids) - 1, i + delta))
        if i != j:
            ids.insert(j, ids.pop(i))
            self._apply_order(ids)

    def drop_book(self, dragged: str, target: str, after: bool) -> None:
        ids = [b.id for b in self.books]
        if dragged not in ids:
            return
        ids.remove(dragged)
        k = ids.index(target) + (1 if after else 0)
        ids.insert(k, dragged)
        self._apply_order(ids)
