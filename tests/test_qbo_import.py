"""QBO invoice-report parser tests. Real-world fixture: the May 2026 file Alex
shared verifies the header-at-row-4 layout. Tests below use inline DataFrame
fixtures so they're fast and don't depend on a binary asset."""
from __future__ import annotations

import io

import pandas as pd
import pytest

from core import qbo_import


def _make_xlsx(rows: list[list]) -> io.BytesIO:
    """Build an in-memory xlsx where the first column is the title block,
    then a blank row, then the canonical header + body."""
    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.to_excel(xw, index=False, header=False, sheet_name="Sheet1")
    buf.seek(0)
    return buf


def test_detect_header_row_canonical_layout():
    rows = [
        ["Oncura Partners Diagnostics, LLC", None, None, None, None, None, None],
        ["Invoice Report", None, None, None, None, None, None],
        ["May 2026", None, None, None, None, None, None],
        [None, None, None, None, None, None, None],
        ["Date", "Num", "Customer", "Due date", "Amount", "Open balance", "Shipping date"],
        ["05/01/2026", "46055", "Acme Vet", "05/01/2026", 450, 450, None],
    ]
    raw = pd.DataFrame(rows)
    assert qbo_import.detect_header_row(raw) == 4


def test_detect_header_row_drifts_when_extra_preamble():
    """If QBO adds an extra disclaimer row, header detection still hits."""
    rows = [
        ["Oncura Partners Diagnostics, LLC", None, None, None, None, None, None],
        ["Invoice Report", None, None, None, None, None, None],
        ["May 2026", None, None, None, None, None, None],
        ["DISCLAIMER: …", None, None, None, None, None, None],
        [None, None, None, None, None, None, None],
        ["Date", "Num", "Customer", "Due date", "Amount", "Open balance", "Shipping date"],
        ["05/01/2026", "46055", "Acme Vet", "05/01/2026", 450, 450, None],
    ]
    raw = pd.DataFrame(rows)
    assert qbo_import.detect_header_row(raw) == 5


def test_read_invoice_report_parses_canonical():
    buf = _make_xlsx([
        ["Oncura Partners Diagnostics, LLC", None, None, None, None, None, None],
        ["Invoice Report", None, None, None, None, None, None],
        ["May 2026", None, None, None, None, None, None],
        [None, None, None, None, None, None, None],
        ["Date", "Num", "Customer", "Due date", "Amount", "Open balance", "Shipping date"],
        ["05/01/2026", "46055", "Acme Vet", "05/01/2026", 450, 450, None],
        ["05/11/2026", "45020", "Bravo Animal Clinic", "05/11/2026", 500, 500, None],
        # A footer / total row — should be dropped because date isn't parseable
        ["TOTAL", None, None, None, None, 950, None],
    ])
    df = qbo_import.read_invoice_report(buf)
    assert len(df) == 2
    assert list(df.columns) == ["invoice_date", "invoice_num", "customer", "amount", "open_balance"]
    assert df.iloc[0]["customer"] == "Acme Vet"
    assert df.iloc[0]["amount"] == 450.0
    assert df.iloc[1]["invoice_num"] == "45020"


def test_read_invoice_report_drops_empty_customer():
    buf = _make_xlsx([
        ["Date", "Num", "Customer", "Due date", "Amount", "Open balance", "Shipping date"],
        ["05/01/2026", "46055", "Acme Vet", "05/01/2026", 450, 450, None],
        ["05/02/2026", "46056", None, "05/02/2026", 100, 100, None],
        ["05/03/2026", "46057", "  ", "05/03/2026", 200, 200, None],
    ])
    df = qbo_import.read_invoice_report(buf)
    assert len(df) == 1
    assert df.iloc[0]["customer"] == "Acme Vet"


def test_split_chargeable_filters_correctly():
    df = pd.DataFrame([
        {"invoice_date": pd.Timestamp("2026-05-01"), "invoice_num": "1",
         "customer": "A", "amount": 100, "open_balance": 100},
        {"invoice_date": pd.Timestamp("2026-05-01"), "invoice_num": "2",
         "customer": "B", "amount": 200, "open_balance": 0},     # paid
        {"invoice_date": pd.Timestamp("2026-05-01"), "invoice_num": "3",
         "customer": "C", "amount": -50, "open_balance": -50},   # refund
        {"invoice_date": pd.Timestamp("2026-05-01"), "invoice_num": "4",
         "customer": "D", "amount": 12000, "open_balance": 12000},  # large
    ])
    t = qbo_import.split_chargeable(df, min_amount=0.01, max_amount=10000)
    assert len(t["chargeable"]) == 1
    assert t["chargeable"].iloc[0]["customer"] == "A"
    assert len(t["zero_balance"]) == 1
    assert len(t["negative"]) == 1
    assert len(t["flagged_large"]) == 1
    assert t["flagged_large"].iloc[0]["customer"] == "D"


def test_split_chargeable_empty_input():
    df = pd.DataFrame(columns=qbo_import.NORMALIZED_COLUMNS)
    t = qbo_import.split_chargeable(df)
    assert all(v.empty for v in t.values())
