import os
import stat
import zipfile

import pytest

from midgar import markdown
from midgar.store import LibraryError, Store
from midgar.transfer import export_zip, import_markdown, import_zip, split_markdown_doc


def passthrough(data, name):
    return data, "image/png"


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "data" / "library.db")
    yield s
    s.close()


def test_file_is_private(store):
    assert stat.S_IMODE(os.stat(store.path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(store.path.parent).st_mode) == 0o700


def test_books_chapters_and_counts(store):
    b = store.create_book("  Dune ", "Sand")
    store.create_chapter(b.id, "One", "text")
    store.create_chapter(b.id, "Glossary", "words", is_info=True)
    got = store.get_book(b.id)
    assert (got.title, got.chapter_count, got.info_count, got.regular_count) == ("Dune", 2, 1, 1)
    store.delete_book(b.id)
    assert store.list_books() == []
    assert store.stats()["chapters"] == 0   # cascade


def test_reorder(store):
    a, b, c = (store.create_book(t) for t in "abc")
    store.reorder_books([c.id, a.id, b.id])
    assert [x.title for x in store.list_books()] == ["c", "a", "b"]
    ch = [store.create_chapter(a.id, t) for t in "xyz"]
    store.reorder_chapters(a.id, [ch[2].id, ch[0].id, ch[1].id])
    assert [x.title for x in store.list_chapters(a.id)] == ["z", "x", "y"]


def test_image_gc_respects_pending_and_refs(store):
    b = store.create_book("B")
    used = store.add_image("image/png", b"1")
    orphan = store.add_image("image/png", b"2")
    store.gc_images()
    assert store.get_image(orphan)          # still pending → kept
    store.create_chapter(b.id, "c", f"![x](img:{used})")
    store.discard_pending([orphan])
    assert store.get_image(orphan) is None
    assert store.get_image(used)


def test_search(store):
    b = store.create_book("Atlas", "maps of the world")
    store.create_chapter(b.id, "North", "The **glacier** was 100% blue")
    hits = store.search("glacier")
    assert hits[0].kind == "chapter" and "glacier" in hits[0].snippet
    assert store.search("100%")[0].chapter_id   # LIKE wildcards escaped
    assert store.search("_") == []
    assert store.search("maps")[0].kind == "book"


def test_backup_restore_roundtrip(store, tmp_path):
    b = store.create_book("Keep me")
    store.create_chapter(b.id, "c", "hello")
    backup = tmp_path / "b.midgar"
    store.backup_to(backup)
    store.delete_book(b.id)
    store.create_book("Temp")
    safety = store.restore_from(backup, tmp_path / "safety")
    assert [x.title for x in store.list_books()] == ["Keep me"]
    assert safety and safety.exists()
    store.create_book("after restore still writable")
    assert len(store.list_books()) == 2


def test_validate_rejects_junk(tmp_path):
    p = tmp_path / "junk"
    p.write_bytes(b"not a database at all" * 100)
    with pytest.raises(LibraryError):
        Store.validate_backup(p)


def test_snapshot_rotation(store, tmp_path):
    d = tmp_path / "snaps"
    d.mkdir()
    for day in range(1, 10):
        (d / f"library-2020-01-0{day}.db").write_bytes(b"")
    store.snapshot(d, keep=3)
    assert len(list(d.glob("library-*.db"))) == 3


def test_markdown_escapes_and_blocks_remote():
    html = markdown.render("<script>alert(1)</script>\n\n![x](https://evil.example/p.png)\n\n[l](javascript:alert(1))")
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "evil.example" not in html and "Remote image not loaded" in html
    assert "javascript" not in html.split("<p>l")[0] and 'href="javascript' not in html


def test_markdown_features():
    md = "# T\n\n- a\n  - b\n\n1. x\n2. y\n\n| a | b |\n|---|:-:|\n| 1 | 2 |\n\n```py\n<x>\n```\n\n> q\n\n**b** *i* ~~s~~ `c`"
    html = markdown.render(md, resolver=lambda i: None)
    for frag in ("<h1>T</h1>", "<ul><li>a\n<ul><li>b</li></ul></li></ul>", "<ol><li>x</li><li>y</li></ol>",
                 'style="text-align:center"', '<code class="lang-py">&lt;x&gt;</code>', "<blockquote>",
                 "<strong>b</strong>", "<em>i</em>", "<del>s</del>", "<code>c</code>"):
        assert frag in html, frag
    assert "1999. It" in markdown.render("back in\n1999. It was")


def test_markdown_local_images():
    html = markdown.render("![cat](img:abc123)", resolver=lambda i: "data:image/png;base64,AAAA")
    assert '<img src="data:image/png;base64,AAAA" alt="cat">' in html


def test_split_doc():
    assert split_markdown_doc('---\ntitle: "A: B"\ninfo: true\n---\n# A: B\nbody', "f.md") == ("A: B", "body", True)
    assert split_markdown_doc("# Head\ntext", "x.md")[:2] == ("Head", "text")
    assert split_markdown_doc("text", "my-file_name.md")[0] == "my file name"


def test_import_export_roundtrip(store, tmp_path):
    b = store.create_book("Book/One", "desc")
    files = [("02-two.md", b"# Two\n![p](pics/Cat.PNG)"), ("10-ten.md", b"ten"), ("01-one.md", b"one"),
             ("cat.png", b"PNGDATA"), ("unused.png", b"X")]
    res = import_markdown(store, b.id, files, passthrough)
    assert [c.title for c in res.chapters] == ["01 one", "Two", "10 ten"]
    assert res.unmatched_images == 0
    assert store.stats()["images"] == 1            # unused.png garbage-collected
    out = tmp_path / "export.zip"
    assert export_zip(store, out) == 1
    names = zipfile.ZipFile(out).namelist()
    assert any(n.startswith("Book One/images/") for n in names)
    books, r2 = import_zip(store, out, passthrough)
    assert books[0].title == "Book/One" and books[0].description == "desc"
    assert [c.title for c in store.list_chapters(books[0].id)] == ["01 one", "Two", "10 ten"]
    assert "img:" in store.list_chapters(books[0].id)[1].content
    assert r2.unmatched_images == 0
