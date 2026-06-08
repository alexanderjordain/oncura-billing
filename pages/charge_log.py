"""Charge log — per-run audit view of every charge attempt + outcome.

Read-only. Same shape as oncura-apps/pages/access_log.py — list the recent
entries, surface integrity-check status, and break down by initials / event.
"""
from __future__ import annotations

import streamlit as st

from core import audit, auth, ui

auth.require_login()
ui.inject()

ui.header(
    "Charge log",
    "Every cycle start, charge attempt, outcome, and approval is recorded here. "
    "Per-entry SHA-256 hashes; the GitHub commit history on `data/charge_log.json` "
    "is the authoritative trail.",
    kicker="AUDIT",
)

s = audit.summary()
m1, m2, m3, m4 = st.columns(4)
m1.metric("Entries", s["entry_count"])
m2.metric("Distinct operators", len(s["by_initials"]))
m3.metric("Total $ approved", f"${s['total_charged_approved']:,.2f}")
m4.metric(
    "Latest event",
    (s["latest_timestamp"] or "—")[:19].replace("T", " "),
)

ok, tampered = audit.verify_integrity()
if ok:
    st.success(
        f":material/verified: All {s['entry_count']} entry hashes verify cleanly.",
        icon=":material/verified:",
    )
else:
    st.error(
        f":material/error: {len(tampered)} entrie(s) failed hash verification: "
        f"`{', '.join(tampered[:5])}`. Compare against `data/charge_log.json` on origin/main."
    )

st.markdown("### Recent activity")
limit = st.slider("Entries to show", min_value=20, max_value=1000, value=200, step=20)
entries = audit.list_entries(limit=limit)

if not entries:
    st.info("No charge-log entries yet — the first cycle run will populate this.")
else:
    rows = [
        {
            "Timestamp": e.get("timestamp", "")[:19].replace("T", " "),
            "Operator": e.get("initials", ""),
            "Event": e.get("event", ""),
            "Customer": e.get("customer") or "—",
            "Invoice #": e.get("invoice_num") or "—",
            "Amount": f"${float(e['amount']):,.2f}" if e.get("amount") is not None else "—",
            "Auth.net Txn": e.get("auth_net_transaction_id") or "—",
            "Reason": e.get("response_reason") or e.get("note") or "",
        }
        for e in entries
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True, height=520)


with st.expander(":gray[Per-event counts]"):
    if not s["by_event"]:
        st.caption("No entries yet.")
    else:
        st.dataframe(
            [{"Event": k, "Count": v} for k, v in sorted(s["by_event"].items(), key=lambda kv: -kv[1])],
            use_container_width=True,
            hide_index=True,
        )

with st.expander(":gray[Per-operator counts]"):
    if not s["by_initials"]:
        st.caption("No entries yet.")
    else:
        st.dataframe(
            [{"Operator": k, "Events": v} for k, v in sorted(s["by_initials"].items(), key=lambda kv: -kv[1])],
            use_container_width=True,
            hide_index=True,
        )
