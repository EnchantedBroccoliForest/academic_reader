"""EPUB importer.

Walks the EPUB spine, extracts images to ``{output_dir}/images/``, cleans
each document, then runs the section splitter to produce
heading-derived sections and TOC.
"""

import os
import shutil
from datetime import datetime
from typing import List, Tuple
from urllib.parse import unquote

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

from reader3 import (
    Book,
    BookMetadata,
    clean_html_content,
    split_inputs_into_sections,
)


def _extract_metadata(book_obj) -> BookMetadata:
    def get_list(key):
        data = book_obj.get_metadata("DC", key)
        return [x[0] for x in data] if data else []

    def get_one(key):
        data = book_obj.get_metadata("DC", key)
        return data[0][0] if data else None

    return BookMetadata(
        title=get_one("title") or "Untitled",
        language=get_one("language") or "en",
        authors=get_list("creator"),
        description=get_one("description"),
        publisher=get_one("publisher"),
        date=get_one("date"),
        identifiers=get_list("identifier"),
        subjects=get_list("subject"),
    )


def _extract_images(book_obj, images_dir: str) -> dict:
    image_map: dict = {}
    for item in book_obj.get_items():
        if item.get_type() != ebooklib.ITEM_IMAGE:
            continue
        original_fname = os.path.basename(item.get_name())
        safe_fname = "".join(
            c for c in original_fname if c.isalnum() or c in "._-"
        ).strip() or "image"
        local_path = os.path.join(images_dir, safe_fname)
        with open(local_path, "wb") as f:
            f.write(item.get_content())
        rel_path = f"images/{safe_fname}"
        image_map[item.get_name()] = rel_path
        image_map[original_fname] = rel_path
    return image_map


def _natural_title(href: str) -> str:
    name = os.path.basename(href)
    for suffix in (".xhtml", ".html", ".htm"):
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name.replace("_", " ").replace("-", " ").strip().title() or "Section"


def process_epub(epub_path: str, output_dir: str) -> Book:
    print(f"Loading {epub_path}...")
    book_obj = epub.read_epub(epub_path)
    metadata = _extract_metadata(book_obj)

    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    images_dir = os.path.join(output_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    print("Extracting images...")
    image_map = _extract_images(book_obj, images_dir)

    print("Processing spine...")
    raw_inputs: List[Tuple[str, str, str]] = []
    for spine_item in book_obj.spine:
        item_id, _linear = spine_item
        item = book_obj.get_item_with_id(item_id)
        if not item or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue

        raw_content = item.get_content().decode("utf-8", errors="ignore")
        soup = BeautifulSoup(raw_content, "html.parser")

        for img in soup.find_all("img"):
            src = img.get("src", "")
            if not src:
                continue
            src_decoded = unquote(src)
            filename = os.path.basename(src_decoded)
            if src_decoded in image_map:
                img["src"] = image_map[src_decoded]
            elif filename in image_map:
                img["src"] = image_map[filename]

        soup = clean_html_content(soup)

        body = soup.find("body")
        final_html = (
            "".join(str(x) for x in body.contents) if body else str(soup)
        )

        href = item.get_name()
        raw_inputs.append((href, _natural_title(href), final_html))

    sections, toc = split_inputs_into_sections(raw_inputs)

    return Book(
        metadata=metadata,
        sections=sections,
        toc=toc,
        images=image_map,
        source_file=os.path.basename(epub_path),
        processed_at=datetime.now().isoformat(),
        version="4.0",
    )
