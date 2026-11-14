"""Server-rendered HTML for the read-only bookshelf page.

Kept free of FastAPI and SQL: ``api/routes.py`` loads the data through the service
layer and hands plain models to these helpers.
"""

from __future__ import annotations

from html import escape

from .models import BookOut, ReadingStatus, Stats

_IMPORT_HINT = "uv run python -m bookshelf.ingest.goodreads data/goodreads_library_export.csv"

_STATUS_LABEL = {
    ReadingStatus.READ: "Read",
    ReadingStatus.CURRENTLY_READING: "Reading",
    ReadingStatus.TO_READ: "To read",
}

_STATUS_CLASS = {
    ReadingStatus.READ: "read",
    ReadingStatus.CURRENTLY_READING: "reading",
    ReadingStatus.TO_READ: "to-read",
}

_STYLE = """
:root {
  --bg: #f6f3ee;
  --panel: #fffdfa;
  --ink: #1d1b19;
  --muted: #6f6a63;
  --line: #e3ded5;
  --accent: #8a5a2b;
  --read: #2f6f4f;
  --reading: #8a5a2b;
  --to-read: #3f5b8a;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  line-height: 1.5;
}
.wrap { max-width: 960px; margin: 0 auto; padding: 40px 24px 64px; }
header {
  display: flex; align-items: baseline; justify-content: space-between;
  gap: 16px; flex-wrap: wrap;
}
h1 { font-size: 1.9rem; margin: 0; letter-spacing: -0.02em; }
.sub { color: var(--muted); margin: 4px 0 24px; }
.docs {
  color: var(--accent); text-decoration: none; font-size: 0.9rem;
  border-bottom: 1px solid currentColor;
}
.stats {
  display: flex; gap: 10px; flex-wrap: wrap; margin: 0 0 24px;
  padding: 0; list-style: none;
}
.stats li {
  background: var(--panel); border: 1px solid var(--line); border-radius: 999px;
  padding: 6px 14px; font-size: 0.85rem; color: var(--muted);
}
.stats strong { color: var(--ink); font-weight: 600; }
.filters { display: flex; gap: 10px; flex-wrap: wrap; margin: 0 0 20px; }
input[type="search"], select {
  font: inherit; padding: 9px 12px; border: 1px solid var(--line); border-radius: 10px;
  background: var(--panel); color: inherit;
}
input[type="search"] { flex: 1 1 240px; min-width: 0; }
button {
  font: inherit; padding: 9px 16px; border-radius: 10px; border: 1px solid var(--accent);
  background: var(--accent); color: #fff; cursor: pointer;
}
button:hover { filter: brightness(1.08); }
.reset { align-self: center; color: var(--muted); font-size: 0.85rem; }
.results { color: var(--muted); font-size: 0.85rem; margin: 0 0 16px; }
.grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px; margin: 0; padding: 0; list-style: none;
}
.card {
  background: var(--panel); border: 1px solid var(--line); border-radius: 14px;
  padding: 18px 18px 16px; display: flex; flex-direction: column; gap: 6px;
}
.card h2 { font-size: 1.05rem; margin: 0; line-height: 1.3; }
.row { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.author { margin: 0; color: var(--muted); font-size: 0.9rem; }
.meta { margin: 0; color: var(--muted); font-size: 0.8rem; }
.pill {
  border-radius: 999px; padding: 2px 10px; font-size: 0.72rem; font-weight: 600;
  letter-spacing: 0.02em; text-transform: uppercase;
}
.pill.read { background: #e3f1e9; color: var(--read); }
.pill.reading { background: #f6e9db; color: var(--reading); }
.pill.to-read { background: #e5eaf4; color: var(--to-read); }
.stars { color: #c98a2e; font-size: 0.85rem; letter-spacing: 0.08em; }
.muted { color: var(--muted); font-size: 0.78rem; }
.shelves {
  display: flex; flex-wrap: wrap; gap: 6px; margin: 2px 0 0;
  padding: 0; list-style: none;
}
.shelves li {
  background: var(--bg); border: 1px solid var(--line); border-radius: 6px;
  padding: 1px 7px; font-size: 0.72rem; color: var(--muted);
}
details { margin-top: 4px; font-size: 0.85rem; }
summary { cursor: pointer; color: var(--accent); }
details p { margin: 6px 0 0; color: var(--muted); }
.empty {
  background: var(--panel); border: 1px dashed var(--line); border-radius: 14px;
  padding: 32px; text-align: center; color: var(--muted);
}
.empty code {
  display: block; margin-top: 12px; font-size: 0.8rem; color: var(--ink);
  word-break: break-all;
}
"""


