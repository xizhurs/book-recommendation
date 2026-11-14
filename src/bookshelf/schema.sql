CREATE TABLE IF NOT EXISTS authors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goodreads_book_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    author_id INTEGER NOT NULL REFERENCES authors (id),
    isbn10 TEXT,
    isbn13 TEXT,
    publisher TEXT,
    binding TEXT,
    pages INTEGER,
    year_published INTEGER,
    original_year INTEGER,
    average_rating REAL,
    openlibrary_work_id TEXT,
    openlibrary_edition_id TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS library_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL UNIQUE REFERENCES books (id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('read', 'currently_reading', 'to_read')),
    rating INTEGER CHECK (rating BETWEEN 1 AND 5),
    date_read TEXT,
    date_added TEXT,
    read_count INTEGER NOT NULL DEFAULT 0,
    shelves_raw TEXT,
    review TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS import_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    inserted INTEGER NOT NULL DEFAULT 0,
    updated INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_books_title ON books (title);
CREATE INDEX IF NOT EXISTS idx_books_author ON books (author_id);
CREATE INDEX IF NOT EXISTS idx_books_isbn10 ON books (isbn10);
CREATE INDEX IF NOT EXISTS idx_books_isbn13 ON books (isbn13);
CREATE INDEX IF NOT EXISTS idx_library_entries_status ON library_entries (status);
CREATE INDEX IF NOT EXISTS idx_library_entries_rating ON library_entries (rating);

CREATE TABLE IF NOT EXISTS remote_cache (
    source TEXT NOT NULL,
    cache_key TEXT NOT NULL,
    payload TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    PRIMARY KEY (source, cache_key)
);

CREATE INDEX IF NOT EXISTS idx_remote_cache_expires ON remote_cache (expires_at);
