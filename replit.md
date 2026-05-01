# Reader3 — Self-Hosted EPUB & Academic Paper Reader

## Overview

A self-hosted web reader for academic papers and EPUBs, optimized for LLM-assisted study. Import books/papers (EPUB, PDF, arXiv ID, or arbitrary HTML URLs), which are converted into structured sections. A web UI lets you navigate sections and copy them as Markdown for use with LLMs.

## Architecture

- **Backend**: FastAPI + Uvicorn (`server.py`) — serves library and per-section reader pages
- **Frontend**: Plain ES2020 JavaScript + CSS (no build step), Jinja2 templates, KaTeX via CDN for math rendering
- **Package manager**: Python `pip` (dependencies listed in `pyproject.toml`)

## Key Files

- `server.py` — FastAPI web server, runs on port 5000
- `import.py` — CLI tool to import books/papers
- `reader3.py` — Core data model, HTML cleaning, section splitting, pickle I/O
- `importers/` — Import modules for EPUB, PDF, arXiv, and HTML URLs
- `templates/` — Jinja2 HTML templates (`library.html`, `reader.html`)
- `static/` — CSS and JavaScript assets

## Running Locally

The app starts automatically via the "Start application" workflow:

```
python server.py
```

Server runs at `http://0.0.0.0:5000`.

## Importing Books

Use the CLI to import content:

```bash
python import.py path/to/paper.pdf
python import.py arxiv:1706.03762
python import.py path/to/book.epub
python import.py https://example.com/article
```

Books are stored as `*_data/book.pkl` in the working directory (or `READER3_LIBRARY` env var path).

## Environment Variables

- `READER3_LIBRARY` — Path to directory containing imported books (defaults to `.`)

## Deployment

Configured for autoscale deployment using uvicorn:
```
uvicorn server:app --host=0.0.0.0 --port=5000
```
