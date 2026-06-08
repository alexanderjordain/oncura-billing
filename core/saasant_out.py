"""SaasAnt "Received Payments" output builder.

Same schema and column names as oncura-programs/core/flex_finance.py uses for
its receive-payments imports — verified columns SaasAnt's QBO connector expects
for the Received Payments import type.

Hard rule: 'Ref No (Receive Payment No)' must be UNIQUE per row, or SaasAnt
collapses everything onto one payment booked against the first customer. The
Authorize.net transaction ID makes a natural unique ref since each charge
gets its own.
"""
from __future__ import annotations

import datetime as dt
import io

import pandas as pd

# SaasAnt's required columns for a Received Payments import (matches
# flex_finance.RECEIVE_PAYMENT_COLS in oncura-programs).
RECEIVE_PAYMENT_COLS = [
    "PaymentDate",
    "Customer",
    "Payment Method",
    "Deposit To Account Name",
    "Ref No (Receive Payment No)",
    "Amount",
    "Reference No",
]

PAYMENT_METHOD_CARD = "Credit Card"
PAYMENT_METHOD_ECHECK = "eCheck"
DEPOSIT_TO = "Undeposited Funds"


def _date_str(d) -> str:
    if isinstance(d, str):
        return d
    if isinstance(d, dt.date):
        return d.strftime("%m/%d/%Y")
    try:
        return d.strftime("%m/%d/%Y")
    except AttributeError:
        return str(d)


def build_received_payments(
    approved_charges: list[dict],
    *,
    payment_date: dt.date | str,
    reference_label: str = "DocuSign",
) -> pd.DataFrame:
    """Build the SaasAnt Received Payments import from approved Auth.net charges.

    `approved_charges` items shape:
        {
            "customer": "TVC - Ark of Socorro Veterinary Clinic",   # QBO Customer display name
            "amount": 811.25,                                        # Open balance charged
            "auth_net_transaction_id": "60123456789",                # unique per row
            "payment_method": "card" | "echeck",                     # from CIM profile type
            "invoice_num": "46055",                                  # QBO invoice the charge pays
        }

    `payment_date` is the day Tanya processed the batch.

    Validates uniqueness of Ref No before returning — SaasAnt's silent
    row-collapse-on-duplicate-ref bug is the failure mode this catches.
    """
    rows = []
    for c in approved_charges:
        rows.append({
            "PaymentDate": _date_str(payment_date),
            "Customer": c["customer"],
            "Payment Method": PAYMENT_METHOD_ECHECK if c.get("payment_method") == "echeck" else PAYMENT_METHOD_CARD,
            "Deposit To Account Name": DEPOSIT_TO,
            "Ref No (Receive Payment No)": str(c["auth_net_transaction_id"]),
            "Amount": round(float(c["amount"]), 2),
            "Reference No": reference_label,
        })
    df = pd.DataFrame(rows, columns=RECEIVE_PAYMENT_COLS)
    if not df.empty:
        _assert_unique_refs(df["Ref No (Receive Payment No)"])
    return df


def build_declines_report(declined_or_error: list[dict]) -> pd.DataFrame:
    """Per-row list of attempts that did NOT result in a clean payment.
    Tanya uses this to follow up — re-attempt later, contact the clinic, or
    add a new payment method to their CIM profile.

    `declined_or_error` items shape:
        {
            "customer": ..., "invoice_num": ..., "amount": ...,
            "outcome": "declined" | "error" | "unmapped",
            "reason": "Insufficient funds" | "No CIM profile mapped" | ...,
            "auth_net_response_code": "2",  # optional
        }
    """
    if not declined_or_error:
        return pd.DataFrame(columns=[
            "Customer", "Invoice #", "Amount", "Outcome", "Reason", "Auth.net code",
        ])
    rows = [{
        "Customer": d.get("customer", ""),
        "Invoice #": d.get("invoice_num", ""),
        "Amount": round(float(d.get("amount", 0.0) or 0.0), 2),
        "Outcome": d.get("outcome", ""),
        "Reason": d.get("reason", ""),
        "Auth.net code": d.get("auth_net_response_code", ""),
    } for d in declined_or_error]
    return pd.DataFrame(rows)


def to_xlsx_bytes(df: pd.DataFrame, sheet_name: str = "Import") -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.to_excel(xw, index=False, sheet_name=sheet_name[:31])
    return buf.getvalue()


def _assert_unique_refs(values) -> None:
    vals = list(values)
    if len(set(vals)) != len(vals):
        dupes = {v for v in vals if vals.count(v) > 1}
        raise ValueError(
            f"Non-unique Ref No in Received Payments (SaasAnt will collapse rows): "
            f"{sorted(map(str, dupes))[:10]}"
        )
