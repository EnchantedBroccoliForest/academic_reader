"""Section splitter and migration tests."""

import os
import sys
import pickle

# Allow ``python -m pytest tests/`` from repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from bs4 import BeautifulSoup

from reader3 import (
    Book,
    BookMetadata,
    ChapterContent,
    TOCEntry,
    build_toc_from_sections,
    migrate_book,
    slugify,
    split_html_into_sections,
    split_inputs_into_sections,
)


HTML_SIMPLE = """
<body>
  <h1>Introduction</h1>
  <p>Hello world.</p>
  <h2>Background</h2>
  <p>Some background.</p>
  <h2>Method</h2>
  <p>We do X.</p>
  <h3>Setup</h3>
  <p>Setup details.</p>
  <h3>Algorithm</h3>
  <p>Algo details.</p>
  <h1>Results</h1>
  <p>Numbers.</p>
</body>
"""


def test_split_basic_structure():
    used = set()
    secs = split_html_into_sections(HTML_SIMPLE, "x.html", "Untitled", 0, used)
    titles = [s.title for s in secs]
    assert titles == ["Introduction", "Background", "Method", "Setup", "Algorithm", "Results"]
    levels = [s.level for s in secs]
    assert levels == [1, 2, 2, 3, 3, 1]


def test_split_anchors_present_on_headings():
    used = set()
    secs = split_html_into_sections(HTML_SIMPLE, "x.html", "Untitled", 0, used)
    for sec in secs:
        soup = BeautifulSoup(sec.html, "html.parser")
        first = soup.find(["h1", "h2", "h3"])
        assert first is not None, f"section {sec.title!r} has no heading"
        assert first.get("id") == sec.id, "heading id must match section id"


def test_split_parent_links_match_hierarchy():
    used = set()
    secs = split_html_into_sections(HTML_SIMPLE, "x.html", "Untitled", 0, used)
    by_title = {s.title: s for s in secs}
    assert by_title["Introduction"].parent_id is None
    assert by_title["Background"].parent_id == by_title["Introduction"].id
    assert by_title["Method"].parent_id == by_title["Introduction"].id
    assert by_title["Setup"].parent_id == by_title["Method"].id
    assert by_title["Algorithm"].parent_id == by_title["Method"].id
    assert by_title["Results"].parent_id is None


def test_split_unique_ids():
    """Two H2s with the same title should get distinct ids."""
    html = """
    <body>
      <h1>Top</h1>
      <h2>Setup</h2><p>a</p>
      <h2>Setup</h2><p>b</p>
    </body>
    """
    used = set()
    secs = split_html_into_sections(html, "x.html", "Untitled", 0, used)
    setups = [s for s in secs if s.title == "Setup"]
    assert len(setups) == 2
    assert setups[0].id != setups[1].id


def test_split_no_headings_emits_one_section():
    html = "<body><p>Just a blob of text.</p></body>"
    used = set()
    secs = split_html_into_sections(html, "x.html", "MyTitle", 0, used)
    assert len(secs) == 1
    assert secs[0].title == "MyTitle"
    assert "Just a blob of text" in secs[0].text


def test_split_unwraps_single_wrappers():
    """Readability output is typically wrapped in <article> or <div>.
    The splitter must descend through single-child wrappers."""
    html = """
    <body>
      <article>
        <div>
          <h1>Top</h1>
          <p>p1</p>
          <h2>Sub</h2>
          <p>p2</p>
        </div>
      </article>
    </body>
    """
    used = set()
    secs = split_html_into_sections(html, "x.html", "Untitled", 0, used)
    assert [s.title for s in secs] == ["Top", "Sub"]


def test_split_empty_html_returns_nothing():
    used = set()
    assert split_html_into_sections("", "x.html", "T", 0, used) == []
    assert split_html_into_sections("   ", "x.html", "T", 0, used) == []


def test_split_inputs_assigns_linear_order():
    inputs = [
        ("a.html", "A", "<h1>One</h1><p>...</p>"),
        ("b.html", "B", "<h1>Two</h1><p>...</p><h2>Two-A</h2><p>...</p>"),
    ]
    secs, toc = split_inputs_into_sections(inputs)
    assert [s.order for s in secs] == list(range(len(secs)))
    assert [s.title for s in secs] == ["One", "Two", "Two-A"]
    # TOC: One at root, Two at root with Two-A child.
    assert [e.title for e in toc] == ["One", "Two"]
    assert [c.title for c in toc[1].children] == ["Two-A"]


def test_build_toc_from_sections_handles_skipped_levels():
    from reader3 import Section
    secs = [
        Section(id="a", level=1, title="A", parent_id=None, html="", text="", order=0, source_file=""),
        Section(id="b", level=3, title="B", parent_id=None, html="", text="", order=1, source_file=""),
        Section(id="c", level=1, title="C", parent_id=None, html="", text="", order=2, source_file=""),
    ]
    toc = build_toc_from_sections(secs)
    titles = [e.title for e in toc]
    assert titles == ["A", "C"]
    assert [c.title for c in toc[0].children] == ["B"]


def test_slugify_basic():
    assert slugify("Hello World") == "hello-world"
    assert slugify("3.2 Multi-Head Attention") == "3-2-multi-head-attention"
    assert slugify("") == "section"
    assert slugify("   ") == "section"
    assert slugify("###") == "section"


def test_migrate_book_v3_to_v4(tmp_path):
    """v3 pickles (with ChapterContent spine) round-trip into v4 sections."""
    chap = ChapterContent(
        id="c1", href="x.html", title="Chapter 1", order=0,
        content="<h1>Intro</h1><p>hi</p><h2>Bg</h2><p>more</p>",
        text="Intro hi Bg more",
    )

    # Construct the legacy shape directly via __dict__ — the new dataclass
    # rejects ``spine`` as an init arg, but unpickle never calls __init__.
    legacy = Book.__new__(Book)
    legacy.__dict__.update(dict(
        metadata=BookMetadata(title="Old Book", language="en", authors=["A"]),
        spine=[chap],
        toc=[],
        images={},
        source_file="old.epub",
        processed_at="",
        version="3.0",
    ))
    pkl = tmp_path / "book.pkl"
    pkl.write_bytes(pickle.dumps(legacy))

    loaded = pickle.loads(pkl.read_bytes())
    migrated = migrate_book(loaded)

    assert migrated.version.startswith("4.")
    assert [s.title for s in migrated.sections] == ["Intro", "Bg"]
    assert migrated.toc[0].title == "Intro"
    assert migrated.toc[0].children[0].title == "Bg"


def test_book_spine_alias_back_compat():
    """Book.spine should keep returning Book.sections."""
    from reader3 import Section
    b = Book(
        metadata=BookMetadata(title="t"),
        sections=[Section(id="x", level=1, title="X", parent_id=None,
                          html="<p>x</p>", text="x", order=0)],
    )
    assert b.spine == b.sections
