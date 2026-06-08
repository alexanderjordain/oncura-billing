"""Audit log fingerprint + record tests."""
from __future__ import annotations

from core import audit


def test_fingerprint_stability():
    fp1 = audit.fingerprint("46055", "Acme Vet", 450.00, "2026-05")
    fp2 = audit.fingerprint("46055", "Acme Vet", 450.00, "2026-05")
    assert fp1 == fp2
    assert len(fp1) == 64  # sha256


def test_fingerprint_customer_case_insensitive():
    """Customer name case shouldn't matter — same charge."""
    fp1 = audit.fingerprint("46055", "Acme Vet", 450.00, "2026-05")
    fp2 = audit.fingerprint("46055", "ACME VET", 450.00, "2026-05")
    assert fp1 == fp2


def test_fingerprint_amount_uses_cents():
    """Float-noise immunity: 450.00 == 450.0000000001."""
    fp1 = audit.fingerprint("46055", "Acme Vet", 450.00, "2026-05")
    fp2 = audit.fingerprint("46055", "Acme Vet", 450.0000001, "2026-05")
    assert fp1 == fp2


def test_fingerprint_distinguishes_periods():
    """Same invoice + customer + amount, different month = different fingerprint
    (so re-charging the same clinic next month doesn't collide)."""
    fp1 = audit.fingerprint("46055", "Acme Vet", 450.00, "2026-05")
    fp2 = audit.fingerprint("46055", "Acme Vet", 450.00, "2026-06")
    assert fp1 != fp2


def test_fingerprint_distinguishes_amounts():
    fp1 = audit.fingerprint("46055", "Acme Vet", 450.00, "2026-05")
    fp2 = audit.fingerprint("46055", "Acme Vet", 500.00, "2026-05")
    assert fp1 != fp2


def test_entry_hash_changes_with_content():
    e1 = {"id": "x", "amount": 100, "customer": "A"}
    e2 = {"id": "x", "amount": 200, "customer": "A"}
    assert audit._entry_hash(e1) != audit._entry_hash(e2)


def test_entry_hash_ignores_self_field():
    """If the entry_hash field is included in the entry, recomputing should
    give the same result whether the prior hash is present or not."""
    e = {"id": "x", "amount": 100, "customer": "A"}
    h = audit._entry_hash(e)
    e_with_hash = {**e, "entry_hash": h}
    assert audit._entry_hash(e_with_hash) == h
