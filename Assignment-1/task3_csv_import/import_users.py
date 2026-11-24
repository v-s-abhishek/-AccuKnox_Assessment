"""
Task 1.3 - read users (name, email) from a CSV file and insert them into SQLite.

Usage:
    python import_users.py
    python import_users.py data.csv --db app.db
    python import_users.py --show

Checks before inserting:
  - name and email are both present
  - email looks like name@domain.tld (a simple check, not full RFC 5322)
  - names starting with = + - @ are rejected, so the data is safe if someone
    opens it in Excel later (CSV formula injection)
  - duplicate emails in the file are skipped (first one wins), and emails that
    are already in the database are skipped too, so a second run inserts nothing

Every skipped row is printed with its line number and the reason.
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_CSV = HERE / "users.csv"
DEFAULT_DB = HERE / "users.db"

REQUIRED_COLUMNS = {"name", "email"}
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
FORMULA_PREFIXES = ("=", "+", "-", "@")
MAX_NAME_LEN = 100
MAX_EMAIL_LEN = 254


@dataclass
class ImportReport:
    read: int = 0
    inserted: int = 0
    already_in_db: int = 0
    rejected: list[tuple[int, str]] = None

    def __post_init__(self):
        self.rejected = [] if self.rejected is None else self.rejected


# --- validation ---
def clean_row(row: dict) -> tuple[dict | None, str | None]:
    """Return (clean_user, None) or (None, reason)."""
    name = " ".join((row.get("name") or "").split())
    email = (row.get("email") or "").strip().lower()

    if not name:
        return None, "name is missing"
    if len(name) > MAX_NAME_LEN:
        return None, f"name longer than {MAX_NAME_LEN} characters"
    if name.startswith(FORMULA_PREFIXES):
        return None, "name looks like a spreadsheet formula"
    if not email:
        return None, "email is missing"
    if len(email) > MAX_EMAIL_LEN or not EMAIL_RE.match(email):
        return None, f"invalid email {email!r}"
    return {"name": name, "email": email}, None


def read_users(csv_path: Path, report: ImportReport) -> list[dict]:
    """Read and validate the CSV; return unique, valid users."""
    users: list[dict] = []
    seen: set[str] = set()

    # utf-8-sig also strips the BOM Excel adds when it saves CSV files.
    with csv_path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        headers = {h.strip().lower() for h in (reader.fieldnames or []) if h}
        missing = REQUIRED_COLUMNS - headers
        if missing:
            raise ValueError(f"CSV is missing required column(s): {', '.join(sorted(missing))}")

        for row in reader:
            report.read += 1
            row = {(k or "").strip().lower(): v for k, v in row.items()}
            user, reason = clean_row(row)
            if user is None:
                report.rejected.append((reader.line_num, reason))
            elif user["email"] in seen:
                report.rejected.append((reader.line_num, f"duplicate email in file {user['email']!r}"))
            else:
                seen.add(user["email"])
                users.append(user)
    return users


# --- database ---
def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
            email       TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (instr(email, '@') > 1),
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )


def insert_users(conn: sqlite3.Connection, users: list[dict]) -> int:
    """Insert all users in a single transaction; return the number of new rows."""
    before = conn.total_changes
    with conn:  # all-or-nothing: rolls back if anything fails
        conn.executemany(
            "INSERT OR IGNORE INTO users (name, email) VALUES (:name, :email)", users
        )
    return conn.total_changes - before


def show_users(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT id, name, email FROM users ORDER BY id").fetchall()
    print(f"\n{'ID':>4}  {'Name':<25}{'Email'}")
    print("-" * 65)
    for uid, name, email in rows:
        print(f"{uid:>4}  {name:<25}{email}")
    print(f"{len(rows)} user(s) in the database.")


# --- command line ---
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Import users from a CSV file into SQLite.")
    p.add_argument("csv", nargs="?", type=Path, default=DEFAULT_CSV, help="CSV file (default: users.csv)")
    p.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite file (default: users.db)")
    p.add_argument("--show", action="store_true", help="print the users table afterwards")
    args = p.parse_args(argv)

    report = ImportReport()
    try:
        users = read_users(args.csv, report)
    except FileNotFoundError:
        print(f"Error: file not found: {args.csv}", file=sys.stderr)
        return 1
    except (ValueError, UnicodeDecodeError, csv.Error) as exc:
        print(f"Error reading {args.csv}: {exc}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(args.db)
    try:
        init_db(conn)
        report.inserted = insert_users(conn, users)
        report.already_in_db = len(users) - report.inserted

        print(f"Rows read          : {report.read}")
        print(f"Inserted           : {report.inserted}")
        print(f"Already in database: {report.already_in_db}")
        print(f"Rejected           : {len(report.rejected)}")
        for line, reason in report.rejected:
            print(f"  line {line}: {reason}")

        if args.show:
            show_users(conn)
    except sqlite3.Error as exc:
        print(f"Database error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
