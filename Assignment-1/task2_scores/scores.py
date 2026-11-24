"""
Task 1.2 - get student test scores from an API, work out the average and plot it.

Data comes from the NAEP Data Service (the Nation's Report Card). It's public and
doesn't need a key. NAEP only publishes average scores per state, not scores for
individual students, so each bar in the chart is one state.

Usage:
    python scores.py
    python scores.py --subject reading --grade 4 --year 2022 --states CA,TX,NY,FL
    python scores.py --file sample_scores.json     (offline, individual students)

--file is only used when you ask for it. If the API fails, the script stops with
an error instead of quietly switching to sample data.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # render to a file; no window needed
import matplotlib.pyplot as plt  # noqa: E402
import requests  # noqa: E402

NAEP_URL = "https://www.nationsreportcard.gov/DataService/GetAdhocData.aspx"
TIMEOUT_SECONDS = 20
# NAEP "composite" scale codes per subject.
SUBSCALES = {"mathematics": "MRPCM", "reading": "RRPCM"}
DEFAULT_STATES = "AL,AZ,CA,FL,GA,IL,MA,NY,TX,WA"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "screenshots" / "scores_chart.png"

# Chart colours: one blue for all the bars, near-black for the average line.
BAR_COLOUR = "#2a78d6"
AVG_COLOUR = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
SURFACE = "#fcfcfb"


@dataclass(frozen=True)
class Score:
    label: str
    value: float


@dataclass(frozen=True)
class Summary:
    count: int
    average: float
    median: float
    stdev: float
    highest: Score
    lowest: Score
    above_average: int


# --- getting the data ---
def fetch_naep(subject: str, grade: int, year: int, states: list[str]) -> list[dict]:
    """Query the NAEP API and return its `result` list."""
    params = {
        "type": "data",
        "subject": subject,
        "grade": grade,
        "subscale": SUBSCALES[subject],
        "variable": "TOTAL",            # all students
        "jurisdiction": ",".join(states),
        "stattype": "MN:MN",            # mean scale score
        "Year": year,
    }
    response = requests.get(NAEP_URL, params=params, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("NAEP did not return valid JSON") from exc

    if payload.get("status") != 200:
        raise RuntimeError(f"NAEP returned status {payload.get('status')!r}")
    result = payload.get("result")
    if not isinstance(result, list):
        raise RuntimeError("Unexpected NAEP response: 'result' list is missing")
    return result


def load_file(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise RuntimeError(f"{path} must contain a JSON list of records")
    return data


# --- cleaning + stats ---
def to_number(value) -> float | None:
    """Return a float for numeric values (incl. numeric strings), else None."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # drops NaN


def parse_records(records: list[dict]) -> tuple[list[Score], list[str]]:
    """Return (valid scores, reasons for skipped records).

    Works for both NAEP records (jurisLabel / value) and simple student records
    (name / score). A record is skipped when the score is missing, non-numeric or
    negative, or when NAEP flags it as not displayable / in error.
    """
    scores: list[Score] = []
    skipped: list[str] = []

    for i, rec in enumerate(records, start=1):
        if not isinstance(rec, dict):
            skipped.append(f"record {i}: not an object")
            continue

        label = rec.get("jurisLabel") or rec.get("jurisdiction") or rec.get("name") or f"#{i}"
        label = str(label).strip()

        if rec.get("isStatDisplayable", 1) != 1 or rec.get("errorFlag", 0) not in (0, None):
            skipped.append(f"{label}: flagged by source as not reportable")
            continue

        raw = rec.get("value", rec.get("score"))
        value = to_number(raw)
        if value is None or value < 0:
            skipped.append(f"{label}: invalid score {raw!r}")
            continue

        scores.append(Score(label, value))
    return scores, skipped


def summarise(scores: list[Score]) -> Summary:
    if not scores:
        raise ValueError("no valid scores to summarise")
    values = [s.value for s in scores]
    avg = statistics.mean(values)
    return Summary(
        count=len(values),
        average=avg,
        median=statistics.median(values),
        stdev=statistics.stdev(values) if len(values) > 1 else 0.0,
        highest=max(scores, key=lambda s: s.value),
        lowest=min(scores, key=lambda s: s.value),
        above_average=sum(v > avg for v in values),
    )