def _stars(rating: int | None) -> str:
    if rating is None:
        return '<span class="muted">Unrated</span>'
    filled = "\u2605" * rating
    hollow = "\u2606" * (5 - rating)
    return f'<span class="stars" aria-label="Rated {rating} out of 5">{filled}{hollow}</span>'


def _shelves(raw: str | None) -> str:
    if not raw:
        return ""
    chips = [escape(name.strip()) for name in raw.split(",") if name.strip()]
    if not chips:
        return ""
    return '<ul class="shelves">' + "".join(f"<li>{chip}</li>" for chip in chips) + "</ul>"


def _review(review: str | None) -> str:
    if not review:
        return ""
    return f"<details><summary>Review</summary><p>{escape(review)}</p></details>"


def _book_card(book: BookOut) -> str:
    meta: list[str] = []
    if book.date_read is not None:
        meta.append(f"Read {book.date_read.isoformat()}")
    if book.pages:
        meta.append(f"{book.pages} pages")
    if book.year_published:
        meta.append(str(book.year_published))
    meta_html = f'<p class="meta">{" · ".join(meta)}</p>' if meta else ""
    return (
        '<li class="card">'
        '<div class="row">'
        f'<span class="pill {_STATUS_CLASS[book.status]}">{_STATUS_LABEL[book.status]}</span>'
        f"{_stars(book.rating)}"
        "</div>"
        f"<h2>{escape(book.title)}</h2>"
        f'<p class="author">{escape(book.author)}</p>'
        f"{meta_html}"
        f"{_shelves(book.shelves_raw)}"
        f"{_review(book.review)}"
        "</li>"
    )


def _stats_bar(stats: Stats) -> str:
    items = [f"<li><strong>{stats.total_books}</strong> books</li>"]
    for value in ReadingStatus:
        count = stats.by_status.get(value.value, 0)
        items.append(f"<li><strong>{count}</strong> {_STATUS_LABEL[value].lower()}</li>")
    if stats.average_rating is not None:
        items.append(f"<li><strong>{stats.average_rating:.1f}</strong> avg rating</li>")
    return '<ul class="stats">' + "".join(items) + "</ul>"


def _status_options(selected: ReadingStatus | None) -> str:
    options = ['<option value="">All statuses</option>']
    for value in ReadingStatus:
        chosen = " selected" if value == selected else ""
        options.append(f'<option value="{value.value}"{chosen}>{_STATUS_LABEL[value]}</option>')
    return "".join(options)


def _empty_state(filtered: bool) -> str:
    if filtered:
        return (
            '<div class="empty"><p>No books match those filters.</p>'
            '<a class="reset" href="/">Reset</a></div>'
        )
    return (
        '<div class="empty"><p>No books yet. Import your Goodreads library to get started:</p>'
        f"<code>{_IMPORT_HINT}</code></div>"
    )


def _book_count(total: int) -> str:
    return f"{total} book" if total == 1 else f"{total} books"


def render_index(
    *,
    stats: Stats,
    books: list[BookOut],
    total: int,
    q: str | None,
    status: ReadingStatus | None,
) -> str:
    filtered = bool(q) or status is not None
    if not books:
        body = _empty_state(filtered)
    else:
        cards = "".join(_book_card(book) for book in books)
        body = f'<ul class="grid">{cards}</ul>'
    results = f'<p class="results">Showing {len(books)} of {_book_count(total)}</p>'
    reset = '<a class="reset" href="/">Reset</a>' if filtered else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Bookshelf</title>
<style>{_STYLE}</style>
</head>
<body>
<div class="wrap">
<header>
<h1>AI Bookshelf</h1>
<a class="docs" href="/docs">API docs</a>
</header>
<p class="sub">Your local reading history, served from SQLite.</p>
{_stats_bar(stats)}
<form class="filters" method="get" action="/">
<input type="search" name="q" value="{escape(q or "")}" placeholder="Search title or author"
 aria-label="Search title or author" maxlength="200">
<select name="status" aria-label="Reading status">{_status_options(status)}</select>
<button type="submit">Filter</button>
{reset}
</form>
{results}
{body}
</div>
</body>
</html>
"""
