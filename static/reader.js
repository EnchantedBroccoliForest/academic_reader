// reader3 client-side: KaTeX rendering, hotkeys, scroll-spy, copy-for-LLM,
// section palette, and Codex explanations. Plain ES2020, no build step.

(function () {
  'use strict';

  const cfg = window.__READER3__ || {};
  const bookId = cfg.bookId;
  const sections = cfg.sections || [];   // [{id, title, level}]
  const currentId = cfg.currentSectionId;
  const paperTitle = cfg.title || '';
  const paperAuthors = (cfg.authors || []).join(', ');
  const sourceTag = cfg.sourceTag || '';
  let activeIdx = Math.max(0, sections.findIndex(s => s.id === currentId));
  let keyConfigured = !!(cfg.codexKey && cfg.codexKey.configured);
  let keySource = cfg.codexKey ? cfg.codexKey.source : null;
  let codexModel = cfg.codexKey ? cfg.codexKey.model : '';

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

  // ---- Helpers -----------------------------------------------------------
  function sectionEls() {
    return Array.from(document.querySelectorAll('.reader-section'));
  }

  function scrollRoot() {
    const main = document.getElementById('main');
    if (main && main.scrollHeight > main.clientHeight + 2) return main;
    return document.scrollingElement || document.documentElement;
  }

  function activeSectionEl() {
    const all = sectionEls();
    return all[activeIdx] || all[0] || null;
  }

  function activeSectionMeta() {
    return sections[activeIdx] || sections[0] || { id: '', title: '', level: 1 };
  }

  function prefersReducedMotion() {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  // ---- HTML -> Markdown (lightweight, good enough for paste) ------------
  function htmlToMarkdown(rootEl) {
    const out = [];

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
      if (node.classList && node.classList.contains('copy-section-btn')) return;
      const tag = node.tagName.toLowerCase();
      if (/^h[1-6]$/.test(tag)) {
        const level = parseInt(tag[1], 10);
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
      const t = inline(node).trim();
      if (t) { out.push(t); out.push(''); }
    }

    Array.from(rootEl.childNodes).forEach(block);
    return out.join('\n').replace(/\n{3,}/g, '\n\n').trim() + '\n';
  }

  // ---- Provenance header for copies -------------------------------------
  function provenance(sectionTitleArg) {
    const lines = [];
    if (paperTitle) lines.push('> From: "' + paperTitle + '"' + (paperAuthors ? ' - ' + paperAuthors : ''));
    if (sectionTitleArg) lines.push('> Section: ' + sectionTitleArg);
    if (sourceTag) lines.push('> Source: ' + sourceTag);
    return lines.join('\n') + (lines.length ? '\n\n' : '');
  }

  async function copyText(text, msg) {
    try {
      await navigator.clipboard.writeText(text);
      toast(msg || 'Copied');
    } catch (e) {
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
    const root = activeSectionEl() || document.querySelector('.book-content');
    if (!root) return;
    const meta = activeSectionMeta();
    const text = provenance(meta.title) + htmlToMarkdown(root);
    copyText(text, 'Section copied for LLM');
    if (btn) {
      const original = btn.textContent;
      btn.classList.add('copied');
      btn.textContent = 'Copied!';
      setTimeout(() => {
        btn.classList.remove('copied');
        btn.textContent = original;
      }, 1400);
    }
  }

  function copySelection() {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed) return toast('No selection');
    const text = sel.toString();
    const md = '> ' + text.split('\n').map(l => l.trim()).filter(Boolean).join('\n> ');
    copyText(provenance(activeSectionMeta().title) + md + '\n', 'Selection copied');
  }

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

  // ---- Continuous section navigation ------------------------------------
  function setActive(idx, { scrollToc = false } = {}) {
    if (idx < 0 || idx >= sections.length) return;
    activeIdx = idx;
    const meta = activeSectionMeta();
    document.querySelectorAll('.toc-link').forEach(a => {
      a.classList.toggle('active', a.getAttribute('data-section-id') === meta.id);
    });
    const label = document.getElementById('active-section-label');
    if (label) {
      const level = meta.level > 1 ? ' · H' + meta.level : '';
      label.textContent = 'Section ' + (idx + 1) + ' of ' + sections.length + level;
    }
    const summary = document.querySelector('.toc-summary-current');
    if (summary) summary.textContent = meta.title;
    if (scrollToc) {
      const active = document.querySelector('.toc-link.active');
      if (active) active.scrollIntoView({ block: 'nearest' });
    }
    try {
      localStorage.setItem('reader3:' + bookId + ':lastSection', meta.id);
      localStorage.setItem('reader3:' + bookId + ':lastOpened', String(Date.now()));
    } catch (_) {}
  }

  function scrollToSection(id, { updateHash = true } = {}) {
    const target = document.getElementById(id);
    if (!target) return;
    activeLockedUntil = Date.now() + 1200;
    target.scrollIntoView({
      block: 'start',
      behavior: prefersReducedMotion() ? 'auto' : 'smooth',
    });
    const idx = sections.findIndex(s => s.id === id);
    if (idx >= 0) setActive(idx, { scrollToc: true });
    if (updateHash && history.replaceState) {
      history.replaceState(null, '', '#' + encodeURIComponent(id));
    }
  }

  function go(idx) {
    if (idx < 0 || idx >= sections.length) return;
    scrollToSection(sections[idx].id);
  }

  let scrollQueued = false;
  let activeLockedUntil = 0;
  function updateProgressAndActive() {
    scrollQueued = false;
    const root = scrollRoot();
    const max = Math.max(0, root.scrollHeight - root.clientHeight);
    const pct = max ? (root.scrollTop / max) * 100 : 0;
    const fill = document.querySelector('.reading-progress-fill');
    if (fill) fill.style.width = Math.max(0, Math.min(100, pct)) + '%';
    if (Date.now() < activeLockedUntil) return;

    const viewportTop = root === document.scrollingElement || root === document.documentElement
      ? 0
      : root.getBoundingClientRect().top;
    let bestIdx = activeIdx;
    sectionEls().forEach((el, idx) => {
      const top = el.getBoundingClientRect().top - viewportTop;
      if (top <= 120) bestIdx = idx;
    });
    if (bestIdx !== activeIdx) setActive(bestIdx, { scrollToc: true });
  }

  function queueScrollUpdate() {
    if (scrollQueued) return;
    scrollQueued = true;
    requestAnimationFrame(updateProgressAndActive);
  }

  function setupScrollSpy() {
    const main = document.getElementById('main');
    if (main) main.addEventListener('scroll', queueScrollUpdate, { passive: true });
    window.addEventListener('scroll', queueScrollUpdate, { passive: true });
    window.addEventListener('resize', queueScrollUpdate);
    queueScrollUpdate();
  }

  function setupTocLinks() {
    document.querySelectorAll('.toc-link').forEach(link => {
      link.addEventListener('click', e => {
        const id = link.getAttribute('data-section-id');
        if (!id) return;
        e.preventDefault();
        scrollToSection(id);
        const details = document.getElementById('toc-disclosure');
        if (details && !window.matchMedia('(min-width: 761px)').matches) {
          details.open = false;
        }
      });
    });
  }

  // ---- Section palette --------------------------------------------------
  function setupPalette() {
    const overlay = document.getElementById('palette-overlay');
    const input = document.getElementById('palette-input');
    const results = document.getElementById('palette-results');
    const more = document.getElementById('palette-more');
    if (!overlay || !input || !results) return;

    const MAX_SHOWN = 80;
    let visibleItems = [];
    let selectedIdx = 0;

    function esc(str) {
      return String(str).replace(/[<>&"]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c]));
    }

    function render(query) {
      const q = (query || '').toLowerCase().trim();
      const all = sections.filter(s => !q || s.title.toLowerCase().includes(q));
      const matches = all.slice(0, MAX_SHOWN);
      visibleItems = matches;
      selectedIdx = 0;
      results.innerHTML = matches.map((s, i) =>
        '<div class="palette-item' + (i === 0 ? ' selected' : '') + '" data-id="' + esc(s.id) + '">' +
        '<span class="lvl">H' + s.level + '</span>' +
        esc(s.title) +
        '</div>'
      ).join('');
      if (more) {
        const hidden = all.length - matches.length;
        if (hidden > 0) {
          more.textContent = hidden + ' more section' + (hidden === 1 ? '' : 's') +
                             ' - keep typing to narrow';
          more.hidden = false;
        } else if (!all.length) {
          more.textContent = 'No section matches "' + query + '"';
          more.hidden = false;
        } else {
          more.hidden = true;
        }
      }
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
      close();
      scrollToSection(item.id);
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
      scrollToSection(it.getAttribute('data-id'));
      close();
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

  function setupHelp() {
    const h = document.getElementById('help-modal');
    if (!h) return;
    const close = () => h.classList.remove('show');
    h.addEventListener('click', e => { if (e.target === h) close(); });
    const btn = h.querySelector('.help-close');
    if (btn) btn.addEventListener('click', close);
  }

  // ---- TOC disclosure (mobile) -------------------------------------------
  function setupToc() {
    const details = document.getElementById('toc-disclosure');
    if (!details) return;
    const wide = window.matchMedia('(min-width: 761px)');

    function sync() {
      if (wide.matches) {
        details.open = true;
      } else if (!details.dataset.userToggled) {
        details.open = false;
      }
    }
    details.addEventListener('toggle', () => {
      if (!wide.matches) details.dataset.userToggled = '1';
      if (details.open) {
        const active = details.querySelector('.toc-link.active');
        if (active) active.scrollIntoView({ block: 'nearest' });
      }
    });
    wide.addEventListener('change', () => {
      delete details.dataset.userToggled;
      sync();
    });
    sync();
  }

  // ---- Codex explanation panel ------------------------------------------
  function setupCodexPanel() {
    const form = document.getElementById('codex-key-form');
    const input = document.getElementById('codex-key-input');
    const clearBtn = document.getElementById('codex-key-clear');
    const pill = document.getElementById('codex-key-pill');
    const status = document.getElementById('codex-status');
    const output = document.getElementById('codex-output');
    const selectionBox = document.getElementById('codex-selection');
    if (!form || !input || !pill || !status || !output) return;

    let selectionTimer = null;
    let explainAbort = null;
    let requestSeq = 0;
    let lastText = '';

    function setKeyState(data) {
      keyConfigured = !!(data && data.configured);
      keySource = data ? data.source : null;
      codexModel = data ? data.model : codexModel;
      pill.textContent = keyConfigured ? (keySource === 'env' ? 'Env key' : 'Session key') : 'No key';
      pill.classList.toggle('ready', keyConfigured);
      if (keyConfigured && !output.textContent.trim()) {
        status.textContent = codexModel ? 'Ready - ' + codexModel : 'Ready';
      }
    }

    function setStatus(msg, mode) {
      status.textContent = msg;
      status.classList.toggle('is-error', mode === 'error');
      status.classList.toggle('is-loading', mode === 'loading');
    }

    function showSelection(text) {
      if (!selectionBox) return;
      selectionBox.hidden = false;
      selectionBox.textContent = text.length > 420 ? text.slice(0, 420).trim() + '...' : text;
    }

    async function refreshKeyStatus() {
      try {
        const resp = await fetch('/api/codex/key-status');
        if (resp.ok) setKeyState(await resp.json());
      } catch (_) {}
    }

    form.addEventListener('submit', async e => {
      e.preventDefault();
      const apiKey = input.value.trim();
      if (!apiKey) {
        setStatus('API key is required.', 'error');
        return;
      }
      setStatus('Saving key...', 'loading');
      try {
        const resp = await fetch('/api/codex/key', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ api_key: apiKey }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(data.detail || 'Could not save key.');
        input.value = '';
        setKeyState(data);
        setStatus(codexModel ? 'Ready - ' + codexModel : 'Ready');
      } catch (err) {
        setStatus(err.message || 'Could not save key.', 'error');
      }
    });

    if (clearBtn) {
      clearBtn.addEventListener('click', async () => {
        setStatus('Clearing key...', 'loading');
        try {
          const resp = await fetch('/api/codex/key', { method: 'DELETE' });
          const data = await resp.json().catch(() => ({}));
          if (!resp.ok) throw new Error(data.detail || 'Could not clear key.');
          setKeyState(data);
          setStatus(data.configured ? 'Ready - ' + data.model : 'No key');
        } catch (err) {
          setStatus(err.message || 'Could not clear key.', 'error');
        }
      });
    }

    function selectedTextInPaper() {
      const sel = window.getSelection();
      if (!sel || sel.isCollapsed || !sel.rangeCount) return '';
      const root = document.querySelector('.book-content');
      if (!root) return '';
      let node = sel.getRangeAt(0).commonAncestorContainer;
      if (node.nodeType === 3) node = node.parentElement;
      if (!node || !root.contains(node)) return '';
      return sel.toString().replace(/\s+/g, ' ').trim();
    }

    async function explain(text) {
      if (!text || text === lastText) return;
      lastText = text;
      showSelection(text);
      if (!keyConfigured) {
        output.textContent = '';
        setStatus('Add a Codex API key first.', 'error');
        return;
      }

      if (explainAbort) explainAbort.abort();
      explainAbort = new AbortController();
      const seq = ++requestSeq;
      output.classList.add('dim');
      setStatus('Explaining...', 'loading');
      try {
        const meta = activeSectionMeta();
        const resp = await fetch('/api/codex/explain', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          signal: explainAbort.signal,
          body: JSON.stringify({
            text,
            paper_title: paperTitle,
            section_title: meta.title,
            source_tag: sourceTag,
          }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(data.detail || 'Explanation failed.');
        if (seq !== requestSeq) return;
        output.textContent = data.explanation || '';
        output.classList.remove('dim');
        setStatus(data.model ? 'Codex - ' + data.model : 'Codex');
      } catch (err) {
        if (err.name === 'AbortError') return;
        output.classList.remove('dim');
        setStatus(err.message || 'Explanation failed.', 'error');
      }
    }

    function scheduleExplain() {
      clearTimeout(selectionTimer);
      selectionTimer = setTimeout(() => {
        const text = selectedTextInPaper();
        if (text) explain(text);
      }, 500);
    }

    document.addEventListener('selectionchange', scheduleExplain);
    document.addEventListener('mouseup', scheduleExplain);
    document.addEventListener('keyup', scheduleExplain);
    refreshKeyStatus();
  }

  // ---- Keybindings ------------------------------------------------------
  function isTyping() {
    const a = document.activeElement;
    if (!a) return false;
    const tag = (a.tagName || '').toLowerCase();
    return tag === 'input' || tag === 'textarea' || a.isContentEditable;
  }

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      document.querySelectorAll('.palette-overlay.show, .help-modal.show')
              .forEach(el => el.classList.remove('show'));
      return;
    }
    if (isTyping()) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;

    switch (e.key) {
      case 'j': go(activeIdx + 1); break;
      case 'k': go(activeIdx - 1); break;
      case 'c': copyCurrentSection(); break;
      case 'C': copyEntirePaper(); break;
      case 'y': copySelection(); break;
      case 'g': if (window.__reader3_openPalette) window.__reader3_openPalette(); break;
      case '?': toggleHelp(); break;
      default: return;
    }
    e.preventDefault();
  });

  // ---- Wire up ----------------------------------------------------------
  document.addEventListener('DOMContentLoaded', () => {
    renderMath();
    setupPalette();
    setupHelp();
    setupToc();
    setupTocLinks();
    setupScrollSpy();
    setupCodexPanel();

    document.querySelectorAll('[data-copy-current]').forEach(btn => {
      btn.addEventListener('click', () => copyCurrentSection(btn));
    });
    document.querySelectorAll('[data-copy-paper]').forEach(btn => {
      btn.addEventListener('click', () => copyEntirePaper());
    });

    const hash = decodeURIComponent((window.location.hash || '').replace(/^#/, ''));
    if (hash && document.getElementById(hash)) {
      setTimeout(() => scrollToSection(hash, { updateHash: false }), 60);
    } else {
      setActive(activeIdx, { scrollToc: true });
    }
  });
})();
