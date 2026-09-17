/* ─────────────────────────────────────────────
   MY LIBRARY — app.js
   Storage: localStorage  |  No dependencies
───────────────────────────────────────────── */

// ── State ──────────────────────────────────
let state = {
  books: [],
  currentBookId: null,
  currentChapterId: null,
  editorMode: 'write',
  editingBookId: null,
  pendingDeleteFn: null,
};

// ── Persist ────────────────────────────────
function save() { localStorage.setItem('mylibrary', JSON.stringify(state.books)); }
function load() {
  try { state.books = JSON.parse(localStorage.getItem('mylibrary')) || []; }
  catch { state.books = []; }
}

// ── Helpers ────────────────────────────────
function uid() { return Date.now().toString(36) + Math.random().toString(36).slice(2); }

function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.remove('hidden');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add('hidden'), 2200);
}

function showView(id) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.getElementById(id).classList.add('active');
}

function bookById(id) { return state.books.find(b => b.id === id); }
function chapterById(book, id) { return book.chapters.find(c => c.id === id); }

function chapterCounts(book) {
  const total = book.chapters.length;
  const info = book.chapters.filter(c => c.isInfo).length;
  return { regular: total - info, info, total };
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Markdown Parser (no deps) ───────────────
function parseMarkdown(md) {
  let html = md
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/```([\s\S]*?)```/g, (_, c) => `<pre><code>${c.trim()}</code></pre>`)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/^#{6}\s(.+)/gm, '<h6>$1</h6>')
    .replace(/^#{5}\s(.+)/gm, '<h5>$1</h5>')
    .replace(/^#{4}\s(.+)/gm, '<h4>$1</h4>')
    .replace(/^#{3}\s(.+)/gm, '<h3>$1</h3>')
    .replace(/^#{2}\s(.+)/gm, '<h2>$1</h2>')
    .replace(/^#{1}\s(.+)/gm, '<h1>$1</h1>')
    .replace(/^---$/gm, '<hr>')
    .replace(/^&gt;\s(.+)/gm, '<blockquote>$1</blockquote>')
    .replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/_(.+?)_/g, '<em>$1</em>')
    .replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/!\[(.+?)\]\((.+?)\)/g, '<img src="$2" alt="$1" />')
    .replace(/^\d+\.\s(.+)/gm, '<li>$1</li>')
    .replace(/^[-*]\s(.+)/gm, '<li>$1</li>')
    .replace(/(<li>[\s\S]+?<\/li>)(?!\s*<li>)/g, (m) => `<ul>${m}</ul>`)
    .split(/\n{2,}/).map(block => {
      block = block.trim();
      if (!block) return '';
      if (/^<(h[1-6]|ul|ol|li|pre|blockquote|hr|tr)/.test(block)) return block;
      return `<p>${block.replace(/\n/g, '<br>')}</p>`;
    }).join('\n');
  return html;
}

// ── Library View ───────────────────────────
function renderLibrary() {
  const grid = document.getElementById('library-grid');
  const empty = document.getElementById('empty-state');
  grid.querySelectorAll('.book-card').forEach(el => el.remove());

  if (state.books.length === 0) {
    empty.style.display = '';
    return;
  }
  empty.style.display = 'none';

  state.books.forEach(book => {
    const counts = chapterCounts(book);
    const card = document.createElement('div');
    card.className = 'book-card';
    card.dataset.id = book.id;

    card.innerHTML = `
      <div class="book-cover-wrap">
        ${book.cover
          ? `<img class="book-cover-img" src="${book.cover}" alt="${escHtml(book.title)}" />`
          : `<div class="book-cover-placeholder">📖</div>`}
        <div class="book-card-menu">
          <button class="btn-edit-meta" title="Edit">✎</button>
          <button class="btn-del" title="Delete">✕</button>
        </div>
      </div>
      <div class="book-card-info">
        <div class="book-card-title">${escHtml(book.title)}</div>
        <div class="book-card-meta">${counts.regular} chapter${counts.regular !== 1 ? 's' : ''}${counts.info > 0 ? ` · Informational: ${counts.info}` : ''}</div>
      </div>
    `;

    card.querySelector('.book-cover-wrap').addEventListener('click', e => {
      if (e.target.closest('.book-card-menu')) return;
      openBook(book.id);
    });
    card.querySelector('.book-card-title').addEventListener('click', () => openBook(book.id));
    card.querySelector('.btn-edit-meta').addEventListener('click', e => {
      e.stopPropagation();
      openBookModal(book.id);
    });
    card.querySelector('.btn-del').addEventListener('click', e => {
      e.stopPropagation();
      confirmDelete(`Delete "${book.title}"? All chapters will be lost.`, () => {
        state.books = state.books.filter(b => b.id !== book.id);
        save();
        renderLibrary();
        toast('Book deleted.');
      });
    });

    grid.appendChild(card);
  });
}

// ── Book View ──────────────────────────────
function openBook(id) {
  state.currentBookId = id;
  state.currentChapterId = null;
  const book = bookById(id);
  document.getElementById('book-title-display').textContent = book.title;
  updateChapterBadge(book);
  renderChapterSidebar(book);
  document.getElementById('chapter-area').innerHTML = `
    <div class="chapter-welcome" id="chapter-welcome">
      <p>Select a chapter to read,<br>or create a new one.</p>
    </div>`;
  showView('view-book');
}

function updateChapterBadge(book) {
  const counts = chapterCounts(book);
  document.getElementById('book-chapter-count').textContent = `${counts.regular} chapter${counts.regular !== 1 ? 's' : ''}`;
  const infoBadge = document.getElementById('book-info-count');
  if (counts.info > 0) {
    infoBadge.textContent = `Informational: ${counts.info}`;
    infoBadge.style.display = '';
  } else {
    infoBadge.style.display = 'none';
  }
}

function renderChapterSidebar(book) {
  const list = document.getElementById('chapter-list');
  list.innerHTML = '';
  book.chapters.forEach((ch, idx) => {
    const li = document.createElement('li');
    li.innerHTML = `
      <button class="chapter-list-btn" data-id="${ch.id}">${idx + 1}. ${escHtml(ch.title)}${ch.isInfo ? '<span class="info-tag">INFO</span>' : ''}</button>
      <div class="chapter-item-actions">
        <button class="btn-ch-edit" title="Edit">✎</button>
        <button class="btn-del" title="Delete">✕</button>
      </div>
    `;
    li.querySelector('.chapter-list-btn').addEventListener('click', () => viewChapter(book, ch.id));
    li.querySelector('.btn-ch-edit').addEventListener('click', () => openEditor(book.id, ch.id));
    li.querySelector('.btn-del').addEventListener('click', () => {
      confirmDelete(`Delete chapter "${ch.title}"?`, () => {
        book.chapters = book.chapters.filter(c => c.id !== ch.id);
        save();
        updateChapterBadge(book);
        renderChapterSidebar(book);
        if (state.currentChapterId === ch.id) {
          state.currentChapterId = null;
          document.getElementById('chapter-area').innerHTML = `
            <div class="chapter-welcome"><p>Select a chapter to read,<br>or create a new one.</p></div>`;
        }
        toast('Chapter deleted.');
      });
    });
    list.appendChild(li);
  });
}

function viewChapter(book, chId) {
  state.currentChapterId = chId;
  const ch = chapterById(book, chId);
  document.querySelectorAll('.chapter-list-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.id === chId);
  });
  const area = document.getElementById('chapter-area');
  area.innerHTML = `
    <div class="chapter-reader">
      <h2 class="chapter-reader-title">${escHtml(ch.title)}${ch.isInfo ? '<span class="info-tag" style="margin-left:10px;vertical-align:4px;">INFO</span>' : ''}</h2>
      <div class="md-content">${parseMarkdown(ch.content || '')}</div>
    </div>`;
}

// ── Editor ─────────────────────────────────
function openEditor(bookId, chapterId) {
  state.currentBookId = bookId;
  state.currentChapterId = chapterId;
  const book = bookById(bookId);
  const ch = chapterId ? chapterById(book, chapterId) : null;

  document.getElementById('editor-chapter-title').value = ch ? ch.title : '';
  document.getElementById('editor-textarea').value = ch ? ch.content : '';
  document.getElementById('editor-is-info').checked = ch ? !!ch.isInfo : false;
  document.getElementById('editor-preview').innerHTML = '';
  document.getElementById('editor-preview').classList.add('hidden');
  document.getElementById('editor-textarea').classList.remove('hidden');
  document.getElementById('btn-toggle-preview').textContent = 'Preview';
  state.editorMode = 'write';

  showView('view-editor');
}

document.getElementById('btn-toggle-preview').addEventListener('click', () => {
  const ta = document.getElementById('editor-textarea');
  const pv = document.getElementById('editor-preview');
  if (state.editorMode === 'write') {
    pv.innerHTML = `<div class="md-content">${parseMarkdown(ta.value)}</div>`;
    pv.classList.remove('hidden');
    ta.classList.add('hidden');
    document.getElementById('btn-toggle-preview').textContent = 'Edit';
    state.editorMode = 'preview';
  } else {
    pv.classList.add('hidden');
    ta.classList.remove('hidden');
    document.getElementById('btn-toggle-preview').textContent = 'Preview';
    state.editorMode = 'write';
  }
});

document.getElementById('btn-save-chapter').addEventListener('click', () => {
  const title = document.getElementById('editor-chapter-title').value.trim() || 'Untitled Chapter';
  const content = document.getElementById('editor-textarea').value;
  const isInfo = document.getElementById('editor-is-info').checked;
  const book = bookById(state.currentBookId);

  if (state.currentChapterId) {
    const ch = chapterById(book, state.currentChapterId);
    ch.title = title;
    ch.content = content;
    ch.isInfo = isInfo;
  } else {
    const newCh = { id: uid(), title, content, isInfo };
    book.chapters.push(newCh);
    state.currentChapterId = newCh.id;
  }
  save();
  toast('Chapter saved.');
  openBook(state.currentBookId);
  viewChapter(book, state.currentChapterId);
});

document.getElementById('btn-back-book').addEventListener('click', () => {
  openBook(state.currentBookId);
});

// ── Book Modal ─────────────────────────────
let pendingCover = null;

function openBookModal(bookId) {
  state.editingBookId = bookId || null;
  pendingCover = null;
  const book = bookId ? bookById(bookId) : null;

  document.getElementById('modal-book-title').textContent = book ? 'Edit Book' : 'New Book';
  document.getElementById('input-book-title').value = book ? book.title : '';

  const preview = document.getElementById('cover-preview');
  const placeholder = document.getElementById('cover-placeholder');
  if (book && book.cover) {
    preview.src = book.cover;
    preview.classList.remove('hidden');
    placeholder.style.display = 'none';
  } else {
    preview.classList.add('hidden');
    placeholder.style.display = '';
  }

  document.getElementById('modal-book').classList.remove('hidden');
  document.getElementById('input-book-title').focus();
}

document.getElementById('btn-new-book').addEventListener('click', () => openBookModal(null));
document.getElementById('btn-edit-book-meta').addEventListener('click', () => openBookModal(state.currentBookId));

document.getElementById('btn-modal-cancel').addEventListener('click', closeBookModal);
document.getElementById('btn-modal-save').addEventListener('click', saveBook);

document.getElementById('modal-book').addEventListener('click', e => {
  if (e.target === e.currentTarget) closeBookModal();
});

function closeBookModal() {
  document.getElementById('modal-book').classList.add('hidden');
}

function saveBook() {
  const title = document.getElementById('input-book-title').value.trim();
  if (!title) { toast('Please enter a title.'); return; }

  if (state.editingBookId) {
    const book = bookById(state.editingBookId);
    book.title = title;
    if (pendingCover !== null) book.cover = pendingCover;
    save();
    toast('Book updated.');
    if (document.getElementById('view-book').classList.contains('active')) {
      document.getElementById('book-title-display').textContent = title;
    }
  } else {
    const newBook = { id: uid(), title, cover: pendingCover || null, chapters: [] };
    state.books.push(newBook);
    save();
    toast('Book created.');
  }

  closeBookModal();
  renderLibrary();
}

document.getElementById('cover-upload-area').addEventListener('click', () => {
  document.getElementById('input-cover').click();
});
document.getElementById('input-cover').addEventListener('change', e => {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = ev => {
    pendingCover = ev.target.result;
    const preview = document.getElementById('cover-preview');
    preview.src = pendingCover;
    preview.classList.remove('hidden');
    document.getElementById('cover-placeholder').style.display = 'none';
  };
  reader.readAsDataURL(file);
});

// ── Confirm Delete Modal ───────────────────
function confirmDelete(msg, fn) {
  state.pendingDeleteFn = fn;
  document.getElementById('confirm-message').textContent = msg;
  document.getElementById('modal-confirm').classList.remove('hidden');
}
document.getElementById('btn-confirm-cancel').addEventListener('click', () => {
  document.getElementById('modal-confirm').classList.add('hidden');
  state.pendingDeleteFn = null;
});
document.getElementById('btn-confirm-ok').addEventListener('click', () => {
  document.getElementById('modal-confirm').classList.add('hidden');
  if (state.pendingDeleteFn) { state.pendingDeleteFn(); state.pendingDeleteFn = null; }
});
document.getElementById('modal-confirm').addEventListener('click', e => {
  if (e.target === e.currentTarget) {
    document.getElementById('modal-confirm').classList.add('hidden');
    state.pendingDeleteFn = null;
  }
});

// ── Navigation ─────────────────────────────
document.getElementById('btn-back-library').addEventListener('click', () => {
  state.currentBookId = null;
  renderLibrary();
  showView('view-library');
});
document.getElementById('btn-new-chapter').addEventListener('click', () => {
  openEditor(state.currentBookId, null);
});

// ── Keyboard shortcut: Ctrl/Cmd+S to save ─
document.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key === 's') {
    if (document.getElementById('view-editor').classList.contains('active')) {
      e.preventDefault();
      document.getElementById('btn-save-chapter').click();
    }
  }
});

// ── Init ───────────────────────────────────
load();
renderLibrary();
showView('view-library');