"""Password-gate comparison behavior — constant-time matching."""
from __future__ import annotations

from core import auth


def test_pw_match_correct_password():
    assert auth._pw_match("s3cret", "s3cret")


def test_pw_match_wrong_password():
    assert not auth._pw_match("s3cret", "other")
    assert not auth._pw_match("", "other")
    assert not auth._pw_match("s3cre", "s3cret")  # prefix is not a match


def test_pw_match_empty_or_missing_expected_never_matches():
    # An unset/blank secret must never authenticate, even on empty input.
    assert not auth._pw_match("", "")
    assert not auth._pw_match("anything", "")
    assert not auth._pw_match("anything", None)


def test_pw_match_handles_non_ascii():
    # hmac.compare_digest rejects non-ASCII str — we compare utf-8 bytes.
    assert auth._pw_match("pässwörd", "pässwörd")
    assert not auth._pw_match("pässwörd", "password")
