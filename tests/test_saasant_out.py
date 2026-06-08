"""SaasAnt Received Payments output tests."""
from __future__ import annotations

import datetime as dt

import pytest

from core import saasant_out


def test_build_received_payments_schema():
    df = saasant_out.build_received_payments(
        [{
            "customer": "Acme Vet", "amount": 450.00,
            "auth_net_transaction_id": "60123456789",
            "payment_method": "card", "invoice_num": "46055",
        }],
        payment_date=dt.date(2026, 5, 10),
        reference_label="DocuSign",
    )
    assert list(df.columns) == saasant_out.RECEIVE_PAYMENT_COLS
    row = df.iloc[0]
    assert row["Customer"] == "Acme Vet"
    assert row["Amount"] == 450.00
    assert row["Ref No (Receive Payment No)"] == "60123456789"
    assert row["Payment Method"] == "Credit Card"
    assert row["PaymentDate"] == "05/10/2026"


def test_build_received_payments_echeck_label():
    df = saasant_out.build_received_payments(
        [{
            "customer": "Bravo Animal Clinic", "amount": 500.00,
            "auth_net_transaction_id": "60111111111",
            "payment_method": "echeck", "invoice_num": "45020",
        }],
        payment_date=dt.date(2026, 5, 10),
    )
    assert df.iloc[0]["Payment Method"] == "eCheck"


def test_unique_ref_no_raises_on_duplicate():
    with pytest.raises(ValueError, match="Non-unique Ref No"):
        saasant_out.build_received_payments(
            [
                {"customer": "A", "amount": 100,
                 "auth_net_transaction_id": "1234", "payment_method": "card"},
                {"customer": "B", "amount": 200,
                 "auth_net_transaction_id": "1234", "payment_method": "card"},
            ],
            payment_date=dt.date(2026, 5, 10),
        )


def test_build_received_payments_empty_input():
    df = saasant_out.build_received_payments([], payment_date=dt.date(2026, 5, 10))
    assert df.empty
    assert list(df.columns) == saasant_out.RECEIVE_PAYMENT_COLS


def test_build_declines_report_shape():
    df = saasant_out.build_declines_report([
        {"customer": "Acme", "invoice_num": "46055", "amount": 450.0,
         "outcome": "declined", "reason": "Insufficient funds",
         "auth_net_response_code": "2"},
    ])
    assert len(df) == 1
    assert df.iloc[0]["Outcome"] == "declined"
    assert df.iloc[0]["Auth.net code"] == "2"


def test_build_declines_report_empty():
    df = saasant_out.build_declines_report([])
    assert df.empty
    assert "Customer" in df.columns
