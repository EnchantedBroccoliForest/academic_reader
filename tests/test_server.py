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
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    for mod in ("server",):
        sys.modules.pop(mod, None)
    import server as server_mod
    server_mod.BOOKS_DIR = str(tmp_path)
    server_mod._session_codex_api_key = ""
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


# --- continuous reader -----------------------------------------------------

def test_book_root_renders_all_sections(client):
    resp = client.get("/read/paper_data", follow_redirects=False)
    assert resp.status_code == 200
    html = resp.text
    assert 'class="reader-section"' in html
    assert 'id="attention-is-all-you-need"' in html
    assert 'id="background"' in html
    assert 'id="self-attention"' in html
    assert 'id="codex-panel"' in html


def test_section_ref_redirects_to_continuous_anchor(client):
    resp = client.get("/read/paper_data/background", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/read/paper_data#background"


def test_integer_section_ref_still_redirects(client):
    resp = client.get("/read/paper_data/1", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/read/paper_data#background"


# --- F4 -------------------------------------------------------------------

def test_abstract_renders_once_on_continuous_reader(client):
    html = client.get("/read/paper_data").text
    assert html.count("We propose the Transformer.") == 1


# --- Codex ----------------------------------------------------------------

def test_codex_key_status_starts_unconfigured(client):
    resp = client.get("/api/codex/key-status")
    assert resp.status_code == 200
    assert resp.json()["configured"] is False


def test_codex_key_can_be_saved_and_cleared(client):
    saved = client.post("/api/codex/key", json={"api_key": "sk-test"})
    assert saved.status_code == 200
    assert saved.json()["configured"] is True
    assert saved.json()["source"] == "session"

    cleared = client.delete("/api/codex/key")
    assert cleared.status_code == 200
    assert cleared.json()["configured"] is False


def test_codex_explain_requires_a_key(client):
    resp = client.post("/api/codex/explain", json={"text": "multi-head attention"})
    assert resp.status_code == 400
    assert "key" in resp.json()["detail"].lower()


def test_response_text_extracts_responses_api_content(client):
    import server

    assert server._response_text({"output_text": " hello "}) == "hello"
    assert server._response_text({
        "output": [{
            "content": [{"type": "output_text", "text": "from nested content"}]
        }]
    }) == "from nested content"


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
    assert 'href="/read/paper_data"' in html
    assert 'href="/read/paper_data/attention-is-all-you-need"' not in html


def test_favicon_is_served(client):
    assert client.get("/favicon.ico").status_code == 200


def test_unknown_book_404s(client):
    assert client.get("/read/nope_data").status_code == 404
    assert client.get("/api/nope_data/markdown").status_code == 404
