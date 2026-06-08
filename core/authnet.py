"""Authorize.net CIM client — minimal, JSON-only.

Three operations the app needs:
  list_customer_profile_ids()     -> [profile_id, ...]
  get_customer_profile(pid)       -> {id, description, email, payment_profiles: [...]}
  create_transaction(pid, ppid, amount, invoice_num)  -> {ok, transaction_id, response_code, reason}

Auth.net's API takes one JSON envelope at a single endpoint
(`/xml/v1/request.api` despite the JSON in/out). Sandbox vs production is
controlled by AUTHNET_ENV in Streamlit secrets. ALWAYS start in sandbox.

PCI scope: we reference stored profile IDs only. NO raw card data ever flows
through this module. Don't add code that accepts or stores card / bank
numbers — keeps Oncura's PCI footprint at SAQ-A or below.

Status: stubs are correct against the documented API but UNTESTED until
sandbox credentials are configured. Once AUTHNET_API_LOGIN_ID and
AUTHNET_TRANSACTION_KEY are set (and AUTHNET_ENV = 'sandbox'), the
existing functions will work — no code changes needed.
"""
from __future__ import annotations

import os
from typing import Iterable

try:
    import requests
except ImportError:
    requests = None


SANDBOX_ENDPOINT = "https://apitest.authorize.net/xml/v1/request.api"
PRODUCTION_ENDPOINT = "https://api.authorize.net/xml/v1/request.api"

REQUEST_TIMEOUT = 30


# ── Configuration ────────────────────────────────────────────────────────────
def _secret(key: str, default=None):
    """Pull from Streamlit secrets first, env var fallback."""
    try:
        import streamlit as st

        v = st.secrets.get(key)
        if v:
            return v
    except Exception:
        pass
    return os.environ.get(key, default)


def _config() -> dict:
    login = _secret("AUTHNET_API_LOGIN_ID")
    key = _secret("AUTHNET_TRANSACTION_KEY")
    env = (_secret("AUTHNET_ENV", "sandbox") or "sandbox").strip().lower()
    if not login or not key:
        raise RuntimeError(
            "Authorize.net credentials not configured. Set "
            "AUTHNET_API_LOGIN_ID + AUTHNET_TRANSACTION_KEY in Streamlit secrets. "
            "Start in sandbox (AUTHNET_ENV='sandbox') before flipping to production."
        )
    endpoint = PRODUCTION_ENDPOINT if env == "production" else SANDBOX_ENDPOINT
    return {"login": login, "key": key, "env": env, "endpoint": endpoint}


def is_configured() -> bool:
    """Quick check — does the app have working creds in scope? Used by the UI
    to grey out the charge flow when no creds are set."""
    try:
        _config()
        return True
    except Exception:
        return False


def env_label() -> str:
    """'sandbox' or 'production' — surfaced in the UI so the operator can never
    accidentally hit prod thinking they're testing."""
    try:
        return _config()["env"]
    except Exception:
        return "(not configured)"


