"""A single book: chapter sidebar + reader."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango  # noqa: E402

from .library_page import make_cover  # noqa: E402
from .reader import ReaderView  # noqa: E402
from .ui import confirm, counts_label, shortcut  # noqa: E402


class ChapterRow(Gtk.ListBoxRow):
    def __init__(self, page: "BookPage", chapter, number: int | None):
        super().__init__()
        self.page, self.chapter = page, chapter
        box = Gtk.Box(spacing=10, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        box.add_css_class("chapter-row")
        num = Gtk.Label(label=str(number) if number else "·", xalign=1)
        num.add_css_class("chapter-number")
        num.add_css_class("dim-label")
        box.append(num)
        title = Gtk.Label(label=chapter.title, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END,
                          tooltip_text=chapter.title)
        box.append(title)
        if chapter.is_info:
            pill = Gtk.Label(label="INFO", valign=Gtk.Align.CENTER, tooltip_text="Information chapter")
            pill.add_css_class("info-pill")
            box.append(pill)
        self.set_child(box)

        src = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        src.connect("prepare", lambda *_a: Gdk.ContentProvider.new_for_value(chapter.id))
        src.connect("drag-begin", lambda s, _d: (s.set_icon(Gtk.WidgetPaintable(widget=self), 20, 16),
                                                 self.add_css_class("dragging")))
        src.connect("drag-end", lambda *_a: self.remove_css_class("dragging"))
        self.add_controller(src)
        tgt = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
        tgt.connect("motion", self._on_motion)
        tgt.connect("leave", lambda *_a: self._clear())
        tgt.connect("drop", self._on_drop)
        self.add_controller(tgt)

    def _clear(self):
        self.remove_css_class("drop-before")
        self.remove_css_class("drop-after")

    def _on_motion(self, _t, _x, y):
        self._clear()
        self.add_css_class("drop-after" if y > self.get_height() / 2 else "drop-before")
        return Gdk.DragAction.MOVE

    def _on_drop(self, _t, value, _x, y):
        self._clear()
        if value and value != self.chapter.id:
            self.page.drop_chapter(value, self.chapter.id, y > self.get_height() / 2)
            return True
        return False


class BookPage(Adw.NavigationPage):
    def __init__(self, win, book_id: str, chapter_id: str | None = None):
        super().__init__(title="Book", tag=f"book-{book_id}")
        self.win, self.store, self.book_id = win, win.store, book_id
        self.chapters = []
        self.current_id = chapter_id

        # ── sidebar ──
        side_header = Adw.HeaderBar(show_end_title_buttons=False)
        self.side_title = Adw.WindowTitle()
        side_header.set_title_widget(self.side_title)
        book_menu = Gio.Menu()
        s = Gio.Menu()
        s.append("Edit Details…", "book.edit")
        s.append("Import Markdown…", "book.import")
        s.append("Export as Markdown…", "book.export")
        book_menu.append_section(None, s)
        s = Gio.Menu()
        s.append("Delete Book…", "book.delete")
        book_menu.append_section(None, s)
        side_header.pack_end(Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=book_menu,
                                            tooltip_text="Book Options"))

        self.cover_slot = Gtk.Box(margin_start=12, margin_end=12, margin_top=6, margin_bottom=6, spacing=12)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.list.add_css_class("navigation-sidebar")
        self.list.connect("row-activated", lambda _l, row: self.show_chapter(row.chapter.id))
        self.list_stack = Gtk.Stack()
        self.list_stack.add_named(Gtk.ScrolledWindow(child=self.list, vexpand=True,
                                                     hscrollbar_policy=Gtk.PolicyType.NEVER), "list")
        none = Adw.StatusPage(title="No Chapters", description="Add one, or import Markdown files.")
        none.add_css_class("compact")
        self.list_stack.add_named(none, "empty")

        side_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        side_content.append(self.cover_slot)
        side_content.append(Gtk.Separator())
        side_content.append(self.list_stack)

        new_ch = Gtk.Button(child=Adw.ButtonContent(icon_name="list-add-symbolic", label="New Chapter"),
                            action_name="book.new-chapter", tooltip_text="New Chapter (Ctrl+Shift+N)",
                            margin_start=12, margin_end=12, margin_top=8, margin_bottom=10)
        new_ch.add_css_class("suggested-action")
        sidebar = Adw.ToolbarView(content=side_content)
        sidebar.add_top_bar(side_header)
        sidebar.add_bottom_bar(new_ch)

        # ── content ──
        self.content_header = Adw.HeaderBar(show_start_title_buttons=False, show_back_button=False)
        self.content_title = Adw.WindowTitle()
        self.content_header.set_title_widget(self.content_title)
        self.sidebar_btn = Gtk.ToggleButton(icon_name="sidebar-show-symbolic", tooltip_text="Toggle Sidebar (F9)")
        self.content_header.pack_start(self.sidebar_btn)
        self.prev_btn = Gtk.Button(icon_name="go-previous-symbolic", tooltip_text="Previous Chapter (Alt+←)",
                                   action_name="book.prev")
        self.next_btn = Gtk.Button(icon_name="go-next-symbolic", tooltip_text="Next Chapter (Alt+→)",
                                   action_name="book.next")
        self.nav_box = nav_box = Gtk.Box()
        nav_box.add_css_class("linked")
        nav_box.append(self.prev_btn)
        nav_box.append(self.next_btn)
        self.content_header.pack_start(nav_box)

        ch_menu = Gio.Menu()
        s = Gio.Menu()
        s.append("Move Up", "book.move-up")
        s.append("Move Down", "book.move-down")
        ch_menu.append_section(None, s)
        s = Gio.Menu()
        s.append("Serif Text", "book.font::serif")
        s.append("Sans Text", "book.font::sans")
        s.append("Larger Text", "book.zoom-in")
        s.append("Smaller Text", "book.zoom-out")
        s.append("Reset Text Size", "book.zoom-reset")
        ch_menu.append_section("Reading", s)
        s = Gio.Menu()
        s.append("Delete Chapter…", "book.delete-chapter")
        ch_menu.append_section(None, s)
        self.ch_menu_btn = Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=ch_menu,
                                          tooltip_text="Chapter Options")
        self.content_header.pack_end(self.ch_menu_btn)
        self.edit_btn = Gtk.Button(child=Adw.ButtonContent(icon_name="document-edit-symbolic", label="Edit"),
                                   action_name="book.edit-chapter", tooltip_text="Edit Chapter (Ctrl+E)")
        self.content_header.pack_end(self.edit_btn)

        self.reader = ReaderView(self.store, on_pager=lambda d: self.step(-1 if d == "prev" else 1))
        self.welcome = Adw.StatusPage(icon_name="x-office-document-symbolic")
        welcome_btn = Gtk.Button(label="New Chapter", halign=Gtk.Align.CENTER, action_name="book.new-chapter")
        welcome_btn.add_css_class("pill")
        welcome_btn.add_css_class("suggested-action")
        self.welcome.set_child(welcome_btn)
        self.content_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.content_stack.add_named(self.welcome, "welcome")
        self.content_stack.add_named(self.reader, "reader")
        content = Adw.ToolbarView(content=self.content_stack)
        content.add_top_bar(self.content_header)

        self.split = Adw.OverlaySplitView(sidebar=sidebar, content=content, min_sidebar_width=250,
                                          max_sidebar_width=340, sidebar_width_fraction=0.26)
        self.split.bind_property("show-sidebar", self.sidebar_btn, "active",
                                 GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        self.split.connect("notify::collapsed", self._on_collapsed)

        bp_bin = Adw.BreakpointBin(child=self.split)
        bp_bin.set_size_request(360, 300)
        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 760sp"))
        bp.add_setter(self.split, "collapsed", True)
        bp.add_setter(self.nav_box, "visible", False)   # the in-page pager covers prev/next
        bp_bin.add_breakpoint(bp)
        self.set_child(bp_bin)

        self._install_actions()
        self.connect("showing", lambda *_a: self.reload())

    # ── actions & shortcuts ─────────────────────────────────
    def _install_actions(self):
        group = Gio.SimpleActionGroup()
        self.actions = {}
        for name, cb in (
            ("edit", lambda: self.win.edit_book(self.book_id)),
            ("import", lambda: self.win.import_markdown(self.book_id)),
            ("export", lambda: self.win.export_books([self.book_id], self.book.title)),
            ("delete", lambda: self.win.delete_book(self.book_id)),
            ("new-chapter", lambda: self.win.open_editor(self.book_id, None)),
            ("edit-chapter", lambda: self.current_id and self.win.open_editor(self.book_id, self.current_id)),
            ("delete-chapter", self.delete_current),
            ("move-up", lambda: self.move_current(-1)),
            ("move-down", lambda: self.move_current(+1)),
            ("prev", lambda: self.step(-1)),
            ("next", lambda: self.step(+1)),
            ("zoom-in", lambda: self.reader.set_zoom(self.reader.zoom + 0.1)),
            ("zoom-out", lambda: self.reader.set_zoom(self.reader.zoom - 0.1)),
            ("zoom-reset", lambda: self.reader.set_zoom(1.0)),
        ):
            act = Gio.SimpleAction(name=name)
            act.connect("activate", lambda _a, _p, cb=cb: cb())
            group.add_action(act)
            self.actions[name] = act
        font = Gio.SimpleAction.new_stateful("font", GLib.VariantType.new("s"),
                                            GLib.Variant.new_string(self.reader.family))
        font.connect("activate", lambda a, v: (a.set_state(v), self.reader.set_family(v.get_string())))
        group.add_action(font)
        self.insert_action_group("book", group)

        for accel, name in (("<Control><Shift>n", "new-chapter"), ("<Control>e", "edit-chapter"),
                            ("<Alt>Left", "prev"), ("<Alt>Right", "next"), ("<Control>Page_Up", "prev"),
                            ("<Control>Page_Down", "next"), ("<Control>plus", "zoom-in"),
                            ("<Control>equal", "zoom-in"), ("<Control>minus", "zoom-out"),
                            ("<Control>0", "zoom-reset"), ("<Control>i", "import"),
                            ("<Alt>Up", "move-up"), ("<Alt>Down", "move-down")):
            shortcut(self, accel, lambda n=name: self.actions[n].activate(None) if self.actions[n].get_enabled() else None)
        shortcut(self, "F9", lambda: self.split.set_show_sidebar(not self.split.get_show_sidebar()))
        shortcut(self, "Delete", lambda: self.delete_current() if self.list.has_focus() or
                 (self.list.get_focus_child() is not None) else False)

    def _on_collapsed(self, *_a):
        collapsed = self.split.get_collapsed()
        self.content_header.set_show_back_button(collapsed)
        self.content_header.set_show_start_title_buttons(collapsed)
        if collapsed and self._index() < 0:
            self.split.set_show_sidebar(True)

    # ── data ─────────────────────────────────────────────────
    def reload(self):
        self.book = self.store.get_book(self.book_id)
        if self.book is None:      # deleted elsewhere
            return
        self.set_title(self.book.title)
        self.side_title.set_title(self.book.title)
        self.side_title.set_subtitle(counts_label(self.book.regular_count, self.book.info_count))

        child = self.cover_slot.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.cover_slot.remove(child)
            child = nxt
        if self.book.description or self.book.cover_id:
            self.cover_slot.append(make_cover(self.win.textures, self.book, 56, 84, small=True))
            desc = Gtk.Label(label=self.book.description or counts_label(self.book.regular_count,
                                                                          self.book.info_count), wrap=True, xalign=0, lines=5,
                             ellipsize=Pango.EllipsizeMode.END, valign=Gtk.Align.CENTER, hexpand=True,
                             wrap_mode=Pango.WrapMode.WORD_CHAR)
            desc.add_css_class("dim-label")
            desc.add_css_class("caption")
            self.cover_slot.append(desc)
        self.cover_slot.set_visible(bool(self.book.description or self.book.cover_id))

        self.chapters = self.store.list_chapters(self.book_id)
        self.list.remove_all()
        number = 0
        for ch in self.chapters:
            if not ch.is_info:
                number += 1
            self.list.append(ChapterRow(self, ch, None if ch.is_info else number))
        self.list_stack.set_visible_child_name("list" if self.chapters else "empty")
        if self.current_id and not any(c.id == self.current_id for c in self.chapters):
            self.current_id = None
        self.show_chapter(self.current_id)

    def _index(self) -> int:
        return next((i for i, c in enumerate(self.chapters) if c.id == self.current_id), -1)

    def show_chapter(self, chapter_id: str | None):
        self.current_id = chapter_id
        idx = self._index()
        has = idx >= 0
        for name in ("edit-chapter", "delete-chapter", "move-up", "move-down", "zoom-in", "zoom-out", "zoom-reset"):
            self.actions[name].set_enabled(has)
        self.actions["prev"].set_enabled(has and idx > 0)
        self.actions["next"].set_enabled(bool(self.chapters) and idx < len(self.chapters) - 1)
        self.edit_btn.set_visible(has)
        self.ch_menu_btn.set_visible(has)
        if not has:
            self.list.unselect_all()
            self.content_title.set_title(self.book.title)
            self.content_title.set_subtitle("")
            self.welcome.set_title(self.book.title)
            self.welcome.set_description(
                "Pick a chapter from the sidebar to start reading." if self.chapters else
                "This book has no chapters yet.")
            self.content_stack.set_visible_child_name("welcome")
            if self.split.get_collapsed():
                self.split.set_show_sidebar(True)
            return
        ch = self.chapters[idx]
        self.list.select_row(self.list.get_row_at_index(idx))
        number = sum(1 for c in self.chapters[: idx + 1] if not c.is_info)
        eyebrow = "Information" if ch.is_info else f"Chapter {number}"
        self.content_title.set_title(ch.title)
        self.content_title.set_subtitle(self.book.title)
        prev_t = self.chapters[idx - 1].title if idx > 0 else None
        next_t = self.chapters[idx + 1].title if idx + 1 < len(self.chapters) else None
        self.reader.show(eyebrow, ch.title, ch.content, prev_t, next_t)
        self.content_stack.set_visible_child_name("reader")
        if self.split.get_collapsed():
            self.split.set_show_sidebar(False)

    def step(self, delta: int):
        if not self.chapters:
            return
        idx = self._index()
        j = 0 if idx < 0 else idx + delta
        if 0 <= j < len(self.chapters):
            self.show_chapter(self.chapters[j].id)

    # ── edits ────────────────────────────────────────────────
    def delete_current(self):
        idx = self._index()
        if idx < 0:
            return False
        ch = self.chapters[idx]

        def go():
            self.store.delete_chapter(ch.id)
            remaining = [c for c in self.chapters if c.id != ch.id]
            self.current_id = remaining[min(idx, len(remaining) - 1)].id if remaining else None
            self.reload()
            self.win.toast(f"Deleted “{ch.title}”")

        confirm(self, f"Delete “{ch.title}”?", "This chapter and its pictures will be removed permanently.",
                "Delete", go)
        return True

    def _apply_order(self, ids):
        self.store.reorder_chapters(self.book_id, ids)
        self.reload()

    def move_current(self, delta: int):
        ids = [c.id for c in self.chapters]
        i = self._index()
        j = i + delta
        if i >= 0 and 0 <= j < len(ids):
            ids.insert(j, ids.pop(i))
            self._apply_order(ids)

    def drop_chapter(self, dragged: str, target: str, after: bool):
        ids = [c.id for c in self.chapters]
        if dragged not in ids:
            return
        ids.remove(dragged)
        ids.insert(ids.index(target) + (1 if after else 0), dragged)
        self._apply_order(ids)

