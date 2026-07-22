"""Smoke tests for the cms_wm_core package."""

from cms_wm_core import __version__


def test_version_is_defined():
    assert __version__
    assert isinstance(__version__, str)
