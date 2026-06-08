"""Oncura Billing — DocuSign monthly batch charge automation.

A four-step wizard that takes Tanya from "QBO invoice export in hand" to
"charges processed + SaasAnt file ready to upload" without one-at-a-time
entry into Authorize.net.

Wizard:
  1. Cycle setup   — month, payment date, reference label
  2. Upload        — QBO invoice report; parse + triage; flag unmatched CIM
  3. Review        — per-invoice table (customer · open balance · CIM profile ·
                     payment method · charge?); operator confirms
  4. Charge & results — submit each row through Authorize.net; collect
                     approved / declined / error; download SaasAnt + declines

Audit: every cycle start / charge attempt / outcome is recorded in
data/charge_log.json (GitHub-backed). Re-running the same QBO export
detects already-charged fingerprints and skips them.

Phase 1 (this build): scaffolding + parser + SaasAnt output + Auth.net client
behind a "creds not configured" gate. Phase 2 = sandbox testing + live cycle.

Run locally:  ONCURA_BILLING_LOCAL=1 streamlit run app.py
"""
from __future__ import annotations

import datetime as dt
import io

import pandas as pd
import streamlit as st

from core import audit, auth, authnet, loaders, qbo_import, saasant_out, ui

st.set_page_config(page_title="Oncura Billing", page_icon="*", layout="wide")
auth.require_login()
ui.inject()


# ── Header + identity strip ───────────────────────────────────────────────────
ui.header(
    "DocuSign monthly billing",
    "Upload the QBO invoice report → review the matches → submit all charges → "
    "download the SaasAnt receive-payments file + declines report.",
    kicker="ONCURA · AUTH.NET CYCLE",
)

id_l, id_r = st.columns([5, 1])
id_l.markdown(
    f"<span style='font-family: var(--mono); color: var(--muted); font-size: .8rem; "
    f"letter-spacing: .08em;'>"
    f"OPERATOR: <b style='color: var(--ink)'>{auth.current_initials()}</b>"
    f" · AUTH.NET ENV: <b style='color: var(--ink)'>{authnet.env_label()}</b></span>",
    unsafe_allow_html=True,
)
if id_r.button("Log out", key="logout_btn", use_container_width=True):
    auth.logout()
    st.rerun()

# Big visible banner when running against the sandbox so operator is never
# confused about whether charges are real.
_env = authnet.env_label()
if _env == "production":
    st.error(
        ":material/warning: **PRODUCTION** — charges submitted here are REAL. "
        "Switch AUTHNET_ENV to 'sandbox' in Streamlit secrets to test safely.",
        icon=":material/warning:",
    )
elif _env == "sandbox":
    st.info(
        ":material/science: **SANDBOX** — charges submitted here are TEST transactions. "
        "Flip AUTHNET_ENV to 'production' in Streamlit secrets when ready for live billing.",
        icon=":material/science:",
    )
else:
    st.warning(
        ":material/warning: **Authorize.net credentials not configured.** The wizard can "
        "parse uploads and preview matches, but the charge step will be disabled until "
        "AUTHNET_API_LOGIN_ID + AUTHNET_TRANSACTION_KEY + AUTHNET_ENV are set in Streamlit "
        "Cloud secrets. Sign up for a free sandbox at https://sandbox.authorize.net to start.",
        icon=":material/key_off:",
    )

st.divider()


# ── Wizard state ──────────────────────────────────────────────────────────────
SS = st.session_state
SS.setdefault("step", 0)
today = dt.date.today()
SS.setdefault("cycle_year", today.year if today.day >= 10 else (today.year if today.month > 1 else today.year - 1))
SS.setdefault("cycle_month", today.month if today.day >= 10 else (today.month - 1 or 12))
SS.setdefault("payment_date", today)
SS.setdefault("reference_label", "DocuSign")
SS.setdefault("uploaded_bytes", None)
SS.setdefault("uploaded_name", None)
SS.setdefault("parsed_df", None)
SS.setdefault("approved", [])
SS.setdefault("declined", [])
SS.setdefault("errors", [])
SS.setdefault("cycle_id", None)

