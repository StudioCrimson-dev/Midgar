# Midgar

A quiet, private place to write and read your own books — now a native
Linux desktop app built with GTK 4 and libadwaita, designed for Arch Linux
and tuned for tiling Wayland compositors such as **Hyprland**.

Organise long-form writing into books and chapters, write in Markdown with
inline pictures, and read it back in a clean, book-like view. Everything
stays on your device. There are no accounts, no sync and no network
connections — ever.

---

## Features

- **Library** — a cover grid of your books. Drag covers to reorder them (or
  use *Move Earlier / Later* from the card menu). Books without a cover get a
  typographic one automatically.
- **Books & chapters** — any number of chapters per book. Chapters can be
  marked as **information chapters** (notes, glossaries, worldbuilding); they
  are labelled `INFO`, left out of the chapter numbering and counted
  separately. Drag chapters in the sidebar to reorder them.
- **Reader** — a typeset reading view with chapter eyebrows, previous / next
  navigation, adjustable text size and a serif or sans typeface. It follows
  your light / dark preference.
- **Editor** — Markdown with syntax highlighting, a formatting toolbar,
  live **Write / Preview** switcher, word and character counts, and an
  unsaved-changes guard (you can't lose work by closing the editor or the
  window).
- **Pictures** — paste, drag-and-drop or insert images. Large photos are
  downscaled automatically; pictures are stored inside the library and
  referenced from the text as `img:<id>`.
- **Library-wide search** — `Ctrl+F` searches book titles, descriptions,
  chapter titles and chapter text, with result snippets.
- **Import Markdown** — bulk-import `.md` / `.markdown` / `.mdown` / `.txt`
  files as chapters. Select the referenced pictures at the same time and they
  are matched up by file name.
