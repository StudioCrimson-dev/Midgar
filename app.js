/* ─────────────────────────────────────────────
   MIDGAR — app.js
   Storage: IndexedDB (local to your browser)
───────────────────────────────────────────── */
(function () {
'use strict';

const $ = id => document.getElementById(id);

// ── State ──────────────────────────────────
let state = {
  books: [],
  currentBookId: null,
  currentChapterId: null,
  editorMode: 'write',
  editingBookId: null,
  pendingDeleteFn: null,
};
let editorDirty = false;              // unsaved changes in the chapter editor
const pendingUploadIds = new Set();   // images stored this editing/modal session but not yet committed to a saved chapter/book

// ── IndexedDB data layer ────────────────────
// Object stores:
//   books    (keyPath: id)            → title, description, coverId, order, chapterCount, infoCount
//   chapters (keyPath: id, idx bookId) → bookId, title, content, isInfo, order
//   images   (keyPath: id)             → blob, type
// Chapter text refers to pictures as ![alt](img:<imageId>); the image bytes live in the
// "images" store, so the chapter text itself stays a plain, portable string.
const DB_NAME = 'midgar-db';
const DB_VERSION = 1;
let dbPromise = null;

function openDB() {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    if (!window.indexedDB) { reject(new Error('IndexedDB is not available in this browser.')); return; }
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const idb = req.result;
      if (!idb.objectStoreNames.contains('books')) idb.createObjectStore('books', { keyPath: 'id' });
      if (!idb.objectStoreNames.contains('chapters')) {
        const store = idb.createObjectStore('chapters', { keyPath: 'id' });
        store.createIndex('bookId', 'bookId');
      }
      if (!idb.objectStoreNames.contains('images')) idb.createObjectStore('images', { keyPath: 'id' });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return dbPromise;
}

function reqToPromise(req) {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function idbGet(store, key) {
  const idb = await openDB();
  return reqToPromise(idb.transaction(store, 'readonly').objectStore(store).get(key));
}
async function idbGetAll(store) {
  const idb = await openDB();
  return reqToPromise(idb.transaction(store, 'readonly').objectStore(store).getAll());
}
async function idbGetAllByIndex(store, indexName, key) {
  const idb = await openDB();
  return reqToPromise(idb.transaction(store, 'readonly').objectStore(store).index(indexName).getAll(key));
}
async function idbPut(store, value) {
  const idb = await openDB();
  return reqToPromise(idb.transaction(store, 'readwrite').objectStore(store).put(value));
}
async function idbDelete(store, key) {
  const idb = await openDB();
  return reqToPromise(idb.transaction(store, 'readwrite').objectStore(store).delete(key));
}

// ── Helpers ────────────────────────────────
function uid() { return Date.now().toString(36) + Math.random().toString(36).slice(2); }

function toast(msg) {
  const el = $('toast');
  el.textContent = msg;
  el.classList.remove('hidden');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add('hidden'), 2600);
}

function showView(id) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  $(id).classList.add('active');
}

function bookById(id) { return state.books.find(b => b.id === id); }
function chapterById(book, id) { return book.chapters.find(c => c.id === id); }

// Uses the exact loaded chapter list when available (the open book), otherwise
// the counts denormalized onto the book doc (the library view, before it's opened).
function chapterCounts(book) {
  if (Array.isArray(book.chapters)) {
    const total = book.chapters.length;
    const info = book.chapters.filter(c => c.isInfo).length;
    return { regular: total - info, info, total };
  }
  const total = book.chapterCount || 0;
  const info = book.infoCount || 0;
  return { regular: total - info, info, total };
}

function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function indentOf(line) { return line.match(/^ */)[0].length; }
function byName(a, b) { return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }); }

function readText(file) {
  if (typeof file.text === 'function') return file.text();
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = () => reject(r.error);
    r.readAsText(file);
  });
}

function friendlyError(err) {
  console.error(err);
  if (err && err.name === 'QuotaExceededError') return 'Storage is full — free up space on this device and try again.';
  if (err && /IndexedDB is not available/i.test(err.message || '')) return "This browser doesn't support local storage in this context (e.g. private browsing can block it).";
  return "Something went wrong saving that locally — please try again.";
}

// ── Images ─────────────────────────────────
// Shrinks big photos so uploads stay small. GIFs and SVGs are kept as-is
// (re-encoding would flatten animation / rasterise vectors). Whichever is
// smaller — the original or the re-encoded copy — is what gets uploaded.
async function prepareImage(file, maxDim = 1600) {
  if (!file.type || !file.type.startsWith('image/')) throw new Error('Not an image');
  if (file.type === 'image/gif' || file.type === 'image/svg+xml') return file;
  try {
    const bmp = await createImageBitmap(file);
    const scale = Math.min(1, maxDim / Math.max(bmp.width, bmp.height));
    if (scale === 1 && file.size < 800 * 1024) { bmp.close(); return file; }
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(bmp.width * scale));
    canvas.height = Math.max(1, Math.round(bmp.height * scale));
    canvas.getContext('2d').drawImage(bmp, 0, 0, canvas.width, canvas.height);
    bmp.close();
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/webp', 0.85));
    return blob && blob.size < file.size ? blob : file;
  } catch {
    return file;   // couldn't decode/resize — upload the original
  }
}

