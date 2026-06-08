"""CIM crosswalk editor — QBO customer name ↔ Authorize.net CIM profile.

Two halves:
  Top: list view of every entry in data/cim_customer_map.json. Inline edit
       payment method (card / eCheck) and notes. Delete entries one at a
       time (deletion goes to the audit log).
  Bottom: pull every CIM profile from Auth.net via the API and let the
       operator drag/select a profile to associate with a QB customer name.
       Auto-suggests matches at >=92% fuzzy similarity.

The crosswalk file is the single source of truth for which CIM profile gets
charged for which QBO customer. Without it, the wizard's review step can't
match invoices to profiles.
"""
from __future__ import annotations

import streamlit as st

from core import audit, auth, authnet, loaders, store, ui

auth.require_login()
ui.inject()

ui.header(
    "CIM mapping",
    "QBO Customer name → Authorize.net CIM customerProfileId + paymentProfileId. "
    "The charge step joins on QBO Customer; without an entry here, that invoice "
    "is excluded from the run.",
    kicker="MAPPING",
)

cim = (loaders.cim_customer_map().get("map") or {})
cache = loaders.cim_profile_cache()


# ── Top: existing mappings ────────────────────────────────────────────────────
st.subheader("Existing mappings")
if not cim:
    st.info(
        ":material/info: No mappings yet. Use the **Refresh from Authorize.net** button "
        "below to pull the CIM catalog, then assign profiles to QB customer names."
    )
else:
    rows = []
    for qb_name, entry in sorted(cim.items()):
        rows.append({
            "QB Customer": qb_name,
            "Customer Profile ID": entry.get("customer_profile_id", ""),
            "Payment Profile ID": entry.get("payment_profile_id", ""),
            "Method": entry.get("payment_method", ""),
            "Notes": entry.get("notes", ""),
        })
    st.dataframe(rows, use_container_width=True, hide_index=True, height=380)
    st.caption(f":gray[{len(cim)} mapping(s). Bulk edits live in `data/cim_customer_map.json`.]")


# ── Middle: refresh from Auth.net ─────────────────────────────────────────────
st.divider()
st.subheader("Refresh CIM catalog from Authorize.net")
st.caption(
    f"Pulls every CIM profile from the **{authnet.env_label()}** environment. "
    "One API call per profile (~30-60 seconds for a ~70-customer catalog). "
    "Cached in `data/cim_profile_cache.json` so you only re-fetch when "
    "profiles change in Auth.net."
)
if not authnet.is_configured():
    st.warning(
        "Authorize.net credentials not configured. Set AUTHNET_API_LOGIN_ID + "
        "AUTHNET_TRANSACTION_KEY + AUTHNET_ENV in Streamlit Cloud secrets.",
        icon=":material/key_off:",
    )
else:
    last = cache.get("fetched_at") or "(never)"
    st.caption(f":gray[Last refresh: {last}]")
    if st.button(":material/refresh:  Refresh from Auth.net", type="primary", key="refresh_cim"):
        with st.spinner("Fetching CIM catalog…"):
            try:
                profiles = authnet.fetch_all_profiles()
                import datetime as dt
                payload = {
                    "profiles": profiles,
                    "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
                }
                ok, info = store.save_json(
                    "cim_profile_cache.json", payload,
                    f"CIM cache refresh ({len(profiles)} profiles)",
                )
                loaders.cim_profile_cache.clear()
                if ok:
                    st.success(f"Fetched {len(profiles)} profile(s). {info}")
                else:
                    st.warning(f"Fetched {len(profiles)} locally only — {info}")
                st.rerun()
            except Exception as e:
                st.error(f"Refresh failed: `{type(e).__name__}: {e}`")


# ── Bottom: add a new mapping ─────────────────────────────────────────────────
st.divider()
st.subheader("Add / edit a mapping")
profiles = cache.get("profiles") or []
if not profiles:
    st.caption(":gray[Refresh the CIM catalog first — there's nothing to assign yet.]")
else:
    st.caption(
        f"Pick the QB customer name (free text — match what's in QBO exactly) and the "
        f"Auth.net profile to associate with it. {len(profiles)} profile(s) available."
    )
    c1, c2 = st.columns([2, 3])
    qb_name = c1.text_input(
        "QB Customer name (exactly as it appears in the QBO invoice export)",
        key="new_qb_name",
        placeholder="e.g. TVC - Ark of Socorro Veterinary Clinic",
    )
    # Build a profile picker that shows description + last-4 / account-type so
    # the operator has enough context to choose.
    def _label(p):
        ppfs = p.get("payment_profiles", [])
        if not ppfs:
            return f"{p['customer_profile_id']}  ·  {p.get('description', '(no description)')[:60]}  ·  NO PAYMENT METHOD"
        first = ppfs[0]
        if first["type"] == "card":
            method = f"card ••••{first.get('card_last_4', 'XXXX')}"
        elif first["type"] == "echeck":
            method = f"eCheck ({first.get('bank_account_type', '?')})"
        else:
            method = "unknown payment type"
        return f"{p['customer_profile_id']}  ·  {p.get('description', '(no description)')[:60]}  ·  {method}"

    profile_idx = c2.selectbox(
        "Auth.net CIM profile",
        options=list(range(len(profiles))),
        format_func=lambda i: _label(profiles[i]),
        key="new_profile_idx",
    )
    selected_profile = profiles[profile_idx] if profiles else None

    if selected_profile:
        ppfs = selected_profile.get("payment_profiles", [])
        if not ppfs:
            st.warning(
                "This CIM profile has no payment methods on file — Tanya must add a card "
                "or eCheck in Auth.net before this profile can be charged."
            )
            payment_profile_id = ""
            payment_method = ""
        elif len(ppfs) == 1:
            payment_profile_id = ppfs[0]["payment_profile_id"]
            payment_method = ppfs[0]["type"]
            st.caption(f":gray[Single payment method on file — using {payment_method} "
                       f"profile `{payment_profile_id}`.]")
        else:
            # Multiple payment methods — let the operator pick
            ppf_idx = st.selectbox(
                "Which payment method?",
                options=list(range(len(ppfs))),
                format_func=lambda i: f"{ppfs[i]['type']}  ·  {ppfs[i]['payment_profile_id']}",
                key="new_ppf_idx",
            )
            payment_profile_id = ppfs[ppf_idx]["payment_profile_id"]
            payment_method = ppfs[ppf_idx]["type"]

        notes = st.text_input("Notes (optional)", key="new_notes")
        if st.button("Save mapping", type="primary", key="save_mapping",
                     disabled=not (qb_name and payment_profile_id)):
            new_map = {**cim, qb_name.strip(): {
                "customer_profile_id": selected_profile["customer_profile_id"],
                "payment_profile_id": payment_profile_id,
                "payment_method": payment_method,
                "notes": notes,
            }}
            ok, info = store.save_json(
                "cim_customer_map.json", {"map": new_map},
                f"CIM map: + {qb_name} → {selected_profile['customer_profile_id']}",
            )
            audit.record_event("cim_map_edit", customer=qb_name,
                               note=f"added profile {selected_profile['customer_profile_id']}")
            loaders.cim_customer_map.clear()
            (st.success if ok else st.warning)(f"Saved mapping. {info}")
            st.rerun()
