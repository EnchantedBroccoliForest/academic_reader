// reader3 library page: filter, "Continue" from localStorage, import
// (button + drag/drop), and delete. Plain ES2020, no build step.

(function () {
  'use strict';

  const ACCEPTED = /\.(pdf|epub)$/i;

  // ---- "Continue" + last-opened from localStorage (no DB) ---------------
  function fmtAgo(ts) {
    const diff = Date.now() - ts;
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return mins + 'm ago';
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return hrs + 'h ago';
    const days = Math.floor(hrs / 24);
    if (days < 30) return days + 'd ago';
    const months = Math.floor(days / 30);
    return months + 'mo ago';
  }

  document.querySelectorAll('.book-card').forEach(card => {
    const id = card.getAttribute('data-book-id');
    let lastSec = null, lastOpened = 0;
    try {
      lastSec = localStorage.getItem('reader3:' + id + ':lastSection');
      lastOpened = parseInt(localStorage.getItem('reader3:' + id + ':lastOpened') || '0', 10);
    } catch (_) {}
    const lastEl = card.querySelector('[data-last-opened-for="' + id + '"]');
    if (lastEl && lastOpened) lastEl.textContent = 'Last opened ' + fmtAgo(lastOpened);
    const cont = card.querySelector('[data-continue-for="' + id + '"]');
    if (cont && lastSec) {
      cont.href = '/read/' + id + '/' + lastSec;
      cont.hidden = false;
    }
  });

  // ---- Live filter -------------------------------------------------------
  const filterInput = document.getElementById('library-filter');
  const noResults = document.getElementById('no-results');
  if (filterInput) {
    filterInput.addEventListener('input', () => {
      const q = filterInput.value.toLowerCase().trim();
      let visible = 0;
      document.querySelectorAll('.book-card').forEach(card => {
        const hay = card.getAttribute('data-search') || '';
        const match = !q || hay.includes(q);
        card.classList.toggle('is-hidden', !match);
        if (match) visible++;
      });
      if (noResults) noResults.hidden = visible !== 0;
    });
  }

  // ---- Status toast ------------------------------------------------------
  const status = document.getElementById('upload-status');
  const statusMsg = status.querySelector('.upload-msg');
  const barFill = status.querySelector('.upload-bar-fill');

  function showStatus(msg, { progress = null, error = false, success = false } = {}) {
    status.hidden = false;
    status.classList.toggle('is-error', !!error);
    status.classList.toggle('is-success', !!success);
    statusMsg.textContent = msg;
    if (progress === null) {
      barFill.style.width = '0%';
      status.classList.add('is-indeterminate');
    } else {
      status.classList.remove('is-indeterminate');
      barFill.style.width = Math.max(0, Math.min(100, progress)) + '%';
    }
  }
  function hideStatusSoon(delay) {
    setTimeout(() => {
      status.hidden = true;
      status.classList.remove('is-error', 'is-success', 'is-indeterminate');
      barFill.style.width = '0%';
    }, delay);
  }

  // ---- Upload ------------------------------------------------------------
  function uploadFile(file) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/upload');
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          const pct = (e.loaded / e.total) * 100;
          if (pct < 100) {
            showStatus(`Uploading ${file.name}… ${Math.round(pct)}%`, { progress: pct });
          } else {
            showStatus(`Processing ${file.name}…`, { progress: null });
          }
        }
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try { resolve(JSON.parse(xhr.responseText)); }
          catch (e) { reject(new Error('The server sent a response we could not read.')); }
        } else {
          let detail = `Import failed (${xhr.status})`;
          try { detail = JSON.parse(xhr.responseText).detail || detail; } catch (_) {}
          reject(new Error(detail));
        }
      };
      xhr.onerror = () => reject(new Error('Lost the connection to the server.'));
      const fd = new FormData();
      fd.append('file', file);
      xhr.send(fd);
    });
  }

  async function handleFiles(fileList) {
    const files = Array.from(fileList || []);
    const usable = files.filter(f => ACCEPTED.test(f.name));
    if (!usable.length) {
      if (files.length) {
        showStatus('Only PDF and EPUB files can be imported here.', { error: true, progress: 0 });
        hideStatusSoon(3000);
      }
      return;
    }
    for (let i = 0; i < usable.length; i++) {
      const file = usable[i];
      const prefix = usable.length > 1 ? `(${i + 1}/${usable.length}) ` : '';
      try {
        showStatus(prefix + `Uploading ${file.name}…`, { progress: 0 });
        const result = await uploadFile(file);
        showStatus(prefix + `Imported "${result.title}"`, { progress: 100, success: true });
        if (i === usable.length - 1) {
          setTimeout(() => { window.location.reload(); }, 600);
          return;
        }
      } catch (err) {
        showStatus(prefix + (err.message || 'Import failed'), { error: true, progress: 0 });
        hideStatusSoon(4500);
        return;
      }
    }
  }

  // ---- Add button (works on touch, where drag/drop does not) -------------
  const addBtn = document.getElementById('add-btn');
  const fileInput = document.getElementById('file-input');
  if (addBtn && fileInput) {
    addBtn.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', () => {
      handleFiles(fileInput.files);
      fileInput.value = '';
    });
  }

  // ---- Delete ------------------------------------------------------------
  document.querySelectorAll('[data-delete-for]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const card = btn.closest('.book-card');
      const id = btn.getAttribute('data-delete-for');
      const title = (card && card.getAttribute('data-title')) || id;
      if (!window.confirm(`Remove "${title}" from your library?\n\nThis deletes its ${id} folder from disk.`)) {
        return;
      }
      btn.disabled = true;
      showStatus(`Removing "${title}"…`, { progress: null });
      try {
        const resp = await fetch('/api/' + encodeURIComponent(id), { method: 'DELETE' });
        if (!resp.ok) {
          let detail = `Could not remove it (${resp.status})`;
          try { detail = (await resp.json()).detail || detail; } catch (_) {}
          throw new Error(detail);
        }
        try {
          localStorage.removeItem('reader3:' + id + ':lastSection');
          localStorage.removeItem('reader3:' + id + ':lastOpened');
        } catch (_) {}
        showStatus(`Removed "${title}"`, { progress: 100, success: true });
        if (card) card.remove();
        hideStatusSoon(1600);
        if (!document.querySelector('.book-card')) {
          setTimeout(() => window.location.reload(), 700);
        }
      } catch (err) {
        btn.disabled = false;
        showStatus(err.message || 'Could not remove it', { error: true, progress: 0 });
        hideStatusSoon(4000);
      }
    });
  });

  // ---- Drag & drop -------------------------------------------------------
  const overlay = document.getElementById('drop-overlay');
  let dragDepth = 0;

  function hasFiles(e) {
    if (!e.dataTransfer) return false;
    const types = e.dataTransfer.types;
    if (!types) return false;
    for (let i = 0; i < types.length; i++) {
      if (types[i] === 'Files') return true;
    }
    return false;
  }

  window.addEventListener('dragenter', (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    dragDepth++;
    overlay.classList.add('show');
  });
  window.addEventListener('dragover', (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  });
  window.addEventListener('dragleave', (e) => {
    if (!hasFiles(e)) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) overlay.classList.remove('show');
  });
  window.addEventListener('drop', (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    dragDepth = 0;
    overlay.classList.remove('show');
    handleFiles(e.dataTransfer.files);
  });
})();
