import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import to_float, _norm, canon, simplify_pos, win_probs, _fbd_iso


def test_to_float_valid():
    assert to_float("1.236") == 1.24
    assert to_float(3) == 3.0


def test_to_float_invalid():
    assert to_float(None) == 0.0
    assert to_float("not-a-number") == 0.0


def test_norm_strips_club_suffixes_and_punctuation():
    assert _norm("Ipswich Town FC") == "ipswichtown"
    assert _norm("Nott'm Forest") == "nottmforest"
    assert _norm("Brighton & Hove Albion") == "brightonhovealbion"


def test_canon_known_aliases_collapse_to_same_key():
    assert canon("Man City") == canon("Manchester City") == "mancity"
    assert canon("Spurs") == canon("Tottenham Hotspur") == "tottenham"


def test_canon_unknown_name_falls_back_to_normalised():
    assert canon("Some New Club FC") == _norm("Some New Club FC")


def test_simplify_pos():
    assert simplify_pos("GK") == "GKP"
    assert simplify_pos("D") == "DEF"
    assert simplify_pos("F") == "FWD"
    assert simplify_pos("S") == "FWD"
    assert simplify_pos("M") == "MID"
    assert simplify_pos("") == "MID"


def test_win_probs_sums_to_100():
    p = win_probs(1500, 1500, home=True)
    assert p["ipswich"] + p["draw"] + p["opponent"] == 100


def test_win_probs_home_advantage():
    equal_home = win_probs(1500, 1500, home=True)
    equal_away = win_probs(1500, 1500, home=False)
    assert equal_home["ipswich"] > equal_away["ipswich"]


def test_win_probs_stronger_team_favoured():
    p = win_probs(1700, 1300, home=True)
    assert p["ipswich"] > p["opponent"]


def test_fbd_iso_two_digit_year():
    assert _fbd_iso("22/08/26") == "2026-08-22"


def test_fbd_iso_four_digit_year():
    assert _fbd_iso("22/08/2026") == "2026-08-22"


def test_fbd_iso_blank_passthrough():
    assert _fbd_iso("") == ""
