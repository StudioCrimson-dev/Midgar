"""Moving writing in and out of the library as plain Markdown.

* ``import_markdown`` turns ``.md`` files (plus any images they reference,
  matched by file name) into chapters.
* ``export_zip`` writes one book, or the whole library, as a zip of Markdown
  files with an ``images/`` folder per book. The layout round-trips: selecting
  a book folder's ``.md`` files and its images in *Import Markdown* recreates
  the chapters, pictures included.

No GTK here: image preparation is injected so this stays testable.
"""

from __future__ import annotations

import contextlib
import json
import mimetypes
import os
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .store import IMG_REF, Book, Chapter, Store

MARKDOWN_EXTS = (".md", ".markdown", ".mdown", ".txt")
PrepareImage = Callable[[bytes, str], tuple[bytes, str]]   # (data, filename) → (data, mime)


def natural_key(name: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def split_markdown_doc(text: str, filename: str) -> tuple[str, str, bool]:
    """Split a Markdown file into (title, body, is_info).

    Title comes from YAML front matter ``title:``, else a leading ``# Heading``,
    else the file name. ``info: true`` in front matter marks an information
    chapter (that's what Midgar's own export writes).
    """
    body = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    title, is_info = "", False
    fm = re.match(r"^---\n([\s\S]*?)\n---[ \t]*(?:\n|$)", body)
    if fm:
        t = re.search(r"^title:[ \t]*(.+)$", fm.group(1), re.M | re.I)
        if t:
            title = re.sub(r"^(['\"])(.*)\1$", r"\2", t.group(1).strip())
            if t.group(1).strip().startswith('"'):
                with contextlib.suppress(ValueError):
                    title = json.loads(t.group(1).strip())
        info = re.search(r"^info:[ \t]*(\S+)", fm.group(1), re.M | re.I)
        is_info = bool(info and info.group(1).lower() in ("true", "yes", "1"))
        body = body[fm.end():]
    h1 = re.match(r"^\s*#[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*(?:\n|$)", body)
    if h1:
        heading = re.sub(r"[*`]", "", h1.group(1).strip())
        if not title or heading.lower() == title.lower():
            title = title or heading
            body = body[h1.end():]   # shown separately — drop the duplicate heading
    if not title:
        stem = filename.rsplit(".", 1)[0] if "." in filename else filename
        title = re.sub(r"[-_]+", " ", stem).strip() or "Untitled Chapter"
    return title, body.lstrip("\n"), is_info


def rewrite_image_refs(text: str, image_map: dict[str, str]) -> tuple[str, int]:
    """Point ``![](some/dir/pic.png)`` at the imported image of the same name."""
    missing = 0

    def repl(m: re.Match) -> str:
        nonlocal missing
        pre, url = m.group(1), m.group(2)
        if re.match(r"^(https?:|data:|img:)", url, re.I):
            return m.group(0)
        from urllib.parse import unquote
        name = unquote(re.split(r"[?#]", url)[0].rsplit("/", 1)[-1]).lower()
        iid = image_map.get(name)
        if iid:
            return f"{pre}img:{iid}"
        missing += 1
        return m.group(0)

    out = re.sub(r"(!\[[^\]]*\]\(\s*)((?:[^()\s]|\([^()\s]*\))+)", repl, text)
    return out, missing


@dataclass
class ImportResult:
    chapters: list[Chapter] = field(default_factory=list)
    unmatched_images: int = 0
    errors: list[str] = field(default_factory=list)


def import_markdown(store: Store, book_id: str, files: Iterable[tuple[str, bytes]],
                    prepare_image: PrepareImage) -> ImportResult:
    files = list(files)
    md_files = sorted((f for f in files if f[0].lower().endswith(MARKDOWN_EXTS)), key=lambda f: natural_key(f[0]))
    img_files = [f for f in files if (mimetypes.guess_type(f[0])[0] or "").startswith("image/")]
    result = ImportResult()
    if not md_files:
        result.errors.append("Pick at least one Markdown file.")
        return result

    image_map: dict[str, str] = {}
    session: set[str] = set()
    for name, data in img_files:
        try:
            blob, mime = prepare_image(data, name)
            iid = store.add_image(mime, blob)
            session.add(iid)
            image_map[os.path.basename(name).lower()] = iid
        except Exception as err:  # noqa: BLE001 — one bad picture shouldn't stop the import
            result.errors.append(f"{os.path.basename(name)}: {err}")

    for name, data in md_files:
        try:
            text = data.decode("utf-8-sig", errors="replace")
            title, body, is_info = split_markdown_doc(text, os.path.basename(name))
            body, missing = rewrite_image_refs(body, image_map)
            result.unmatched_images += missing
            result.chapters.append(store.create_chapter(book_id, title, body, is_info))
        except Exception as err:  # noqa: BLE001
            result.errors.append(f"{os.path.basename(name)}: {err}")

    store.discard_pending(session)   # anything not referenced by an imported chapter goes
    return result


# ── export ─────────────────────────────────────────────────────
_UNSAFE = re.compile(r'[\x00-\x1f<>:"/\\|?*]+')


def safe_name(name: str, fallback: str) -> str:
    cleaned = _UNSAFE.sub(" ", name).strip().strip(".")
    return re.sub(r"\s+", " ", cleaned)[:80] or fallback


def _ext_for(mime: str) -> str:
    return {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp",
            "image/svg+xml": ".svg"}.get(mime, mimetypes.guess_extension(mime) or ".bin")


def _front_matter(ch: Chapter) -> str:
    lines = ["---", f"title: {json.dumps(ch.title, ensure_ascii=False)}"]
    if ch.is_info:
        lines.append("info: true")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def _write_book(zf: zipfile.ZipFile, store: Store, book: Book, root: str) -> None:
    written: dict[str, str] = {}

    def add_image(iid: str) -> str | None:
        if iid in written:
            return written[iid]
        img = store.get_image(iid)
        if not img:
            return None
        rel = f"images/{iid}{_ext_for(img[0])}"
        zf.writestr(f"{root}/{rel}", img[1])
        written[iid] = rel
        return rel

    meta = {"title": book.title, "description": book.description, "cover": None, "chapters": []}
    if book.cover_id:
        img = store.get_image(book.cover_id)
        if img:
            meta["cover"] = f"cover{_ext_for(img[0])}"
            zf.writestr(f"{root}/{meta['cover']}", img[1])

    chapters = store.list_chapters(book.id)
    width = max(2, len(str(len(chapters))))
    for n, ch in enumerate(chapters, 1):
        def repl(m: re.Match) -> str:
            rel = add_image(m.group(1))
            return rel if rel else m.group(0)
        body = IMG_REF.sub(repl, ch.content)
        fname = f"{n:0{width}d} - {safe_name(ch.title, 'Chapter')}.md"
        zf.writestr(f"{root}/{fname}", _front_matter(ch) + body.rstrip("\n") + "\n")
        meta["chapters"].append({"file": fname, "title": ch.title, "info": ch.is_info})
    zf.writestr(f"{root}/book.json", json.dumps(meta, indent=2, ensure_ascii=False) + "\n")


def export_zip(store: Store, dest: Path | str, book_ids: list[str] | None = None) -> int:
    """Export the given books (default: all) to a zip at ``dest``. Returns book count."""
    dest = Path(dest)
    books = store.list_books()
    if book_ids is not None:
        books = [b for b in books if b.id in set(book_ids)]
    tmp = dest.with_name(dest.name + ".part")
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            used: set[str] = set()
            width = max(2, len(str(len(books))))
            for n, book in enumerate(books, 1):
                base = safe_name(book.title, "Book")
                folder = base if len(books) == 1 else f"{n:0{width}d} - {base}"
                while folder.lower() in used:
                    folder += " (2)"
                used.add(folder.lower())
                _write_book(zf, store, book, folder)
        os.chmod(tmp, 0o600)
        os.replace(tmp, dest)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise
    return len(books)


def import_zip(store: Store, src: Path | str, prepare_image: PrepareImage) -> tuple[list[Book], ImportResult]:
    """Re-create books from a zip made by :func:`export_zip`.

    Each folder containing a ``book.json`` becomes a new book (existing books
    are never touched or overwritten).
    """
    books: list[Book] = []
    total = ImportResult()
    with zipfile.ZipFile(src) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        roots = sorted({n.rsplit("/", 1)[0] if "/" in n else "" for n in names
                        if n.rsplit("/", 1)[-1] == "book.json"}, key=natural_key)
        if not roots:
            total.errors.append("That zip doesn't contain a Midgar export (no book.json found).")
            return books, total
        for root in roots:
            prefix = f"{root}/" if root else ""
            try:
                meta = json.loads(zf.read(prefix + "book.json").decode("utf-8"))
            except (KeyError, ValueError) as err:
                total.errors.append(f"{root or 'book'}: unreadable book.json ({err})")
                continue
            cover_id = None
            if meta.get("cover"):
                with contextlib.suppress(KeyError, Exception):
                    blob, mime = prepare_image(zf.read(prefix + meta["cover"]), meta["cover"])
                    cover_id = store.add_image(mime, blob)
            book = store.create_book(str(meta.get("title") or root or "Imported Book"),
                                     str(meta.get("description") or ""), cover_id)
            order = [c.get("file") for c in meta.get("chapters", []) if c.get("file")]
            member_files = [n for n in names if n.startswith(prefix) and n != prefix + "book.json"
                            and "/" not in n[len(prefix):].replace("images/", "", 1)]
            md = [n for n in member_files if n.lower().endswith(MARKDOWN_EXTS)]
            rank = {f: i for i, f in enumerate(order)}
            md.sort(key=lambda n: (rank.get(n[len(prefix):], len(rank)), natural_key(n)))
            imgs = [n for n in member_files if n[len(prefix):].startswith("images/")]
            # Feed import_markdown in our chosen order (it sorts by name; prefix with rank).
            payload = [(f"{i:06d}-{os.path.basename(n)}", zf.read(n)) for i, n in enumerate(md)]
            payload += [(os.path.basename(n), zf.read(n)) for n in imgs]
            res = import_markdown(store, book.id, payload, prepare_image) if md else ImportResult()
            total.chapters += res.chapters
            total.unmatched_images += res.unmatched_images
            total.errors += [e for e in res.errors if not e.startswith("Pick at least")]
            books.append(store.get_book(book.id))
    return books, total