- **Export & backup** — see [Your data](#your-data).

## Install (Arch Linux)

```bash
git clone https://github.com/StudioCrimson-dev/The-Library.git
cd The-Library/packaging/arch
makepkg -si
```

This builds a regular pacman package (`midgar`) from your checkout, runs the
test-suite and installs the `midgar` command, desktop entry, icon and
AppStream metadata. Remove it with `sudo pacman -R midgar`.

Runtime dependencies (installed automatically): `python`, `python-gobject`,
`gtk4`, `libadwaita`, `webkitgtk-6.0`, `gtksourceview5`, `gdk-pixbuf2`.

Recommended optional packages:

| Package                  | Why                                                             |
|--------------------------|-----------------------------------------------------------------|
| `xdg-desktop-portal-gtk` | Native file pickers and light/dark following on Hyprland        |
| `webp-pixbuf-loader`     | Lets you add `.webp` pictures                                   |
| `noto-fonts`             | A good serif face for the reader (any installed serif works)    |

### Troubleshooting

- **`No module named build` / `No module named gi`** — an older copy of the
  PKGBUILD, or running from source, picked up a Python from a version manager
  (mise, pyenv, asdf, conda — Omarchy sets up mise by default) instead of
  Arch's. The current PKGBUILD always uses `/usr/bin/python`; `git pull` and
  run `makepkg -si` again. To run from source, use `/usr/bin/python -m midgar`.

### Running from source

No build step is needed during development:

```bash
/usr/bin/python -m midgar
```

Run the tests with `/usr/bin/python -m pytest`.

## Hyprland notes

Midgar is a native Wayland client (no XWayland) and draws its own header bar,
so it doesn't depend on compositor decorations.

- **Window class / app id:** `io.github.studiocrimson_dev.Midgar` — use it in
  window rules, e.g. (Hyprland's `windowrulev2` syntax; adjust to your
  version):

  ```ini
  windowrulev2 = workspace 3, class:^(io\.github\.studiocrimson_dev\.Midgar)$
  ```

- **Tiling-friendly layout:** the book view collapses its chapter sidebar into
  an overlay below ~760 px wide, so it stays usable in narrow tiles; the
  library grid reflows to any width.
- **Dark mode:** libadwaita reads the system colour scheme through the
  desktop portal. On Hyprland install `xdg-desktop-portal-gtk` and set:

  ```bash
  gsettings set org.gnome.desktop.interface color-scheme prefer-dark
  ```

- **Hide the window buttons** if you never use them (tiling users often
  don't): add `gtk-decoration-layout=:` under `[Settings]` in
  `~/.config/gtk-4.0/settings.ini`.
- **Keyboard first:** everything is reachable from the keyboard — see below or
  press `Ctrl+?` in the app.

## Keyboard shortcuts

| Shortcut                   | Action                              |
|----------------------------|-------------------------------------|
| `Ctrl+N`                   | New book                            |
| `Ctrl+F`                   | Search the library                  |
| `Ctrl+Shift+B`             | Back up library                     |
| `Ctrl+?`                   | Show all shortcuts                  |
| `Ctrl+Q`                   | Quit                                |
| `Alt+←` / `Alt+→`          | Previous / next chapter             |
| `Ctrl+E`                   | Edit chapter                        |
| `Ctrl+Shift+N`             | New chapter                         |
| `Ctrl+I` (reading)         | Import Markdown into this book      |
| `Alt+↑` / `Alt+↓`          | Move chapter up / down              |
| `Ctrl+=` / `Ctrl+-` / `Ctrl+0` | Reader text size                |
| `F9`                       | Toggle chapter sidebar              |
| `Ctrl+S`                   | Save chapter                        |
| `Ctrl+P`                   | Toggle Write / Preview              |
| `Ctrl+B` / `Ctrl+I` (editor) | Bold / italic                     |
| `Ctrl+K`                   | Insert link                         |
| `Ctrl+Shift+I`             | Insert pictures                     |
| `Esc` / `Ctrl+W`           | Close the editor                    |

## Your data

### Where it lives

Everything — books, chapters and pictures — is stored in one SQLite database:

```
~/.local/share/midgar/library.db        ($XDG_DATA_HOME/midgar)
~/.local/share/midgar/snapshots/        automatic daily snapshots (last 7)
~/.local/share/midgar/safety/           copies made before a restore
```

Set `MIDGAR_DATA_DIR` to use a different folder (handy for a second, separate
library or for testing).

### Why SQLite

- **Crash-safe.** Every change is a transaction written with write-ahead
  logging and full sync, so a crash or power cut can't leave a half-saved
  chapter or a corrupted library.
- **Private.** The data folder is created `0700` and the database `0600` —
  readable only by your user.
- **One file to protect.** Easy to back up, easy to move.

### Backups

- **Automatic snapshots:** once a day, on start-up, Midgar keeps a consistent
  copy of the library in `snapshots/` (the last seven days).
- **Back Up Library…** (main menu, `Ctrl+Shift+B`) writes a single
  self-contained `.midgar` file. Copy it wherever you like — a USB drive, your
  own NAS or your own cloud storage. Midgar itself never uploads anything.
- **Restore from Backup…** checks that the file is an intact Midgar library,
  saves a safety copy of your current library, then replaces it.

> Tip: don't copy `library.db` by hand while Midgar is running — use *Back Up
> Library…*, which always produces a consistent file.

### Export / import as Markdown

- **Export as Markdown…** (per book, or *Export Library as Markdown…* from the
  main menu) writes a zip containing one folder per book: numbered chapter
  `.md` files with front matter (`title:`, `info: true`), an `images/`
  folder, the cover, and a `book.json` with the book's details.
- **Import Books from Export…** turns such a zip back into books (always as
  new books — nothing existing is overwritten).
- The chapter files are plain Markdown, so they also open in any other editor.

## Privacy & security

- No network code, no telemetry, no update checks.
- The reader is a WebKitGTK view with JavaScript, plugins, media and storage
  disabled, an ephemeral session (no cookies or cache on disk) and a strict
  Content-Security-Policy that blocks every network fetch. Pictures are
  inlined from the local database.
- **Remote images are never loaded.** `![](https://…)` shows a "remote image
  not loaded" note instead, so reading a chapter can't contact a server.
- Links open in your web browser only when you click them.
- Markdown never renders raw HTML — it is escaped and shown as text, so
  imported files can't inject anything.

## Markdown reference

```markdown
# Heading 1
## Heading 2

**bold**, *italic*, ***bold italic***, ~~strikethrough~~

> A blockquote,
> which can span multiple lines.

- A bullet list
  - nested

1. A numbered list
2. Keeps its order

`inline code`

​```
a fenced code block
​```

| Column A | Column B |
|----------|:--------:|
| left     | centered |

[A link](https://example.com)
![A picture](img:abc123)

---
```

## Project structure

```
midgar/
├── application.py   # Adw.Application: startup, CSS, accelerators
├── window.py        # Main window, navigation, import/export/backup actions
├── library_page.py  # Cover grid, search, drag-to-reorder
├── book_page.py     # Chapter sidebar + reader
├── editor_page.py   # Markdown editor (GtkSourceView) + preview
├── book_dialog.py   # New / edit book dialog
├── reader.py        # Hardened WebKit reading view
├── markdown.py      # Dependency-free, escaping Markdown renderer
├── store.py         # SQLite data layer (no GTK — unit-tested)
├── transfer.py      # Markdown import, zip export/import (no GTK)
├── images.py        # Picture validation, downscaling, textures
├── ui.py            # Dialog / file-picker helpers
├── paths.py         # XDG data locations
└── style.css        # App stylesheet
data/                # .desktop file, AppStream metadata, icons
packaging/arch/      # PKGBUILD
tests/               # pytest suite for the storage, Markdown and transfer layers
```

## Coming from the web version

The previous browser version kept everything in the browser's IndexedDB,
which the desktop app can't read. To bring writing across, copy each
chapter's text into a `.md` file and use **Import Markdown…** in the book
(select the pictures at the same time).

## License

Currently none, because the project is private.
