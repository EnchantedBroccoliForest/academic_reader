"""Regression tests for the server-side fixes.

Each test here pins a bug that was found by driving the running app; they
exist so the same defect can't come back silently.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

from reader3 import (
    Book,
    BookMetadata,
    save_to_pickle,
    split_inputs_into_sections,
)

PAPER_HTML = """
<h1>Attention Is All You Need</h1>
<p>Display math: $$\\sum_{i=1}^n x_i$$ and inline $a_b$.</p>
<h2>Background</h2>
<p>Some background.</p>
<h3>Self-Attention</h3>
<p>Details.</p>
"""


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A server bound to a throwaway library containing one paper."""
    sections, toc = split_inputs_into_sections(
        [("paper.html", "Attention Is All You Need", PAPER_HTML)]
    )
    book = Book(
        metadata=BookMetadata(
            title="Attention Is All You Need",
            authors=["Ashish Vaswani"],
            abstract="We propose the Transformer.",
        ),
        sections=sections,
        toc=toc,
        source_file="paper.html",
        processed_at="2026-08-19T00:00:00",
        version="4.0",
    )
    save_to_pickle(book, str(tmp_path / "paper_data"))

    monkeypatch.setenv("READER3_LIBRARY", str(tmp_path))
    for mod in ("server",):
        sys.modules.pop(mod, None)
    import server as server_mod
    server_mod.BOOKS_DIR = str(tmp_path)
    server_mod._load_cached.cache_clear()
    return TestClient(server_mod.app)


# --- C1 -------------------------------------------------------------------

def test_whole_paper_markdown_does_not_duplicate_headings(client):
    """The heading lives inside section.html; the server must not add another."""
    md = client.get("/api/paper_data/markdown").text
    headings = [ln.strip() for ln in md.splitlines() if ln.startswith("#")]
    assert headings.count("# Attention Is All You Need") == 1
    assert headings.count("## Background") == 1
    assert headings.count("### Self-Attention") == 1


def test_whole_paper_markdown_keeps_section_bodies(client):
    md = client.get("/api/paper_data/markdown").text
    assert "Some background." in md
    assert "Details." in md
    assert "## Abstract" in md


# --- H3 -------------------------------------------------------------------

def test_whole_paper_markdown_does_not_escape_latex(client):
    """markdownify escapes _ and *, which turns valid TeX into invalid TeX."""
    md = client.get("/api/paper_data/markdown").text
    assert "\\_" not in md
    assert "\\sum_{i=1}^n x_i" in md


# --- C4 -------------------------------------------------------------------

def test_book_root_redirects_to_first_section(client):
    """Rendering here would break relative images/... paths."""
    resp = client.get("/read/paper_data", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/read/paper_data/attention-is-all-you-need"


def test_integer_section_ref_still_redirects(client):
    resp = client.get("/read/paper_data/1", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/read/paper_data/background"


# --- F4 -------------------------------------------------------------------

def test_abstract_renders_on_first_section_only(client):
    first = client.get("/read/paper_data/attention-is-all-you-need").text
    assert "We propose the Transformer." in first
    later = client.get("/read/paper_data/background").text
    assert "We propose the Transformer." not in later


# --- F3 -------------------------------------------------------------------

def test_upload_rejects_unsupported_types_but_names_both_supported(client):
    resp = client.post("/api/upload", files={"file": ("notes.txt", b"hi", "text/plain")})
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "PDF" in detail and "EPUB" in detail


# --- F5 -------------------------------------------------------------------

def test_delete_removes_the_folder(client, tmp_path):
    assert (tmp_path / "paper_data").is_dir()
    resp = client.delete("/api/paper_data")
    assert resp.status_code == 200
    assert not (tmp_path / "paper_data").exists()
    assert client.get("/read/paper_data", follow_redirects=False).status_code == 404


@pytest.mark.parametrize("bad", ["..", "../etc", "etc", "paper", "%2e%2e", "paper_data/.."])
def test_delete_refuses_anything_outside_the_library(client, bad, tmp_path):
    """Only ``*_data`` folders directly inside the library may be deleted.

    Some of these never reach the handler at all (the client or the router
    rejects them first); what matters is that nothing on disk is touched.
    """
    resp = client.delete(f"/api/{bad}")
    assert resp.status_code != 200
    assert (tmp_path / "paper_data").is_dir()


# --- misc -----------------------------------------------------------------

def test_library_lists_the_book_with_a_snippet(client):
    html = client.get("/").text
    assert "Attention Is All You Need" in html
    assert "We propose the Transformer." in html


def test_favicon_is_served(client):
    assert client.get("/favicon.ico").status_code == 200


def test_unknown_book_404s(client):
    assert client.get("/read/nope_data").status_code == 404
    assert client.get("/api/nope_data/markdown").status_code == 404


# --- review-bot findings on PR #3 ------------------------------------------

def test_reserve_folder_never_hands_out_the_same_path_twice(tmp_path):
    """Concurrent uploads of the same filename must not share an output dir."""
    import server as server_mod

    handed = [server_mod._reserve_folder(str(tmp_path), "paper") for _ in range(25)]
    assert len(set(handed)) == 25, "a path was reserved twice"
    assert all(os.path.isdir(p) for p in handed), "reservation did not create the dir"
    assert os.path.basename(handed[0]) == "paper_data"
    assert os.path.basename(handed[1]) == "paper-2_data"


def test_reserve_folder_is_atomic_under_threads(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    import server as server_mod

    with ThreadPoolExecutor(max_workers=16) as pool:
        handed = list(pool.map(
            lambda _: server_mod._reserve_folder(str(tmp_path), "paper"), range(64)
        ))
    assert len(set(handed)) == 64, "concurrent reservations collided"


def test_continue_link_is_hidden_not_just_marked_hidden(client):
    """`.btn { display: inline-flex }` beats the UA [hidden] rule, so the
    stylesheet needs its own. Reported by a review bot on PR #3."""
    css = open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "static", "reader.css"),
        encoding="utf-8",
    ).read()
    assert "[hidden] { display: none !important; }" in css

    html = client.get("/").text
    assert "data-continue-for" in html and "hidden>" in html
