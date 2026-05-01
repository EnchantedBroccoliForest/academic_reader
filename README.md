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

Visit [localhost:8123](http://localhost:8123/) for your library. The reader splits documents into sections at every H1/H2/H3 so the TOC actually navigates, math is rendered with KaTeX, and you can grab a section as markdown for your LLM with one keystroke. Press `?` in the reader for the full shortcut list; the essentials:

| key | action |
| --- | --- |
| `j` / `k` | next / previous section |
| `c`       | copy current section as markdown (with provenance header) |
| `C`       | copy entire paper |
| `y`       | copy current selection (with provenance header) |
| `g`       | fuzzy "go to section…" palette |
| `?`       | shortcut help |

Set `READER3_LIBRARY=~/papers` to point the server at a different library directory. Delete a book by removing its `*_data/` folder.

## License

MIT