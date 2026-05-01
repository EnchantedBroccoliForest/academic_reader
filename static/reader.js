// reader3 client-side: KaTeX rendering, hotkeys, scroll-spy, copy-for-LLM,
// section palette. No build step; this is plain ES2020.

(function () {
  'use strict';

  const cfg = window.__READER3__ || {};
  const bookId = cfg.bookId;
  const sections = cfg.sections || [];   // [{id, title, level}]
  const currentId = cfg.currentSectionId;
  const currentIdx = sections.findIndex(s => s.id === currentId);
  const paperTitle = cfg.title || '';
  const paperAuthors = (cfg.authors || []).join(', ');
  const sourceTag = cfg.sourceTag || '';
  const sectionTitle = cfg.sectionTitle || '';

  // ---- KaTeX -------------------------------------------------------------
  function renderMath() {
    if (typeof renderMathInElement !== 'function') return;
    const root = document.querySelector('.book-content');
    if (!root) return;
    try {
      renderMathInElement(root, {
        delimiters: [
          {left: '$$', right: '$$', display: true},
          {left: '\\[', right: '\\]', display: true},
          {left: '\\(', right: '\\)', display: false},
          {left: '$', right: '$', display: false},
        ],
        throwOnError: false,
        ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'],
      });
    } catch (e) {
      console.warn('KaTeX render error', e);
    }
  }

  // ---- Toast -------------------------------------------------------------
  let toastTimer = null;
  function toast(msg) {
    let el = document.getElementById('toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'toast';
      el.className = 'toast';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), 1600);
  }

  // ---- HTML -> Markdown (lightweight, good enough for paste) ------------
  // Handles headings, paragraphs, lists, code, blockquote, links, images,
  // and emphasis. Leaves KaTeX-rendered <span class="katex"> alone by using
  // its [data-original-text] when we can; falls back to plain text.
  function htmlToMarkdown(rootEl) {
    const out = [];

    function escape(s) { return s.replace(/([\\`*_{}\[\]()#+\-.!])/g, '\\$1'); }
    function inline(node) {
      if (node.nodeType === 3) return node.nodeValue;
      if (node.nodeType !== 1) return '';
      const tag = node.tagName.toLowerCase();
      const kids = () => Array.from(node.childNodes).map(inline).join('');
      switch (tag) {
        case 'br': return '\n';
        case 'strong': case 'b': return '**' + kids() + '**';
        case 'em': case 'i': return '*' + kids() + '*';
        case 'code': return '`' + node.textContent + '`';
        case 'a': {
          const href = node.getAttribute('href') || '';
          return '[' + kids() + '](' + href + ')';
        }
        case 'img': {
          const alt = node.getAttribute('alt') || '';
          const src = node.getAttribute('src') || '';
          return '![' + alt + '](' + src + ')';
        }
        case 'span': {
          // KaTeX-rendered: try to recover original LaTeX from its annotation.
          if (node.classList && node.classList.contains('katex')) {
            const ann = node.querySelector('annotation[encoding="application/x-tex"]');
            if (ann) {
              const isDisplay = node.classList.contains('katex-display') ||
                                (node.parentElement && node.parentElement.classList.contains('katex-display'));
              const tex = ann.textContent;
              return isDisplay ? '\n$$' + tex + '$$\n' : '$' + tex + '$';
            }
          }
          return kids();
        }
        default: return kids();
      }
    }

    function block(node) {
      if (node.nodeType === 3) {
        const t = node.nodeValue.trim();
        if (t) out.push(t);
        return;
      }
      if (node.nodeType !== 1) return;
      // Skip the copy button itself.
      if (node.classList && node.classList.contains('copy-section-btn')) return;
      const tag = node.tagName.toLowerCase();
      if (/^h[1-6]$/.test(tag)) {
        const level = parseInt(tag[1], 10);
        // Strip embedded copy button text from the heading.
        const clone = node.cloneNode(true);
        clone.querySelectorAll('.copy-section-btn').forEach(b => b.remove());
        out.push('\n' + '#'.repeat(level) + ' ' + clone.textContent.trim() + '\n');
        return;
      }
      if (tag === 'p') { out.push(inline(node).trim()); out.push(''); return; }
      if (tag === 'blockquote') {
        const inner = Array.from(node.childNodes).map(inline).join('').trim();
        out.push(inner.split('\n').map(l => '> ' + l).join('\n'));
        out.push('');
        return;
      }
      if (tag === 'pre') {
        const code = node.textContent.replace(/\n$/, '');
        out.push('```');
        out.push(code);
        out.push('```');
        out.push('');
        return;
      }
      if (tag === 'ul' || tag === 'ol') {
        let i = 1;
        for (const li of node.children) {
          if (li.tagName && li.tagName.toLowerCase() === 'li') {
            const marker = tag === 'ol' ? (i++ + '.') : '-';
            out.push(marker + ' ' + inline(li).trim());
          }
        }
        out.push('');
        return;
      }
      if (tag === 'hr') { out.push('---\n'); return; }
      if (tag === 'table') {
        // Crude but functional table -> markdown
        const rows = Array.from(node.querySelectorAll('tr'));
        if (!rows.length) return;
        const toRow = tr => '| ' + Array.from(tr.children).map(c => (c.textContent || '').trim().replace(/\|/g, '\\|')).join(' | ') + ' |';
        out.push(toRow(rows[0]));
        out.push('| ' + Array.from(rows[0].children).map(() => '---').join(' | ') + ' |');
        for (let i = 1; i < rows.length; i++) out.push(toRow(rows[i]));
        out.push('');
        return;
      }
      if (tag === 'div' || tag === 'section' || tag === 'article') {
        Array.from(node.childNodes).forEach(block);
        return;
      }
      // Fallback: treat as inline paragraph.
      const t = inline(node).trim();
      if (t) { out.push(t); out.push(''); }
    }

    Array.from(rootEl.childNodes).forEach(block);
    return out.join('\n').replace(/\n{3,}/g, '\n\n').trim() + '\n';
  }

  // ---- Provenance header for copies -------------------------------------
  function provenance(sectionTitleArg) {
    const lines = [];
    if (paperTitle) lines.push('> From: "' + paperTitle + '"' + (paperAuthors ? ' — ' + paperAuthors : ''));
    if (sectionTitleArg) lines.push('> Section: ' + sectionTitleArg);
    if (sourceTag) lines.push('> Source: ' + sourceTag);
    return lines.join('\n') + (lines.length ? '\n\n' : '');
  }

  async function copyText(text, msg) {
    try {
      await navigator.clipboard.writeText(text);
      toast(msg || 'Copied');
    } catch (e) {
      // Fallback: textarea + execCommand
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); toast(msg || 'Copied'); }
      catch (_) { toast('Copy failed'); }
      ta.remove();
    }
  }

  function copyCurrentSection(btn) {
    const root = document.querySelector('.book-content');
    if (!root) return;
    const md = htmlToMarkdown(root);
    const text = provenance(sectionTitle) + md;
    copyText(text, 'Section copied for LLM');
    if (btn) {
      btn.classList.add('copied');
      btn.textContent = 'Copied!';
      setTimeout(() => {
        btn.classList.remove('copied');
        btn.textContent = '\u{1F4CB} Copy for LLM';
      }, 1400);
    }
  }

  function copySelection() {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed) return toast('No selection');
    const text = sel.toString();
    const md = '> ' + text.split('\n').map(l => l.trim()).filter(Boolean).join('\n> ');
    copyText(provenance(sectionTitle) + md + '\n', 'Selection copied');
  }

  // ---- Hotkey navigation ------------------------------------------------
  function go(idx) {
    if (idx < 0 || idx >= sections.length) return;
    window.location.href = '/read/' + bookId + '/' + sections[idx].id;
  }

  // ---- Scroll-spy on TOC -------------------------------------------------
  function setupScrollSpy() {
    const headings = document.querySelectorAll('.book-content h1, .book-content h2, .book-content h3');
    if (!headings.length) return;
    const tocLinks = new Map();
    document.querySelectorAll('.toc-link').forEach(a => {
      const id = a.getAttribute('data-section-id');
      if (id) tocLinks.set(id, a);
    });

    const observer = new IntersectionObserver(entries => {
      // Use the topmost intersecting heading.
      const visible = entries.filter(e => e.isIntersecting)
                             .sort((a, b) => a.target.offsetTop - b.target.offsetTop);
      if (!visible.length) return;
      const id = visible[0].target.id;
      // Only mutate the active link inside the *current* page; the active
      // section in the TOC for this page is already set by the server.
    }, { rootMargin: '-10% 0px -75% 0px', threshold: 0 });

    headings.forEach(h => { if (h.id) observer.observe(h); });
  }

  // ---- Section palette --------------------------------------------------
  function setupPalette() {
    const overlay = document.getElementById('palette-overlay');
    const input = document.getElementById('palette-input');
    const results = document.getElementById('palette-results');
    if (!overlay || !input || !results) return;

    let visibleItems = [];
    let selectedIdx = 0;

    function render(query) {
      const q = (query || '').toLowerCase().trim();
      const matches = sections.filter(s =>
        !q || s.title.toLowerCase().includes(q)
      ).slice(0, 80);
      visibleItems = matches;
      selectedIdx = 0;
      results.innerHTML = matches.map((s, i) =>
        '<div class="palette-item' + (i === 0 ? ' selected' : '') + '" data-id="' + s.id + '">' +
        '<span class="lvl">H' + s.level + '</span>' +
        s.title.replace(/[<>&]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;'}[c])) +
        '</div>'
      ).join('');
    }

    function open() {
      overlay.classList.add('show');
      input.value = '';
      render('');
      setTimeout(() => input.focus(), 0);
    }
    function close() { overlay.classList.remove('show'); }

    function pick(i) {
      const item = visibleItems[i];
      if (!item) return;
      window.location.href = '/read/' + bookId + '/' + item.id;
    }

    input.addEventListener('input', () => render(input.value));
    input.addEventListener('keydown', e => {
      if (e.key === 'ArrowDown') {
        selectedIdx = Math.min(selectedIdx + 1, visibleItems.length - 1);
        updateSelected();
        e.preventDefault();
      } else if (e.key === 'ArrowUp') {
        selectedIdx = Math.max(selectedIdx - 1, 0);
        updateSelected();
        e.preventDefault();
      } else if (e.key === 'Enter') {
        pick(selectedIdx);
        e.preventDefault();
      } else if (e.key === 'Escape') {
        close();
      }
    });
    function updateSelected() {
      Array.from(results.children).forEach((el, i) => {
        el.classList.toggle('selected', i === selectedIdx);
      });
      const sel = results.children[selectedIdx];
      if (sel) sel.scrollIntoView({ block: 'nearest' });
    }
    results.addEventListener('click', e => {
      const it = e.target.closest('.palette-item');
      if (!it) return;
      const id = it.getAttribute('data-id');
      window.location.href = '/read/' + bookId + '/' + id;
    });
    overlay.addEventListener('click', e => { if (e.target === overlay) close(); });

    window.__reader3_openPalette = open;
    window.__reader3_closePalette = close;
  }

  // ---- Help modal -------------------------------------------------------
  function toggleHelp() {
    const h = document.getElementById('help-modal');
    if (!h) return;
    h.classList.toggle('show');
  }

  // ---- Keybindings ------------------------------------------------------
  function isTyping() {
    const a = document.activeElement;
    if (!a) return false;
    const tag = (a.tagName || '').toLowerCase();
    return tag === 'input' || tag === 'textarea' || a.isContentEditable;
  }

  document.addEventListener('keydown', e => {
    // Always-on Escape closes overlays.
    if (e.key === 'Escape') {
      document.querySelectorAll('.palette-overlay.show, .help-modal.show')
              .forEach(el => el.classList.remove('show'));
      return;
    }
    if (isTyping()) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;

    switch (e.key) {
      case 'j': go(currentIdx + 1); break;
      case 'k': go(currentIdx - 1); break;
      case 'c': copyCurrentSection(); break;
      case 'C': copyEntirePaper(); break;
      case 'y': copySelection(); break;
      case 'g': if (window.__reader3_openPalette) window.__reader3_openPalette(); break;
      case '?': toggleHelp(); break;
      default: return;
    }
    e.preventDefault();
  });

  // ---- Whole-paper copy -------------------------------------------------
  async function copyEntirePaper() {
    toast('Fetching full paper...');
    try {
      const resp = await fetch('/api/' + bookId + '/markdown');
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const md = await resp.text();
      copyText(md, 'Whole paper copied for LLM');
    } catch (e) {
      toast('Copy-all failed: ' + e.message);
    }
  }

  // ---- Wire up ----------------------------------------------------------
  document.addEventListener('DOMContentLoaded', () => {
    renderMath();
    setupPalette();
    setupScrollSpy();

    // Wire the copy button next to the heading.
    document.querySelectorAll('.copy-section-btn').forEach(btn => {
      btn.addEventListener('click', () => copyCurrentSection(btn));
    });

    // Persist last-section / scroll position for "Continue".
    try {
      localStorage.setItem('reader3:' + bookId + ':lastSection', currentId);
      localStorage.setItem('reader3:' + bookId + ':lastOpened', String(Date.now()));
    } catch (_) { /* private mode */ }
  });
})();
