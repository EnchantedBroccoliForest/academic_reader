"""
Core data model and section-splitting utilities for reader3.

Importers (EPUB, PDF, HTML, arXiv) live in the ``importers/`` package and
return a fully-assembled :class:`Book`. The ``import.py`` CLI dispatches
to the right importer based on the source.

For backward compatibility, ``uv run reader3.py <file.epub>`` still works
and delegates to ``importers.epub.process_epub``.
"""

import os
import pickle
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup, Comment


# ---------------------------------------------------------------------------
# Data model (v4.0)
# ---------------------------------------------------------------------------


@dataclass
class Section:
    """A logical section of a document, split at H1/H2/H3 boundaries."""
    id: str
    level: int
    title: str
    parent_id: Optional[str]
    html: str
    text: str
    order: int
    source_file: str = ""


@dataclass
class TOCEntry:
    """Heading-derived TOC entry."""
    title: str
    section_id: str = ""
    level: int = 1
    children: List["TOCEntry"] = field(default_factory=list)
    # Vestigial back-compat fields so v3 pickles still unpickle cleanly.
    href: str = ""
    file_href: str = ""
    anchor: str = ""


@dataclass
class Reference:
    id: str
    text: str
    arxiv_id: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None


@dataclass
class Figure:
    id: str
    number: str
    caption: str
    src: Optional[str]
    section_id: str


@dataclass
class BookMetadata:
    title: str
    language: str = "en"
    authors: List[str] = field(default_factory=list)
    description: Optional[str] = None
    publisher: Optional[str] = None
    date: Optional[str] = None
    identifiers: List[str] = field(default_factory=list)
    subjects: List[str] = field(default_factory=list)
    arxiv_id: Optional[str] = None
    doi: Optional[str] = None
    abstract: Optional[str] = None


@dataclass
class ChapterContent:
    """Vestigial; kept so v3.0 pickles continue to unpickle."""
    id: str = ""
    href: str = ""
    title: str = ""
    content: str = ""
    text: str = ""
    order: int = 0


@dataclass
class Book:
    metadata: BookMetadata
    sections: List[Section] = field(default_factory=list)
    toc: List[TOCEntry] = field(default_factory=list)
    images: Dict[str, str] = field(default_factory=dict)
    references: Dict[str, Reference] = field(default_factory=dict)
    figures: List[Figure] = field(default_factory=list)
    tables: List[Figure] = field(default_factory=list)
    source_file: str = ""
    processed_at: str = ""
    version: str = "4.0"

    def __getattr__(self, name):
        # ``book.spine`` keeps working for any caller that hasn't migrated.
        # __getattr__ runs only when normal lookup misses.
        if name == "spine":
            return self.__dict__.get("sections", [])
        raise AttributeError(name)


# ---------------------------------------------------------------------------
# HTML utilities (shared across importers)
# ---------------------------------------------------------------------------


def clean_html_content(soup: BeautifulSoup) -> BeautifulSoup:
    """Strip dangerous/useless tags. Leaves <math> intact for KaTeX/MathML."""
    for tag in soup(['script', 'style', 'iframe', 'video', 'nav', 'form', 'button']):
        tag.decompose()
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    for tag in soup.find_all('input'):
        tag.decompose()
    return soup


def extract_plain_text(soup_or_html) -> str:
    if isinstance(soup_or_html, str):
        soup = BeautifulSoup(soup_or_html, 'html.parser')
    else:
        soup = soup_or_html
    text = soup.get_text(separator=' ')
    return ' '.join(text.split())


# ---------------------------------------------------------------------------
# Section splitter
# ---------------------------------------------------------------------------


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = 60) -> str:
    s = _SLUG_RE.sub("-", (text or "").lower()).strip("-")
    if len(s) > max_len:
        s = s[:max_len].rstrip("-")
    return s or "section"


def _make_unique_id(title: str, used: set) -> str:
    base = slugify(title)
    sid = base
    i = 2
    while sid in used:
        sid = f"{base}-{i}"
        i += 1
    used.add(sid)
    return sid


