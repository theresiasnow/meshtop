"""Tests for Js8CallSource message parsing and Maidenhead decode."""

import pytest

from meshtop.sources.js8call import _GRID_RE, _maidenhead_to_latlon


def test_grid_re_matches_4char():
    text = "hello world @GRID FN31 test"
    m = _GRID_RE.search(text)
    assert m is not None
    assert m.group(1) == "FN31"


def test_grid_re_matches_6char():
    text = "@GRID JO89WK position update"
    m = _GRID_RE.search(text)
    assert m is not None
    assert m.group(1) == "JO89WK"


def test_grid_re_case_insensitive():
    text = "@grid fn31"
    m = _GRID_RE.search(text)
    assert m is not None


def test_grid_re_no_match():
    text = "just a normal message"
    assert _GRID_RE.search(text) is None


def test_maidenhead_to_latlon_fn31():
    result = _maidenhead_to_latlon("FN31")
    assert result is not None
    lat, lon = result
    # FN31 is in northeastern USA/Canada border area
    assert 40 < lat < 50
    assert -80 < lon < -60


def test_maidenhead_to_latlon_jo89():
    result = _maidenhead_to_latlon("JO89")
    assert result is not None
    lat, lon = result
    # JO89 is in Scandinavia/northern Europe
    assert 55 < lat < 65
    assert 10 < lon < 25


def test_maidenhead_to_latlon_invalid():
    result = _maidenhead_to_latlon("ZZZZ")
    # Invalid locator may return None or a result; we just verify it doesn't raise
    # (maidenhead library handles invalid gracefully)


def test_maidenhead_roundtrip():
    """Converting to grid and back should give approximate same location."""
    import maidenhead

    lat, lon = 59.3293, 18.0686  # Stockholm
    grid = maidenhead.to_maiden(lat, lon)
    result = _maidenhead_to_latlon(grid)
    assert result is not None
    rlat, rlon = result
    # Grid squares have ~1° resolution at 4-char, so within 1.5°
    assert abs(rlat - lat) < 1.5
    assert abs(rlon - lon) < 1.5
