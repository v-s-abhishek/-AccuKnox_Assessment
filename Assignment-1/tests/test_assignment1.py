"""
Tests for Assignment 1. The API calls are mocked with responses in the same
shape as the real Open Library and NAEP APIs, so these run without internet.

    python -m unittest discover -s tests -v
"""

import io
from contextlib import closing
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import requests

ROOT = Path(__file__).resolve().parent.parent
for sub in ("task1_books", "task2_scores", "task3_csv_import"):
    sys.path.insert(0, str(ROOT / sub))

import books  # noqa: E402
import import_users  # noqa: E402
import scores  # noqa: E402


def fake_response(payload, status=200):
    resp = mock.Mock()
    resp.status_code = status
    resp.json.return_value = payload
    if status >= 400:
        err = requests.exceptions.HTTPError(response=resp)
        resp.raise_for_status.side_effect = err
    else:
        resp.raise_for_status.return_value = None
    return resp


OPEN_LIBRARY_PAYLOAD = {
    "numFound": 5, "start": 0,
    "docs": [
        {"title": "Learning Python", "author_name": ["Mark Lutz", "David Ascher"], "first_publish_year": 1999},
        {"title": "Fluent Python", "author_name": ["Luciano Ramalho"], "first_publish_year": 2015},
        {"title": "Python Notes"},                                   # no author, no year
        {"author_name": ["Nobody"], "first_publish_year": 2001},     # no title -> skipped
        {"title": "Robert'); DROP TABLE books;--", "author_name": ["Bobby Tables"], "first_publish_year": 2010},
    ],
}

NAEP_PAYLOAD = {
    "status": 200,
    "result": [
        {"jurisdiction": "AK", "jurisLabel": "Alaska", "value": 274.34, "isStatDisplayable": 1, "errorFlag": 0},
        {"jurisdiction": "AL", "jurisLabel": "Alabama", "value": 268.70, "isStatDisplayable": 1, "errorFlag": 0},
        {"jurisdiction": "AR", "jurisLabel": "Arkansas", "value": 274.36, "isStatDisplayable": 1, "errorFlag": 0},
        {"jurisdiction": "AZ", "jurisLabel": "Arizona", "value": 279.93, "isStatDisplayable": 1, "errorFlag": 0},
        {"jurisdiction": "CA", "jurisLabel": "California", "value": 275.61, "isStatDisplayable": 1, "errorFlag": 0},
        {"jurisdiction": "XX", "jurisLabel": "Flagged", "value": 999, "isStatDisplayable": 0, "errorFlag": 0},
    ],
}


class TestBooks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "books.db"

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = books.main(["--db", str(self.db), *args])
        return code, out.getvalue(), err.getvalue()

    def test_normalise_handles_missing_fields(self):
        self.assertEqual(books.normalise_book({"title": "X"}), {"title": "X", "author": "Unknown", "year": None})
        self.assertIsNone(books.normalise_book({"author_name": ["A"]}))
        self.assertEqual(books.normalise_book({"title": "T", "author_name": ["A", "B"]})["author"], "A, B")
        self.assertIsNone(books.normalise_book({"title": "T", "first_publish_year": "1999"})["year"])

    @mock.patch("books.requests.get")
    def test_fetch_store_display_and_idempotent(self, get):
        get.return_value = fake_response(OPEN_LIBRARY_PAYLOAD)

        code, out, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("4 new", out)
        self.assertIn("Fluent Python", out)

        # request sent the right parameters, a timeout and a User-Agent
        _, kwargs = get.call_args
        self.assertEqual(kwargs["params"]["fields"], "title,author_name,first_publish_year")
        self.assertIn("timeout", kwargs)
        self.assertIn("User-Agent", kwargs["headers"])

        code, out, _ = self.run_main()
        self.assertIn("0 new", out)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM books").fetchone()[0], 4)
            # SQL-injection title stored as plain text, table still exists
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM books WHERE author='Bobby Tables'").fetchone()[0], 1)

    @mock.patch("books.requests.get", side_effect=requests.exceptions.ConnectionError())
    def test_network_error_is_friendly(self, _):
        code, _, err = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("could not connect", err)

    @mock.patch("books.requests.get")
    def test_http_error_is_friendly(self, get):
        get.return_value = fake_response({}, status=503)
        code, _, err = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("HTTP 503", err)


class TestScores(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.png = Path(self.tmp.name) / "chart.png"

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_skips_invalid(self):
        recs = [{"name": "A", "score": 80}, {"name": "B", "score": None},
                {"name": "C", "score": "absent"}, {"name": "D", "score": "90"}, {"name": "E", "score": True}]
        valid, skipped = scores.parse_records(recs)
        self.assertEqual([s.label for s in valid], ["A", "D"])
        self.assertEqual(len(skipped), 3)

    def test_average(self):
        s = scores.summarise([scores.Score("a", 10), scores.Score("b", 20), scores.Score("c", 60)])
        self.assertAlmostEqual(s.average, 30.0)
        self.assertEqual(s.highest.label, "c")
        self.assertEqual(s.above_average, 1)

    @mock.patch("scores.requests.get")
    def test_naep_end_to_end(self, get):
        get.return_value = fake_response(NAEP_PAYLOAD)
        out = io.StringIO()
        with redirect_stdout(out):
            code = scores.main(["--states", "AK,AL,AR,AZ,CA", "--out", str(self.png)])
        self.assertEqual(code, 0)
        self.assertIn("Average score      : 274.59", out.getvalue())   # (274.34+268.70+274.36+279.93+275.61)/5
        self.assertIn("Flagged: flagged by source", out.getvalue())
        self.assertTrue(self.png.exists() and self.png.stat().st_size > 10_000)
        self.assertEqual(get.call_args.kwargs["params"]["subscale"], "MRPCM")

    @mock.patch("scores.requests.get")
    def test_naep_bad_status(self, get):
        get.return_value = fake_response({"status": 400, "result": "bad params"})
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = scores.main(["--out", str(self.png)])
        self.assertEqual(code, 1)
        self.assertIn("status 400", err.getvalue())


class TestImportUsers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "users.db"

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *args):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = import_users.main([*args, "--db", str(self.db)])
        return code, out.getvalue()

    def test_sample_csv_twice(self):
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("Inserted           : 6", out)
        self.assertIn("Rejected           : 6", out)

        code, out = self.run_main()
        self.assertIn("Inserted           : 0", out)
        self.assertIn("Already in database: 6", out)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 6)
            row = conn.execute("SELECT name, email FROM users WHERE email LIKE 'kabir%'").fetchone()
            self.assertEqual(row, ("Kabir Singh", "kabir.singh@example.com"))

    def test_missing_column(self):
        bad = Path(self.tmp.name) / "bad.csv"
        bad.write_text("full_name,mail\nA,a@b.com\n", encoding="utf-8")
        code, _ = self.run_main(str(bad))
        self.assertEqual(code, 1)

    def test_missing_file(self):
        code, _ = self.run_main(str(Path(self.tmp.name) / "nope.csv"))
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
