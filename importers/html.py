"""HTML URL importer.

Fetches a URL, runs it through ``readability-lxml`` to strip nav/ads,
then through the shared ``clean_html_content`` cleaner before splitting
into sections.
"""

import os
import shutil
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from readability import Document

from reader3 import (
    Book,
    BookMetadata,
    clean_html_content,
    split_inputs_into_sections,
)


_USER_AGENT = "reader3/0.2 (+https://github.com/karpathy/reader3)"


def fetch_html(url: str, timeout: float = 30.0) -> str:
    headers = {"User-Agent": _USER_AGENT, "Accept": "text/html,*/*"}
    resp = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def extract_main_content(raw_html: str) -> tuple[str, str]:
    """Returns (title, cleaned_html)."""
    doc = Document(raw_html)
    title = (doc.title() or "Untitled").strip()
    article_html = doc.summary(html_partial=True)
    soup = BeautifulSoup(article_html, "html.parser")
    soup = clean_html_content(soup)
    return title, str(soup)


def process_html(
    url: str,
    output_dir: str,
    *,
    raw_html: Optional[str] = None,
    metadata_override: Optional[BookMetadata] = None,
    cache_source: bool = True,
) -> Book:
    if raw_html is None:
        print(f"Fetching {url}...")
        raw_html = fetch_html(url)

    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(os.path.join(output_dir, "images"), exist_ok=True)

    title, cleaned = extract_main_content(raw_html)

    if cache_source:
        with open(os.path.join(output_dir, "source.html"), "w", encoding="utf-8") as f:
            f.write(raw_html)

    metadata = metadata_override or BookMetadata(
        title=title,
        language="en",
        identifiers=[url],
    )

    source_label = urlparse(url).netloc or "html"
    sections, toc = split_inputs_into_sections(
        [(source_label, metadata.title, cleaned)]
    )

    return Book(
        metadata=metadata,
        sections=sections,
        toc=toc,
        images={},
        source_file=url,
        processed_at=datetime.now().isoformat(),
        version="4.0",
    )
