from datetime import UTC, datetime

import pytest

from pokechamp.regulations import REGULATIONS, current_regulation, regulation_on


def at(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def test_known_dates_map_to_the_right_regulation():
    assert regulation_on(at(2026, 4, 20)).code == "M-A"
    assert regulation_on(at(2026, 7, 1)).code == "M-B"
    assert regulation_on(at(2026, 10, 8)).code == "M-C"


def test_switchover_is_exact_to_the_hour():
    # M-C began 2026-09-09 02:00 UTC. One hour earlier is still M-B.
    assert regulation_on(at(2026, 9, 9, 1)).code == "M-B"
    assert regulation_on(at(2026, 9, 9, 2)).code == "M-C"


def test_after_last_known_end_falls_back_to_newest():
    assert regulation_on(at(2027, 1, 15)).code == "M-C"


def test_before_launch_is_an_error():
    with pytest.raises(LookupError):
        regulation_on(at(2025, 1, 1))


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError):
        regulation_on(datetime(2026, 10, 8))


def test_current_regulation_accepts_injected_now():
    assert current_regulation(at(2026, 10, 8)).code == "M-C"


def test_regulations_do_not_overlap():
    regs = sorted(REGULATIONS.values(), key=lambda r: r.start)
    for earlier, later in zip(regs, regs[1:], strict=False):
        assert earlier.end is not None and earlier.end <= later.start


def test_showdown_format_ids_cover_both_game_types_where_known():
    for code in ("M-B", "M-C"):
        assert set(REGULATIONS[code].showdown_formats) == {"doubles", "singles"}
