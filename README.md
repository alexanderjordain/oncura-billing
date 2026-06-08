# Oncura Billing

DocuSign monthly batch charge automation. Takes Tanya from "QBO invoice export in hand" to "all customers charged through Authorize.net + SaasAnt receive-payments file ready to upload" in one guided run.

## Why

~50–70 DocuSign customers get charged on the 10th of each month. Each amount is different (no fixed recurring billing). Until now Tanya entered every charge one at a time in the Auth.net dashboard. This app batches the run, surfaces declines for follow-up, and produces the SaasAnt import file for QBO.

## Status

**Phase 1 (this build): scaffolding + parser + SaasAnt output + Auth.net client stubs.** The four-step wizard loads, parses the QBO invoice export, joins to the CIM crosswalk, and surfaces unmatched customers. The charge step itself is disabled until Authorize.net sandbox credentials are configured.

**Phase 2 (pending sandbox creds):** wire `core/authnet.create_transaction` into the wizard's per-row submit loop; collect approved/declined/error results; produce the SaasAnt + declines outputs; record the cycle in the audit log.

## Wizard

```
1. Cycle setup    → month, payment date, reference label
2. Upload         → QBO invoice report (Date / Num / Customer / Amount / Open balance)
3. Match & review → per-invoice CIM-profile join; unmatched surfaced; operator confirms
4. Process        → submit each row through Auth.net; download SaasAnt + declines
```

## Stack

- **Streamlit** entry: `app.py`
- **`core/qbo_import.py`** — robust QBO Invoice Report parser (header-row auto-detect)
- **`core/saasant_out.py`** — SaasAnt "Received Payments" import builder (matches `oncura-programs/core/flex_finance.RECEIVE_PAYMENT_COLS`)
- **`core/authnet.py`** — Authorize.net CIM client (sandbox/production switch via secrets)
- **`core/audit.py`** — append-only charge log with SHA-256 per-entry integrity
- **`core/store.py`** — GitHub Contents API + local fallback (same pattern as the suite)
- **`core/auth.py`** — combined password + initials gate
- **`pages/cim_mapping.py`** — admin editor for the QBO→CIM crosswalk
- **`pages/charge_log.py`** — audit log view + integrity check

## Security

- **No raw card or bank data** ever flows through this app. The Authorize.net client references CIM `customerProfileId` + `paymentProfileId` only.
- **Credentials** live in Streamlit Cloud secrets — never in the repo:
  ```toml
  APP_PASSWORD = "..."
  GITHUB_TOKEN = "..."
  AUTHNET_API_LOGIN_ID = "..."
  AUTHNET_TRANSACTION_KEY = "..."
  AUTHNET_ENV = "sandbox"   # or "production"
  ```
- **ALWAYS start in `AUTHNET_ENV=sandbox`.** The app shows a big yellow "SANDBOX" banner when testing and a big red "PRODUCTION" banner when live, so the operator can never confuse the two.

## Local dev

```bash
pip install -r requirements.txt
ONCURA_BILLING_LOCAL=1 streamlit run app.py
```

`ONCURA_BILLING_LOCAL=1` bypasses the password gate. Authorize.net + GitHub features stay disabled until secrets are configured.

## Deploy on Streamlit Cloud

1. Connect this repo on https://share.streamlit.io
2. App file: `app.py`
3. Paste the secrets above into Settings → Secrets

## Tests

```bash
python -m pytest tests/ -q       # ~25 tests, no network
python scripts/smoke_test.py     # syntax + cross-module reference check
```

CI runs both on every push (`.github/workflows/smoke.yml`).
