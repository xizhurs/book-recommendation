from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field


class ReadingStatus(StrEnum):
    READ = "read"
    CURRENTLY_READING = "currently_reading"
    TO_READ = "to_read"


class BookOut(BaseModel):
    id: int
    goodreads_book_id: str
    title: str
    author: str
    isbn10: str | None = None
    isbn13: str | None = None
    publisher: str | None = None
    binding: str | None = None
    pages: int | None = None
    year_published: int | None = None
    original_year: int | None = None
    average_rating: float | None = None
    status: ReadingStatus
    rating: int | None = None
    date_read: date | None = None
    date_added: date | None = None
    read_count: int = 0
    shelves_raw: str | None = None
    review: str | None = None


class BookPage(BaseModel):
    items: list[BookOut]
    total: int
    limit: int
    offset: int


class AuthorCount(BaseModel):
    name: str
    count: int


class ShelfCount(BaseModel):
    name: str
    count: int


class Stats(BaseModel):
    total_books: int
    by_status: dict[str, int]
    rating_counts: dict[str, int]
    average_rating: float | None = None
    top_authors: list[AuthorCount] = Field(default_factory=list)
    top_shelves: list[ShelfCount] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    schema_version: int
