"""Server-rendered HTML for the read-only bookshelf page.

Kept free of FastAPI and SQL: ``api/routes.py`` loads the data through the service
layer and hands plain models to these helpers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from html import escape
from urllib.parse import urlencode

from .models import BookOut, DiscoveryItem, DiscoveryPage, ReadingStatus, Recommendation, Stats

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
nav { display: flex; gap: 16px; font-size: 0.9rem; }
nav a { color: var(--muted); text-decoration: none; border-bottom: 1px solid transparent; }
nav a:hover { color: var(--ink); border-bottom-color: var(--line); }
nav a[aria-current="page"] { color: var(--accent); border-bottom-color: currentColor; }
.cover {
  width: 100%; height: 150px; object-fit: cover; border-radius: 10px;
  background: var(--line); margin-bottom: 6px;
}
.badge-owned { background: #e5eaf4; color: var(--to-read); }
.answer {
  background: var(--panel); border: 1px solid var(--line); border-radius: 14px;
  padding: 20px; white-space: pre-wrap; margin: 0 0 12px;
}
.steps { margin: 0; padding-left: 18px; font-size: 0.82rem; color: var(--muted); }
.steps li { margin: 6px 0; }
.steps code { color: var(--ink); }
.steps pre { margin: 4px 0 0; white-space: pre-wrap; word-break: break-word; font-size: 0.75rem; }
.privacy { margin: 8px 0 16px; }
.askform { display: grid; gap: 10px; margin: 0 0 16px; }
.askrow { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.askrow label {
  color: var(--muted); font-size: 0.82rem; display: flex; gap: 6px; align-items: center;
}
input[type="text"], input[type="number"] {
  font: inherit; padding: 9px 12px; border: 1px solid var(--line); border-radius: 10px;
  background: var(--panel); color: inherit; min-width: 0;
}
input[type="number"] { width: 5em; }
button.secondary { background: var(--panel); color: inherit; border-color: var(--line); }
.history { margin: 0 0 16px; font-size: 0.85rem; }
.history .turn { margin: 8px 0; white-space: pre-wrap; }
.history .q { font-weight: 600; }
.history form { margin-top: 8px; }
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


def _nav(current: str) -> str:
    links = (
        ("/", "Library"),
        ("/find", "Find books"),
        ("/ask", "Ask"),
        ("/docs", "API docs"),
    )
    parts: list[str] = []
    for href, label in links:
        current_attr = ' aria-current="page"' if href == current else ""
        parts.append(f'<a href="{href}"{current_attr}>{label}</a>')
    return "<nav>" + "".join(parts) + "</nav>"


def _shell(*, title: str, current: str, content: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>{_STYLE}</style>
</head>
<body>
<div class="wrap">
<header>
<h1>AI Bookshelf</h1>
{_nav(current)}
</header>
{content}
</div>
</body>
</html>
"""


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
    content = f"""<p class="sub">Your local reading history, served from SQLite.</p>
{_stats_bar(stats)}
<form class="filters" method="get" action="/">
<input type="search" name="q" value="{escape(q or "")}" placeholder="Search title or author"
 aria-label="Search title or author" maxlength="200">
<select name="status" aria-label="Reading status">{_status_options(status)}</select>
<button type="submit">Filter</button>
{reset}
</form>
{results}
{body}"""
    return _shell(title="AI Bookshelf", current="/", content=content)


def _discover_card(item: DiscoveryItem) -> str:
    details: list[str] = []
    if item.first_publish_year is not None:
        details.append(str(item.first_publish_year))
    if item.edition_count:
        details.append(f"{item.edition_count} editions")
    if item.isbn13:
        details.append(f"ISBN {item.isbn13}")
    meta = f'<span class="muted">{escape(" · ".join(details))}</span>' if details else ""
    owned = '<span class="pill badge-owned">In your library</span>' if item.in_library else ""
    cover = (
        f'<img class="cover" src="{escape(item.cover_url, quote=True)}" alt="" loading="lazy">'
        if item.cover_url
        else ""
    )
    link = f"https://openlibrary.org{escape(item.openlibrary_key, quote=True)}"
    return (
        f'<li class="card">{cover}'
        f'<div class="row">{owned}{meta}</div>'
        f"<h2>{escape(item.title)}</h2>"
        f'<p class="author">{escape(item.author or "Unknown author")}</p>'
        f'<a class="docs" href="{escape(link, quote=True)}" target="_blank" rel="noopener">'
        "View on Open Library</a>"
        "</li>"
    )


def render_discover(
    *,
    query: str | None,
    page: DiscoveryPage | None,
    error: str | None,
) -> str:
    if error is not None:
        meta = ""
        body = f'<div class="empty"><p>{escape(error)}</p></div>'
    elif page is None:
        meta = ""
        body = (
            '<div class="empty">'
            "<p>Search Open Library for books that are not on your shelf yet.</p>"
            '<p class="muted">Only the search text is sent; your library stays local.</p></div>'
        )
    else:
        if page.items:
            cards = "".join(_discover_card(item) for item in page.items)
            body = f'<ul class="grid">{cards}</ul>'
        else:
            reason = (
                "Everything matching that search is already in your library."
                if page.skipped_owned
                else "Open Library returned no matches."
            )
            body = f'<div class="empty"><p>{reason}</p></div>'
        source = "cached" if page.cached else "fresh"
        parts = [
            f"{page.total_found} found",
            f"{page.skipped_owned} already in your library",
            source,
        ]
        if page.reranked:
            parts.append("reranked")
        meta = f'<p class="results">{" · ".join(parts)}</p>'
    content = f"""<p class="sub">Find something new. Results are cached locally for a day.</p>
<form class="filters" method="get" action="/find">
<input type="search" name="q" value="{escape(query or "")}" placeholder="Title, author, or topic"
 aria-label="Search Open Library" maxlength="200">
<button type="submit">Search</button>
</form>
{meta}
{body}"""
    return _shell(title="Find books · AI Bookshelf", current="/find", content=content)


