# CLAUDE.md — oncura-billing

## What this app is

DocuSign monthly batch charge automation. Tanya uploads the QBO invoice export, the app joins it to a QBO→Authorize.net CIM crosswalk, she confirms, and the app submits every charge through Authorize.net's CIM API. Outputs: SaasAnt "Received Payments" import file (approved only) + declines report + audit-logged run record.

This app is a deliberate sibling of `oncura-programs` and `oncura-apps`. Same `core/` module shape, same UI patterns from `UI_STYLE_GUIDE.md`, same audit + dedup primitives.

## Architecture

```
app.py                        # 4-step wizard
core/
  auth.py                     # password + initials gate
  ui.py                       # theme + record_button + initials_input + persistence_warning
  store.py                    # GitHub Contents API + local fallback
  loaders.py                  # cached JSON loaders (cim_customer_map, cim_profile_cache)
  audit.py                    # append-only charge log + fingerprint dedup
  qbo_import.py               # QBO invoice-report xlsx parser (header-row auto-detect)
  saasant_out.py              # SaasAnt Received Payments builder (RECEIVE_PAYMENT_COLS)
  authnet.py                  # Auth.net CIM JSON client (sandbox/production via secrets)
data/
  cim_customer_map.json       # {qb_customer: {customer_profile_id, payment_profile_id, ...}}
  cim_profile_cache.json      # snapshot of last "refresh from Auth.net" pull
  charge_log.json             # audit log (created on first cycle commit)
pages/
  cim_mapping.py              # admin: edit crosswalk + refresh from Auth.net
  charge_log.py               # audit view + integrity check
tests/                        # ~25 tests covering parser, saasant builder, fingerprints
scripts/smoke_test.py
.github/workflows/smoke.yml
```

## Phase 2 to-do (when sandbox creds land)

1. **Wire `authnet.create_transaction` into the wizard's step-4 submit loop.** For each `chargeable & matched` row: call create_transaction, record `charge_attempt` (with fingerprint) before submit, then record `charge_approved` / `charge_declined` / `charge_error` based on response.
2. **Build the result-step outputs.** Approved rows → `saasant_out.build_received_payments` → xlsx download. Declined/errored rows → `saasant_out.build_declines_report` → xlsx download.
3. **Idempotency**: check `audit.fingerprints_seen(fps)` before submit; skip already-charged rows and surface a "X of Y previously charged" banner.
4. **CIM profile cache refresh button** on `pages/cim_mapping.py` (already coded but untested without creds).
5. **End-to-end sandbox test**: list profiles → assign one to a fake QB customer → upload a one-row QBO export → run the charge → confirm SaasAnt + declines outputs + audit entries.

Once sandbox cycle works clean, flip `AUTHNET_ENV` to `production` in Streamlit Cloud secrets and run a single-clinic live cycle as the smoke test before opening it to the full ~50-70-clinic batch.

## Key invariants

- **No raw card or bank data EVER flows through this app.** `core/authnet.py` references profile IDs only. Don't add code paths that accept full card numbers — keeps PCI scope at SAQ-A or below.
- **`AUTHNET_ENV` is the most important secret.** Big banner colors per env; mismatched setup is a money mistake.
- **Audit-log fingerprint = `sha256(invoice_num + customer + amount + period)`.** Re-uploading the same QBO export collides on this fingerprint and rows already-charged get skipped.
- **`Ref No (Receive Payment No)` in the SaasAnt output is always the Auth.net `transaction_id`** — guaranteed unique per row, dodges the GA "non-unique Ref No collapses rows" footgun.

## Deploy

- **Repo**: github.com/alexanderjordain/oncura-billing (public, matches the suite pattern)
- **Live**: TBD — connect on https://share.streamlit.io after sandbox creds land
- **Secrets**: APP_PASSWORD + GITHUB_TOKEN + AUTHNET_API_LOGIN_ID + AUTHNET_TRANSACTION_KEY + AUTHNET_ENV

## Test/smoke discipline

Same as `oncura-programs`:

```bash
python scripts/smoke_test.py    # AST cross-module reference check
python -m pytest tests/ -q      # ~25 tests
```

Both run in CI on every push.
