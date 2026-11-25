"""SQLite-backed storage for the Midgar library.

Everything lives in a single database file inside the user's data directory
(``$XDG_DATA_HOME/midgar/library.db``). The file is created with owner-only
permissions and opened with WAL journalling + ``synchronous=FULL`` so that a
crash or power loss can never leave a half-written chapter behind: every
change is a transaction that either fully lands or doesn't land at all.

Chapter text refers to pictures as ``![alt](img:<id>)``; the bytes live in the
``images`` table, so chapter text stays plain, portable Markdown.

This module has no GTK dependency so it can be tested headlessly.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import os
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

APP_MARKER = "midgar"
SCHEMA_VERSION = 1
IMG_REF = re.compile(r"img:([A-Za-z0-9]+)")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS images (
    id         TEXT PRIMARY KEY,
    mime       TEXT NOT NULL,
    data       BLOB NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS books (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    cover_id    TEXT,
    position    INTEGER NOT NULL,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS chapters (
    id         TEXT PRIMARY KEY,
    book_id    TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    title      TEXT NOT NULL,
    content    TEXT NOT NULL DEFAULT '',
    is_info    INTEGER NOT NULL DEFAULT 0,
    position   INTEGER NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS chapters_by_book ON chapters(book_id, position);
"""


class LibraryError(Exception):
    """A user-presentable storage error."""


@dataclass
class Book:
    id: str
    title: str
    description: str
    cover_id: str | None
    position: int
    updated_at: float
    chapter_count: int = 0
    info_count: int = 0

    @property
    def regular_count(self) -> int:
        return self.chapter_count - self.info_count


@dataclass
class Chapter:
    id: str
    book_id: str
    title: str
    content: str
    is_info: bool
    position: int
    updated_at: float


@dataclass
class SearchHit:
    kind: str            # "book" or "chapter"
    book_id: str
    book_title: str
    chapter_id: str | None
    title: str
    snippet: str


def new_id() -> str:
    return uuid.uuid4().hex


def image_refs(text: str | None) -> set[str]:
    return set(IMG_REF.findall(text or ""))


def _now() -> float:
    return time.time()


