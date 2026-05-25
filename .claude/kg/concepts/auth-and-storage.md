---
concept: auth-and-storage
tags: [auth, security, fernet, encryption, sessions]
related: [user-data-model, compliance-gaps, groq-llm-integration]
files: [src/wealthtax_agent/auth.py, src/wealthtax_agent/db/crypto.py, src/wealthtax_agent/db/models.py]
last-updated: 2026-05-25
---

# Auth and Storage

Authentication, session tokens, and encryption posture — stated honestly.

## Modes

| Mode | Auth | Notes |
|---|---|---|
| `self_hosted` | None — single user, no sidebar | Set via `WEALTHTAX_MODE=self_hosted` |
| `saas` | Email + password, auth sidebar in `main.py` | Requires DB; sessions Fernet-signed |

## Auth flow (`auth.py`)

1. User submits email + password.
2. `auth.py` looks up user, verifies hashed password.
3. On success: Fernet-signed session token stored in `user_sessions` table + Streamlit session state.
4. All protected routes check `_render_auth_sidebar()` gate in `main.py`.

## Password hashing

- Field `hashed_password` exists on the `User` ORM model.
- **The hashing scheme has not been verified in-session.** Verify `auth.py` before any production deployment to confirm bcrypt or Argon2 — not plain sha256 or md5.

## Encryption at rest (`db/crypto.py`)

`cryptography.fernet.Fernet` symmetric encryption. Key loaded from `WEALTHTAX_FERNET_KEY` env var.

Encrypted columns on `users`: `full_name_enc`, `sin_or_ssn_enc`, `dob_enc`, `address_enc`.

`TaxReturn.fields` (structured financial data) is stored as **plaintext JSON** — not Fernet-encrypted.

## Session tokens

Fernet-signed; stored in `user_sessions`. No expiry enforcement has been verified in-session.

## Key invariants

- Fernet key must be generated once and stored safely — losing it makes PII unrecoverable.
- `self_hosted` mode exposes the app with no auth gate.

## Known gaps

- Password hashing scheme unverified — confirm before production.
- No rate limiting, brute-force protection, or MFA.
- No session expiry enforcement verified.
- `TaxReturn.fields` is plaintext JSON — financial data exposed on DB breach.
- No SOC 2, PIPEDA, or independent security audit has been performed.
