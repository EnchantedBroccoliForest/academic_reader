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


def test_clean_html_strips_event_handlers_and_bad_schemes():
    """Section HTML is rendered with ``| safe``; this is the only guard."""
    from bs4 import BeautifulSoup
    from reader3 import clean_html_content

    raw = """<div>
      <a href="javascript:alert(1)">click</a>
      <a href="https://example.com">ok</a>
      <img src="x" onerror="alert(1)">
      <img src="images/fig1.png">
      <p onmouseover="alert(2)">hover</p>
      <svg onload="alert(3)"></svg>
      <object data="evil"></object><embed src="evil">
      <script>alert(4)</script>
      <math><mi>x</mi></math>
    </div>"""
    out = str(clean_html_content(BeautifulSoup(raw, "html.parser")))

    assert "onerror" not in out
    assert "onmouseover" not in out
    assert "onload" not in out
    assert "javascript:" not in out
    assert "<script" not in out
    assert "<svg" not in out
    assert "<object" not in out
    assert "<embed" not in out
    # ...without eating legitimate content.
    assert 'href="https://example.com"' in out
    assert 'src="images/fig1.png"' in out
    assert "<math>" in out


def test_clean_html_allows_image_data_urls_but_not_html_ones():
    from bs4 import BeautifulSoup
    from reader3 import clean_html_content

    raw = ('<div><img src="data:image/png;base64,AAAA">'
           '<a href="data:text/html,<h1>x</h1>">bad</a></div>')
    out = str(clean_html_content(BeautifulSoup(raw, "html.parser")))
    assert "data:image/png" in out
    assert "data:text/html" not in out


def test_pdf_importer_sanitizes_raw_html_in_the_text_layer():
    """python-markdown passes raw HTML through; the importer must not."""
    from importers.pdf import _markdown_to_html

    html = _markdown_to_html(
        'Body text\n\n<img src=x onerror="alert(1)">\n\n<script>alert(2)</script>\n'
    )
    assert "Body text" in html
    assert "onerror" not in html
    assert "<script" not in html