def split_html_into_sections(
    html: str,
    source_file: str,
    fallback_title: str,
    start_order: int,
    used_ids: set,
) -> List[Section]:
    """Split one HTML document into Sections at every h1/h2/h3.

    The heading element is given an ``id`` attribute matching the resulting
    Section.id so anchor links and #fragment scrolling work after pages are
    rendered individually.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    body = soup.find("body") or soup

    # Unwrap single-child wrappers (<article>, <div>, <main>, ...) so headings
    # become direct children of the iteration root. Stop as soon as the root
    # has either headings as direct children or multiple element children.
    def _has_top_level_heading(node) -> bool:
        for c in getattr(node, "children", []):
            if getattr(c, "name", None) in ("h1", "h2", "h3"):
                return True
        return False

    while True:
        element_kids = [c for c in body.children if getattr(c, "name", None)]
        if _has_top_level_heading(body):
            break
        if len(element_kids) == 1 and element_kids[0].name in (
            "article", "main", "section", "div", "body"
        ):
            body = element_kids[0]
            continue
        break

    sections: List[Section] = []
    parent_stack: List[Tuple[int, str]] = []
    current_title = fallback_title
    current_level = 1
    current_id: Optional[str] = None
    current_buffer: List[Any] = []
    has_seen_heading = False

    def flush():
        nonlocal current_id
        html_parts = [str(elem) for elem in current_buffer]
        section_html = "".join(html_parts).strip()
        if not section_html:
            return
        sid = current_id or _make_unique_id(current_title, used_ids)
        parent_id = None
        for lvl, pid in reversed(parent_stack):
            if lvl < current_level:
                parent_id = pid
                break
        plain = extract_plain_text(BeautifulSoup(section_html, "html.parser"))
        sec = Section(
            id=sid,
            level=current_level,
            title=current_title,
            parent_id=parent_id,
            html=section_html,
            text=plain,
            order=start_order + len(sections),
            source_file=source_file,
        )
        sections.append(sec)
        while parent_stack and parent_stack[-1][0] >= current_level:
            parent_stack.pop()
        parent_stack.append((current_level, sid))

    for child in list(body.children):
        if getattr(child, "name", None) in ("h1", "h2", "h3"):
            if has_seen_heading or current_buffer:
                flush()
            heading_text = child.get_text(strip=True) or fallback_title
            current_title = heading_text
            current_level = int(child.name[1])
            current_id = _make_unique_id(heading_text, used_ids)
            child["id"] = current_id
            current_buffer = [child]
            has_seen_heading = True
        else:
            current_buffer.append(child)

    flush()

    # No headings at all: emit the whole document as a single section.
    if not sections and (html or "").strip():
        sid = _make_unique_id(fallback_title, used_ids)
        plain = extract_plain_text(soup)
        sections.append(
            Section(
                id=sid,
                level=1,
                title=fallback_title,
                parent_id=None,
                html=("".join(str(c) for c in body.contents) if hasattr(body, "contents") else str(body)),
                text=plain,
                order=start_order,
                source_file=source_file,
            )
        )

    return sections


def build_toc_from_sections(sections: List[Section]) -> List[TOCEntry]:
    root: List[TOCEntry] = []
    stack: List[Tuple[int, TOCEntry]] = []
    for sec in sections:
        entry = TOCEntry(title=sec.title, section_id=sec.id, level=sec.level)
        while stack and stack[-1][0] >= sec.level:
            stack.pop()
        if stack:
            stack[-1][1].children.append(entry)
        else:
            root.append(entry)
        stack.append((sec.level, entry))
    return root


def split_inputs_into_sections(
    raw_inputs: List[Tuple[str, str, str]],
) -> Tuple[List[Section], List[TOCEntry]]:
    """``raw_inputs``: list of (source_file, fallback_title, html) tuples."""
    used: set = set()
    all_sections: List[Section] = []
    for source_file, fallback_title, html in raw_inputs:
        chunk = split_html_into_sections(
            html=html,
            source_file=source_file,
            fallback_title=(fallback_title
                            or (os.path.basename(source_file) if source_file else "Section")),
            start_order=len(all_sections),
            used_ids=used,
        )
        all_sections.extend(chunk)
    # Reassign linear order to be safe.
    for i, sec in enumerate(all_sections):
        sec.order = i
    toc = build_toc_from_sections(all_sections)
    return all_sections, toc


# ---------------------------------------------------------------------------
# Migration from v3 (chapter-based) pickles
# ---------------------------------------------------------------------------


def migrate_book(book) -> "Book":
    version = getattr(book, "version", "") or ""
    has_sections = "sections" in getattr(book, "__dict__", {})
    if has_sections and version.startswith("4."):
        return book

    old_spine = getattr(book, "__dict__", {}).get("spine") or []
    raw: List[Tuple[str, str, str]] = []
    for ch in old_spine:
        title = (getattr(ch, "title", "")
                 or os.path.basename(getattr(ch, "href", ""))
                 or "Section")
        raw.append((getattr(ch, "href", ""), title, getattr(ch, "content", "") or ""))
    sections, toc = split_inputs_into_sections(raw) if raw else ([], [])

    metadata = getattr(book, "metadata", None)
    if metadata is None:
        metadata = BookMetadata(title="Untitled")

    new_book = Book(
        metadata=metadata,
        sections=sections,
        toc=toc,
        images=getattr(book, "__dict__", {}).get("images") or {},
        source_file=getattr(book, "__dict__", {}).get("source_file", ""),
        processed_at=getattr(book, "__dict__", {}).get("processed_at", ""),
        references=getattr(book, "__dict__", {}).get("references") or {},
        figures=getattr(book, "__dict__", {}).get("figures") or [],
        tables=getattr(book, "__dict__", {}).get("tables") or [],
        version="4.0",
    )
    return new_book


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def save_to_pickle(book: Book, output_dir: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    p_path = os.path.join(output_dir, "book.pkl")
    with open(p_path, "wb") as f:
        pickle.dump(book, f)
    print(f"Saved structured data to {p_path}")
    return p_path


def load_book(folder_name: str) -> Optional[Book]:
    file_path = os.path.join(folder_name, "book.pkl")
    if not os.path.exists(file_path):
        return None
    try:
        with open(file_path, "rb") as f:
            book = pickle.load(f)
        return migrate_book(book)
    except Exception as e:
        print(f"Error loading book {folder_name}: {e}")
        return None


# ---------------------------------------------------------------------------
# CLI: EPUB pass-through (kept for back-compat)
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run reader3.py <file.epub>")
        print("       (for PDFs/arXiv/URLs use: uv run import.py <source>)")
        sys.exit(1)

    from importers.epub import process_epub  # local import keeps reader3.py importable without ebooklib

    epub_file = sys.argv[1]
    assert os.path.exists(epub_file), "File not found."
    out_dir = os.path.splitext(epub_file)[0] + "_data"

    book_obj = process_epub(epub_file, out_dir)
    save_to_pickle(book_obj, out_dir)
    print("\n--- Summary ---")
    print(f"Title: {book_obj.metadata.title}")
    print(f"Authors: {', '.join(book_obj.metadata.authors)}")
    print(f"Sections: {len(book_obj.sections)}")
    print(f"TOC Root Items: {len(book_obj.toc)}")
    print(f"Images extracted: {len(book_obj.images)}")
