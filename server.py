import os
import re
import shutil
import tempfile
from functools import lru_cache
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from reader3 import Book, load_book, save_to_pickle

_HERE = os.path.dirname(os.path.abspath(__file__))

app = FastAPI()
templates = Jinja2Templates(directory=os.path.join(_HERE, "templates"))

# Mount static assets (CSS/JS extracted from inline <style>/<script>).
_STATIC_DIR = os.path.join(_HERE, "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

BOOKS_DIR = os.environ.get("READER3_LIBRARY", ".")
CODEX_MODEL = os.environ.get("READER3_CODEX_MODEL", "gpt-5")
_session_codex_api_key = ""

# Handlers below are deliberately ``def`` rather than ``async def``: they do
# blocking disk I/O, unpickling and markdown conversion. Starlette runs sync
# handlers in a threadpool, so one slow book no longer stalls every other
# request. The two genuinely async handlers (upload) await the request body
# and hand their CPU-bound work to ``run_in_threadpool`` explicitly.


def _book_pkl_path(folder_name: str) -> str:
    return os.path.join(BOOKS_DIR, folder_name, "book.pkl")


@lru_cache(maxsize=32)
def _load_cached(folder_name: str, mtime: float) -> Optional[Book]:
    return load_book(os.path.join(BOOKS_DIR, folder_name))


def load_book_cached(folder_name: str) -> Optional[Book]:
    """Cache key includes mtime, so re-imports take effect without restart."""
    pkl = _book_pkl_path(folder_name)
    if not os.path.exists(pkl):
        return None
    return _load_cached(folder_name, os.path.getmtime(pkl))


def _section_index(book: Book, section_id: str) -> Optional[int]:
    for i, sec in enumerate(book.sections):
        if sec.id == section_id:
            return i
    return None


def _source_tag(book: Book) -> str:
    if book.metadata.arxiv_id:
        return f"arXiv:{book.metadata.arxiv_id}"
    if book.source_file:
        return book.source_file
    return ""


def _codex_api_key() -> tuple[str, Optional[str]]:
    if _session_codex_api_key:
        return _session_codex_api_key, "session"
    env_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if env_key:
        return env_key, "env"
    return "", None


def _codex_key_status() -> dict:
    _key, source = _codex_api_key()
    return {
        "configured": bool(source),
        "source": source,
        "model": CODEX_MODEL,
    }


def _safe_book_dir(book_id: str) -> str:
    """Resolve a book folder, refusing anything that escapes the library."""
    folder = os.path.basename(book_id)
    if not folder or not folder.endswith("_data"):
        raise HTTPException(status_code=404, detail="Book not found")
    path = os.path.join(BOOKS_DIR, folder)
    if not os.path.isdir(path):
        raise HTTPException(status_code=404, detail="Book not found")
    return path


@app.get("/", response_class=HTMLResponse)
def library_view(request: Request):
    books = []
    if os.path.exists(BOOKS_DIR):
        for item in sorted(os.listdir(BOOKS_DIR)):
            if not item.endswith("_data"):
                continue
            full = os.path.join(BOOKS_DIR, item)
            if not os.path.isdir(full):
                continue
            book = load_book_cached(item)
            if not book:
                continue
            first_id = book.sections[0].id if book.sections else ""
            books.append({
                "id": item,
                "title": book.metadata.title,
                "author": ", ".join(book.metadata.authors),
                "sections": len(book.sections),
                "first_section_id": first_id,
                "arxiv_id": book.metadata.arxiv_id,
                "abstract": _snippet(book),
                "added": _added_on(book),
            })
    return templates.TemplateResponse(
        request, "library.html", {"books": books}
    )


def _snippet(book: Book, limit: int = 260) -> str:
    """First readable prose for the library card: abstract, else body text.

    Falls back to walking sections because plenty of documents (EPUBs, scraped
    pages) have no abstract, and a card with only a title is hard to recognise.
    """
    text = (book.metadata.abstract or book.metadata.description or "").strip()
    if not text:
        collected = []
        for sec in book.sections:
            chunk = " ".join((sec.text or "").split())
            if chunk:
                collected.append(chunk)
            if sum(len(c) for c in collected) >= limit:
                break
        text = " ".join(collected)
    if not text:
        return ""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def _added_on(book: Book) -> str:
    """``processed_at`` is an ISO timestamp; show just the date."""
    stamp = (book.processed_at or "").strip()
    return stamp[:10] if len(stamp) >= 10 else ""


@app.get("/read/{book_id}", response_class=HTMLResponse)
def read_book_root(request: Request, book_id: str):
    """Render the whole book as one continuous, section-anchored page."""
    book = load_book_cached(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    if not book.sections:
        raise HTTPException(status_code=404, detail="Book has no readable sections")
    return _render_book(request, book, book_id)


@app.get("/read/{book_id}/{section_ref}", response_class=HTMLResponse)
def read_section(request: Request, book_id: str, section_ref: str):
    """Back-compat section URLs redirect to the continuous page anchor."""
    book = load_book_cached(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    if not book.sections:
        raise HTTPException(status_code=404, detail="Book has no readable sections")

    if section_ref.isdigit():
        idx = int(section_ref)
        if 0 <= idx < len(book.sections):
            return RedirectResponse(url=f"/read/{book_id}#{book.sections[idx].id}", status_code=302)
        raise HTTPException(status_code=404, detail="Section not found")

    idx = _section_index(book, section_ref)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"Unknown section: {section_ref}")
    return RedirectResponse(url=f"/read/{book_id}#{book.sections[idx].id}", status_code=302)


def _render_book(request: Request, book: Book, book_id: str):
    first = book.sections[0]
    return templates.TemplateResponse(
        request,
        "reader.html",
        {
            "book": book,
            "book_id": book_id,
            "section": first,
            "section_idx": 0,
            "section_count": len(book.sections),
            "source_tag": _source_tag(book),
            "abstract": book.metadata.abstract,
            "codex_key": _codex_key_status(),
        },
    )


def _section_markdown(section) -> str:
    """One section as markdown. The heading is already inside ``section.html``
    — do not prepend another one."""
    try:
        from markdownify import markdownify as _md
    except ImportError:  # pragma: no cover
        from reader3 import extract_plain_text
        return extract_plain_text(section.html)

    try:
        return _md(
            section.html,
            heading_style="ATX",
            # LaTeX is full of _ and *; markdownify would escape them into
            # \_ and \*, which is not valid TeX and breaks every equation.
            escape_underscores=False,
            escape_asterisks=False,
            escape_misc=False,
        )
    except TypeError:
        # Older markdownify without the escape_* options.
        return _md(section.html, heading_style="ATX")
    except Exception:
        return section.text


@app.get("/api/{book_id}/markdown", response_class=PlainTextResponse)
def book_markdown(book_id: str):
    """Whole paper as markdown with provenance header. Used by hotkey ``C``."""
    book = load_book_cached(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    parts = []
    title = book.metadata.title or "Untitled"
    authors = ", ".join(book.metadata.authors)
    parts.append(f'> From: "{title}"' + (f" — {authors}" if authors else ""))
    if book.metadata.arxiv_id:
        parts.append(f"> Source: arXiv:{book.metadata.arxiv_id}")
    elif book.source_file:
        parts.append(f"> Source: {book.source_file}")
    parts.append("")

    if book.metadata.abstract:
        parts.append("## Abstract\n\n" + book.metadata.abstract.strip() + "\n")

    for sec in book.sections:
        parts.append("\n" + _section_markdown(sec).strip() + "\n")

    return "\n".join(parts)


def _response_text(data: dict) -> str:
    """Extract text from the Responses API shape, with fallback traversal."""
    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    parts = []
    for item in data.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if not isinstance(content, dict):
                continue
            text = content.get("text") or content.get("output_text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return "\n\n".join(parts).strip()


def _openai_error_detail(resp) -> str:
    try:
        payload = resp.json()
    except Exception:
        payload = {}
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return f"OpenAI request failed with HTTP {resp.status_code}."


@app.get("/api/codex/key-status")
def codex_key_status():
    return JSONResponse(_codex_key_status())


@app.post("/api/codex/key")
async def save_codex_key(request: Request):
    global _session_codex_api_key
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    key = str(payload.get("api_key") or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="API key is required.")
    _session_codex_api_key = key
    return JSONResponse(_codex_key_status())


@app.delete("/api/codex/key")
def clear_codex_key():
    global _session_codex_api_key
    _session_codex_api_key = ""
    return JSONResponse(_codex_key_status())


@app.post("/api/codex/explain")
async def explain_selection(request: Request):
    api_key, _source = _codex_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="Add a Codex API key first.")

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    text = " ".join(str(payload.get("text") or "").split())
    if not text:
        raise HTTPException(status_code=400, detail="Select text to explain.")
    if len(text) > 12000:
        raise HTTPException(status_code=413, detail="Select a shorter passage.")

    paper_title = str(payload.get("paper_title") or "").strip()
    section_title = str(payload.get("section_title") or "").strip()
    source_tag = str(payload.get("source_tag") or "").strip()

    prompt_parts = []
    if paper_title:
        prompt_parts.append(f"Paper or book: {paper_title}")
    if section_title:
        prompt_parts.append(f"Section: {section_title}")
    if source_tag:
        prompt_parts.append(f"Source: {source_tag}")
    prompt_parts.append("Highlighted passage:")
    prompt_parts.append(text)
    prompt_parts.append(
        "Explain this passage for an attentive academic reader. "
        "Be concise, define important terms, preserve equations, and call out "
        "the author's core move without inventing facts outside the passage."
    )

    body = {
        "model": CODEX_MODEL,
        "instructions": (
            "You are Codex, a precise academic reading companion. "
            "Explain highlighted text in plain language while respecting the "
            "source passage. Prefer short paragraphs or tight bullets."
        ),
        "input": "\n\n".join(prompt_parts),
        "max_output_tokens": 700,
    }

    try:
        import httpx
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach OpenAI: {exc}")

    if resp.status_code >= 400:
        status = resp.status_code if resp.status_code in (400, 401, 403, 429) else 502
        raise HTTPException(status_code=status, detail=_openai_error_detail(resp))

    try:
        data = resp.json()
    except Exception:
        raise HTTPException(status_code=502, detail="OpenAI returned an unreadable response.")

    explanation = _response_text(data)
    if not explanation:
        raise HTTPException(status_code=502, detail="OpenAI returned no explanation text.")
    return JSONResponse({"explanation": explanation, "model": CODEX_MODEL})


_UPLOAD_SLUG_RE = re.compile(r"[^a-zA-Z0-9._-]+")
_MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB
_SUPPORTED_UPLOADS = (".pdf", ".epub")


def _slug_for_upload(filename: str) -> str:
    base = os.path.splitext(os.path.basename(filename))[0]
    base = _UPLOAD_SLUG_RE.sub("_", base).strip("._-")
    return (base or "upload")[:80]


def _unique_folder(dest_root: str, slug: str) -> str:
    folder = f"{slug}_data"
    path = os.path.join(dest_root, folder)
    if not os.path.exists(path):
        return path
    i = 2
    while True:
        path = os.path.join(dest_root, f"{slug}-{i}_data")
        if not os.path.exists(path):
            return path
        i += 1


def _import_upload(tmp_path: str, out_dir: str, ext: str) -> Book:
    """Blocking import work. Runs in a threadpool, never on the event loop."""
    if ext == ".epub":
        from importers.epub import process_epub
        return process_epub(tmp_path, out_dir)
    from importers.pdf import process_pdf
    return process_pdf(tmp_path, out_dir)


@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)):
    """Accept a PDF or EPUB upload, import it, and add it to the library.
    Returns ``{book_id, title, url}`` on success."""
    name = file.filename or ""
    ext = os.path.splitext(name)[1].lower()
    if ext not in _SUPPORTED_UPLOADS:
        raise HTTPException(
            status_code=400,
            detail="Only PDF and EPUB files are supported.",
        )

    os.makedirs(BOOKS_DIR, exist_ok=True)

    tmp_dir = tempfile.mkdtemp(prefix="reader3_upload_")
    # Keep the original basename so importer title fallbacks (which use the
    # file's basename when the document has no embedded title) stay sensible.
    safe_basename = os.path.basename(name) or f"upload{ext}"
    safe_basename = _UPLOAD_SLUG_RE.sub("_", safe_basename)
    if not safe_basename.lower().endswith(ext):
        safe_basename += ext
    tmp_path = os.path.join(tmp_dir, safe_basename)
    try:
        with open(tmp_path, "wb") as out:
            total = 0
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
                    )
                out.write(chunk)

        slug = _slug_for_upload(name)
        out_dir = _unique_folder(BOOKS_DIR, slug)

        try:
            book = await run_in_threadpool(_import_upload, tmp_path, out_dir, ext)
            # Preserve the original filename for provenance/source_file display.
            book.source_file = os.path.basename(name)
            await run_in_threadpool(save_to_pickle, book, out_dir)
        except Exception as exc:
            if os.path.isdir(out_dir):
                shutil.rmtree(out_dir, ignore_errors=True)
            kind = "EPUB" if ext == ".epub" else "PDF"
            raise HTTPException(
                status_code=500, detail=f"Failed to process {kind}: {exc}"
            )

        book_id = os.path.basename(out_dir)
        url = f"/read/{book_id}"
        return JSONResponse({
            "book_id": book_id,
            "title": book.metadata.title,
            "url": url,
        })
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.delete("/api/{book_id}")
def delete_book(book_id: str):
    """Remove a book's ``*_data`` folder from the library."""
    path = _safe_book_dir(book_id)
    title = ""
    book = load_book_cached(os.path.basename(path))
    if book:
        title = book.metadata.title
    shutil.rmtree(path, ignore_errors=True)
    if os.path.isdir(path):
        raise HTTPException(status_code=500, detail="Could not delete the folder.")
    # The mtime-keyed cache can't know the file is gone; clear it.
    _load_cached.cache_clear()
    return JSONResponse({"book_id": os.path.basename(path), "title": title})


@app.get("/read/{book_id}/images/{image_name}")
def serve_image(book_id: str, image_name: str):
    safe_book_id = os.path.basename(book_id)
    safe_image_name = os.path.basename(image_name)
    img_path = os.path.join(BOOKS_DIR, safe_book_id, "images", safe_image_name)
    if not os.path.exists(img_path):
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(img_path)


@app.get("/favicon.ico")
def favicon():
    path = os.path.join(_STATIC_DIR, "favicon.svg")
    if os.path.exists(path):
        return FileResponse(path, media_type="image/svg+xml")
    raise HTTPException(status_code=404, detail="No favicon")


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("READER3_HOST", "127.0.0.1")
    print(f"Starting server at http://{host}:5000")
    uvicorn.run(app, host=host, port=5000)
