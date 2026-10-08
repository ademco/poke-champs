"""Keep docs/DATA_SOURCES.md in sync with the source registry in code."""

from pathlib import Path

from pokechamp.sources import SOURCES

DOC = Path(__file__).resolve().parents[1] / "docs" / "DATA_SOURCES.md"


def test_every_registered_source_is_documented():
    text = DOC.read_text(encoding="utf-8")
    missing = [key for key in SOURCES if f"`{key}`" not in text]
    assert missing == [], f"add these source keys to docs/DATA_SOURCES.md: {missing}"


def test_nothing_unverified_is_marked_approved():
    # A source is only "approved" once its license is known and open.
    for src in SOURCES.values():
        if src.status == "approved":
            assert "not verified" not in src.license.lower(), src.key
            assert "no explicit license" not in src.license.lower(), src.key
