"""
Task 1.1 - fetch books from an API, save them in SQLite and print them.

I used the Open Library search API because it's free, needs no key, and gives
title, author_name and first_publish_year directly.

Usage:
    python books.py
    python books.py --query "machine learning" --limit 30
    python books.py --show-only     (just print what's already saved)

Running it twice won't create duplicates: (title, author) is UNIQUE and the
insert uses INSERT OR IGNORE.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import requests

API_URL = "https://openlibrary.org/search.json"
USER_AGENT = "AccuKnoxAssignment/1.0 (books.py; contact: candidate@example.com)"
TIMEOUT_SECONDS = 15
DEFAULT_DB = Path(__file__).with_name("books.db")

MAX_TITLE_LEN = 300
MAX_AUTHOR_LEN = 200


# --- fetching from the API ---
def fetch_books(query: str, limit: int) -> list[dict]:
    """Call the API and return a list of clean dicts: {title, author, year}."""
    params = {
        "q": query,
        "limit": limit,
        "fields": "title,author_name,first_publish_year",
    }
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    response = requests.get(API_URL, params=params, headers=headers, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()

    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("API did not return valid JSON") from exc

    docs = payload.get("docs")
    if not isinstance(docs, list):
        raise RuntimeError("Unexpected API response: 'docs' list is missing")

    books = []
    for doc in docs:
        book = normalise_book(doc)
        if book is not None:
            books.append(book)
    return books


def normalise_book(doc: dict) -> dict | None:
    """Turn one raw API record into {title, author, year}, or None if it is unusable.

    Assumptions:
      * A book without a title is skipped (it cannot be identified).
      * `author_name` is a list. All authors are kept, joined with ", ".
        A missing author is stored as "Unknown".
      * A missing or implausible year is stored as NULL (None).
    """
    if not isinstance(doc, dict):
        return None

    title = doc.get("title")
    if not isinstance(title, str) or not title.strip():
        return None
    title = " ".join(title.split())[:MAX_TITLE_LEN]

    authors = doc.get("author_name") or []
    if isinstance(authors, str):
        authors = [authors]
    authors = [" ".join(a.split()) for a in authors if isinstance(a, str) and a.strip()]
    author = ", ".join(authors)[:MAX_AUTHOR_LEN] if authors else "Unknown"

    year = doc.get("first_publish_year")
    if isinstance(year, bool) or not isinstance(year, int) or not (0 < year <= 2100):
        year = None

    return {"title": title, "author": author, "year": year}


# --- database ---
def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS books (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT    NOT NULL,
            author      TEXT    NOT NULL DEFAULT 'Unknown',
            year        INTEGER,
            fetched_at  TEXT    NOT NULL DEFAULT (datetime('now')),
            UNIQUE (title, author)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_books_year ON books(year)")


def save_books(conn: sqlite3.Connection, books: list[dict]) -> int:
    """Insert books in one transaction; return how many rows were new."""
    before = conn.total_changes
    with conn:  # commits on success, rolls back on any error
        conn.executemany(
            "INSERT OR IGNORE INTO books (title, author, year) VALUES (:title, :author, :year)",
            books,
        )
    return conn.total_changes - before


# --- printing ---
def show_books(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT id, title, author, year FROM books ORDER BY year IS NULL, year, title"
    ).fetchall()

    if not rows:
        print("The database is empty.")
        return

    def cut(text: str, width: int) -> str:
        return text if len(text) <= width else text[: width - 1] + "…"

    header = f"{'ID':>4}  {'Year':<6}{'Title':<50}{'Author'}"
    print(header)
    print("-" * 100)
    for book_id, title, author, year in rows:
        year_txt = str(year) if year is not None else "-"
        print(f"{book_id:>4}  {year_txt:<6}{cut(title, 48):<50}{cut(author, 40)}")
    print("-" * 100)
    print(f"{len(rows)} book(s) in the database.")


# --- command line ---
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch books from Open Library into SQLite.")
    parser.add_argument("--query", default="python", help="search term (default: python)")
    parser.add_argument("--limit", type=int, default=20, help="number of books, 1-100 (default: 20)")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite file (default: books.db)")
    parser.add_argument("--show-only", action="store_true", help="skip the API call, just display")
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 100:
        parser.error("--limit must be between 1 and 100 (Open Library's maximum)")
    if not args.query.strip():
        parser.error("--query must not be empty")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    conn = sqlite3.connect(args.db)
    try:
        init_db(conn)

        if not args.show_only:
            print(f"Fetching up to {args.limit} books for '{args.query}' from Open Library...")
            try:
                books = fetch_books(args.query, args.limit)
            except requests.exceptions.Timeout:
                print(f"Error: the API did not answer within {TIMEOUT_SECONDS}s.", file=sys.stderr)
                return 1
            except requests.exceptions.ConnectionError:
                print("Error: could not connect to the API. Check your internet connection.", file=sys.stderr)
                return 1
            except requests.exceptions.HTTPError as exc:
                print(f"Error: the API returned HTTP {exc.response.status_code}.", file=sys.stderr)
                return 1
            except RuntimeError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                return 1

            new_rows = save_books(conn, books)
            print(f"Received {len(books)} valid book(s); {new_rows} new, "
                  f"{len(books) - new_rows} already stored.\n")

        show_books(conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
