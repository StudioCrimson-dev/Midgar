"""A small, dependency-free Markdown → HTML renderer.

Covers the everyday subset: headings, emphasis, strikethrough, blockquotes,
nested lists, fenced code, tables, links, images and horizontal rules.

Safety model (unchanged from the original web version, tightened for an
offline app):
  * all text is HTML-escaped — raw HTML in a chapter is shown, never rendered;
  * link URLs are limited to http(s)/mailto/tel;
  * images may only come from the local library (``img:<id>``) or inline
    ``data:image/...`` URIs. Remote ``http(s)`` images are *not* loaded, so
    reading a chapter can never cause a network request.
"""

from __future__ import annotations

import re
from typing import Callable, Optional

ImageResolver = Callable[[str], Optional[str]]   # image id → data: URI (or None)

FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})([^`]*)$")
HEADING = re.compile(r"^\s{0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
HR = re.compile(r"^\s{0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
QUOTE = re.compile(r"^\s{0,3}>")
ITEM = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])[ \t]+(.*)$")


def esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


class _Renderer:
    def __init__(self, resolver: ImageResolver | None):
        self.resolver = resolver

    # ── blocks ────────────────────────────────────────────────
    @staticmethod
    def is_block_start(line: str, in_paragraph: bool) -> bool:
        if FENCE.match(line) or HEADING.match(line) or HR.match(line) or QUOTE.match(line):
            return True
        m = ITEM.match(line)
        if not m:
            return False
        # Inside a paragraph only "1." may start a numbered list, so
        # "…back in\n1999. It was…" stays prose.
        return not in_paragraph or not m.group(2)[0].isdigit() or int(m.group(2)[:-1]) == 1

    @staticmethod
    def split_row(line: str) -> list[str]:
        s = line.strip()
        if s.startswith("|"):
            s = s[1:]
        if s.endswith("|") and not s.endswith("\\|"):
            s = s[:-1]
        return [c.replace("\x01", "|").strip() for c in s.replace("\\|", "\x01").split("|")]

    def blocks(self, lines: list[str]) -> str:
        out: list[str] = []
        i, n = 0, len(lines)
        while i < n:
            line = lines[i]
            if not line.strip():
                i += 1
                continue

            m = FENCE.match(line)
            if m:
                ch = "`" if m.group(1)[0] == "`" else "~"
                closer = re.compile(r"^\s{0,3}" + re.escape(ch) + "{" + str(len(m.group(1))) + r",}\s*$")
                lang = re.sub(r"[^\w+-]", "", (m.group(2).strip().split() or [""])[0])
                buf = []
                i += 1
                while i < n and not closer.match(lines[i]):
                    buf.append(lines[i])
                    i += 1
                i += 1
                cls = f' class="lang-{lang}"' if lang else ""
                out.append(f"<pre><code{cls}>{esc(chr(10).join(buf))}</code></pre>")
                continue

            m = HEADING.match(line)
            if m:
                lvl = len(m.group(1))
                out.append(f"<h{lvl}>{self.inline(m.group(2))}</h{lvl}>")
                i += 1
                continue

            if HR.match(line):
                out.append("<hr>")
                i += 1
                continue

            if QUOTE.match(line):
                buf = []
                while i < n and QUOTE.match(lines[i]):
                    buf.append(re.sub(r"^\s{0,3}>[ \t]?", "", lines[i]))
                    i += 1
                out.append(f"<blockquote>{self.blocks(buf)}</blockquote>")
                continue

            if "|" in line and i + 1 < n and "|" in lines[i + 1] and "-" in lines[i + 1]:
                head, sep = self.split_row(line), self.split_row(lines[i + 1])
                if len(head) == len(sep) and all(re.fullmatch(r":?-+:?", c) for c in sep):
                    aligns = ["center" if c.startswith(":") and c.endswith(":") else
                              "right" if c.endswith(":") else
                              "left" if c.startswith(":") else "" for c in sep]

                    def cell(tag, text, a):
                        style = f' style="text-align:{a}"' if a else ""
                        return f"<{tag}{style}>{self.inline(text)}</{tag}>"

                    rows = []
                    i += 2
                    while i < n and lines[i].strip() and "|" in lines[i]:
                        rows.append(self.split_row(lines[i]))
                        i += 1
                    thead = "".join(cell("th", c, aligns[k]) for k, c in enumerate(head))
                    tbody = "".join(
                        "<tr>" + "".join(cell("td", r[k] if k < len(r) else "", aligns[k])
                                         for k in range(len(head))) + "</tr>" for r in rows)
                    out.append(f'<div class="table-wrap"><table><thead><tr>{thead}</tr></thead>'
                               f"<tbody>{tbody}</tbody></table></div>")
                    continue

            m = ITEM.match(line)
            if m:
                base = len(m.group(1))
                ordered = m.group(2)[0].isdigit()
                start = int(m.group(2)[:-1]) if ordered else 1

                def same_list(lm):
                    return bool(lm) and len(lm.group(1)) == base and lm.group(2)[0].isdigit() == ordered

                items: list[list[str]] = []
                cur: list[str] = []
                while i < n:
                    l = lines[i]
                    lm = ITEM.match(l)
                    if same_list(lm) and not HR.match(l):
                        cur = [lm.group(3)]
                        items.append(cur)
                        i += 1
                        continue
                    if not l.strip():
                        j = i
                        while j < n and not lines[j].strip():
                            j += 1
                        if j < n and (_indent(lines[j]) > base or same_list(ITEM.match(lines[j]))):
                            cur.extend([""] * (j - i))
                            i = j
                            continue
                        break
                    if _indent(l) > base:
                        cur.append(l[min(_indent(l), base + 2):])
                        i += 1
                        continue
                    if not self.is_block_start(l, True):
                        cur.append(l.strip())   # lazy continuation
                        i += 1
                        continue
                    break
                tag = "ol" if ordered else "ul"
                start_attr = f' start="{start}"' if ordered and start != 1 else ""
                lis = "".join(
                    "<li>" + re.sub(r"^<p>([\s\S]*?)</p>", r"\1", self.blocks(it), count=1) + "</li>"
                    for it in items)
                out.append(f"<{tag}{start_attr}>{lis}</{tag}>")
                continue

            buf = [line.strip()]
            i += 1
            while i < n and lines[i].strip() and not self.is_block_start(lines[i], True):
                buf.append(lines[i].strip())
                i += 1
            out.append(f"<p>{self.inline(chr(10).join(buf))}</p>")
        return "\n".join(out)

    # ── inline ────────────────────────────────────────────────
    def inline(self, raw: str) -> str:
        stash: list[str] = []

        def hold(html: str) -> str:
            stash.append(html)
            return f"\x00{len(stash) - 1}\x00"

        s = re.sub(r"(`+)([\s\S]*?[^`])\1(?!`)", lambda m: hold(f"<code>{esc(m.group(2).strip())}</code>"), raw)
        s = re.sub(r"\\([\\`*_{}\[\]()#+\-.!~|>])", lambda m: hold(esc(m.group(1))), s)
        s = self.format_inline(esc(s), hold)
        for _ in range(10):
            if not re.search(r"\x00\d+\x00", s):
                break
            s = re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], s)
        return s.replace("\n", "<br>\n")

    def format_inline(self, s: str, hold) -> str:
        url_re = r"((?:[^()\s]|\([^()\s]*\))+)"
        title_re = r"(?:\s+&quot;[\s\S]*?&quot;)?"
        s = re.sub(r"!\[([^\]]*)\]\(\s*" + url_re + title_re + r"\s*\)",
                   lambda m: hold(self.image_html(m.group(1), m.group(2))), s)
        s = re.sub(r"\[((?:[^\[\]]|\[[^\[\]]*\])+)\]\(\s*" + url_re + title_re + r"\s*\)",
                   lambda m: hold(self.link_html(self.format_inline(m.group(1), hold), m.group(2))), s)
        s = re.sub(r"&lt;((?:https?://|mailto:)\S*?)&gt;", lambda m: hold(self.link_html(m.group(1), m.group(1))), s)
        s = re.sub(r"\*\*\*(?=\S)([\s\S]*?\S)\*\*\*", r"<strong><em>\1</em></strong>", s)
        s = re.sub(r"\*\*(?=\S)([\s\S]*?\S)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"\*(?=\S)([\s\S]*?\S)\*", r"<em>\1</em>", s)
        s = re.sub(r"(^|[^\w])__(?=\S)([\s\S]*?\S)__(?!\w)", r"\1<strong>\2</strong>", s)
        s = re.sub(r"(^|[^\w])_(?=\S)([\s\S]*?\S)_(?!\w)", r"\1<em>\2</em>", s)
        s = re.sub(r"~~(?=\S)([\s\S]*?\S)~~", r"<del>\1</del>", s)
        return s

    @staticmethod
    def safe_url(url: str, kind: str) -> str | None:
        if "\x00" in url:
            return None
        clean = re.sub(r"[\x00-\x20\x7f]", "", url)
        m = re.match(r"^([a-z][a-z0-9+.\-]*):", clean, re.I)
        if not m:
            return url if kind == "link" else None
        scheme = m.group(1).lower()
        if kind == "link":
            return url if scheme in ("http", "https", "mailto", "tel") else None
        if scheme == "img":
            return clean if re.fullmatch(r"img:[a-z0-9]+", clean, re.I) else None
        if scheme == "data":
            ok = re.fullmatch(r"data:image/(png|jpe?g|gif|webp);base64,[a-z0-9+/=]+", clean, re.I)
            return clean if ok else None
        if scheme in ("http", "https"):
            return "remote"
        return None

    def image_html(self, alt: str, url: str) -> str:
        u = self.safe_url(url, "image")
        if u is None:
            return alt
        if u == "remote":
            return (f'<span class="img-note" title="Remote images are never loaded">'
                    f'Remote image not loaded{": " + alt if alt else ""}</span>')
        stored = re.fullmatch(r"img:([a-z0-9]+)", u, re.I)
        if stored:
            src = self.resolver(stored.group(1)) if self.resolver else None
            if not src:
                return f'<span class="img-note">Missing image{": " + alt if alt else ""}</span>'
            u = src
        return f'<img src="{u}" alt="{alt}">'

    def link_html(self, label_html: str, url: str) -> str:
        u = self.safe_url(url, "link")
        if u is None:
            return label_html
        return f'<a href="{u}" title="{u}">{label_html}</a>'


def render(md: str, resolver: ImageResolver | None = None) -> str:
    """Render Markdown source to an HTML fragment."""
    text = str(md or "").replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    lines = [re.sub(r"^\t+", lambda m: "    " * len(m.group(0)), l) for l in text.split("\n")]
    return _Renderer(resolver).blocks(lines)