@dataclass(frozen=True)
class AskForm:
    """Values the Ask page echoes back and the choices it offers."""

    query: str = ""
    session_id: str = ""
    provider: str = "ollama"
    model: str = ""
    max_steps: int | None = None
    rerank: bool = True
    openai_ready: bool = False
    models: dict[str, str] = field(default_factory=dict)


def render_ask(
    *,
    form: AskForm,
    result: Recommendation | None,
    error: str | None,
    history: list[tuple[str, str]] | None = None,
) -> str:
    if error is not None:
        body = f'<div class="empty"><p>{escape(error)}</p></div>'
    elif result is None:
        body = (
            '<div class="empty">'
            "<p>Ask for a recommendation grounded in your own shelf.</p>"
            '<p class="muted">Try “What should I read after Dune?” or '
            "“Which highly rated books have I been putting off?”</p></div>"
        )
    else:
        body = _answer_body(result)
    content = f"""<p class="sub">The model chooses tools, reads the results, then answers.</p>
{_ask_form(form)}
<p class="muted privacy">Tool results never include review text. With
<code>LLM_PROVIDER=ollama</code> everything stays on this machine; with
<code>openai</code> your question, earlier turns of the session and library metadata go to
the hosted API.</p>
{_history(form.session_id, history or [])}
{body}
{_SESSION_SCRIPT}"""
    return _shell(title="Ask · AI Bookshelf", current="/ask", content=content)


def _ask_form(form: AskForm) -> str:
    providers = []
    for value, label, ready in (
        ("ollama", "Ollama (local)", True),
        (
            "openai",
            "OpenAI (hosted)" + ("" if form.openai_ready else " — no API key"),
            form.openai_ready,
        ),
    ):
        chosen = " selected" if value == form.provider else ""
        disabled = "" if ready or value == form.provider else " disabled"
        providers.append(f'<option value="{value}"{chosen}{disabled}>{escape(label)}</option>')
    suggestions = "".join(
        f'<option value="{escape(name)}">' for name in dict.fromkeys(form.models.values()) if name
    )
    steps = "" if form.max_steps is None else str(form.max_steps)
    skip_rerank = "" if form.rerank else " checked"
    return f"""<form class="askform" method="get" action="/ask">
<div class="askrow">
<input type="search" name="q" value="{escape(form.query)}" style="flex: 1 1 280px"
 placeholder="What should I read next?" aria-label="Ask the bookshelf" maxlength="1000">
<button type="submit">Ask</button>
</div>
<div class="askrow">
<label>Session <input type="text" id="session_id" name="session_id"
 value="{escape(form.session_id)}" maxlength="200" placeholder="none (no memory)"
 aria-label="Session id"></label>
<button type="button" class="secondary" id="new-session">New session</button>
<label>Provider
<select name="provider" aria-label="LLM provider">{"".join(providers)}</select></label>
<label>Model <input type="text" name="model" value="{escape(form.model)}" list="models"
 placeholder="default" maxlength="100" aria-label="Model name"></label>
<datalist id="models">{suggestions}</datalist>
<label>Max steps <input type="number" name="max_steps" min="1" max="8" value="{steps}"
 placeholder="auto" aria-label="Max steps"></label>
<label><input type="checkbox" name="no_rerank" value="1"{skip_rerank}> Skip rerank</label>
</div>
</form>"""


def _history(session_id: str, turns: list[tuple[str, str]]) -> str:
    if not session_id or not turns:
        return ""
    items = "".join(
        f'<div class="turn"><div class="q">{escape(question)}</div>{escape(answer)}</div>'
        for question, answer in turns
    )
    clear = "/ask/clear?" + urlencode({"session_id": session_id})
    return (
        f'<details class="history"><summary>Earlier in this session ({len(turns)})</summary>'
        f"{items}"
        f'<form method="post" action="{escape(clear)}">'
        '<button type="submit" class="secondary">Clear this session\'s memory</button></form>'
        "</details>"
    )


# Remembers the session id in this browser and fills it in on a fresh /ask visit.
_SESSION_SCRIPT = """<script>
(function () {
  var input = document.getElementById("session_id");
  if (!input) return;
  var key = "bookshelf.session_id";
  try { if (!input.value) input.value = localStorage.getItem(key) || ""; } catch (e) {}
  document.getElementById("new-session").addEventListener("click", function () {
    input.value = "web-" + Math.random().toString(36).slice(2, 10);
  });
  input.form.addEventListener("submit", function () {
    try { localStorage.setItem(key, input.value.trim()); } catch (e) {}
  });
})();
</script>"""


def _answer_body(result: Recommendation) -> str:
    meta = (
        f'<p class="results">{escape(result.provider)} · {escape(result.model)} · '
        f"{len(result.steps)} tool call{'s' if len(result.steps) != 1 else ''}</p>"
    )
    if not result.steps:
        return f'{meta}<div class="answer">{escape(result.answer)}</div>'
    items: list[str] = []
    for step in result.steps:
        arguments = json.dumps(step.arguments, ensure_ascii=False, indent=2)
        items.append(
            "<li>"
            f"<code>{escape(step.name)}</code>"
            f"<details><summary>arguments and result</summary>"
            f"<pre>{escape(arguments)}</pre>"
            f"<pre>{escape(step.result)}</pre>"
            "</details></li>"
        )
    steps = f'<ol class="steps">{"".join(items)}</ol>'
    return (
        f'{meta}<div class="answer">{escape(result.answer)}</div>'
        f"<details><summary>Tool calls</summary>{steps}</details>"
    )