// Stores the image's bytes in IndexedDB and marks the new id as "pending" (stored but
// not yet referenced by a saved chapter/book) until the caller commits or discards it.
async function storeImage(file, maxDim) {
  const blob = await prepareImage(file, maxDim);
  const id = uid();
  pendingUploadIds.add(id);
  await idbPut('images', { id, blob, type: blob.type || file.type || 'application/octet-stream' });
  return id;
}

// id → Promise<blob: URL>. Cached so each image's bytes are only read out of
// IndexedDB once; the object URL is revoked when the image is deleted.
const urlCache = new Map();
function imageUrl(id) {
  if (!id) return Promise.resolve(null);
  if (!urlCache.has(id)) {
    urlCache.set(id, idbGet('images', id)
      .then(rec => rec ? URL.createObjectURL(rec.blob) : null)
      .catch(() => { urlCache.delete(id); return null; }));
  }
  return urlCache.get(id);
}

// Deletes an image's bytes from IndexedDB and revokes its cached object URL, if any.
async function deleteImage(id) {
  const cached = urlCache.get(id);
  if (cached) {
    cached.then(url => { if (url) URL.revokeObjectURL(url); }).catch(() => {});
    urlCache.delete(id);
  }
  try { await idbDelete('images', id); } catch (err) { console.error(err); }
}

// Fills in <img data-img-id="…"> elements that the markdown renderer produced.
async function hydrateImages(root) {
  const imgs = [...root.querySelectorAll('img[data-img-id]')];
  await Promise.all(imgs.map(async img => {
    const url = await imageUrl(img.dataset.imgId);
    if (url) img.src = url;
    else img.classList.add('img-missing');
  }));
}

function extractImageIds(text) {
  return new Set([...String(text || '').matchAll(/img:([a-z0-9]+)/gi)].map(m => m[1]));
}

// Deletes any image that was referenced before this edit (or uploaded during
// this session) but isn't referenced in the final saved text — e.g. the user
// added a picture then deleted the line, or removed one that was already saved.
async function pruneOrphanedImages(oldContent, newContent) {
  const keep = extractImageIds(newContent);
  const toCheck = new Set([...extractImageIds(oldContent || ''), ...pendingUploadIds]);
  await Promise.all([...toCheck].filter(id => !keep.has(id)).map(id => deleteImage(id)));
}

function discardPendingUploads() {
  const ids = [...pendingUploadIds];
  pendingUploadIds.clear();
  ids.forEach(id => deleteImage(id));
}

// ── Markdown Parser (no deps) ───────────────
// Block pass (headings, lists, quotes, code, tables, paragraphs) followed by an
// inline pass (emphasis, code, links, images). All text is HTML-escaped and URLs
// are checked against an allow-list, so imported files can't inject script.
const MD = {
  fence:   /^\s{0,3}(`{3,}|~{3,})([^`]*)$/,
  heading: /^\s{0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$/,
  hr:      /^\s{0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$/,
  quote:   /^\s{0,3}>/,
  item:    /^(\s*)([-*+]|\d{1,9}[.)])[ \t]+(.*)$/,
};

function parseMarkdown(md) {
  const lines = String(md || '')
    .replace(/\r\n?/g, '\n')
    .replace(/\u0000/g, '')
    .split('\n')
    .map(l => l.replace(/^\t+/, t => '    '.repeat(t.length)));
  return parseBlocks(lines);
}

function isBlockStart(line, inParagraph) {
  if (MD.fence.test(line) || MD.heading.test(line) || MD.hr.test(line) || MD.quote.test(line)) return true;
  const m = line.match(MD.item);
  if (!m) return false;
  // Inside a paragraph, only "1." may start a numbered list (so "…in\n1999. It…" stays prose)
  return !inParagraph || !/^\d/.test(m[2]) || parseInt(m[2], 10) === 1;
}

function splitRow(line) {
  let s = line.trim();
  if (s.startsWith('|')) s = s.slice(1);
  if (s.endsWith('|') && !s.endsWith('\\|')) s = s.slice(0, -1);
  return s.replace(/\\\|/g, '\u0001').split('|').map(c => c.replace(/\u0001/g, '|').trim());
}

