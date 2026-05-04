"""Database layer: import-only smoke (no ``.accdb`` / drivers required)."""

from __future__ import annotations


def test_database_classes_are_importable():
    from resaid.database import ARIESDatabase, DatabaseInterface, PhdWinDatabase

    assert issubclass(ARIESDatabase, DatabaseInterface)
    assert issubclass(PhdWinDatabase, DatabaseInterface)
