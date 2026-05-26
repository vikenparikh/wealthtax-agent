# Security Policy

## Password Hashing

WealthTax Agent uses **bcrypt** (via the `bcrypt` Python package, version ≥ 4.0)
for all user password storage.

### Scheme details

| Property | Value |
|---|---|
| Algorithm | bcrypt (Blowfish cipher) |
| Work factor (cost) | 12 rounds (bcrypt default via `bcrypt.gensalt()`) |
| Input clamping | Passwords are truncated at 72 bytes before hashing (bcrypt max) |
| Output format | Standard 60-character bcrypt hash string (`$2b$12$...`) |
| Verification | `bcrypt.checkpw()` — constant-time comparison |

### Rationale

bcrypt was chosen for:
- Time-tested resistance against GPU-based brute-force attacks.
- Wide ecosystem support and audited Python bindings.
- Built-in salt generation (no salt reuse possible).

Argon2 (`argon2-cffi`) is the preferred modern successor; migration is on the
backlog for v1.0. The current bcrypt cost factor (12) provides approximately
100-300 ms verification time on a modern CPU, which is acceptable for a
single-user / low-concurrency deployment.

### Key management

User PII fields (`full_name`, `sin_or_ssn`, `dob`, `address`) and `TaxReturn.fields`
are encrypted at rest with **Fernet** (AES-128-CBC + HMAC-SHA256).

| Property | Value |
|---|---|
| Algorithm | Fernet (symmetric, `cryptography` library) |
| Key source | `WEALTHTAX_FERNET_KEY` env var (URL-safe base64, 32 bytes) |
| Key rotation | Re-encrypt all `LargeBinary` + `EncryptedJSON` rows, then rotate env var |

### Reporting a vulnerability

Email **vsparikh1996@gmail.com** with subject `[WealthTax Security]`. We aim to
acknowledge within 48 hours.
