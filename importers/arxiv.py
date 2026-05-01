"""arXiv importer.

Resolves an arXiv id (or arxiv.org URL), fetches metadata from the public
API, then prefers the ar5iv HTML rendering (cleanest math + structure).
Falls back to the PDF when ar5iv isn't available.
"""

import os
import re
import shutil
from datetime import datetime
from typing import Optional
from xml.etree import ElementTree as ET

import httpx

from reader3 import Book, BookMetadata


_ARXIV_ID_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf|html)/|arxiv:)\s*(?P<id>\d{4}\.\d{4,5}(?:v\d+)?|[a-z\-]+/\d{7}(?:v\d+)?)",
    re.IGNORECASE,
)
_BARE_ID_RE = re.compile(
    r"^\s*(?P<id>\d{4}\.\d{4,5}(?:v\d+)?|[a-z\-]+/\d{7}(?:v\d+)?)\s*$",
    re.IGNORECASE,
)
_USER_AGENT = "reader3/0.2 (+https://github.com/karpathy/reader3)"


def parse_arxiv_id(source: str) -> Optional[str]:
    """Extract a canonical arXiv id from a URL, ``arxiv:NNNN.MMMMM`` form,
    or a bare id."""
    if not source:
        return None
    m = _ARXIV_ID_RE.search(source)
    if m:
        return m.group("id")
    m = _BARE_ID_RE.match(source)
    if m:
        return m.group("id")
    return None


def fetch_arxiv_metadata(arxiv_id: str) -> BookMetadata:
    url = f"https://export.arxiv.org/api/query?id_list={arxiv_id}"
    resp = httpx.get(url, headers={"User-Agent": _USER_AGENT}, timeout=30.0)
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
    ns = {"a": "http://www.w3.org/2005/Atom",
          "arxiv": "http://arxiv.org/schemas/atom"}

    entry = root.find("a:entry", ns)
    if entry is None:
        return BookMetadata(title=f"arXiv:{arxiv_id}", arxiv_id=arxiv_id)

    title = (entry.findtext("a:title", default="", namespaces=ns) or "").strip()
    title = re.sub(r"\s+", " ", title) or f"arXiv:{arxiv_id}"
    abstract = (entry.findtext("a:summary", default="", namespaces=ns) or "").strip()
    abstract = re.sub(r"\s+", " ", abstract) or None
    published = (entry.findtext("a:published", default="", namespaces=ns) or "").strip() or None

    authors = []
    for a in entry.findall("a:author", ns):
        name = (a.findtext("a:name", default="", namespaces=ns) or "").strip()
        if name:
            authors.append(name)

    doi = None
    doi_el = entry.find("arxiv:doi", ns)
    if doi_el is not None and doi_el.text:
        doi = doi_el.text.strip()

    subjects = []
    for cat in entry.findall("a:category", ns):
        term = cat.attrib.get("term")
        if term:
            subjects.append(term)

    return BookMetadata(
        title=title,
        language="en",
        authors=authors,
        description=abstract,
        date=published,
        identifiers=[f"arXiv:{arxiv_id}"],
        subjects=subjects,
        arxiv_id=arxiv_id,
        doi=doi,
        abstract=abstract,
    )


def _try_fetch_ar5iv(arxiv_id: str, timeout: float = 30.0) -> Optional[str]:
    """ar5iv serves the LaTeX-rendered HTML; far cleaner than PDF text
    extraction. Returns None on any failure."""
    url = f"https://ar5iv.labs.arxiv.org/html/{arxiv_id}"
    try:
        resp = httpx.get(
            url,
            headers={"User-Agent": _USER_AGENT, "Accept": "text/html"},
            timeout=timeout,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return None
        body = resp.text
        # ar5iv returns a 200 page with an apologetic body when conversion fails.
        if "Sorry, ar5iv could not convert" in body or "Document could not be converted" in body:
            return None
        return body
    except (httpx.HTTPError, httpx.TimeoutException):
        return None


def _download_pdf(arxiv_id: str, dest: str, timeout: float = 60.0) -> bool:
    url = f"https://arxiv.org/pdf/{arxiv_id}"
    try:
        with httpx.stream(
            "GET",
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=timeout,
            follow_redirects=True,
        ) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=64 * 1024):
                    f.write(chunk)
        return True
    except httpx.HTTPError:
        return False


def process_arxiv(arxiv_id: str, output_dir: str) -> Book:
    """Try ar5iv HTML first, fall back to PDF."""
    print(f"Fetching arXiv metadata for {arxiv_id}...")
    metadata = fetch_arxiv_metadata(arxiv_id)

    print(f"Trying ar5iv HTML rendering for {arxiv_id}...")
    raw_html = _try_fetch_ar5iv(arxiv_id)
    if raw_html:
        print("  ar5iv hit; importing as HTML.")
        from importers.html import process_html
        return process_html(
            url=f"https://ar5iv.labs.arxiv.org/html/{arxiv_id}",
            output_dir=output_dir,
            raw_html=raw_html,
            metadata_override=metadata,
        )

    print("  ar5iv unavailable; falling back to PDF.")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = os.path.join(tmp, f"{arxiv_id.replace('/', '_')}.pdf")
        if not _download_pdf(arxiv_id, pdf_path):
            raise RuntimeError(f"Failed to download arXiv PDF for {arxiv_id}")
        from importers.pdf import process_pdf
        book = process_pdf(
            pdf_path=pdf_path,
            output_dir=output_dir,
            metadata_override=metadata,
            cache_source=True,
        )
    book.source_file = f"arXiv:{arxiv_id}"
    return book


def slug_for_arxiv(arxiv_id: str) -> str:
    return "arxiv_" + arxiv_id.replace("/", "_") + "_data"
