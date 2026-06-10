"""Combined password + initials login gate for the billing app.

Tanya runs charges from this app — every audit-log entry needs an
attributable approver. The login captures initials at the same moment
as the password so the audit trail starts cleanly.

Same APP_PASSWORD as oncura-programs / oncura-apps. Local dev bypass:
set ONCURA_BILLING_LOCAL=1 to skip the gate.
"""
from __future__ import annotations

import hmac
import os

import streamlit as st


def _secret(key, default=None):
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


def _pw_match(entered, expected) -> bool:
    """Constant-time password comparison. The app will sit on a public Cloud
    URL, so the equality check must not leak match-prefix length via timing.
    Same pattern as oncura-flex-rebate-app core/auth.py."""
    if not expected:
        return False
    return hmac.compare_digest(
        str(entered).encode("utf-8"), str(expected).encode("utf-8")
    )


def require_login():
    if st.session_state.get("auth_ok"):
        return

    app_pw = _secret("APP_PASSWORD")
    if not app_pw:
        if os.environ.get("ONCURA_BILLING_LOCAL") == "1":
            st.session_state["auth_ok"] = True
            st.session_state["user_initials"] = "DEV"
            return
        st.error(
            "App password not configured. Set `APP_PASSWORD` in Streamlit secrets. "
            "For local dev, run with env var `ONCURA_BILLING_LOCAL=1`."
        )
        st.stop()

    from . import ui

    ui.inject()
    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"] { display: none !important; }
        [data-testid="stSidebarCollapsedControl"] { display: none !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        ui.header("DocuSign Billing", kicker="Oncura · Monthly Auth.net Cycle")
        st.caption(
            "Password + initials. Initials are recorded on every charge attempt "
            "so the audit trail attributes each transaction to an operator."
        )
        with st.form("login_form", clear_on_submit=False):
            entered_pw = st.text_input("Password", type="password")
            entered_initials = st.text_input(
                "Your initials",
                max_chars=4,
                placeholder="e.g. AJ",
                help="2–4 characters. Persists for this session.",
            )
            submitted = st.form_submit_button("Enter", type="primary", use_container_width=True)
        if submitted:
            if not _pw_match(entered_pw, app_pw):
                st.error("Incorrect password.")
                st.stop()
            initials = (entered_initials or "").strip().upper()
            if not initials:
                st.error("Initials are required for the audit log.")
                st.stop()
            st.session_state["auth_ok"] = True
            st.session_state["user_initials"] = initials
            st.rerun()
    st.stop()


def current_initials() -> str:
    return st.session_state.get("user_initials", "")


def logout():
    for k in ("auth_ok", "user_initials"):
        st.session_state.pop(k, None)
