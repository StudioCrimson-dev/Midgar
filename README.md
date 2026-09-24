# Midgar

A quiet, distraction-free place to write and read your own books. Midgar is a
single-page web app for organizing long-form writing into books and chapters,
with Markdown formatting, inline images, and a clean reading view — all
stored entirely in your browser.

No sign-in, no server, no account. Open the page and start writing.

---

## Features

- **Books & chapters** — organize your writing into books, each with any
  number of chapters. Chapters can be marked as "informational" (e.g. notes,
  glossaries, worldbuilding) and are called out separately from the regular
  chapter count.
- **Markdown editor** — a built-in Markdown renderer (no external libraries)
  supports headings, bold/italic/strikethrough, blockquotes, ordered and
  unordered lists (with nesting), fenced code blocks, tables, links, and
  images. A live **Preview** toggle lets you see the rendered chapter before
  saving.
- **Images, inline** — drop an image into the editor, paste one from your
  clipboard, or use the **+ Image** button. Images are stored locally
  alongside your text and referenced from it, so chapters stay portable.
  Book covers work the same way.
- **Markdown import** — bulk-import `.md` / `.markdown` / `.mdown` / `.txt`
  files as chapters in one go. Select any images referenced by those files at
  the same time and Midgar matches them up by file name automatically.
- **Autosave-safe editing** — Midgar warns you before you navigate away or
  close the tab with unsaved chapter changes, and `Ctrl`/`Cmd`+`S` saves the
  current chapter from anywhere in the editor.
- **Fully local & private** — everything you write stays on your device.
  There's no account, no network requests, and nothing is ever sent
  anywhere.

## How it works

Midgar is a static site: one HTML page, one stylesheet, and one JavaScript
file. There's no backend and no build step.

| File          | Purpose                                                        |
|---------------|-----------------------------------------------------------------|
| `index.html`  | Page structure/markup for every view (library, book, editor).  |
| `style.css`   | All visual styling.                                             |
| `app.js`      | App logic: rendering, the Markdown parser, and the data layer.  |

### Storage: IndexedDB

Midgar stores all of your data in [IndexedDB](https://developer.mozilla.org/en-US/docs/Web/API/IndexedDB_API),
a structured database built into every modern browser. It's used instead of
`localStorage` because it can hold much more data and — importantly — can
store binary data (your images) directly, rather than needing them
base64-encoded into text.

The database is named `midgar-db` and has three object stores:

- **`books`** — one record per book: `id`, `title`, `description`,
  `coverId` (points at an image), `order`, and denormalized `chapterCount`
  / `infoCount` so the library grid doesn't need to load full chapter lists.
- **`chapters`** — one record per chapter: `id`, `bookId` (indexed, so a
  book's chapters can be looked up directly), `title`, `content` (the raw
  Markdown text), `isInfo`, and `order`.
- **`images`** — one record per image: `id` and the raw `blob` (with its
  MIME `type`). Chapter and cover text never embeds image data directly —
  they reference an image by writing `![alt](img:<id>)`, and Midgar resolves
  that to the actual picture (as a temporary [object URL](https://developer.mozilla.org/en-US/docs/Web/API/URL/createObjectURL_static))
  at render time.

This means a chapter's Markdown source is always plain, portable text — the
`img:` references just aren't meaningful outside this app's own database.

### What this means for your data

- **It's per-browser, per-device.** Your library lives in *this browser's*
  storage on *this device*. It won't show up if you open Midgar in a
  different browser, a different computer, or a private/incognito window.
- **Clearing site data deletes it.** If you (or your browser) clear cookies
  and site data, use a "clean up storage" tool, or clear IndexedDB
  specifically, your library is gone. There is currently no export/backup
  feature — treat this as you would any other local-only app.
- **There's no sync.** Midgar doesn't talk to a network at all, so nothing
  is backed up automatically. If this matters to you, periodically copying
  your chapters' text elsewhere is worth doing until an export feature
  exists (see [Possible improvements](#possible-improvements)).
- **Private/incognito windows work, but don't persist.** Some browsers
  restrict or wipe IndexedDB when a private window closes — fine for trying
  Midgar out, not for anything you want to keep.

## Running it

Midgar needs no build tools, no `npm install`, and no server-side code.

**Option 1 — just open it.**
Double-click `index.html`, or open it via `File → Open` in your browser.
IndexedDB works fine from a `file://` URL in every major browser.

**Option 2 — serve it locally** (optional, but a good habit for web
projects in general):

```bash
# from the project folder
python3 -m http.server 8000
# then visit http://localhost:8000
```

Either way works identically — there's nothing to configure.

## Browser support

Midgar uses IndexedDB, the Canvas API (for resizing images before storing
them), and standard ES2017+ JavaScript. It works in current versions of
Chrome, Firefox, Safari, and Edge. Very old browsers, or browsers with
IndexedDB disabled by policy, won't be able to run it — Midgar will show a
toast explaining that local storage isn't available rather than failing
silently.

## Markdown reference

Midgar's Markdown support covers the everyday subset:

```markdown
# Heading 1
## Heading 2

**bold**, *italic*, ***bold italic***, ~~strikethrough~~

> A blockquote,
> which can span multiple lines.

- A bullet list
- With nested items
  - Like this

1. A numbered list
2. Keeps its order

`inline code` and:

​```js
a fenced code block
​```

| Column A | Column B |
|----------|:--------:|
| left     | centered |

[A link](https://example.com)
![An image](img:someuploadedimageid)

---
```

Raw HTML is not supported and is escaped rather than rendered, both for
simplicity and so that imported `.md` files can't inject anything into the
page.

## Keyboard shortcuts

| Shortcut          | Action                                  |
|--------------------|------------------------------------------|
| `Ctrl`/`Cmd` + `S` | Save the chapter you're editing          |
| `Esc`              | Close whichever dialog is open           |
| `Enter`            | Save, while focused in the book title field |

## Project structure

```
midgar/
├── index.html   # Views: library, book, chapter editor, modals
├── style.css    # All styling
├── app.js       # Rendering, Markdown parser, IndexedDB data layer
└── README.md    # You are here
```

## Possible improvements

Ideas that would be natural next steps, not yet implemented:

- **Export/import** — a way to download your whole library (including
  images) as a single file, and restore it later or move it to another
  browser/device.
- **Search** — finding a chapter by title or content across a large
  library.
- **Reordering** — drag-and-drop reordering of books and chapters (currently
  order is set by creation time).
- **Storage usage indicator** — since everything (including images) lives in
  the browser, a way to see how much space your library is using.

## License

Add whatever license fits your project here.