function parseBlocks(lines) {
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    let m;

    // Fenced code block
    if ((m = line.match(MD.fence))) {
      const ch = m[1][0];
      const closer = new RegExp('^\\s{0,3}' + (ch === '`' ? '`' : '~') + '{' + m[1].length + ',}\\s*$');
      const lang = (m[2].trim().split(/\s+/)[0] || '').replace(/[^\w+-]/g, '');
      const buf = [];
      i++;
      while (i < lines.length && !closer.test(lines[i])) buf.push(lines[i++]);
      i++; // skip closing fence
      out.push(`<pre><code${lang ? ` class="lang-${lang}"` : ''}>${escHtml(buf.join('\n'))}</code></pre>`);
      continue;
    }

    // Heading
    if ((m = line.match(MD.heading))) {
      const n = m[1].length;
      out.push(`<h${n}>${inline(m[2])}</h${n}>`);
      i++;
      continue;
    }

    // Horizontal rule
    if (MD.hr.test(line)) { out.push('<hr>'); i++; continue; }

    // Blockquote (may contain any other block)
    if (MD.quote.test(line)) {
      const buf = [];
      while (i < lines.length && MD.quote.test(lines[i])) buf.push(lines[i++].replace(/^\s{0,3}>[ \t]?/, ''));
      out.push(`<blockquote>${parseBlocks(buf)}</blockquote>`);
      continue;
    }

    // Table
    if (line.includes('|') && i + 1 < lines.length && lines[i + 1].includes('|') && lines[i + 1].includes('-')) {
      const head = splitRow(line);
      const sep = splitRow(lines[i + 1]);
      if (head.length === sep.length && sep.every(c => /^:?-+:?$/.test(c))) {
        const aligns = sep.map(c => c.startsWith(':') && c.endsWith(':') ? 'center' : c.endsWith(':') ? 'right' : c.startsWith(':') ? 'left' : '');
        const cell = (tag, text, a) => `<${tag}${a ? ` style="text-align:${a}"` : ''}>${inline(text)}</${tag}>`;
        const rows = [];
        i += 2;
        while (i < lines.length && lines[i].trim() && lines[i].includes('|')) rows.push(splitRow(lines[i++]));
        out.push('<div class="table-wrap"><table><thead><tr>' +
          head.map((c, k) => cell('th', c, aligns[k])).join('') +
          '</tr></thead><tbody>' +
          rows.map(r => '<tr>' + head.map((_, k) => cell('td', r[k] || '', aligns[k])).join('') + '</tr>').join('') +
          '</tbody></table></div>');
        continue;
      }
    }

    // List (bullet or numbered, nesting by indentation)
    if ((m = line.match(MD.item))) {
      const base = m[1].length;
      const ordered = /^\d/.test(m[2]);
      const start = ordered ? parseInt(m[2], 10) : 1;
      const sameList = lm => lm && lm[1].length === base && /^\d/.test(lm[2]) === ordered;
      const items = [];
      let cur = null;
      while (i < lines.length) {
        const l = lines[i];
        const lm = l.match(MD.item);
        if (sameList(lm) && !MD.hr.test(l)) { cur = [lm[3]]; items.push(cur); i++; continue; }
        if (!l.trim()) {
          let j = i;
          while (j < lines.length && !lines[j].trim()) j++;
          const next = lines[j];
          if (next !== undefined && (indentOf(next) > base || sameList(next.match(MD.item)))) {
            for (let k = i; k < j; k++) cur.push('');
            i = j;
            continue;
          }
          break;
        }
        if (indentOf(l) > base) { cur.push(l.slice(Math.min(indentOf(l), base + 2))); i++; continue; }
        if (!isBlockStart(l, true)) { cur.push(l.trim()); i++; continue; }   // lazy continuation
        break;
      }
      const tag = ordered ? 'ol' : 'ul';
      const startAttr = ordered && start !== 1 ? ` start="${start}"` : '';
      out.push(`<${tag}${startAttr}>` +
        items.map(it => `<li>${parseBlocks(it).replace(/^<p>([\s\S]*?)<\/p>/, '$1')}</li>`).join('') +
        `</${tag}>`);
      continue;
    }

    // Paragraph
    const buf = [line.trim()];
    i++;
    while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i], true)) buf.push(lines[i++].trim());
    out.push(`<p>${inline(buf.join('\n'))}</p>`);
  }
  return out.join('\n');
}

