"""The chapter editor: Markdown source with highlighting, live preview, pictures."""

from __future__ import annotations

import re

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GtkSource", "5")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, GtkSource  # noqa: E402

from .images import prepare_image  # noqa: E402
from .reader import ReaderView  # noqa: E402
from .ui import IMAGE_FILTER, pick_files, plural, read_file, shortcut  # noqa: E402


class EditorPage(Adw.NavigationPage):
    def __init__(self, win, book_id: str, chapter_id: str | None):
        super().__init__(title="Editor", tag="editor", can_pop=False)
        self.win, self.store = win, win.store
        self.book_id, self.chapter_id = book_id, chapter_id
        self.session_images: set[str] = set()
        self.dirty = False
        self._loading = True
        self.book = self.store.get_book(book_id)
        chapter = self.store.get_chapter(chapter_id) if chapter_id else None

        # ── header ──
        header = Adw.HeaderBar(show_back_button=False)
        back = Gtk.Button(icon_name="go-previous-symbolic", tooltip_text="Close Editor (Esc)")
        back.connect("clicked", lambda *_a: self.request_close())
        header.pack_start(back)

        self.view_stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher(stack=self.view_stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)

        self.save_btn = Gtk.Button(label="Save", tooltip_text="Save Chapter (Ctrl+S)")
        self.save_btn.add_css_class("suggested-action")
        self.save_btn.connect("clicked", lambda *_a: self.save())
        header.pack_end(self.save_btn)

        opts = Gio.Menu()
        opts.append("Information Chapter", "editor.info")
        opts.append("Monospace Font", "editor.mono")
        header.pack_end(Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=opts,
                                       tooltip_text="Editor Options"))

        # ── write tab ──
        self.title_entry = Gtk.Text(placeholder_text="Chapter title", hexpand=True)
        self.title_entry.add_css_class("editor-title")
        self.title_entry.set_text(chapter.title if chapter else "")
        self.title_entry.connect("changed", lambda *_a: self._mark_dirty())
        self.title_entry.connect("activate", lambda *_a: self.view.grab_focus())

        self.buffer = GtkSource.Buffer()
        lang = GtkSource.LanguageManager.get_default().get_language("markdown")
        if lang:
            self.buffer.set_language(lang)
        self.buffer.set_highlight_matching_brackets(False)
        self._sync_scheme()
        Adw.StyleManager.get_default().connect("notify::dark", lambda *_a: self._sync_scheme())
        self.buffer.set_text(chapter.content if chapter else "")
        self.buffer.set_modified(False)
        self.buffer.connect("changed", lambda *_a: (self._mark_dirty(), self._update_status()))

        self.view = GtkSource.View(buffer=self.buffer, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                                   top_margin=12, bottom_margin=160, left_margin=4, right_margin=4,
                                   pixels_below_lines=2, pixels_inside_wrap=1, auto_indent=True,
                                   insert_spaces_instead_of_tabs=True, tab_width=4,
                                   smart_home_end=GtkSource.SmartHomeEndType.BEFORE, vexpand=True)
        self.view.add_css_class("writing")
        self.mono = (self.store.get_setting("editor.mono", "0") == "1")
        if self.mono:
            self.view.add_css_class("monospace")
        self.view.connect("paste-clipboard", self._on_paste)
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self._on_drop_files)
        self.view.add_controller(drop)

        title_clamp = Adw.Clamp(maximum_size=780, tightening_threshold=600,
                                child=self.title_entry, margin_top=22, margin_start=24, margin_end=24)
        self.info_check = Gtk.CheckButton(label="Information chapter",
                                          tooltip_text="Notes, glossaries, worldbuilding — listed and counted "
                                                       "separately from story chapters")
        self.info_check.set_active(bool(chapter and chapter.is_info))
        self.info_check.connect("toggled", lambda *_a: self._mark_dirty())
        info_clamp = Adw.Clamp(maximum_size=780, tightening_threshold=600, child=self.info_check,
                               margin_start=20, margin_end=24, margin_bottom=4)
        text_clamp = Adw.ClampScrollable(maximum_size=780, tightening_threshold=600, child=self.view)
        scroller = Gtk.ScrolledWindow(child=text_clamp, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_margin_start(20)
        scroller.set_margin_end(20)

        write = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        write.append(title_clamp)
        write.append(info_clamp)
        write.append(self._format_bar())
        write.append(Gtk.Separator())
        write.append(scroller)
        page = self.view_stack.add_titled_with_icon(write, "write", "Write", "document-edit-symbolic")
        page.set_use_underline(False)

        # ── preview tab ──
        self.preview = ReaderView(self.store)
        self.view_stack.add_titled_with_icon(self.preview, "preview", "Preview", "x-office-document-symbolic")
        self.view_stack.connect("notify::visible-child-name", self._on_tab)

        # ── status bar ──
        status = Gtk.Box(spacing=12)
        status.add_css_class("status-bar")
        self.state_label = Gtk.Label(xalign=0, hexpand=True)
        self.state_label.add_css_class("dim-label")
        self.count_label = Gtk.Label(xalign=1)
        self.count_label.add_css_class("dim-label")
        self.count_label.add_css_class("numeric")
        status.append(self.state_label)
        status.append(self.count_label)

        tv = Adw.ToolbarView(content=self.view_stack, bottom_bar_style=Adw.ToolbarStyle.RAISED)
        tv.add_top_bar(header)
        tv.add_bottom_bar(status)
        self.set_child(tv)

        # ── actions & shortcuts ──
        group = Gio.SimpleActionGroup()
        info = Gio.SimpleAction.new_stateful("info", None, GLib.Variant.new_boolean(self.info_check.get_active()))
        info.connect("activate", lambda a, _p: self.info_check.set_active(not self.info_check.get_active()))
        self.info_check.connect("toggled", lambda c: info.set_state(GLib.Variant.new_boolean(c.get_active())))
        group.add_action(info)
        mono = Gio.SimpleAction.new_stateful("mono", None, GLib.Variant.new_boolean(self.mono))
        mono.connect("activate", self._toggle_mono)
        group.add_action(mono)
        self.insert_action_group("editor", group)

        shortcut(self, "<Control>s", self.save)
        shortcut(self, "Escape", self.request_close)
        shortcut(self, "<Control>w", self.request_close)
        shortcut(self, "<Control>b", lambda: self.wrap("**", "**", "bold text"))
        shortcut(self, "<Control>i", lambda: self.wrap("*", "*", "italic text"))
        shortcut(self, "<Control>k", self.insert_link)
        shortcut(self, "<Control><Shift>i", self.pick_images)
        shortcut(self, "<Control>p", lambda: self.view_stack.set_visible_child_name(
            "write" if self.view_stack.get_visible_child_name() == "preview" else "preview"))

        self._loading = False
        self._update_status()
        self._update_title()
        GLib.idle_add(self._initial_focus, chapter is None)

    def _initial_focus(self, new: bool):
        if new:
            self.title_entry.grab_focus()
        else:
            self.view.grab_focus()
            self.buffer.place_cursor(self.buffer.get_start_iter())
        self.title_entry.select_region(0, 0)
        return False

    # ── toolbar ──────────────────────────────────────────────
    def _format_bar(self) -> Gtk.Widget:
        bar = Gtk.Box(spacing=2)
        bar.add_css_class("format-bar")

        def btn(icon=None, label=None, tip="", cb=None, css=None):
            b = Gtk.Button(icon_name=icon) if icon else Gtk.Button(label=label)
            b.set_tooltip_text(tip)
            b.add_css_class("flat")
            if css:
                b.add_css_class(css)
            b.set_focus_on_click(False)
            b.connect("clicked", lambda *_a: cb())
            bar.append(b)

        def sep():
            s = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=6, margin_end=6,
                              margin_top=6, margin_bottom=6)
            bar.append(s)

        btn(label="H1", tip="Heading", cb=lambda: self.line_prefix("# "), css="heading-btn")
        btn(label="H2", tip="Subheading", cb=lambda: self.line_prefix("## "), css="heading-btn")
        sep()
        btn("format-text-bold-symbolic", tip="Bold (Ctrl+B)", cb=lambda: self.wrap("**", "**", "bold text"))
        btn("format-text-italic-symbolic", tip="Italic (Ctrl+I)", cb=lambda: self.wrap("*", "*", "italic text"))
        btn("format-text-strikethrough-symbolic", tip="Strikethrough", cb=lambda: self.wrap("~~", "~~", "text"))
        sep()
        btn("format-indent-more-symbolic", tip="Quote", cb=lambda: self.line_prefix("> "))
        btn("view-list-bullet-symbolic", tip="Bulleted List", cb=lambda: self.line_prefix("- "))
        btn("view-list-ordered-symbolic", tip="Numbered List", cb=lambda: self.line_prefix("1. "))
        btn(label="—", tip="Scene Break", cb=lambda: self.insert_block("---"))
        sep()
        btn("insert-link-symbolic", tip="Link (Ctrl+K)", cb=self.insert_link)
        btn("insert-image-symbolic", tip="Insert Pictures (Ctrl+Shift+I) — you can also paste or drop them",
            cb=self.pick_images)
        clamp = Adw.Clamp(maximum_size=780, tightening_threshold=600, child=bar, margin_start=16, margin_end=20)
        return clamp

    # ── state ────────────────────────────────────────────────
    def _sync_scheme(self):
        sm = GtkSource.StyleSchemeManager.get_default()
        scheme = sm.get_scheme("Adwaita-dark" if Adw.StyleManager.get_default().get_dark() else "Adwaita")
        if scheme:
            self.buffer.set_style_scheme(scheme)

    def _toggle_mono(self, action, _p):
        self.mono = not self.mono
        action.set_state(GLib.Variant.new_boolean(self.mono))
        (self.view.add_css_class if self.mono else self.view.remove_css_class)("monospace")
        self.store.set_setting("editor.mono", "1" if self.mono else "0")

    def _mark_dirty(self):
        if self._loading:
            return
        if not self.dirty:
            self.dirty = True
            self._update_title()
        self._update_status()

    def _update_title(self):
        name = self.title_entry.get_text().strip() or ("New Chapter" if not self.chapter_id else "Untitled Chapter")
        self.set_title(("• " if self.dirty else "") + name)

    def _text(self) -> str:
        return self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter(), True)

    def _update_status(self):
        text = self._text()
        words = len(re.findall(r"[\w'’-]+", re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)))
        self.count_label.set_label(f"{plural(words, 'word')}  ·  {plural(len(text), 'character')}")
        if self.dirty:
            self.state_label.set_markup('<span weight="bold" foreground="#e5a50a">●</span>  Unsaved changes')
        else:
            self.state_label.set_label(f"{self.book.title}" if self.book else "")

    def _on_tab(self, *_a):
        if self.view_stack.get_visible_child_name() == "preview":
            title = self.title_entry.get_text().strip() or "Untitled Chapter"
            self.preview.show("Information" if self.info_check.get_active() else "Preview", title, self._text())

    # ── text helpers ─────────────────────────────────────────
    def wrap(self, before: str, after: str, placeholder: str):
        buf = self.buffer
        if buf.get_has_selection():
            start, end = buf.get_selection_bounds()
            text = buf.get_text(start, end, True)
            buf.begin_user_action()
            buf.delete(start, end)
            buf.insert(start, before + text + after)
            buf.end_user_action()
        else:
            buf.begin_user_action()
            buf.insert_at_cursor(before + placeholder + after)
            buf.end_user_action()
            it = buf.get_iter_at_mark(buf.get_insert())
            end = it.copy()
            end.backward_chars(len(after))
            start = end.copy()
            start.backward_chars(len(placeholder))
            buf.select_range(start, end)
        self.view.grab_focus()

    def line_prefix(self, prefix: str):
        buf = self.buffer
        if buf.get_has_selection():
            start, end = buf.get_selection_bounds()
        else:
            start = end = buf.get_iter_at_mark(buf.get_insert())
        first, last = start.get_line(), end.get_line()
        buf.begin_user_action()
        for line in range(first, last + 1):
            _ok, it = buf.get_iter_at_line(line)
            line_end = it.copy()
            if not line_end.ends_line():
                line_end.forward_to_line_end()
            current = buf.get_text(it, line_end, True)
            stripped = re.sub(r"^(#{1,6} |> |- |\d+\. )", "", current)
            if current.startswith(prefix):
                new = current[len(prefix):]
            else:
                new = prefix + stripped
            buf.delete(it, line_end)
            buf.insert(it, new)
        buf.end_user_action()
        self.view.grab_focus()

    def insert_block(self, text: str):
        buf = self.buffer
        it = buf.get_iter_at_mark(buf.get_insert())
        lead = "" if it.starts_line() else "\n"
        buf.begin_user_action()
        buf.insert_at_cursor(f"{lead}\n{text}\n\n")
        buf.end_user_action()
        self.view.grab_focus()

    def insert_link(self):
        buf = self.buffer
        if buf.get_has_selection():
            start, end = buf.get_selection_bounds()
            label = buf.get_text(start, end, True)
            buf.begin_user_action()
            buf.delete(start, end)
            buf.insert(start, f"[{label}](https://)")
            buf.end_user_action()
            it = buf.get_iter_at_mark(buf.get_insert())
            it.backward_char()
            s = it.copy()
            s.backward_chars(len("https://"))
            buf.select_range(s, it)
        else:
            self.wrap("[", "](https://)", "link text")
        self.view.grab_focus()

    # ── pictures ─────────────────────────────────────────────
    def _insert_images(self, items: list[tuple[str, bytes]]):
        refs, failed = [], 0
        for name, data in items:
            try:
                blob, mime = prepare_image(data, name)
            except ValueError:
                failed += 1
                continue
            iid = self.store.add_image(mime, blob)
            self.session_images.add(iid)
            alt = re.sub(r"\.[^.]+$", "", name).replace("_", " ").replace("-", " ").strip()
            alt = "" if alt.lower() in ("image", "pasted", "") else alt
            refs.append(f"![{alt}](img:{iid})")
        if refs:
            buf = self.buffer
            it = buf.get_iter_at_mark(buf.get_insert())
            lead = "" if it.starts_line() else "\n"
            buf.begin_user_action()
            buf.insert_at_cursor(lead + "\n\n".join(refs) + "\n")
            buf.end_user_action()
        if failed:
            self.win.toast(f"{plural(failed, 'file')} couldn't be read as a picture")

    def pick_images(self):
        pick_files(self.win, "Insert Pictures", IMAGE_FILTER,
                   lambda files: self._insert_images([read_file(f) for f in files]))

    def _on_paste(self, view):
        clip = view.get_clipboard()
        formats = clip.get_formats()
        if formats.contain_gtype(Gdk.Texture.__gtype__) and not formats.contain_gtype(GObject.TYPE_STRING):
            view.stop_emission_by_name("paste-clipboard")

            def done(c, res):
                try:
                    tex = c.read_texture_finish(res)
                except GLib.Error:
                    return
                if tex:
                    self._insert_images([("pasted.png", bytes(tex.save_to_png_bytes().get_data()))])

            clip.read_texture_async(None, done)
        elif formats.contain_gtype(Gdk.FileList.__gtype__):
            view.stop_emission_by_name("paste-clipboard")

            def got(c, res):
                try:
                    value = c.read_value_finish(res)
                except GLib.Error:
                    return
                self._insert_images([read_file(f) for f in value.get_files()])

            clip.read_value_async(Gdk.FileList, GLib.PRIORITY_DEFAULT, None, got)

    def _on_drop_files(self, _target, value, _x, _y):
        files = value.get_files() if value else []
        if not files:
            return False
        self._insert_images([read_file(f) for f in files])
        return True

    # ── save / close ─────────────────────────────────────────
    def save(self, quiet: bool = False) -> bool:
        title = self.title_entry.get_text().strip() or "Untitled Chapter"
        content = self._text()
        is_info = self.info_check.get_active()
        try:
            if self.chapter_id:
                self.store.update_chapter(self.chapter_id, title, content, is_info)
            else:
                self.chapter_id = self.store.create_chapter(self.book_id, title, content, is_info).id
            # anything uploaded but no longer in the text is garbage now
            self.store.discard_pending(self.session_images)
            self.session_images.clear()
        except Exception as err:  # noqa: BLE001
            self.win.toast(f"Couldn't save: {err}")
            return False
        self.dirty = False
        self._update_title()
        self._update_status()
        if not quiet:
            self.win.toast("Chapter saved")
        return True

    def discard(self):
        self.store.discard_pending(self.session_images)
        self.session_images.clear()
        self.dirty = False

    def request_close(self, then=None):
        """Leave the editor, asking first if there are unsaved changes."""
        def leave():
            self.win.close_editor(self.chapter_id)
            if then:
                then()

        if not self.dirty:
            self.discard()
            leave()
            return True
        dlg = Adw.AlertDialog(heading="Save Changes?",
                              body="This chapter has unsaved changes. Changes you don't save are lost.")
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("discard", "Discard")
        dlg.add_response("save", "Save")
        dlg.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("save")
        dlg.set_close_response("cancel")

        def on_response(_d, r):
            if r == "save" and self.save(quiet=True):
                leave()
            elif r == "discard":
                self.discard()
                leave()

        dlg.connect("response", on_response)
        dlg.present(self)
        return True

