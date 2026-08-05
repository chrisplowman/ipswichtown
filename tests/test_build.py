import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import _ord, fmt_kickoff, fmt_updated


def test_ord_suffixes():
    assert _ord(1) == "st"
    assert _ord(2) == "nd"
    assert _ord(3) == "rd"
    assert _ord(4) == "th"
    assert _ord(11) == "th"
    assert _ord(12) == "th"
    assert _ord(13) == "th"
    assert _ord(21) == "st"
    assert _ord(22) == "nd"
    assert _ord(23) == "rd"


def test_fmt_kickoff_none():
    assert fmt_kickoff(None) == "TBC"
    assert fmt_kickoff("") == "TBC"


def test_fmt_kickoff_malformed():
    assert fmt_kickoff("not-a-date") == "TBC"


def test_fmt_kickoff_valid():
    out = fmt_kickoff("2026-08-22T14:00:00Z")
    assert "22" in out
    assert "Aug" in out


def test_fmt_updated_valid():
    out = fmt_updated("2026-08-05T12:34:56+00:00")
    assert "2026" in out
    assert "UTC" in out


def test_fmt_updated_malformed_returns_input():
    assert fmt_updated("not-a-date") == "not-a-date"
