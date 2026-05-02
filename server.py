import os
import re
import tempfile
from functools import lru_cache
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from reader3 import (
    Book,
    BookMetadata,
    ChapterContent,  # re-export so old pickles unpickle
    Section,
    TOCEntry,
    load_book,
    save_to_pickle,
)

_HERE = os.path.dirname(os.path.abspath(__file__))

app = FastAPI()
templates = Jinja2Templates(directory=os.path.join(_HERE, "templates"))

# Mount static assets (CSS/JS extracted from inline <style>/<script>).
_STATIC_DIR = os.path.join(_HERE, "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

BOOKS_DIR = os.environ.get("READER3_LIBRARY", ".")


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


@app.get("/", response_class=HTMLResponse)
async def library_view(request: Request):
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
            })
    return templates.TemplateResponse(
        request, "library.html", {"books": books}
    )


@app.get("/read/{book_id}", response_class=HTMLResponse)
async def read_book_root(request: Request, book_id: str):
    book = load_book_cached(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    if not book.sections:
        raise HTTPException(status_code=404, detail="Book has no readable sections")
    return await _render_section(request, book, book_id, 0)


@app.get("/read/{book_id}/{section_ref}", response_class=HTMLResponse)
async def read_section(request: Request, book_id: str, section_ref: str):
    """``section_ref`` is a Section.id; back-compat: an integer is treated as
    a linear index into ``book.sections``."""
    book = load_book_cached(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    if not book.sections:
        raise HTTPException(status_code=404, detail="Book has no readable sections")

    if section_ref.isdigit():
        idx = int(section_ref)
        if 0 <= idx < len(book.sections):
            return RedirectResponse(
                url=f"/read/{book_id}/{book.sections[idx].id}", status_code=302
            )
        raise HTTPException(status_code=404, detail="Section not found")

    idx = _section_index(book, section_ref)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"Unknown section: {section_ref}")
    return await _render_section(request, book, book_id, idx)


async def _render_section(request: Request, book: Book, book_id: str, idx: int):
    section = book.sections[idx]
    prev_id = book.sections[idx - 1].id if idx > 0 else None
    next_id = book.sections[idx + 1].id if idx + 1 < len(book.sections) else None

    if book.metadata.arxiv_id:
        source_tag = f"arXiv:{book.metadata.arxiv_id}"
    elif book.source_file:
        source_tag = book.source_file
    else:
        source_tag = ""

    return templates.TemplateResponse(
        request,
        "reader.html",
        {
            "book": book,
            "book_id": book_id,
            "section": section,
            "section_idx": idx,
            "section_count": len(book.sections),
            "prev_id": prev_id,
            "next_id": next_id,
            "source_tag": source_tag,
        },
    )


@app.get("/api/{book_id}/markdown", response_class=PlainTextResponse)
async def book_markdown(book_id: str):
    """Whole paper as markdown with provenance header. Used by hotkey ``C``."""
    book = load_book_cached(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    try:
        from markdownify import markdownify as _md
    except ImportError:  # pragma: no cover
        from reader3 import extract_plain_text
        def _md(html, **_):
            return extract_plain_text(html)

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
        parts.append("\n" + "#" * min(sec.level, 6) + " " + sec.title + "\n")
        try:
            md = _md(sec.html, heading_style="ATX")
        except Exception:
            md = sec.text
        parts.append(md.strip() + "\n")

    return "\n".join(parts)


_UPLOAD_SLUG_RE = re.compile(r"[^a-zA-Z0-9._-]+")
_MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB


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


@app.post("/api/upload")
async def upload_pdf(file: UploadFile = File(...)):
    """Accept a PDF upload, run it through the PDF importer, and add it to
    the library. Returns ``{book_id, title, url}`` on success."""
    name = file.filename or ""
    if not name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    os.makedirs(BOOKS_DIR, exist_ok=True)

    tmp_dir = tempfile.mkdtemp(prefix="reader3_upload_")
    # Keep the original basename so the PDF importer's title fallback (which
    # uses the file's basename when the PDF has no embedded title) is sensible.
    safe_basename = os.path.basename(name) or "upload.pdf"
    safe_basename = _UPLOAD_SLUG_RE.sub("_", safe_basename)
    if not safe_basename.lower().endswith(".pdf"):
        safe_basename += ".pdf"
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

        from importers.pdf import process_pdf
        try:
            book = process_pdf(tmp_path, out_dir)
        except Exception as exc:
            if os.path.isdir(out_dir):
                import shutil
                shutil.rmtree(out_dir, ignore_errors=True)
            raise HTTPException(status_code=500, detail=f"Failed to process PDF: {exc}")

        # Preserve the original filename for provenance/source_file display.
        book.source_file = os.path.basename(name)
        save_to_pickle(book, out_dir)

        book_id = os.path.basename(out_dir)
        first_id = book.sections[0].id if book.sections else ""
        url = f"/read/{book_id}/{first_id}" if first_id else f"/read/{book_id}"
        return JSONResponse({
            "book_id": book_id,
            "title": book.metadata.title,
            "url": url,
        })
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.get("/read/{book_id}/images/{image_name}")
async def serve_image(book_id: str, image_name: str):
    safe_book_id = os.path.basename(book_id)
    safe_image_name = os.path.basename(image_name)
    img_path = os.path.join(BOOKS_DIR, safe_book_id, "images", safe_image_name)
    if not os.path.exists(img_path):
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(img_path)


if __name__ == "__main__":
    import uvicorn
    print("Starting server at http://0.0.0.0:5000")
    uvicorn.run(app, host="0.0.0.0", port=5000)
