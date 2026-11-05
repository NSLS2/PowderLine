"""Unit tests for powderline._status (console status markers + ASCII fallback).

Pure tests: no GSAS-II, no network, no server. Cover _supports_unicode(),
emoji(), and the exported CHECK/WARN/CROSS/INFO markers.
"""
import sys

import pytest

from powderline import _status

pytestmark = pytest.mark.core


class _FakeStdout:
    """Minimal stdout stand-in exposing only an ``encoding`` attribute."""

    def __init__(self, encoding):
        self.encoding = encoding


def test_supports_unicode_true_for_utf8(monkeypatch):
    monkeypatch.setattr(sys, "stdout", _FakeStdout("utf-8"))
    assert _status._supports_unicode() is True


@pytest.mark.parametrize("legacy_enc", ["cp1252", "ascii"])
def test_supports_unicode_false_for_legacy_codec(monkeypatch, legacy_enc):
    # cp1252 / ascii cannot encode the emoji -> UnicodeError -> False
    monkeypatch.setattr(sys, "stdout", _FakeStdout(legacy_enc))
    assert _status._supports_unicode() is False


def test_supports_unicode_false_when_encoding_none(monkeypatch):
    # encoding None -> "" -> LookupError on encode() -> False
    monkeypatch.setattr(sys, "stdout", _FakeStdout(None))
    assert _status._supports_unicode() is False


def test_supports_unicode_false_when_stdout_missing_encoding(monkeypatch):
    # getattr fallback: object without .encoding -> "" -> LookupError -> False
    monkeypatch.setattr(sys, "stdout", object())
    assert _status._supports_unicode() is False


def test_emoji_returns_char_when_unicode_ok(monkeypatch):
    monkeypatch.setattr(_status, "UNICODE_OK", True)
    assert _status.emoji("A", "fallback") == "A"


def test_emoji_returns_fallback_when_not_unicode_ok(monkeypatch):
    monkeypatch.setattr(_status, "UNICODE_OK", False)
    assert _status.emoji("A", "fallback") == "fallback"


def test_emoji_default_fallback_is_empty_string(monkeypatch):
    monkeypatch.setattr(_status, "UNICODE_OK", False)
    assert _status.emoji("A") == ""


def test_ascii_fallback_markers(monkeypatch):
    # With UNICODE_OK patched False, emoji() reproduces the ASCII forms the
    # module exports as CHECK/WARN/CROSS/INFO on a legacy console.
    monkeypatch.setattr(_status, "UNICODE_OK", False)
    assert _status.emoji("✅", "[OK]") == "[OK]"
    assert _status.emoji("⚠️", "[!]") == "[!]"
    assert _status.emoji("❌", "[X]") == "[X]"
    assert _status.emoji("ℹ️", "[i]") == "[i]"


def test_exported_markers_consistent_with_unicode_ok():
    # The module-level constants are resolved once at import against the real
    # UNICODE_OK; assert they match whichever branch was taken.
    if _status.UNICODE_OK:
        assert _status.CHECK == "✅"
        assert _status.WARN == "⚠️"
        assert _status.CROSS == "❌"
        assert _status.INFO == "ℹ️"
    else:
        assert _status.CHECK == "[OK]"
        assert _status.WARN == "[!]"
        assert _status.CROSS == "[X]"
        assert _status.INFO == "[i]"