STEPS = [
    ("setup", "Cycle setup"),
    ("upload", "Upload invoice report"),
    ("review", "Match & review"),
    ("results", "Process & results"),
]
SS["step"] = max(0, min(SS["step"], len(STEPS) - 1))
step_key, step_label = STEPS[SS["step"]]
ui.scroll_top_on_step_change("billing_wizard", SS["step"])

st.markdown(f"**Step {SS['step'] + 1} of {len(STEPS)} — {step_label}**")
st.progress((SS["step"] + 1) / len(STEPS))
st.caption("  ·  ".join(
    f"**{lbl}**" if i == SS["step"] else f":gray[{lbl}]"
    for i, (_, lbl) in enumerate(STEPS)
))


# ── Step content ──────────────────────────────────────────────────────────────
with st.container(border=True):
    if step_key == "setup":
        st.markdown("### Cycle setup")
        st.caption(
            "Pick the billing period (the month being charged FOR — typically the prior "
            "month) and the payment date you'll record against the QBO receive-payments."
        )
        c1, c2 = st.columns(2)
        SS.cycle_month = int(c1.selectbox(
            "Billing month", list(range(1, 13)),
            index=SS.cycle_month - 1,
            format_func=lambda m: dt.date(2000, m, 1).strftime("%B"),
            key="w_cycle_month",
        ))
        SS.cycle_year = int(c2.number_input(
            "Billing year", value=SS.cycle_year, step=1, key="w_cycle_year"))
        c3, c4 = st.columns(2)
        SS.payment_date = c3.date_input(
            "Payment date (when the bank deposit hits)",
            value=SS.payment_date, key="w_payment_date",
        )
        SS.reference_label = c4.text_input(
            "Reference label (appears in the QBO Reference No column)",
            value=SS.reference_label, key="w_ref_label",
        )

    elif step_key == "upload":
        st.markdown("### Upload QBO invoice report")
        st.caption(
            f"Drop the QBO 'Invoice Report' xlsx for **{dt.date(SS.cycle_year, SS.cycle_month, 1):%B %Y}**. "
            "Columns expected: Date · Num · Customer · Amount · Open balance."
        )
        up = st.file_uploader(
            "Invoice report (xlsx)",
            type=["xlsx", "xls"],
            key="w_invoice_file",
        )
        if up is not None:
            is_new = (up.name != SS.uploaded_name or SS.uploaded_bytes is None)
            SS.uploaded_bytes = up.getvalue()
            SS.uploaded_name = up.name
            if is_new:
                try:
                    SS.parsed_df = qbo_import.read_invoice_report(io.BytesIO(SS.uploaded_bytes))
                except Exception as e:
                    st.error(f"**Could not parse the file:** `{type(e).__name__}: {e}`")
                    SS.parsed_df = None
                st.rerun()
            st.success(f"Uploaded: **{up.name}** ({len(SS.uploaded_bytes) // 1024:,} KB)")
        elif SS.uploaded_bytes:
            st.info(
                f"Previously uploaded: **{SS.uploaded_name}** — "
                "re-upload to replace, or click Next to continue."
            )

        if SS.parsed_df is not None and not SS.parsed_df.empty:
            df = SS.parsed_df
            triage = qbo_import.split_chargeable(df, min_amount=0.01, max_amount=10000.0)
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Rows parsed", len(df))
            m2.metric("Chargeable", len(triage["chargeable"]))
            m3.metric("Flagged (large)", len(triage["flagged_large"]))
            m4.metric("Open balance total", f"${df['open_balance'].sum():,.2f}")
            with st.expander(f":gray[Preview parsed rows ({len(df)})]"):
                st.dataframe(df, use_container_width=True, height=320)
            if not triage["flagged_large"].empty:
                with st.expander(
                    f":orange[{len(triage['flagged_large'])} invoice(s) over $10,000 — review before charging]",
                    expanded=True,
                ):
                    st.dataframe(triage["flagged_large"], use_container_width=True)

    elif step_key == "review":
        st.markdown("### Match invoices to Auth.net CIM profiles")
        if SS.parsed_df is None or SS.parsed_df.empty:
            st.warning("Upload an invoice report first.")
        else:
            cim_map = (loaders.cim_customer_map().get("map") or {})
            df = SS.parsed_df.copy()
            # Join the CIM crosswalk
            df["customer_profile_id"] = df["customer"].map(
                lambda c: (cim_map.get(c) or {}).get("customer_profile_id", "")
            )
            df["payment_profile_id"] = df["customer"].map(
                lambda c: (cim_map.get(c) or {}).get("payment_profile_id", "")
            )
            df["payment_method"] = df["customer"].map(
                lambda c: (cim_map.get(c) or {}).get("payment_method", "")
            )
            matched = df[df["customer_profile_id"].astype(bool)]
            unmatched = df[~df["customer_profile_id"].astype(bool)]
            m1, m2, m3 = st.columns(3)
            m1.metric("Matched to CIM", len(matched))
            m2.metric("Unmatched", len(unmatched))
            m3.metric("Will charge (matched, open>0)", f"${matched['open_balance'].sum():,.2f}")
            if not unmatched.empty:
                st.warning(
                    f":material/warning: **{len(unmatched)} invoice(s) have no CIM profile mapping** — "
                    "they'll be excluded from the charge run. Open the **CIM Mapping** page "
                    "(sidebar) to add the missing QBO-customer → Auth.net-profile entries, "
                    "then come back and click Next again.",
                    icon=":material/warning:",
                )
                with st.expander(f"Unmatched customers ({len(unmatched)})", expanded=True):
                    st.dataframe(
                        unmatched[["customer", "invoice_num", "open_balance"]],
                        use_container_width=True, hide_index=True,
                    )
            st.markdown("#### Will charge")
            st.dataframe(
                matched[["customer", "invoice_num", "open_balance",
                         "payment_method", "customer_profile_id"]],
                use_container_width=True, hide_index=True, height=360,
            )

    elif step_key == "results":
        st.markdown("### Process charges + results")
        st.info(
            "This step runs the charges through Authorize.net. Each charge is "
            "submitted individually so a single decline doesn't block the rest. "
            "Click **Process Charges** to begin — this is where money moves "
            "(or test-moves, in sandbox).",
            icon=":material/play_arrow:",
        )
        ui.persistence_warning()
        initials = ui.initials_input("stage_charge_initials")
        can_charge = bool(initials) and authnet.is_configured() and SS.parsed_df is not None
        if not authnet.is_configured():
            st.warning(
                "Authorize.net credentials not configured — charging disabled. "
                "Add AUTHNET_API_LOGIN_ID + AUTHNET_TRANSACTION_KEY + AUTHNET_ENV "
                "in Streamlit Cloud secrets to enable.",
                icon=":material/key_off:",
            )
        if ui.record_button(
            "Process charges (real charges in production env)",
            key="run_charges",
            disabled=not can_charge,
            use_container_width=True,
        ):
            st.warning(
                "Charge submission not yet wired into the wizard — Phase 2 work. "
                "The Authorize.net client (`core/authnet.py`) and the SaasAnt output "
                "builder (`core/saasant_out.py`) are both ready; the only piece left is "
                "the per-row submit loop + result collection. Will be filled in once "
                "sandbox credentials are configured and tested."
            )