# ── Low-level request ────────────────────────────────────────────────────────
def _post(payload: dict) -> dict:
    if requests is None:
        raise RuntimeError("`requests` is required but not installed.")
    cfg = _config()
    # Auth.net envelope: merchantAuthentication is appended to whatever
    # request body the caller built.
    op_name = next(iter(payload.keys()))
    payload[op_name] = {
        "merchantAuthentication": {"name": cfg["login"], "transactionKey": cfg["key"]},
        **payload[op_name],
    }
    r = requests.post(cfg["endpoint"], json=payload, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    # Auth.net returns JSON-with-BOM. Strip the BOM if present.
    text = r.text.lstrip("﻿")
    import json
    return json.loads(text)


# ── Customer profile listing ─────────────────────────────────────────────────
def list_customer_profile_ids() -> list[str]:
    """Pull every CIM profile ID for the merchant. Returns string IDs because
    Auth.net's API treats them as opaque tokens (numeric in practice today,
    but never assume).

    Used once on first run to populate the QBO→CIM crosswalk. Re-fetched
    when the operator hits "refresh from Auth.net" on the mapping page.
    """
    resp = _post({"getCustomerProfileIdsRequest": {}})
    ids = resp.get("ids", []) or []
    if isinstance(ids, dict):
        # Single-profile response sometimes shapes as {numericString: "..."}
        single = ids.get("numericString") or ids.get("string") or []
        if isinstance(single, str):
            return [single]
        return list(single)
    return [str(x) for x in ids]


def get_customer_profile(profile_id: str) -> dict:
    """Fetch one CIM profile's details — description, email, and payment
    profiles (card/eCheck details, IDs we need to submit a charge against).

    Returns the normalized shape:
        {
            "customer_profile_id": "...",
            "description": "...",     # often the customer name as Tanya knows them
            "email": "...",
            "merchant_customer_id": "...",  # optional, sometimes a QB customer ID
            "payment_profiles": [
                {
                    "payment_profile_id": "...",
                    "type": "card" | "echeck",
                    "card_last_4": "XXXX",   # for card profiles
                    "bank_account_type": "checking" | "savings",  # for eCheck
                },
                ...
            ],
        }
    """
    resp = _post({
        "getCustomerProfileRequest": {"customerProfileId": str(profile_id)}
    })
    profile = resp.get("profile") or {}
    pp_list = profile.get("paymentProfiles") or []
    # Single-profile responses sometimes return a dict instead of a list of one.
    if isinstance(pp_list, dict):
        pp_list = [pp_list]

    payment_profiles = []
    for pp in pp_list:
        payment = pp.get("payment") or {}
        if "creditCard" in payment:
            cc = payment["creditCard"]
            payment_profiles.append({
                "payment_profile_id": str(pp.get("customerPaymentProfileId", "")),
                "type": "card",
                "card_last_4": (cc.get("cardNumber") or "").replace("X", "")[-4:] or "XXXX",
                "card_type": cc.get("cardType", ""),
            })
        elif "bankAccount" in payment:
            ba = payment["bankAccount"]
            payment_profiles.append({
                "payment_profile_id": str(pp.get("customerPaymentProfileId", "")),
                "type": "echeck",
                "bank_account_type": ba.get("accountType", ""),
                "name_on_account": ba.get("nameOnAccount", ""),
            })
        else:
            # Unknown payment-method type — record what we have so the UI can
            # surface it as "unsupported, investigate" rather than dropping it.
            payment_profiles.append({
                "payment_profile_id": str(pp.get("customerPaymentProfileId", "")),
                "type": "unknown",
            })

    return {
        "customer_profile_id": str(profile.get("customerProfileId", profile_id)),
        "description": profile.get("description", "") or "",
        "email": profile.get("email", "") or "",
        "merchant_customer_id": profile.get("merchantCustomerId", "") or "",
        "payment_profiles": payment_profiles,
    }


def fetch_all_profiles() -> list[dict]:
    """Convenience: list IDs + fetch each profile's details. Used by the CIM
    mapping page's "Refresh from Auth.net" button.

    Slow — one HTTP call per profile. ~50-70 customers = 50-70 calls = ~30-60s.
    Cache the result in session_state; users only need to refresh when CIM
    profiles change in Auth.net.
    """
    ids = list_customer_profile_ids()
    return [get_customer_profile(pid) for pid in ids]


# ── Charge submission ────────────────────────────────────────────────────────
def create_transaction(
    *,
    customer_profile_id: str,
    payment_profile_id: str,
    amount: float,
    invoice_num: str | None = None,
    description: str | None = None,
) -> dict:
    """Submit a charge against a stored CIM profile. PCI-safe — references
    profile IDs only, never card / bank numbers.

    Returns:
        {
            "ok": bool,
            "transaction_id": str | None,
            "response_code": "1" (approved) | "2" (declined) | "3" (error) | "4" (held for review),
            "response_reason_code": str,
            "response_reason_text": str,
            "auth_code": str | None,
        }

    A response_code of "1" with an avs/cvv check failure inside the messages
    can still mean the charge processed. The UI / audit log records the full
    reason text so the operator can see the nuance.
    """
    payload = {
        "createTransactionRequest": {
            "transactionRequest": {
                "transactionType": "authCaptureTransaction",
                "amount": f"{round(float(amount), 2):.2f}",
                "profile": {
                    "customerProfileId": str(customer_profile_id),
                    "paymentProfile": {"paymentProfileId": str(payment_profile_id)},
                },
            }
        }
    }
    if invoice_num:
        payload["createTransactionRequest"]["transactionRequest"]["order"] = {
            "invoiceNumber": str(invoice_num),
            "description": description or f"Invoice {invoice_num}",
        }

    resp = _post(payload)
    tr = resp.get("transactionResponse") or {}
    msgs = (tr.get("messages") or [{}])
    first_msg = msgs[0] if isinstance(msgs, list) and msgs else (msgs if isinstance(msgs, dict) else {})
    response_code = str(tr.get("responseCode", ""))
    return {
        "ok": response_code == "1",
        "transaction_id": tr.get("transId") or None,
        "response_code": response_code,
        "response_reason_code": str(first_msg.get("code", "")),
        "response_reason_text": first_msg.get("description", "") or first_msg.get("text", ""),
        "auth_code": tr.get("authCode") or None,
        "raw": tr,  # full response for audit drill-down
    }
