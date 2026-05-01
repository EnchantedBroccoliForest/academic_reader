"""PDF importer.

Uses ``pymupdf4llm`` to extract markdown-with-structure from a PDF, then
converts the markdown to HTML and runs the section splitter. The original
PDF is cached to ``{output_dir}/source.pdf`` and the raw markdown to
``{output_dir}/source.md`` for debugging.
"""

import os
import shutil
from datetime import datetime
from typing import Optional

import markdown as md_lib

from reader3 import (
    Book,
    BookMetadata,
    split_inputs_into_sections,
)


def _markdown_to_html(text: str) -> str:
    return md_lib.markdown(
        text,
        extensions=["extra", "tables", "footnotes", "sane_lists"],
        output_format="html5",
    )


def _extract_pdf_metadata(pdf_path: str) -> BookMetadata:
    try:
        import pymupdf  # type: ignore
        doc = pymupdf.open(pdf_path)
        meta = doc.metadata or {}
        title = (meta.get("title") or "").strip() or os.path.splitext(
            os.path.basename(pdf_path)
        )[0]
        author = (meta.get("author") or "").strip()
        authors = [a.strip() for a in author.split(",") if a.strip()] if author else []
        date = (meta.get("creationDate") or "").strip() or None
        return BookMetadata(
            title=title,
            language="en",
            authors=authors,
            date=date,
        )
    except Exception:
        return BookMetadata(
            title=os.path.splitext(os.path.basename(pdf_path))[0],
            language="en",
        )


def process_pdf(
    pdf_path: str,
    output_dir: str,
    *,
    metadata_override: Optional[BookMetadata] = None,
    cache_source: bool = True,
) -> Book:
    """Convert a PDF into a section-split Book.

    ``metadata_override`` lets the arXiv importer inject clean metadata
    (title, authors, abstract) that's better than what's embedded in the
    PDF itself.
    """
    import pymupdf4llm  # local import: pymupdf4llm is heavy at import time

    print(f"Extracting markdown from {pdf_path}...")
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(os.path.join(output_dir, "images"), exist_ok=True)

    md_text = pymupdf4llm.to_markdown(pdf_path)

    if cache_source:
        try:
            shutil.copy2(pdf_path, os.path.join(output_dir, "source.pdf"))
        except (OSError, shutil.SameFileError):
            pass
        with open(os.path.join(output_dir, "source.md"), "w", encoding="utf-8") as f:
            f.write(md_text)

    print("Converting markdown to HTML...")
    html = _markdown_to_html(md_text)

    metadata = metadata_override or _extract_pdf_metadata(pdf_path)

    sections, toc = split_inputs_into_sections(
        [("source.md", metadata.title, html)]
    )

    return Book(
        metadata=metadata,
        sections=sections,
        toc=toc,
        images={},
        source_file=os.path.basename(pdf_path),
        processed_at=datetime.now().isoformat(),
        version="4.0",
    )