# ── Navigation ────────────────────────────────────────────────────────────────
st.divider()
nav_reset, nav_msg, nav_b, nav_n = st.columns([1.6, 3.4, 1, 1])
if nav_reset.button("◀ Back to Setup", key="reset_btn", use_container_width=True):
    for k in ("uploaded_bytes", "uploaded_name", "parsed_df",
              "approved", "declined", "errors", "cycle_id",
              "w_invoice_file"):
        SS.pop(k, None)
    SS["step"] = 0
    st.rerun()

can_back = SS["step"] > 0
can_next = SS["step"] < len(STEPS) - 1
next_blocked = ""
if step_key == "upload" and SS.parsed_df is None:
    can_next = False
    next_blocked = "Upload a parsed invoice report before continuing."

if not can_next and next_blocked:
    nav_msg.caption(f":orange[{next_blocked}]")

if can_back and nav_b.button("← Back", key=f"back_{SS['step']}", use_container_width=True):
    SS["step"] -= 1
    st.rerun()
if SS["step"] < len(STEPS) - 1:
    if nav_n.button("Next →", key=f"next_{SS['step']}", type="primary",
                    disabled=not can_next, use_container_width=True):
        SS["step"] += 1
        st.rerun()
else:
    nav_n.markdown("**Done ✓**")
