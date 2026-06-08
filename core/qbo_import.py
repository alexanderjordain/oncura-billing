"""Parser for QBO's "Invoice Report" xlsx export.

Real-world export shape (from `Oncura Partners Diagnostics, LLC_Invoice Report.xlsx`):

  Row 0-3: title block ("Oncura Partners Diagnostics, LLC" / "Invoice Report" / month / blank)
  Row 4:   header row — Date / Num / Customer / Due date / Amount / Open balance / Shipping date
  Row 5+:  data rows; trailing total/footer rows MAY appear.

We detect the header row by looking for the canonical column names so a slightly
different export (e.g. a different month layout, an extra disclaimer line) still parses.

Output is a normalized DataFrame:
  invoice_date  pandas.Timestamp
  invoice_num   str
  customer      str (QBO display name — the lookup key for the CIM crosswalk)
  amount        float (original invoice total)
  open_balance  float (the actual amount to charge — net of any prior partial payments)
"""
from __future__ import annotations

import pandas as pd

NORMALIZED_COLUMNS = ["invoice_date", "invoice_num", "customer", "amount", "open_balance"]

# Canonical QBO column names → our normalized field. Match is case-insensitive
# whitespace-normalized so "Open balance" / "open_balance" / "OPEN BALANCE" all hit.
_HEADER_MAP = {
    "date": "invoice_date",
    "num": "invoice_num",
    "customer": "customer",
    "amount": "amount",
    "open balance": "open_balance",
}


def _norm_header(s) -> str:
    return " ".join(str(s).strip().lower().split())


def detect_header_row(raw: pd.DataFrame, max_scan: int = 12) -> int:
    """Find the row that best matches the canonical QBO invoice-report header."""
    best_idx, best_hits = 0, 0
    for i in range(min(max_scan, len(raw))):
        cells = [_norm_header(v) for v in raw.iloc[i] if pd.notna(v)]
        hits = sum(1 for c in cells if c in _HEADER_MAP)
        if hits > best_hits:
            best_hits = hits
            best_idx = i
    return best_idx


def read_invoice_report(file_or_bytes) -> pd.DataFrame:
    """Parse a QBO Invoice Report xlsx → normalized DataFrame.

    Accepts a path, file-like object, or bytes. Detects the header row
    (canonical row 4 for "Oncura Partners Diagnostics, LLC" exports, but
    robust to layout drift).
    """
    raw = pd.read_excel(file_or_bytes, header=None)
    hidx = detect_header_row(raw)
    headers = [_norm_header(v) for v in raw.iloc[hidx]]
    body = raw.iloc[hidx + 1:].reset_index(drop=True).copy()
    body.columns = headers

    # Build the normalized frame with only the columns we know how to handle.
    out: dict[str, list] = {col: [] for col in NORMALIZED_COLUMNS}
    for src_header, target in _HEADER_MAP.items():
        if src_header in body.columns:
            out[target] = body[src_header].tolist()

    df = pd.DataFrame(out)

    # Coerce types. Drop rows whose date isn't parseable (footer/total rows).
    df["invoice_date"] = pd.to_datetime(df["invoice_date"], errors="coerce")
    df = df.dropna(subset=["invoice_date"]).reset_index(drop=True)

    # Drop rows with a missing customer BEFORE coercing to string — astype(str)
    # turns NaN into "nan" but pandas' boolean ops on the result can keep NaN
    # values around when nullable string dtypes are in play. dropna() first is
    # the unambiguous gate.
    df = df.dropna(subset=["customer"]).reset_index(drop=True)
    df["invoice_num"] = df["invoice_num"].astype(str).str.strip()
    df["customer"] = df["customer"].astype(str).str.strip()
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0).round(2)
    df["open_balance"] = pd.to_numeric(df["open_balance"], errors="coerce").fillna(0.0).round(2)

    # Drop rows whose customer is empty / whitespace-only / the literal "nan".
    df = df[df["customer"].ne("") & df["customer"].str.lower().ne("nan")].reset_index(drop=True)
    return df[NORMALIZED_COLUMNS]


def split_chargeable(df: pd.DataFrame, *, min_amount: float = 0.01,
                     max_amount: float | None = None) -> dict:
    """Triage the parsed invoices into buckets for the review step.

    Returns:
      chargeable: rows with open_balance >= min_amount (and <= max_amount if set)
      zero_balance: rows with open_balance == 0 (already paid — skip)
      flagged_large: rows with open_balance > max_amount (review before charging)
      negative: rows with open_balance < 0 (overpayment / refund situation)
    """
    if df.empty:
        empty = df.iloc[0:0]
        return {"chargeable": empty, "zero_balance": empty,
                "flagged_large": empty, "negative": empty}

    zero = df[df["open_balance"] == 0]
    negative = df[df["open_balance"] < 0]
    positive = df[df["open_balance"] > 0]

    if max_amount is not None:
        flagged = positive[positive["open_balance"] > max_amount]
        chargeable = positive[
            (positive["open_balance"] >= min_amount) & (positive["open_balance"] <= max_amount)
        ]
    else:
        flagged = positive.iloc[0:0]
        chargeable = positive[positive["open_balance"] >= min_amount]

    return {
        "chargeable": chargeable.reset_index(drop=True),
        "zero_balance": zero.reset_index(drop=True),
        "flagged_large": flagged.reset_index(drop=True),
        "negative": negative.reset_index(drop=True),
    }
