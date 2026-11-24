# AccuKnox Assignment 1 - Veera Siva Abhishek

Code for Problem Statement 1 (tasks 1.1 to 1.3). Everything is plain Python with SQLite.
The only extra packages are `requests` and `matplotlib`.

```
task1_books/books.py             1.1  Open Library API -> SQLite -> printed table
task2_scores/scores.py           1.2  NAEP scores API -> average -> bar chart
task2_scores/sample_scores.json       small offline sample (used only with --file)
task3_csv_import/import_users.py 1.3  users.csv -> validation -> SQLite
task3_csv_import/users.csv            12 test rows, 6 of them bad on purpose
tests/test_assignment1.py             11 unit tests (APIs are mocked)
screenshots/                          output from my run on 24 Nov 2026
```

## Setup (Windows)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Running it

```powershell
python task1_books\books.py                  # add --limit 30 or --query "..." if you want
python task2_scores\scores.py                # saves screenshots\scores_chart.png
python task3_csv_import\import_users.py --show
python -m unittest discover -s tests -v
```

## Notes on each task

**1.1 Books.** The task didn't name an API, so I picked Open Library: it's free, needs no key,
and its fields match title / author / year directly. I only request those three fields.
Some books have several authors, so I join them with a comma. A missing author is saved as
"Unknown", a missing year as NULL, and anything without a title is skipped.
`UNIQUE(title, author)` plus `INSERT OR IGNORE` means a second run adds 0 rows.

**1.2 Scores.** I used real data from NAEP (the Nation's Report Card). NAEP doesn't publish
individual students' scores, only state averages, so each bar is a state. The default is
Grade 8 maths, 2019, 10 states. Records that NAEP flags as not reportable, and anything
non-numeric, are dropped and printed. NAEP scores are on a 0-500 scale and the states are only
a few points apart, so I zoomed the y-axis and wrote where it starts on the axis label.
My run gave an average of 280.52 (Massachusetts highest at 294.47, Alabama lowest at 268.70).

**1.3 CSV import.** The script reads with `csv.DictReader`, trims spaces, lower-cases emails, validates,
removes duplicates and inserts everything in one transaction. On the sample file:
12 rows read, 6 inserted, 6 rejected (each with a line number and reason). Running it again
inserts 0.

## Security bits

- All SQL uses `?` / `:name` parameters, never f-strings. One test saves a book titled
  `Robert'); DROP TABLE books;--` to check it's stored as plain text.
- Data is checked in Python first, and the schema has NOT NULL / UNIQUE / CHECK constraints as a backup.
- Every HTTP call has a timeout. Errors print a clear message and exit with code 1 instead of a stack trace.
- Names starting with `= + - @` are rejected (CSV / Excel formula injection).
- No API keys are needed, and only the required fields are requested.
