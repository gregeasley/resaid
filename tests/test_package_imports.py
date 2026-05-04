"""Public package surface and version metadata."""

from __future__ import annotations

import importlib

import pytest


def test_import_resaid():
    import resaid

    assert hasattr(resaid, "__version__")
    assert isinstance(resaid.__version__, str)
    assert resaid.__version__


def test_all_exports_importable():
    import resaid

    for name in resaid.__all__:
        obj = getattr(resaid, name)
        assert obj is not None


@pytest.mark.parametrize(
    "module_name",
    ["resaid.dca", "resaid.econ", "resaid.database"],
)
def test_submodules_import(module_name: str):
    importlib.import_module(module_name)
