# reader 3

![reader3](reader3.png)

A lightweight, self-hosted EPUB reader that lets you read through EPUB books one chapter at a time. This makes it very easy to copy paste the contents of a chapter to an LLM, to read along. Basically - get epub books (e.g. [Project Gutenberg](https://www.gutenberg.org/) has many), open them up in this reader, copy paste text around to your favorite LLM, and read together and along.

This project was 90% vibe coded just to illustrate how one can very easily [read books together with LLMs](https://x.com/karpathy/status/1990577951671509438). I'm not going to support it in any way, it's provided here as is for other people's inspiration and I don't intend to improve it. Code is ephemeral now and libraries are over, ask your LLM to change it in whatever way you like.

## Usage

The project uses [uv](https://docs.astral.sh/uv/). Import a paper or book with the unified `import.py` CLI:

```bash
uv run import.py dracula.epub                 # EPUB
uv run import.py path/to/paper.pdf            # PDF (via pymupdf4llm)
uv run import.py arxiv:1706.03762             # arXiv (prefers ar5iv HTML)
uv run import.py https://arxiv.org/abs/1706.03762
uv run import.py https://example.com/post.html
```

Each call creates a `*_data` folder that registers the book to your local library. Then run the server:

```bash
uv run server.py
```

Visit [localhost:5000](http://localhost:5000/) for your library. You can also import PDFs and EPUBs straight from the library page — hit **Add document** or drag a file onto the window.

The reader splits documents into sections at every H1/H2/H3, renders the whole document in one continuous scroll, keeps the TOC synced to the active section, and renders math with KaTeX (vendored into `static/`, so it works offline). You can grab the active section as markdown for your LLM with one keystroke. Press `?` in the reader for the full shortcut list; the essentials:

| key | action |
| --- | --- |
| `j` / `k` | jump to next / previous section |
| `c`       | copy current section as markdown (with provenance header) |
| `C`       | copy entire paper |
| `y`       | copy current selection (with provenance header) |
| `g`       | fuzzy "go to section…" palette |
| `?`       | shortcut help |

The right-hand Codex panel can explain highlighted text as you read. Set `OPENAI_API_KEY` before starting the server, or paste a key into the panel for the current server session. Set `READER3_CODEX_MODEL` to change the model (default: `gpt-5`).

Set `READER3_LIBRARY=~/papers` to point the server at a different library directory. The server binds to localhost by default; set `READER3_HOST=0.0.0.0` only when you deliberately want to expose it. Delete a book with the trash icon on its library card, or by removing its `*_data/` folder.

## License

MIT