function inline(raw) {
  const stash = [];
  const hold = html => `\u0000${stash.push(html) - 1}\u0000`;
  let s = raw
    .replace(/(`+)([\s\S]*?[^`])\1(?!`)/g, (_, __, code) => hold(`<code>${escHtml(code.trim())}</code>`))
    .replace(/\\([\\`*_{}\[\]()#+\-.!~|>])/g, (_, c) => hold(escHtml(c)));
  s = formatInline(escHtml(s), hold);
  for (let guard = 0; /\u0000\d+\u0000/.test(s) && guard < 10; guard++) {
    s = s.replace(/\u0000(\d+)\u0000/g, (_, n) => stash[+n]);
  }
  return s.replace(/\n/g, '<br>\n');
}

function formatInline(s, hold) {
  const URL_RE = '((?:[^()\\s]|\\([^()\\s]*\\))+)';
  const TITLE_RE = '(?:\\s+&quot;[\\s\\S]*?&quot;)?';
  s = s.replace(new RegExp('!\\[([^\\]]*)\\]\\(\\s*' + URL_RE + TITLE_RE + '\\s*\\)', 'g'),
    (_, alt, url) => hold(imageHtml(alt, url)));
  s = s.replace(new RegExp('\\[((?:[^\\[\\]]|\\[[^\\[\\]]*\\])+)\\]\\(\\s*' + URL_RE + TITLE_RE + '\\s*\\)', 'g'),
    (_, label, url) => hold(linkHtml(formatInline(label, hold), url)));
  s = s.replace(/&lt;((?:https?:\/\/|mailto:)\S*?)&gt;/g, (_, url) => hold(linkHtml(url, url)));
  return s
    .replace(/\*\*\*(?=\S)([\s\S]*?\S)\*\*\*/g, '<strong><em>$1</em></strong>')
    .replace(/\*\*(?=\S)([\s\S]*?\S)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(?=\S)([\s\S]*?\S)\*/g, '<em>$1</em>')
    .replace(/(^|[^\w])__(?=\S)([\s\S]*?\S)__(?!\w)/g, '$1<strong>$2</strong>')
    .replace(/(^|[^\w])_(?=\S)([\s\S]*?\S)_(?!\w)/g, '$1<em>$2</em>')
    .replace(/~~(?=\S)([\s\S]*?\S)~~/g, '<del>$1</del>');
}

// Returns the URL if it's safe for this use, otherwise null.
function safeUrl(url, kind) {
  if (url.includes('\u0000')) return null;
  const clean = url.replace(/[\u0000-\u0020\u007f]/g, '');
  const m = clean.match(/^([a-z][a-z0-9+.\-]*):/i);
  if (!m) return url;                                   // relative path or #anchor
  const scheme = m[1].toLowerCase();
  if (kind === 'link') return ['http', 'https', 'mailto', 'tel'].includes(scheme) ? url : null;
  if (scheme === 'http' || scheme === 'https') return url;
  if (scheme === 'img') return /^img:[a-z0-9]+$/i.test(clean) ? clean : null;
  if (scheme === 'data') return /^data:image\/(png|jpe?g|gif|webp);base64,[a-z0-9+\/=]+$/i.test(clean) ? clean : null;
  return null;
}

function imageHtml(alt, url) {
  const u = safeUrl(url, 'image');
  if (u === null) return alt;
  const stored = u.match(/^img:([a-z0-9]+)$/i);
  if (stored) return `<img data-img-id="${stored[1]}" alt="${alt}">`;
  return `<img src="${u}" alt="${alt}" loading="lazy">`;
}

function linkHtml(labelHtml, url) {
  const u = safeUrl(url, 'link');
  if (u === null) return labelHtml;
  return `<a href="${u}" target="_blank" rel="noopener noreferrer">${labelHtml}</a>`;
}

// ── Markdown import helpers ─────────────────
// Splits a .md file into a chapter title and body. Title comes from YAML front
// matter ("title:"), else a leading "# Heading", else the file name.
function splitMarkdownDoc(text, filename) {
  let body = text.replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n');
  let title = '';
  const fm = body.match(/^---\n([\s\S]*?)\n---[ \t]*(?:\n|$)/);
  if (fm) {
    const t = fm[1].match(/^title:[ \t]*(.+)$/mi);
    if (t) title = t[1].trim().replace(/^(['"])(.*)\1$/, '$2');
    body = body.slice(fm[0].length);
  }
  const h1 = body.match(/^\s*#[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*(?:\n|$)/);
  if (h1) {
    const headingText = h1[1].trim().replace(/[*`]/g, '');
    if (!title || headingText.toLowerCase() === title.toLowerCase()) {
      if (!title) title = headingText;
      body = body.slice(h1[0].length);      // the title is shown separately, so drop the duplicate heading
    }
  }
  if (!title) title = filename.replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' ').trim() || 'Untitled Chapter';
  return { title, body: body.replace(/^\n+/, '') };
}

// Rewrites ![alt](some/path/pic.png) to point at a bundled image with the same
// file name. Returns the new text and how many local images couldn't be matched.
function rewriteImageRefs(text, imageMap) {
  let missing = 0;
  const out = text.replace(/(!\[[^\]]*\]\(\s*)((?:[^()\s]|\([^()\s]*\))+)/g, (all, pre, url) => {
    if (/^(https?:|data:|img:)/i.test(url)) return all;
    let name = url.split(/[?#]/)[0].split('/').pop();
    try { name = decodeURIComponent(name); } catch { /* keep raw */ }
    const id = imageMap.get(name.toLowerCase());
    if (id) return `${pre}img:${id}`;
    missing++;
    return all;
  });
  return { text: out, missing };
}

async function importMarkdownFiles(fileList) {
  const book = bookById(state.currentBookId);
  if (!book) return;
  const files = [...fileList];
  const mdFiles = files
    .filter(f => /\.(md|markdown|mdown|txt)$/i.test(f.name) || f.type === 'text/markdown')
    .sort(byName);
  const imgFiles = files.filter(f => f.type && f.type.startsWith('image/'));
  if (mdFiles.length === 0) { toast('Pick at least one .md file.'); return; }

  const imageMap = new Map();
  for (const f of imgFiles) {
    try { imageMap.set(f.name.toLowerCase(), await storeImage(f)); }
    catch (err) { console.error(err); }
  }

  const added = [];
  let unmatched = 0;
  const base = Date.now();
  let n = 0;
  for (const f of mdFiles) {
    try {
      const { title, body } = splitMarkdownDoc(await readText(f), f.name);
      const rewritten = rewriteImageRefs(body, imageMap);
      unmatched += rewritten.missing;
      const order = base + n++;
      const id = uid();
      const data = { id, bookId: book.id, title, content: rewritten.text, isInfo: false, order };
      await idbPut('chapters', data);
      added.push(data);
    } catch (err) {
      toast(`Couldn't import ${f.name} — ${friendlyError(err)}`);
    }
  }
  if (added.length === 0) return;

  book.chapters.push(...added);
  pendingUploadIds.clear();   // everything above is now committed to saved chapters
  await syncChapterCounts(book);
  updateChapterBadge(book);
  renderChapterSidebar(book);
  viewChapter(book, added[0].id);
  toast(`Imported ${added.length} chapter${added.length !== 1 ? 's' : ''}` +
    (unmatched ? ` — ${unmatched} local image${unmatched !== 1 ? 's' : ''} not found. Select images together with the .md files to include them.` : '.'));
}

// Writes the book's chapter/info counts, kept in sync so the library view
// (which doesn't load full chapter lists) can still show accurate counts.
async function syncChapterCounts(book) {
  const counts = chapterCounts(book);
  try {
    const existing = await idbGet('books', book.id);
    if (existing) await idbPut('books', { ...existing, chapterCount: counts.total, infoCount: counts.info });
    book.chapterCount = counts.total;
    book.infoCount = counts.info;
  } catch (err) { console.error('Could not update chapter counts', err); }
}

// ── Data loading ───────────────────────────
async function loadBooks() {
  const all = await idbGetAll('books');
  all.sort((a, b) => (a.order || 0) - (b.order || 0));
  state.books = all.map(data => ({
    id: data.id,
    title: data.title || 'Untitled Book',
    description: data.description || '',
    coverId: data.coverId || null,
    order: data.order || 0,
    chapterCount: data.chapterCount || 0,
    infoCount: data.infoCount || 0,
    chapters: undefined,   // loaded lazily when the book is opened
  }));
}

async function loadChapters(book) {
  const all = await idbGetAllByIndex('chapters', 'bookId', book.id);
  all.sort((a, b) => (a.order || 0) - (b.order || 0));
  book.chapters = all;
}

// ── Library View ───────────────────────────
function renderLibrary() {
  const grid = $('library-grid');
  const empty = $('empty-state');
  grid.querySelectorAll('.book-card').forEach(el => el.remove());

  if (state.books.length === 0) {
    empty.style.display = '';
    return;
  }
  empty.style.display = 'none';

  state.books.forEach(book => {
    const counts = chapterCounts(book);
    const title = escHtml(book.title);
    const card = document.createElement('div');
    card.className = 'book-card';
    card.dataset.id = book.id;

    card.innerHTML = `
      <div class="book-cover-wrap">
        <div class="book-cover-open" role="button" tabindex="0" aria-label="Open ${title}">
          ${book.coverId
            ? `<img class="book-cover-img" data-img-id="${escHtml(book.coverId)}" alt="" />`
            : `<div class="book-cover-placeholder">📖</div>`}
        </div>
        <div class="book-card-menu">
          <button class="btn-edit-meta" title="Edit details" aria-label="Edit ${title}">✎</button>
          <button class="btn-del" title="Delete book" aria-label="Delete ${title}">✕</button>
        </div>
      </div>
      <div class="book-card-info">
        <div class="book-card-title">${title}</div>
        <div class="book-card-meta">${counts.regular} chapter${counts.regular !== 1 ? 's' : ''}${counts.info > 0 ? ` · Informational: ${counts.info}` : ''}</div>
        ${book.description ? `<div class="book-card-desc">${escHtml(book.description)}</div>` : ''}
      </div>
    `;

    const opener = card.querySelector('.book-cover-open');
    opener.addEventListener('click', () => openBook(book.id));
    opener.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openBook(book.id); }
    });
    card.querySelector('.book-card-title').addEventListener('click', () => openBook(book.id));
    card.querySelector('.btn-edit-meta').addEventListener('click', e => {
      e.stopPropagation();
      openBookModal(book.id);
    });
    card.querySelector('.btn-del').addEventListener('click', e => {
      e.stopPropagation();
      confirmDelete(`Delete "${book.title}"? All chapters will be lost.`, async () => {
        try {
          await deleteBookCompletely(book);
        } catch (err) {
          toast(friendlyError(err));
          return;
        }
        state.books = state.books.filter(b => b.id !== book.id);
        renderLibrary();
        toast('Book deleted.');
      });
    });

    grid.appendChild(card);
    hydrateImages(card);
  });
}

// Deletes the book record, every chapter under it, and every image (cover +
// any referenced in a chapter). IndexedDB has no cascade delete, so chapters
// are fetched and removed explicitly.
async function deleteBookCompletely(book) {
  const chapters = Array.isArray(book.chapters) ? book.chapters : await idbGetAllByIndex('chapters', 'bookId', book.id);
  const imageIds = new Set();
  if (book.coverId) imageIds.add(book.coverId);
  for (const ch of chapters) {
    await idbDelete('chapters', ch.id);
    for (const id of extractImageIds(ch.content)) imageIds.add(id);
  }
  await idbDelete('books', book.id);
  await Promise.all([...imageIds].map(id => deleteImage(id)));
}

// ── Book View ──────────────────────────────
function showWelcome(book) {
  $('chapter-area').innerHTML = `
    <div class="chapter-welcome" id="chapter-welcome">
      <div>
        ${book.description ? `<p class="book-description">${escHtml(book.description)}</p>` : ''}
        <p>Select a chapter to read,<br>or create a new one.</p>
      </div>
    </div>`;
}

async function openBook(id) {
  state.currentBookId = id;
  state.currentChapterId = null;
  const book = bookById(id);
  $('book-title-display').textContent = book.title;
  showView('view-book');
  if (!Array.isArray(book.chapters)) {
    $('chapter-list').innerHTML = '<li class="sidebar-loading">Loading…</li>';
    try { await loadChapters(book); }
    catch (err) { toast(friendlyError(err)); book.chapters = []; }
  }
  updateChapterBadge(book);
  renderChapterSidebar(book);
  showWelcome(book);
}

function updateChapterBadge(book) {
  const counts = chapterCounts(book);
  $('book-chapter-count').textContent = `${counts.regular} chapter${counts.regular !== 1 ? 's' : ''}`;
  const infoBadge = $('book-info-count');
  if (counts.info > 0) {
    infoBadge.textContent = `Informational: ${counts.info}`;
    infoBadge.style.display = '';
  } else {
    infoBadge.style.display = 'none';
  }
}

function renderChapterSidebar(book) {
  const list = $('chapter-list');
  list.innerHTML = '';
  book.chapters.forEach((ch, idx) => {
    const li = document.createElement('li');
    li.innerHTML = `
      <button class="chapter-list-btn" data-id="${escHtml(ch.id)}">${idx + 1}. ${escHtml(ch.title)}${ch.isInfo ? '<span class="info-tag">INFO</span>' : ''}</button>
      <div class="chapter-item-actions">
        <button class="btn-ch-edit" title="Edit chapter" aria-label="Edit chapter ${escHtml(ch.title)}">✎</button>
        <button class="btn-del" title="Delete chapter" aria-label="Delete chapter ${escHtml(ch.title)}">✕</button>
      </div>
    `;
    li.querySelector('.chapter-list-btn').addEventListener('click', () => viewChapter(book, ch.id));
    li.querySelector('.btn-ch-edit').addEventListener('click', () => openEditor(book.id, ch.id));
    li.querySelector('.btn-del').addEventListener('click', () => {
      confirmDelete(`Delete chapter "${ch.title}"?`, async () => {
        try {
          await idbDelete('chapters', ch.id);
          await Promise.all([...extractImageIds(ch.content)].map(id => deleteImage(id)));
        } catch (err) {
          toast(friendlyError(err));
          return;
        }
        book.chapters = book.chapters.filter(c => c.id !== ch.id);
        await syncChapterCounts(book);
        updateChapterBadge(book);
        renderChapterSidebar(book);
        if (state.currentChapterId === ch.id) {
          state.currentChapterId = null;
          showWelcome(book);
        }
        toast('Chapter deleted.');
      });
    });
    list.appendChild(li);
  });
  if (state.currentChapterId) {
    list.querySelectorAll('.chapter-list-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.id === state.currentChapterId);
    });
  }
}

function viewChapter(book, chId) {
  state.currentChapterId = chId;
  const ch = chapterById(book, chId);
  document.querySelectorAll('.chapter-list-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.id === chId);
  });
  const area = $('chapter-area');
  area.innerHTML = `
    <div class="chapter-reader">
      <h2 class="chapter-reader-title">${escHtml(ch.title)}${ch.isInfo ? '<span class="info-tag" style="margin-left:10px;vertical-align:4px;">INFO</span>' : ''}</h2>
      <div class="md-content">${parseMarkdown(ch.content || '')}</div>
    </div>`;
  area.scrollTop = 0;
  hydrateImages(area);
}

// ── Editor ─────────────────────────────────
function setEditorMode(mode) {
  const ta = $('editor-textarea');
  const pv = $('editor-preview');
  if (mode === 'preview') {
    pv.innerHTML = `<div class="md-content">${parseMarkdown(ta.value)}</div>`;
    hydrateImages(pv);
    pv.classList.remove('hidden');
    ta.classList.add('hidden');
    $('btn-toggle-preview').textContent = 'Edit';
  } else {
    pv.classList.add('hidden');
    ta.classList.remove('hidden');
    $('btn-toggle-preview').textContent = 'Preview';
  }
  state.editorMode = mode;
}

function openEditor(bookId, chapterId) {
  state.currentBookId = bookId;
  state.currentChapterId = chapterId;
  const book = bookById(bookId);
  const ch = chapterId ? chapterById(book, chapterId) : null;

  $('editor-chapter-title').value = ch ? ch.title : '';
  $('editor-textarea').value = ch ? ch.content : '';
  $('editor-is-info').checked = ch ? !!ch.isInfo : false;
  $('editor-preview').innerHTML = '';
  setEditorMode('write');
  editorDirty = false;
  pendingUploadIds.clear();

  showView('view-editor');
}

function leaveEditor() {
  editorDirty = false;
  discardPendingUploads();
  openBook(state.currentBookId);
}

['editor-chapter-title', 'editor-textarea', 'editor-is-info'].forEach(id => {
  $(id).addEventListener('input', () => { editorDirty = true; });
  $(id).addEventListener('change', () => { editorDirty = true; });
});

window.addEventListener('beforeunload', e => {
  if (editorDirty && $('view-editor').classList.contains('active')) {
    e.preventDefault();
    e.returnValue = '';
  }
});

$('btn-toggle-preview').addEventListener('click', () => {
  setEditorMode(state.editorMode === 'write' ? 'preview' : 'write');
});

$('btn-save-chapter').addEventListener('click', async () => {
  const title = $('editor-chapter-title').value.trim() || 'Untitled Chapter';
  const content = $('editor-textarea').value;
  const isInfo = $('editor-is-info').checked;
  const book = bookById(state.currentBookId);
  const btn = $('btn-save-chapter');
  btn.disabled = true;

  const previousContent = state.currentChapterId ? chapterById(book, state.currentChapterId).content : '';
  try {
    if (state.currentChapterId) {
      const ch = chapterById(book, state.currentChapterId);
      const order = ch.order ?? Date.now();
      await idbPut('chapters', { id: ch.id, bookId: book.id, title, content, isInfo, order });
      ch.title = title; ch.content = content; ch.isInfo = isInfo;
    } else {
      const id = uid();
      const order = Date.now();
      const newCh = { id, bookId: book.id, title, content, isInfo, order };
      await idbPut('chapters', newCh);
      book.chapters.push(newCh);
      state.currentChapterId = newCh.id;
    }
    await pruneOrphanedImages(previousContent, content);
    await syncChapterCounts(book);
  } catch (err) {
    toast(friendlyError(err));
    btn.disabled = false;
    return;   // stay in the editor so nothing is lost
  }
  btn.disabled = false;
  const savedChapterId = state.currentChapterId;   // openBook() below resets state.currentChapterId
  editorDirty = false;
  pendingUploadIds.clear();
  toast('Chapter saved.');
  openBook(state.currentBookId);
  viewChapter(book, savedChapterId);
});

$('btn-back-book').addEventListener('click', () => {
  if (!editorDirty) { leaveEditor(); return; }
  confirmAction({
    title: 'Discard changes?',
    message: 'This chapter has unsaved changes.',
    okLabel: 'Discard',
  }, leaveEditor);
});

// Chapter pictures: button, paste and drag-and-drop all end up here.
function insertAtCursor(ta, text) {
  ta.focus();
  ta.setRangeText(text, ta.selectionStart, ta.selectionEnd, 'end');
  ta.dispatchEvent(new Event('input', { bubbles: true }));
}

async function addImagesToEditor(fileList) {
  const images = [...fileList].filter(f => f.type && f.type.startsWith('image/'));
  if (images.length === 0) return;
  if (state.editorMode === 'preview') setEditorMode('write');
  const ta = $('editor-textarea');
  let added = 0;
  for (const f of images) {
    try {
      const id = await storeImage(f);
      const alt = f.name.replace(/\.[^.]+$/, '').replace(/[\[\]()]/g, '').trim() || 'image';
      insertAtCursor(ta, `\n\n![${alt}](img:${id})\n\n`);
      added++;
    } catch (err) {
      toast(`Couldn't add ${f.name} — ${friendlyError(err)}`);
    }
  }
  if (added) toast(`Added ${added} picture${added !== 1 ? 's' : ''}.`);
}

$('btn-add-image').addEventListener('click', () => $('input-chapter-image').click());
$('input-chapter-image').addEventListener('change', e => {
  const files = [...e.target.files];
  e.target.value = '';
  addImagesToEditor(files);
});
$('editor-textarea').addEventListener('paste', e => {
  const files = [...(e.clipboardData ? e.clipboardData.files : [])].filter(f => f.type.startsWith('image/'));
  if (files.length) { e.preventDefault(); addImagesToEditor(files); }
});
$('editor-textarea').addEventListener('dragover', e => {
  if (e.dataTransfer && [...e.dataTransfer.types].includes('Files')) e.preventDefault();
});
$('editor-textarea').addEventListener('drop', e => {
  const files = [...(e.dataTransfer ? e.dataTransfer.files : [])].filter(f => f.type.startsWith('image/'));
  if (files.length) { e.preventDefault(); addImagesToEditor(files); }
});

// ── Import .md ─────────────────────────────
$('btn-import-md').addEventListener('click', () => $('input-import-md').click());
$('input-import-md').addEventListener('change', e => {
  const files = [...e.target.files];
  e.target.value = '';
  importMarkdownFiles(files);
});

// ── Book Modal ─────────────────────────────
// pendingCoverId: undefined = unchanged, null = removed, string = newly uploaded id (not yet saved)
let pendingCoverId;
let previousCoverId = null;   // the book's cover before this modal session, for cleanup if replaced

async function showCoverPreview(imageId) {
  const preview = $('cover-preview');
  const placeholder = $('cover-placeholder');
  const url = imageId ? await imageUrl(imageId) : null;
  if (url) {
    preview.src = url;
    preview.classList.remove('hidden');
    placeholder.style.display = 'none';
  } else {
    preview.removeAttribute('src');
    preview.classList.add('hidden');
    placeholder.style.display = '';
  }
  $('btn-remove-cover').classList.toggle('hidden', !url);
}

function openBookModal(bookId) {
  state.editingBookId = bookId || null;
  pendingCoverId = undefined;
  pendingUploadIds.clear();
  const book = bookId ? bookById(bookId) : null;
  previousCoverId = book ? (book.coverId || null) : null;

  $('modal-book-title').textContent = book ? 'Edit Book' : 'New Book';
  $('input-book-title').value = book ? book.title : '';
  $('input-book-description').value = book ? (book.description || '') : '';
  showCoverPreview(book ? book.coverId : null);

  $('modal-book').classList.remove('hidden');
  $('input-book-title').focus();
}

$('btn-new-book').addEventListener('click', () => openBookModal(null));
$('btn-edit-book-meta').addEventListener('click', () => openBookModal(state.currentBookId));

$('btn-modal-cancel').addEventListener('click', closeBookModal);
$('btn-modal-save').addEventListener('click', saveBook);

$('modal-book').addEventListener('click', e => {
  if (e.target === e.currentTarget) closeBookModal();
});

function hideBookModal() { $('modal-book').classList.add('hidden'); }

// Cancel / dismiss: discard anything uploaded during this modal session that was never saved.
function closeBookModal() {
  hideBookModal();
  discardPendingUploads();
  pendingCoverId = undefined;
}

async function saveBook() {
  const title = $('input-book-title').value.trim();
  if (!title) { toast('Please enter a title.'); return; }
  const description = $('input-book-description').value.trim();
  const btn = $('btn-modal-save');
  btn.disabled = true;
  let book;

  try {
    if (state.editingBookId) {
      book = bookById(state.editingBookId);
      const finalCoverId = pendingCoverId !== undefined ? pendingCoverId : book.coverId;
      const existing = await idbGet('books', book.id);
      await idbPut('books', { ...existing, title, description, coverId: finalCoverId ?? null });
      if (pendingCoverId !== undefined && previousCoverId && previousCoverId !== pendingCoverId) {
        deleteImage(previousCoverId);   // old cover replaced/removed
      }
      book.title = title;
      book.description = description;
      book.coverId = finalCoverId ?? null;
    } else {
      const id = uid();
      const data = { id, title, description, coverId: pendingCoverId || null, order: Date.now(), chapterCount: 0, infoCount: 0 };
      await idbPut('books', data);
      book = { ...data, chapters: [] };
      state.books.push(book);
    }
  } catch (err) {
    toast(friendlyError(err));
    btn.disabled = false;
    return;
  }
  btn.disabled = false;
  pendingUploadIds.delete(pendingCoverId);   // now committed, no longer "unsaved"
  pendingCoverId = undefined;
  toast(state.editingBookId ? 'Book updated.' : 'Book created.');

  if ($('view-book').classList.contains('active') && state.currentBookId === book.id) {
    $('book-title-display').textContent = title;
    if (!state.currentChapterId) showWelcome(book);
  }
  hideBookModal();
  renderLibrary();
}

$('cover-upload-area').addEventListener('click', () => $('input-cover').click());
$('cover-upload-area').addEventListener('keydown', e => {
  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $('input-cover').click(); }
});
$('input-cover').addEventListener('change', async e => {
  const file = e.target.files[0];
  e.target.value = '';
  if (!file) return;
  try {
    if (pendingCoverId) {   // replacing an upload from earlier in this same modal session
      pendingUploadIds.delete(pendingCoverId);
      deleteImage(pendingCoverId);
    }
    const id = await storeImage(file, 1200);
    pendingCoverId = id;
    showCoverPreview(id);
  } catch (err) {
    toast(`Couldn't use that file — ${friendlyError(err)}`);
  }
});
$('btn-remove-cover').addEventListener('click', () => {
  if (pendingCoverId) {
    pendingUploadIds.delete(pendingCoverId);
    deleteImage(pendingCoverId);
  }
  pendingCoverId = null;
  showCoverPreview(null);
});

