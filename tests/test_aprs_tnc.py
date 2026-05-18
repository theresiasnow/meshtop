"""Tests for AprsTncSource KISS framing and APRS dispatch."""

from meshtop.sources.aprs_tnc import (
    _aprs_position_str,
    _kiss_unwrap,
    _kiss_wrap,
)
from meshtop.position import Position
from datetime import UTC, datetime


def test_kiss_wrap_unwrap_roundtrip():
    """Data wrapped then unwrapped returns original bytes."""
    original = b"\x82\xa0\xa4\xa6\x40\x40\xe0\x9e\x6e\x98\x8a\x9a\x61\x03\xf0Hello"
    wrapped = _kiss_wrap(original)
    assert wrapped[0] == 0xC0
    assert wrapped[1] == 0x00  # CMD_DATA
    assert wrapped[-1] == 0xC0
    recovered = _kiss_unwrap(wrapped[1:-1])  # strip outer FENDs, pass inner
    assert recovered == original


def test_kiss_wrap_escapes_fend():
    """FEND bytes inside payload are escaped."""
    payload_with_fend = b"\xC0\x00\xC0"  # contains FEND bytes
    wrapped = _kiss_wrap(payload_with_fend)
    # The C0 bytes in payload should be escaped as DB DC
    assert b"\xDB\xDC" in wrapped


def test_kiss_wrap_escapes_fesc():
    """FESC bytes inside payload are escaped."""
    payload_with_fesc = b"\xDB"
    wrapped = _kiss_wrap(payload_with_fesc)
    assert b"\xDB\xDD" in wrapped


def test_kiss_unwrap_returns_none_for_non_data_cmd():
    """Non-data KISS commands (lower nibble != 0) are ignored."""
    # 0x01 = TXDELAY command (lower nibble 1), not a data frame
    frame = bytes([0x01]) + b"some data"
    result = _kiss_unwrap(frame)
    assert result is None


def test_kiss_unwrap_too_short():
    assert _kiss_unwrap(b"") is None
    assert _kiss_unwrap(b"\x00") is None


def test_aprs_position_str_north_east():
    pos = Position(lat=59.3293, lon=18.0686, alt=10.0, fix=True, timestamp=datetime.now(UTC))
    result = _aprs_position_str(pos, "SM0ABC")
    assert result.startswith("!")
    assert "N" in result
    assert "E" in result


def test_aprs_position_str_south_west():
    pos = Position(lat=-33.8688, lon=-70.6693, alt=500.0, fix=True, timestamp=datetime.now(UTC))
    result = _aprs_position_str(pos, "CE3ABC")
    assert "S" in result
    assert "W" in result


def test_aprs_position_str_format():
    """Position string should match APRS uncompressed format: !DDMM.MMN/DDDMM.MME>"""
    pos = Position(lat=48.8566, lon=2.3522, fix=True, timestamp=datetime.now(UTC))
    s = _aprs_position_str(pos, "F4ABC")
    # Should start with ! and contain lat/lon separator /
    assert s[0] == "!"
    assert "/" in s
