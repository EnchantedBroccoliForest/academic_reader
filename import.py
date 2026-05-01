"""Unified import CLI for reader3.

Usage:
    uv run import.py path/to/book.epub
    uv run import.py path/to/paper.pdf
    uv run import.py arxiv:1706.03762
    uv run import.py https://arxiv.org/abs/1706.03762
    uv run import.py https://example.com/paper.html

Options:
    --force     Re-process even if the destination already exists.
    --dest DIR  Write the book folder under DIR instead of the CWD.
"""

import argparse
import os
import sys
from urllib.parse import urlparse

from reader3 import save_to_pickle


def _slugify_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.netloc or "site").replace(":", "_")
    path = parsed.path.strip("/").replace("/", "_") or "index"
    base = f"{host}_{path}"
    base = "".join(c if (c.isalnum() or c in "._-") else "_" for c in base)
    return base[:80] or "page"


def _is_url(s: str) -> bool:
    return s.lower().startswith(("http://", "https://"))


def _is_arxiv_source(s: str) -> bool:
    if s.lower().startswith("arxiv:"):
        return True
    if "arxiv.org" in s.lower():
        return True
    return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Import a paper or book into reader3.")
    parser.add_argument("source", help="EPUB/PDF path, URL, or arxiv:ID")
    parser.add_argument(
        "--dest", default=".", help="Directory to write the book folder into (default: CWD)"
    )
    parser.add_argument(
        "--force", action="store_true", help="Re-process even if destination exists"
    )
    args = parser.parse_args(argv)

    source = args.source
    dest_root = os.path.abspath(args.dest)
    os.makedirs(dest_root, exist_ok=True)

    if _is_arxiv_source(source):
        from importers.arxiv import parse_arxiv_id, process_arxiv, slug_for_arxiv
        arxiv_id = parse_arxiv_id(source)
        if not arxiv_id:
            print(f"Could not parse an arXiv id from: {source}", file=sys.stderr)
            return 2
        out_dir = os.path.join(dest_root, slug_for_arxiv(arxiv_id))
        if os.path.exists(out_dir) and not args.force:
            print(f"Already exists: {out_dir}  (use --force to re-import)")
            return 0
        book = process_arxiv(arxiv_id, out_dir)

    elif _is_url(source):
        from importers.html import process_html
        out_dir = os.path.join(dest_root, _slugify_url(source) + "_data")
        if os.path.exists(out_dir) and not args.force:
            print(f"Already exists: {out_dir}  (use --force to re-import)")
            return 0
        book = process_html(source, out_dir)

    elif source.lower().endswith(".epub"):
        from importers.epub import process_epub
        if not os.path.exists(source):
            print(f"File not found: {source}", file=sys.stderr)
            return 2
        out_dir = os.path.join(
            dest_root, os.path.splitext(os.path.basename(source))[0] + "_data"
        )
        if os.path.exists(out_dir) and not args.force:
            print(f"Already exists: {out_dir}  (use --force to re-import)")
            return 0
        book = process_epub(source, out_dir)

    elif source.lower().endswith(".pdf"):
        from importers.pdf import process_pdf
        if not os.path.exists(source):
            print(f"File not found: {source}", file=sys.stderr)
            return 2
        out_dir = os.path.join(
            dest_root, os.path.splitext(os.path.basename(source))[0] + "_data"
        )
        if os.path.exists(out_dir) and not args.force:
            print(f"Already exists: {out_dir}  (use --force to re-import)")
            return 0
        book = process_pdf(source, out_dir)

    else:
        print(
            f"Unrecognized source: {source}\n"
            "Supported: *.epub, *.pdf, http(s)://..., arxiv:ID, or arxiv.org URLs.",
            file=sys.stderr,
        )
        return 2

    save_to_pickle(book, out_dir)
    print("\n--- Summary ---")
    print(f"Title:    {book.metadata.title}")
    if book.metadata.authors:
        print(f"Authors:  {', '.join(book.metadata.authors)}")
    if book.metadata.arxiv_id:
        print(f"arXiv:    {book.metadata.arxiv_id}")
    print(f"Sections: {len(book.sections)}")
    print(f"Folder:   {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
