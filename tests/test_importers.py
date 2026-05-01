"""Lightweight tests for importer helpers that don't require network."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_arxiv_id_parsing():
    from importers.arxiv import parse_arxiv_id

    cases = {
        "arxiv:1706.03762": "1706.03762",
        "arXiv:1706.03762v3": "1706.03762v3",
        "https://arxiv.org/abs/1706.03762": "1706.03762",
        "https://arxiv.org/pdf/1706.03762": "1706.03762",
        "https://arxiv.org/abs/1706.03762v5": "1706.03762v5",
        "1706.03762": "1706.03762",
        "arxiv:cs/0601001": "cs/0601001",
    }
    for src, expected in cases.items():
        assert parse_arxiv_id(src) == expected, f"failed for {src}"

    assert parse_arxiv_id("not-an-arxiv-thing") is None
    assert parse_arxiv_id("") is None


def test_html_extract_main_content_basic():
    from importers.html import extract_main_content

    raw = """
    <html><head><title>Some Paper</title></head>
    <body>
      <nav>nav junk</nav>
      <article>
        <h1>The Paper</h1>
        <p>This is the body paragraph one.</p>
        <p>This is the body paragraph two.</p>
      </article>
      <footer>footer junk</footer>
    </body></html>
    """
    title, html = extract_main_content(raw)
    assert title  # readability picks up something
    assert "body paragraph one" in html
    assert "footer junk" not in html