def _like_pattern(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _plain(md: str) -> str:
    """Rough Markdown → plain text, for search snippets."""
    s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", md)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"(?m)^\s*(?:[-*+]|\d+[.)])\s+", "", s)        # list markers
    s = re.sub(r"(?m)^\s*\|?[\s:|-]*-{3,}[\s:|-]*$", "", s)    # table rules / hr
    s = re.sub(r"[`*_~#>|]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _snippet(text: str, query: str, width: int = 120) -> str:
    plain = _plain(text)
    idx = plain.lower().find(query.lower())
    if idx < 0:
        return plain[:width] + ("…" if len(plain) > width else "")
    start = max(0, idx - width // 3)
    end = min(len(plain), start + width)
    return ("…" if start else "") + plain[start:end] + ("…" if end < len(plain) else "")


def _secure_create(path: Path) -> None:
    """Create ``path`` (if missing) readable only by the current user."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with contextlib.suppress(OSError):
        os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    os.close(fd)
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)


def _connect(path: Path | str, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        uri = Path(path).resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, isolation_level=None)
    else:
        conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


class Store:
    """All library reads and writes go through here."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        # Images added during an open editor/dialog session that are not yet
        # referenced by saved text. Garbage collection never deletes these.
        self.pending: set[str] = set()
        try:
            _secure_create(self.path)
            self._conn = _connect(self.path)
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = FULL")
            self._migrate()
        except sqlite3.DatabaseError as err:
            raise LibraryError(f"Could not open the library at {self.path}: {err}") from err

    # ── plumbing ───────────────────────────────────────────────
    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._conn.execute("PRAGMA optimize")
        self._conn.close()

    @contextlib.contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield self._conn
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")

    def _migrate(self) -> None:
        # executescript() commits implicitly, so the idempotent DDL runs on its own.
        self._conn.executescript("BEGIN;" + _SCHEMA + "COMMIT;")
        with self.transaction() as c:
            row = c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if row and int(row["value"]) > SCHEMA_VERSION:
                raise LibraryError("This library was created by a newer version of Midgar.")
            c.execute("INSERT OR REPLACE INTO meta VALUES ('app', ?)", (APP_MARKER,))
            c.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))

    # ── settings (tiny key/value store, kept with the data) ─────
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key=?", ("pref." + key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.transaction() as c:
            c.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", ("pref." + key, str(value)))

    # ── books ──────────────────────────────────────────────────
    _BOOK_SELECT = """
        SELECT b.*,
               (SELECT COUNT(*) FROM chapters c WHERE c.book_id = b.id) AS chapter_count,
               (SELECT COUNT(*) FROM chapters c WHERE c.book_id = b.id AND c.is_info) AS info_count
        FROM books b
    """

    @staticmethod
    def _book(row: sqlite3.Row) -> Book:
        return Book(row["id"], row["title"], row["description"], row["cover_id"],
                    row["position"], row["updated_at"], row["chapter_count"], row["info_count"])

    def list_books(self) -> list[Book]:
        rows = self._conn.execute(self._BOOK_SELECT + " ORDER BY b.position, b.created_at")
        return [self._book(r) for r in rows]

    def get_book(self, book_id: str) -> Book | None:
        row = self._conn.execute(self._BOOK_SELECT + " WHERE b.id = ?", (book_id,)).fetchone()
        return self._book(row) if row else None

    def create_book(self, title: str, description: str = "", cover_id: str | None = None) -> Book:
        bid, now = new_id(), _now()
        with self.transaction() as c:
            pos = c.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM books").fetchone()[0]
            c.execute("INSERT INTO books VALUES (?,?,?,?,?,?,?)",
                      (bid, title.strip() or "Untitled Book", description.strip(), cover_id, pos, now, now))
        self.pending.discard(cover_id)
        return self.get_book(bid)

    def update_book(self, book_id: str, title: str, description: str, cover_id: str | None) -> None:
        with self.transaction() as c:
            c.execute("UPDATE books SET title=?, description=?, cover_id=?, updated_at=? WHERE id=?",
                      (title.strip() or "Untitled Book", description.strip(), cover_id, _now(), book_id))
        self.pending.discard(cover_id)
        self.gc_images()

    def delete_book(self, book_id: str) -> None:
        with self.transaction() as c:
            c.execute("DELETE FROM books WHERE id=?", (book_id,))
        self.gc_images()

    def reorder_books(self, ordered_ids: Iterable[str]) -> None:
        with self.transaction() as c:
            c.executemany("UPDATE books SET position=? WHERE id=?",
                          [(i, bid) for i, bid in enumerate(ordered_ids)])

    # ── chapters ───────────────────────────────────────────────
    @staticmethod
    def _chapter(row: sqlite3.Row) -> Chapter:
        return Chapter(row["id"], row["book_id"], row["title"], row["content"],
                       bool(row["is_info"]), row["position"], row["updated_at"])

    def list_chapters(self, book_id: str) -> list[Chapter]:
        rows = self._conn.execute(
            "SELECT * FROM chapters WHERE book_id=? ORDER BY position, created_at", (book_id,))
        return [self._chapter(r) for r in rows]

    def get_chapter(self, chapter_id: str) -> Chapter | None:
        row = self._conn.execute("SELECT * FROM chapters WHERE id=?", (chapter_id,)).fetchone()
        return self._chapter(row) if row else None

    def create_chapter(self, book_id: str, title: str, content: str = "", is_info: bool = False) -> Chapter:
        cid, now = new_id(), _now()
        with self.transaction() as c:
            pos = c.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM chapters WHERE book_id=?",
                            (book_id,)).fetchone()[0]
            c.execute("INSERT INTO chapters VALUES (?,?,?,?,?,?,?,?)",
                      (cid, book_id, title.strip() or "Untitled Chapter", content, int(is_info), pos, now, now))
            c.execute("UPDATE books SET updated_at=? WHERE id=?", (now, book_id))
        self.pending -= image_refs(content)
        return self.get_chapter(cid)

    def update_chapter(self, chapter_id: str, title: str, content: str, is_info: bool) -> None:
        now = _now()
        with self.transaction() as c:
            c.execute("UPDATE chapters SET title=?, content=?, is_info=?, updated_at=? WHERE id=?",
                      (title.strip() or "Untitled Chapter", content, int(is_info), now, chapter_id))
            c.execute("UPDATE books SET updated_at=? WHERE id=(SELECT book_id FROM chapters WHERE id=?)",
                      (now, chapter_id))
        self.pending -= image_refs(content)
        self.gc_images()

    def delete_chapter(self, chapter_id: str) -> None:
        with self.transaction() as c:
            c.execute("DELETE FROM chapters WHERE id=?", (chapter_id,))
        self.gc_images()

    def reorder_chapters(self, book_id: str, ordered_ids: Iterable[str]) -> None:
        with self.transaction() as c:
            c.executemany("UPDATE chapters SET position=? WHERE id=? AND book_id=?",
                          [(i, cid, book_id) for i, cid in enumerate(ordered_ids)])

    # ── images ─────────────────────────────────────────────────
    def add_image(self, mime: str, data: bytes) -> str:
        iid = new_id()
        with self.transaction() as c:
            c.execute("INSERT INTO images VALUES (?,?,?,?)", (iid, mime, sqlite3.Binary(data), _now()))
        self.pending.add(iid)
        return iid

    def get_image(self, image_id: str) -> tuple[str, bytes] | None:
        row = self._conn.execute("SELECT mime, data FROM images WHERE id=?", (image_id,)).fetchone()
        return (row["mime"], bytes(row["data"])) if row else None

    def discard_pending(self, ids: Iterable[str]) -> None:
        """Forget about uploads from a cancelled session and delete them if unused."""
        self.pending -= set(ids)
        self.gc_images()

    def gc_images(self) -> int:
        """Delete images no saved chapter or cover refers to. Returns count removed."""
        keep = set(self.pending)
        for row in self._conn.execute("SELECT content FROM chapters"):
            keep |= image_refs(row["content"])
        for row in self._conn.execute("SELECT cover_id FROM books WHERE cover_id IS NOT NULL"):
            keep.add(row["cover_id"])
        all_ids = [r["id"] for r in self._conn.execute("SELECT id FROM images")]
        doomed = [(i,) for i in all_ids if i not in keep]
        if doomed:
            with self.transaction() as c:
                c.executemany("DELETE FROM images WHERE id=?", doomed)
        return len(doomed)

    # ── search ─────────────────────────────────────────────────
    def search(self, query: str, limit: int = 100) -> list[SearchHit]:
        q = query.strip()
        if not q:
            return []
        pat = _like_pattern(q)
        hits: list[SearchHit] = []
        for r in self._conn.execute(
                "SELECT id, title, description FROM books "
                "WHERE title LIKE :pat ESCAPE '\\' OR description LIKE :pat ESCAPE '\\' "
                "ORDER BY position LIMIT :lim", {"pat": pat, "lim": limit}):
            hits.append(SearchHit("book", r["id"], r["title"], None, r["title"],
                                  _snippet(r["description"], q) if r["description"] else ""))
        for r in self._conn.execute(
                "SELECT c.id, c.title, c.content, b.id AS bid, b.title AS btitle FROM chapters c "
                "JOIN books b ON b.id = c.book_id "
                "WHERE c.title LIKE :pat ESCAPE '\\' OR c.content LIKE :pat ESCAPE '\\' "
                "ORDER BY b.position, c.position LIMIT :lim", {"pat": pat, "lim": limit}):
            hits.append(SearchHit("chapter", r["bid"], r["btitle"], r["id"], r["title"],
                                  _snippet(r["content"], q)))
        return hits

    # ── backup / restore ───────────────────────────────────────
    def backup_to(self, dest: Path | str) -> None:
        """Write a consistent, self-contained copy of the library to ``dest``."""
        dest = Path(dest)
        tmp = dest.with_name(dest.name + ".part")
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
        os.close(fd)
        try:
            out = sqlite3.connect(str(tmp))
            try:
                self._conn.backup(out)
                out.execute("PRAGMA journal_mode = DELETE")
            finally:
                out.close()
            os.replace(tmp, dest)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                tmp.unlink()
            raise

    @staticmethod
    def validate_backup(path: Path | str) -> None:
        """Raise LibraryError unless ``path`` is an intact Midgar library."""
        try:
            conn = _connect(path, readonly=True)
        except sqlite3.Error as err:
            raise LibraryError("That file could not be opened.") from err
        try:
            row = conn.execute("SELECT value FROM meta WHERE key='app'").fetchone()
            if not row or row["value"] != APP_MARKER:
                raise LibraryError("That file is not a Midgar library backup.")
            ver = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if not ver or int(ver["value"]) > SCHEMA_VERSION:
                raise LibraryError("That backup was made by a newer version of Midgar.")
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise LibraryError("That backup is damaged and cannot be restored.")
        except sqlite3.DatabaseError as err:
            raise LibraryError("That file is not a Midgar library backup.") from err
        finally:
            conn.close()

    def restore_from(self, src: Path | str, safety_dir: Path | str | None = None) -> Path | None:
        """Replace the whole library with the backup at ``src``.

        The current library is first saved to ``safety_dir`` (if given) so a
        mistaken restore can always be undone. Returns that safety copy's path.
        """
        self.validate_backup(src)
        safety = None
        if safety_dir is not None:
            safety_dir = Path(safety_dir)
            safety_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            safety = safety_dir / f"before-restore-{stamp}.db"
            self.backup_to(safety)
        source = _connect(src, readonly=True)
        try:
            source.backup(self._conn)   # atomic page-level copy into the live database
        finally:
            source.close()
        self.pending.clear()
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()
        return safety

    def snapshot(self, directory: Path | str, keep: int = 7) -> Path | None:
        """Keep one automatic snapshot per day, pruning to the newest ``keep``."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        today = directory / f"library-{_dt.date.today().isoformat()}.db"
        made = None
        if not today.exists():
            self.backup_to(today)
            made = today
        snaps = sorted(directory.glob("library-????-??-??.db"))
        for old in snaps[:-keep] if keep > 0 else snaps:
            with contextlib.suppress(OSError):
                old.unlink()
        return made

    def stats(self) -> dict[str, int]:
        c = self._conn
        return {
            "books": c.execute("SELECT COUNT(*) FROM books").fetchone()[0],
            "chapters": c.execute("SELECT COUNT(*) FROM chapters").fetchone()[0],
            "images": c.execute("SELECT COUNT(*) FROM images").fetchone()[0],
            "bytes": self.path.stat().st_size if self.path.exists() else 0,
        }