# --- chart ---
def plot_scores(scores: list[Score], summary: Summary, title: str, source: str,
                y_label: str, out_path: Path) -> Path:
    ordered = sorted(scores, key=lambda s: s.value, reverse=True)
    labels = [s.label for s in ordered]
    values = [s.value for s in ordered]

    fig, ax = plt.subplots(figsize=(11, 6), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    bars = ax.bar(labels, values, color=BAR_COLOUR, width=0.7, zorder=2)
    labels_txt = ax.bar_label(bars, fmt="%.1f", padding=3, fontsize=8, color=TEXT_SECONDARY, zorder=4)
    for txt in labels_txt:  # keep labels readable where the average line crosses them
        txt.set_bbox({"facecolor": SURFACE, "edgecolor": "none", "pad": 1})

    ax.axhline(summary.average, color=AVG_COLOUR, linestyle="--", linewidth=1.5, zorder=3)
    ax.annotate(f"Average {summary.average:.2f}", xy=(1.0, summary.average),
                xycoords=("axes fraction", "data"), xytext=(4, 0), textcoords="offset points",
                va="center", ha="left", fontsize=9, fontweight="bold", color=AVG_COLOUR)

    if max(values) <= 100:
        # Percentage-style scores: show the full 0-100 scale.
        ax.set_ylim(0, 105)
    else:
        # NAEP uses a 0-500 scale and states differ by a few points, so zoom the
        # y-axis around the data and say so in the axis label.
        spread = max(values) - min(values)
        pad = max(spread * 0.6, 5)
        lower = max(0, min(values) - pad)
        ax.set_ylim(lower, max(values) + pad * 0.6)
        if lower > 0:
            y_label += f"  (axis starts at {lower:.0f})"

    ax.set_title(title, fontsize=13, fontweight="bold", loc="left", pad=12)
    ax.set_ylabel(y_label, color=TEXT_SECONDARY)
    ax.grid(axis="y", color="#e4e3df", linewidth=0.8, zorder=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#bdbcb6")
    ax.tick_params(colors=TEXT_SECONDARY, length=0)
    plt.setp(ax.get_xticklabels(), rotation=35, ha="right")

    fig.text(0.01, 0.01, source, fontsize=8, color=TEXT_SECONDARY)
    fig.tight_layout(rect=(0, 0.03, 0.94, 1))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=SURFACE)
    plt.close(fig)
    return out_path


# --- command line ---
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch test scores, compute the average, plot a bar chart.")
    p.add_argument("--subject", choices=sorted(SUBSCALES), default="mathematics")
    p.add_argument("--grade", type=int, choices=(4, 8), default=8)
    p.add_argument("--year", type=int, default=2019, help="NAEP assessment year, e.g. 2019, 2022")
    p.add_argument("--states", default=DEFAULT_STATES, help="comma-separated state codes")
    p.add_argument("--file", type=Path, help="offline mode: local JSON list of {name, score}")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="PNG output path")
    args = p.parse_args(argv)
    args.states = [s.strip().upper() for s in args.states.split(",") if s.strip()]
    if not args.file and not all(len(s) == 2 and s.isalpha() for s in args.states):
        p.error("--states must be two-letter codes, e.g. CA,TX,NY")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        if args.file:
            print(f"Loading scores from local file {args.file} (offline mode)...")
            records = load_file(args.file)
            title = "Student Test Scores"
            source = f"Source: local file {args.file.name}"
            y_label = "Score"
        else:
            print(f"Fetching NAEP grade {args.grade} {args.subject} ({args.year}) "
                  f"for {len(args.states)} states...")
            records = fetch_naep(args.subject, args.grade, args.year, args.states)
            title = (f"NAEP Grade {args.grade} {args.subject.title()} - "
                     f"Average Score by State ({args.year})")
            source = "Source: NAEP Data Service, nationsreportcard.gov (scale 0-500)"
            y_label = "Average scale score"
    except requests.exceptions.Timeout:
        print(f"Error: NAEP did not answer within {TIMEOUT_SECONDS}s.", file=sys.stderr)
        return 1
    except requests.exceptions.ConnectionError:
        print("Error: could not connect to NAEP. Check your internet connection.", file=sys.stderr)
        return 1
    except requests.exceptions.HTTPError as exc:
        print(f"Error: NAEP returned HTTP {exc.response.status_code}.", file=sys.stderr)
        return 1
    except (RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    scores, skipped = parse_records(records)
    for reason in skipped:
        print(f"  skipped - {reason}")
    if not scores:
        print("Error: no valid scores in the data.", file=sys.stderr)
        return 1

    s = summarise(scores)
    print()
    print(f"Valid records      : {s.count} (skipped {len(skipped)})")
    print(f"Average score      : {s.average:.2f}")
    print(f"Median / Std dev   : {s.median:.2f} / {s.stdev:.2f}")
    print(f"Highest            : {s.highest.label} ({s.highest.value:.2f})")
    print(f"Lowest             : {s.lowest.label} ({s.lowest.value:.2f})")
    print(f"Above the average  : {s.above_average} of {s.count}")

    out = plot_scores(scores, s, title, source, y_label, args.out)
    print(f"\nChart saved to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
