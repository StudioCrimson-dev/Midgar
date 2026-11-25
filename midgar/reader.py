"""The reading surface: rendered Markdown in a locked-down WebKit view.

Privacy hardening:
  * an *ephemeral* network session — no cookies, cache or storage on disk;
  * JavaScript, plugins, WebGL/WebAudio, media and developer tools disabled;
  * a strict Content-Security-Policy that allows no network fetches at all
    (images are inlined as data: URIs from the local database);
  * every navigation is intercepted: links open in your browser only when you
    click them, and nothing else ever loads.
"""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")
from gi.repository import Adw, Gdk, Gtk, WebKit  # noqa: E402

from . import markdown  # noqa: E402
from .images import data_uri  # noqa: E402

CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src 'none'"

_LIGHT = dict(fg="#1f1f24", dim="#5e5c64", rule="#deddda", accent="#1c71d8", code="#f1f0ee",
              quote="#3d3846", sel="#c0d8f5")
_DARK = dict(fg="#e8e6e3", dim="#9a9996", rule="#3a3a40", accent="#78aeed", code="#2a2a30",
             quote="#c0bfbc", sel="#264b78")

_CSS = """
:root { color-scheme: %(scheme)s; }
html { font-size: %(size)spx; }
body {
  margin: 0; padding: 48px 32px 96px; background: transparent; color: %(fg)s;
  font-family: %(family)s; line-height: 1.72; font-kerning: normal;
  text-rendering: optimizeLegibility; hyphens: auto; -webkit-hyphens: auto;
}
::selection { background: %(sel)s; }
main { max-width: %(measure)sem; margin: 0 auto; }
.eyebrow { font-family: system-ui, sans-serif; font-size: .72rem; font-weight: 700;
  letter-spacing: .14em; text-transform: uppercase; color: %(accent)s; margin: 0 0 .6rem; }
h1.chapter-title { font-size: 2.3rem; line-height: 1.15; margin: 0 0 2.4rem; font-weight: 700;
  letter-spacing: -.01em; padding-bottom: 1.4rem; border-bottom: 1px solid %(rule)s; }
h1, h2, h3, h4, h5, h6 { line-height: 1.25; margin: 2.2em 0 .7em; font-weight: 700; }
h1 { font-size: 1.9rem; } h2 { font-size: 1.5rem; } h3 { font-size: 1.25rem; }
h4, h5, h6 { font-size: 1.05rem; }
p { margin: 0 0 1.1em; }
a { color: %(accent)s; text-decoration-thickness: 1px; text-underline-offset: 3px; }
strong { font-weight: 700; }
blockquote { margin: 1.6em 0; padding: .1em 0 .1em 1.3em; border-left: 3px solid %(accent)s;
  color: %(quote)s; font-style: italic; }
hr { border: 0; text-align: center; margin: 2.6em 0; }
hr::before { content: "\\2042"; color: %(dim)s; font-size: 1.2rem; letter-spacing: .5em; }
code { font-family: "JetBrains Mono", "Cascadia Code", "Fira Code", "DejaVu Sans Mono", monospace;
  font-size: .86em; background: %(code)s; padding: .12em .38em; border-radius: 5px; }
pre { background: %(code)s; padding: 1em 1.2em; border-radius: 10px; overflow-x: auto; line-height: 1.5; }
pre code { background: none; padding: 0; font-size: .84em; }
ul, ol { padding-left: 1.6em; margin: 0 0 1.1em; } li { margin: .25em 0; }
img { display: block; max-width: 100%%; height: auto; margin: 1.8em auto; border-radius: 8px; }
.table-wrap { overflow-x: auto; margin: 1.6em 0; }
table { border-collapse: collapse; width: 100%%; font-size: .92em; font-family: system-ui, sans-serif; }
th, td { border-bottom: 1px solid %(rule)s; padding: .55em .8em; text-align: left; }
th { font-weight: 700; }
.img-note { display: inline-block; font-family: system-ui, sans-serif; font-size: .8rem; color: %(dim)s;
  border: 1px dashed %(rule)s; border-radius: 6px; padding: .3em .7em; }
.empty { color: %(dim)s; font-style: italic; }
nav.pager { display: flex; justify-content: space-between; gap: 16px; margin-top: 4rem; padding-top: 1.4rem;
  border-top: 1px solid %(rule)s; font-family: system-ui, sans-serif; font-size: .9rem; }
nav.pager a { text-decoration: none; display: flex; flex-direction: column; max-width: 48%%; }
nav.pager a.next { margin-left: auto; text-align: right; }
nav.pager small { color: %(dim)s; font-size: .72rem; text-transform: uppercase; letter-spacing: .1em; }
"""

FONT_FAMILIES = {
    "serif": '"Source Serif 4", "Noto Serif", "Literata", "Charter", "DejaVu Serif", Georgia, serif',
    "sans": '"Inter", "Adwaita Sans", "Cantarell", "Noto Sans", system-ui, sans-serif',
}