// ── Confirm Modal ──────────────────────────
function confirmAction({ title = 'Delete?', message = 'This action cannot be undone.', okLabel = 'Delete' }, fn) {
  state.pendingDeleteFn = fn;
  $('confirm-title').textContent = title;
  $('confirm-message').textContent = message;
  $('btn-confirm-ok').textContent = okLabel;
  $('modal-confirm').classList.remove('hidden');
  $('btn-confirm-cancel').focus();
}
function confirmDelete(msg, fn) { confirmAction({ message: msg }, fn); }

function closeConfirm() {
  $('modal-confirm').classList.add('hidden');
  state.pendingDeleteFn = null;
}
$('btn-confirm-cancel').addEventListener('click', closeConfirm);
$('btn-confirm-ok').addEventListener('click', () => {
  const fn = state.pendingDeleteFn;
  closeConfirm();
  if (fn) fn();
});
$('modal-confirm').addEventListener('click', e => {
  if (e.target === e.currentTarget) closeConfirm();
});

// ── Navigation ─────────────────────────────
$('btn-back-library').addEventListener('click', () => {
  state.currentBookId = null;
  renderLibrary();
  showView('view-library');
});
$('btn-new-chapter').addEventListener('click', () => {
  openEditor(state.currentBookId, null);
});

// ── Keyboard shortcuts ─────────────────────
document.addEventListener('keydown', e => {
  // Ctrl/Cmd+S saves the chapter
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    if ($('view-editor').classList.contains('active')) {
      e.preventDefault();
      $('btn-save-chapter').click();
    }
  }
  // Esc closes whichever dialog is open
  if (e.key === 'Escape') {
    if (!$('modal-confirm').classList.contains('hidden')) closeConfirm();
    else if (!$('modal-book').classList.contains('hidden')) closeBookModal();
  }
  // Enter in the book title field saves the book
  if (e.key === 'Enter' && e.target.id === 'input-book-title') {
    e.preventDefault();
    saveBook();
  }
});

// ── Startup ────────────────────────────────
// Everything lives in this browser's IndexedDB, so there's no sign-in step —
// just load whatever's already stored and show the library.
(async function start() {
  showView('view-library');
  $('library-grid').style.visibility = 'hidden';
  try { await loadBooks(); }
  catch (err) { toast(friendlyError(err)); }
  renderLibrary();
  $('library-grid').style.visibility = '';
})();

})();