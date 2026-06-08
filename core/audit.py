"""Per-cycle audit manifest — every charge attempt logged with full context.

Each entry: {id, timestamp, initials, event, invoice_num, customer, amount,
auth_net_transaction_id, response_code, response_reason, entry_hash}. The
entry_hash is sha256 of the entry's canonical JSON minus the hash itself;
the GitHub commit history on data/charge_log.json is the tamper trail.

Event types:
  cycle_start      — operator started a billing run
  charge_attempt   — submitted to Authorize.net (response pending)
  charge_approved  — Auth.net returned approved
  charge_declined  — Auth.net returned declined (with reason)
  charge_error     — request failed (network, malformed, profile missing)
  cycle_finalized  — operator confirmed batch + downloaded outputs

Persistence model identical to oncura-programs / oncura-apps: GitHub
Contents API when GITHUB_TOKEN is set, local file otherwise.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid

from . import store

LOG_PATH = "charge_log.json"

EVENT_TYPES = {
    "cycle_start",
    "charge_attempt",
    "charge_approved",
    "charge_declined",
    "charge_error",
    "cycle_finalized",
    "cim_map_edit",       # operator added/edited a QB→CIM mapping
}


def _empty():
    return {"version": 1, "entries": []}


def _load():
    data, sha = store.load_json(LOG_PATH, default=_empty())
    if not isinstance(data, dict) or "entries" not in data:
        data = _empty()
    return data, sha


def _sha256(s: bytes) -> str:
    return hashlib.sha256(s).hexdigest()


def _entry_hash(entry: dict) -> str:
    content = {k: v for k, v in entry.items() if k != "entry_hash"}
    return _sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8"))


def record_event(
    event: str,
    *,
    invoice_num: str | None = None,
    customer: str | None = None,
    amount: float | None = None,
    auth_net_transaction_id: str | None = None,
    response_code: str | None = None,
    response_reason: str | None = None,
    cycle_id: str | None = None,
    note: str = "",
):
    """Append an audit-log entry. Pulls initials from session_state.

    Returns (ok, entry_id, info). ok=False when no GITHUB_TOKEN is configured
    (local-only save).
    """
    import streamlit as st
    initials = st.session_state.get("user_initials", "UNKNOWN")

    if event not in EVENT_TYPES:
        note = f"[unknown event {event!r}] {note}".strip()

    data, sha = _load()
    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        "initials": initials,
        "event": event,
        "cycle_id": cycle_id,
        "invoice_num": invoice_num,
        "customer": customer,
        "amount": round(float(amount), 2) if amount is not None else None,
        "auth_net_transaction_id": auth_net_transaction_id,
        "response_code": response_code,
        "response_reason": response_reason,
        "note": note,
    }
    entry["entry_hash"] = _entry_hash(entry)
    data["entries"].append(entry)
    msg_parts = [event]
    if customer:
        msg_parts.append(customer)
    if amount is not None:
        msg_parts.append(f"${amount:,.2f}")
    msg = f"Charge log: {' · '.join(msg_parts)} ({initials})"
    ok, info = store.save_json(LOG_PATH, data, msg, sha=sha)
    return ok, entry["id"], info


def list_entries(limit: int | None = None, cycle_id: str | None = None):
    """Most-recent-first. Optional filter by cycle_id."""
    data, _ = _load()
    entries = list(data.get("entries", []))
    if cycle_id:
        entries = [e for e in entries if e.get("cycle_id") == cycle_id]
    entries.reverse()
    if limit is not None:
        return entries[:limit]
    return entries


def verify_integrity():
    data, _ = _load()
    tampered = []
    for entry in data.get("entries", []):
        if "entry_hash" not in entry:
            continue
        if _entry_hash(entry) != entry["entry_hash"]:
            tampered.append(entry["id"])
    return len(tampered) == 0, tampered


def summary():
    data, _ = _load()
    entries = data.get("entries", [])
    by_event: dict[str, int] = {}
    by_initials: dict[str, int] = {}
    total_charged = 0.0
    for e in entries:
        by_event[e.get("event", "?")] = by_event.get(e.get("event", "?"), 0) + 1
        by_initials[e.get("initials", "?")] = by_initials.get(e.get("initials", "?"), 0) + 1
        if e.get("event") == "charge_approved" and e.get("amount") is not None:
            total_charged += float(e["amount"])
    latest = max((e.get("timestamp", "") for e in entries), default="")
    return {
        "entry_count": len(entries),
        "by_event": by_event,
        "by_initials": by_initials,
        "total_charged_approved": round(total_charged, 2),
        "latest_timestamp": latest,
    }


# ── Idempotency / dedup ───────────────────────────────────────────────────────
def fingerprint(invoice_num: str, customer: str, amount: float, period: str) -> str:
    """Stable fingerprint for charge dedup. (invoice + customer + amount + period)
    is unique per legitimate charge — re-uploading the same QBO export collides
    on this fingerprint and gets skipped."""
    key = f"{(invoice_num or '').strip().upper()}|{(customer or '').strip().casefold()}|{round(float(amount), 2):.2f}|{period}"
    return _sha256(key.encode("utf-8"))


def fingerprints_seen(fps: list[str]) -> set[str]:
    """Return the subset of fingerprints already present in the charge log
    (only counts charge_approved + charge_attempt — declines + errors can
    legitimately be retried in the same cycle)."""
    data, _ = _load()
    seen: set[str] = set()
    for e in data.get("entries", []):
        if e.get("event") not in ("charge_approved", "charge_attempt"):
            continue
        if e.get("fingerprint"):
            seen.add(e["fingerprint"])
    return seen & set(fps)