def _harden(settings: WebKit.Settings) -> None:
    for prop, value in (
        ("enable-javascript", False), ("enable-javascript-markup", False),
        ("enable-developer-extras", False), ("enable-webgl", False), ("enable-webaudio", False),
        ("enable-media", False), ("enable-media-stream", False), ("enable-mediasource", False),
        ("enable-html5-local-storage", False), ("enable-html5-database", False),
        ("enable-page-cache", False), ("enable-dns-prefetching", False),
        ("allow-file-access-from-file-urls", False), ("allow-universal-access-from-file-urls", False), ("enable-back-forward-navigation-gestures", False),
        ("javascript-can-open-windows-automatically", False), ("enable-encrypted-media", False),
        ("enable-webrtc", False), ("enable-smooth-scrolling", True),
    ):
        if settings.find_property(prop) is not None:
            settings.set_property(prop, value)


class ReaderView(Gtk.Box):
    """Renders Markdown. ``on_pager('prev'|'next')`` is called for in-page navigation links."""

    def __init__(self, store, on_pager: Callable[[str], None] | None = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, vexpand=True, hexpand=True)
        self.store = store
        self.on_pager = on_pager
        session = WebKit.NetworkSession.new_ephemeral()
        self.web = WebKit.WebView(network_session=session, vexpand=True, hexpand=True)
        _harden(self.web.get_settings())
        self.web.set_background_color(Gdk.RGBA(0, 0, 0, 0))
        self.web.connect("decide-policy", self._on_policy)
        self.web.connect("context-menu", lambda *_a: True)   # no "Inspect element"/"Open link" menu
        self.append(self.web)
        self._last: tuple | None = None
        self.zoom = float(store.get_setting("reader.zoom", "1.0") or 1.0)
        self.family = store.get_setting("reader.font", "serif") or "serif"
        self.measure = store.get_setting("reader.measure", "38") or "38"
        Adw.StyleManager.get_default().connect("notify::dark", lambda *_a: self.refresh())

    # ── rendering ────────────────────────────────────────────
    def _resolve(self, image_id: str) -> str | None:
        img = self.store.get_image(image_id)
        return data_uri(*img) if img else None

    def show(self, eyebrow: str, title: str, body_md: str, prev_title: str | None = None,
             next_title: str | None = None) -> None:
        self._last = (eyebrow, title, body_md, prev_title, next_title)
        body = markdown.render(body_md, self._resolve) if body_md.strip() else \
            '<p class="empty">This chapter is empty.</p>'
        pager = ""
        if prev_title or next_title:
            pager = '<nav class="pager">'
            if prev_title:
                pager += f'<a class="prev" href="midgar-nav:prev"><small>Previous</small>{markdown.esc(prev_title)}</a>'
            if next_title:
                pager += f'<a class="next" href="midgar-nav:next"><small>Next</small>{markdown.esc(next_title)}</a>'
            pager += "</nav>"
        dark = Adw.StyleManager.get_default().get_dark()
        palette = dict(_DARK if dark else _LIGHT)
        try:   # follow the system accent colour where libadwaita exposes it (1.6+)
            rgba = Adw.StyleManager.get_default().get_accent_color_rgba()
            palette["accent"] = "#%02x%02x%02x" % tuple(int(c * 255) for c in (rgba.red, rgba.green, rgba.blue))
        except (AttributeError, TypeError):
            pass
        css = _CSS % dict(palette, scheme="dark" if dark else "light", size=round(17 * self.zoom, 1),
                          family=FONT_FAMILIES.get(self.family, FONT_FAMILIES["serif"]), measure=self.measure)
        html = (f'<!doctype html><html><head><meta charset="utf-8">'
                f'<meta http-equiv="Content-Security-Policy" content="{CSP}">'
                f"<style>{css}</style></head><body><main>"
                f'<p class="eyebrow">{markdown.esc(eyebrow)}</p>'
                f'<h1 class="chapter-title">{markdown.esc(title)}</h1>'
                f"{body}{pager}</main></body></html>")
        self.web.load_html(html, "about:blank")

    def refresh(self) -> None:
        if self._last:
            self.show(*self._last)

    # ── preferences ──────────────────────────────────────────
    def set_zoom(self, zoom: float) -> None:
        self.zoom = max(0.6, min(2.2, round(zoom, 2)))
        self.store.set_setting("reader.zoom", str(self.zoom))
        self.refresh()

    def set_family(self, family: str) -> None:
        self.family = family
        self.store.set_setting("reader.font", family)
        self.refresh()

    # ── navigation policy ────────────────────────────────────
    def _on_policy(self, _web, decision, kind):
        if kind == WebKit.PolicyDecisionType.RESPONSE:
            decision.use()
            return True
        action = decision.get_navigation_action()
        uri = action.get_request().get_uri() or ""
        if kind == WebKit.PolicyDecisionType.NAVIGATION_ACTION and uri.startswith("about:blank") \
                and action.get_navigation_type() != WebKit.NavigationType.LINK_CLICKED:
            decision.use()          # our own load_html()
            return True
        decision.ignore()
        if action.get_navigation_type() == WebKit.NavigationType.LINK_CLICKED:
            if uri.startswith("midgar-nav:") and self.on_pager:
                self.on_pager(uri.split(":", 1)[1])
            elif uri.split(":", 1)[0].lower() in ("http", "https", "mailto", "tel"):
                Gtk.UriLauncher(uri=uri).launch(self.get_root(), None, None, None)
        return True
