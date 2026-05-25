---
concept: compliance-gaps
tags: [compliance, security, privacy, pipeda, soc2, gaps]
related: [groq-llm-integration, auth-and-storage, user-data-model]
files: [src/wealthtax_agent/auth.py, src/wealthtax_agent/llm.py, src/wealthtax_agent/db/models.py]
last-updated: 2026-05-25
---

# Compliance Gaps

Explicit gap inventory. This is a Wealthsimple hackathon prototype — not production-hardened.

## Third-party data exposure

| Gap | Detail |
|---|---|
| No DPA with Groq | Raw slip text (may contain SIN/SSN/PAN) sent to Groq API. No formal Data Processing Agreement. |
| No LLM payload audit log | Cannot reconstruct what financial data was transmitted to Groq per session. |
| PII sanitization unaudited | `llm.py` applies sanitization; no formal verification of coverage. |

## Authentication & access control

| Gap | Detail |
|---|---|
| Password hashing unverified | `hashed_password` field exists; scheme (bcrypt/Argon2 vs sha256) not confirmed in-session — verify `auth.py` before prod. |
| No rate limiting | No brute-force protection on login endpoint. |
| No MFA | Single-factor (email + password) only. |
| No session expiry enforcement | Not verified in-session. |

## Data protection

| Gap | Detail |
|---|---|
| `TaxReturn.fields` plaintext | Structured financial data stored as unencrypted JSON. Fernet covers only `users` PII columns. |
| No right-to-erasure workflow | No data-deletion path (PIPEDA, GDPR Article 17). |
| Filing artifacts in-memory only | Not persisted independently — lost on server restart. |

## `transmissible=false` is a soft flag

The flag is stamped into artifact JSON/XML. There is no technical mechanism preventing a user
from extracting and submitting the artifact directly. It is a UX/legal signal, not enforcement.

## Audit / certification

| Gap | Detail |
|---|---|
| No SOC 2 | Not applicable to a prototype; required before any SaaS launch with real user data. |
| No PIPEDA audit | Canada-specific privacy law; not assessed. |
| Tax calculations not CPA-audited | Bracket tables use real government figures; the computation logic has not been independently reviewed by a CPA or tax attorney. Output is explicitly advisory. |

## Mitigation path (for production)

1. Sign a DPA with Groq (or switch to a self-hosted model / LOCAL_OCR_ONLY).
2. Add structured LLM payload logging with retention + access controls.
3. Verify + document password hashing scheme.
4. Encrypt `TaxReturn.fields` with Fernet (extend `db/crypto.py`).
5. Implement right-to-erasure endpoint.
6. Add rate limiting + MFA for saas mode.
7. Commission a CPA review of bracket logic before claiming "accurate" to users.
