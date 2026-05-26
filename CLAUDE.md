# Claude session handoff — `wealthtax-agent`

This file is the **first thing you read** when you start a Claude session in this repo. It is also the **last thing you update** before you stop responding to the user, and it must be kept current *during* long sessions too (see "Update protocol" at the bottom).

Treat this file as the project's external memory: every fact a future session needs to continue the work — without re-reading the codebase from scratch — should live here.

---

## How to use this file (instructions to Claude)

1. **At the start of every session**, read this file top-to-bottom before anything else. It tells you what's shipped, what's in flight, what's broken, and which user-controlled operations are still pending. Do not start exploring the codebase until you have read this file.
2. **At each meaningful checkpoint during a session**, update the section that just changed. Meaningful = a commit landed on main, a test count moved, a punch-list item closed, a deploy fired, a new architectural decision was made, or a sandbox quirk was discovered. Don't update on noise (e.g. running `git status`).
3. **Before you end your turn**, if any user-facing state changed, append a new entry to the **Session log** at the bottom with: date, headline of what changed, ending git SHA on `main`, and the test count. Keep it to 3-6 lines per entry.
4. **Treat every fact as load-bearing.** If you write "the auth sidebar uses Fernet-encrypted sessions," a future Claude will rely on that without re-verifying. So either verify it before writing it, or qualify it explicitly (e.g. "I did not verify this in-session").
5. **Multi-repo work**: if a task spans multiple repos, list them in the **Multi-repo context** section. Each related repo gets its own short block describing its purpose, the latest interesting commit, and any cross-repo coupling worth knowing.

If this file gets stale (the last "Session log" entry is more than ~10 commits behind `main`), audit and refresh before continuing.

---

## Project at a glance

**Repo:** `vikenparikh/wealthtax-agent` (single-repo for now; multi-repo placeholder below).

**What it is:** an AI-assisted, multi-jurisdiction personal-tax draft assistant. Users upload tax slips (or describe their year in plain English, or type numbers in manually), and the agent classifies forms, extracts fields, runs residency tests, computes draft returns for any combination of **Canada / United States / India**, flags cross-border edge cases (FTC, single-claim student loans, RSU sourcing), and emits filing-ready artifacts (T1 PDF + NETFILE-shaped XML for CA, 1040 PDF + IRS-MeF-shaped JSON for US, ITR JSON for IN). It explicitly does *not* transmit returns — every artifact is stamped `transmissible=false`.

**Stack:** Python 3.10+ · LangGraph pipeline · Pydantic state · Streamlit UI · SQLAlchemy + Alembic on Postgres (SQLite in dev) · Groq-hosted LLMs (Llama 3.1 / Llama 4 Scout) for OCR + extract + explain · Fernet-encrypted PII at rest · Docker + docker-compose · GitHub Actions CI/CD · GHCR for images · Cloudflare Tunnel for ingress (no inbound ports on the VPS).

**Audience:** a single-user prototype today, designed for SaaS deployment when the `production` environment is configured.

---

## Current state

| Fact | Value |
|---|---|
| `main` HEAD | `37f7f9b` — `fix(security+tests): audit findings` |
| Latest release tag (local) | `v0.5.0` at `445d3d8` — **not yet pushed** (sandbox Git relay 403s tag refs) |
| Latest release tag (remote) | none yet |
| Test count | **485 passing** (+7 from S2 transmission guard), ~18s wall on a fresh Python 3.11 venv |
| Streamlit boot smoke | ✅ green via `./scripts/validate.sh` |
| AppTest UI smoke | ✅ both `self_hosted` and `saas` modes render without exception |
| GitHub Actions on `main` | unknown from this sandbox (no MCP tool for `workflow_run`); check the Actions tab in browser |
| Deploy fired against VPS | **not yet** — pending the 4 GitHub Secrets + Cloudflare Tunnel + VPS `.env` |

---

## Architecture

```
                          ┌──────────────────┐
                          │  Streamlit UI    │  src/wealthtax_agent/main.py
                          │  (auth, intake,  │
                          │   chat, drafts)  │
                          └────────┬─────────┘
                                   │ GraphState
                                   ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │  LangGraph pipeline (src/wealthtax_agent/graph.py)               │
   │                                                                   │
   │  parse_docs → classify_forms → extract_forms → dedupe_extracts   │
   │  → residency_test → apply_corrections → ask_clarifications       │
   │  → reason_tax → optimize → explain_return → build_return         │
   │  → format_outputs                                                 │
   └─────────────────────┬───────────────────────────┬─────────────────┘
                         │                           │
                         ▼                           ▼
              ┌──────────────────┐         ┌──────────────────┐
              │  Engines         │         │  Filing artifacts│
              │  ca_engine.py    │         │  ca_t1.py (PDF + │
              │  us_engine.py    │         │   NETFILE XML)   │
              │  in_engine.py    │         │  us_1040.py (PDF │
              │  residency.py    │         │   + MeF JSON)    │
              │  cross_border.py │         │  in_itr.py (ITR  │
              │                  │         │   JSON)          │
              └──────────────────┘         └──────────────────┘
                         │
                         ▼
                ┌──────────────────────────┐
                │  Persistence (SQLAlchemy │
                │  + Alembic + Fernet      │
                │  for PII at rest)        │
                └──────────────────────────┘

Pipeline nodes 1-by-1 (each is a pure function `GraphState → GraphState`):
  parse_docs.py          Bytes → text (local OCR or Groq vision LLM); supports .pdf .png .jpg .xlsx .csv
  classify_forms.py      text → form_code + jurisdiction (rule-based + LLM fallback)
  extract_forms.py       text → FormExtract with structured fields
  ingest/dedupe.py       sha256 + form fingerprint dedupe
  engines/residency.py   days-per-country → resident/non-resident + treaty hints
  corrections/*.py       NL intake + per-field corrections + revision history
  clarify.py             Generates targeted follow-up questions
  reason_tax.py          Dispatch into CA/US/IN engines + cross-border guardrails
  optimize.py            Suggest legal tax-optimization moves (RRSP, FHSA, IRA, FTC...)
  explain_return.py      LLM-generated plain-text + pseudo-XML explanations
  build_return.py        Generate filing-shaped artifacts per jurisdiction
```

**Key entry points:**

- `src/wealthtax_agent/main.py` — Streamlit app
- `src/wealthtax_agent/graph.py` — pipeline assembly
- `src/wealthtax_agent/state.py` — `GraphState`, all dataclasses
- `src/wealthtax_agent/db/__init__.py` — engine factory + `create_all_for_tests`
- `src/wealthtax_agent/llm.py` — Groq client wrapper + sanitization
- `src/wealthtax_agent/config/tax_tables/` — versioned YAML per jurisdiction × year
- `tests/integration/scenarios/test_scenarios_all.py` — 7 cross-border golden scenarios

---

## Repository layout

```
wealthtax-agent/
├── .github/workflows/
│   ├── tests.yml             # runs pytest on push + PR
│   └── deploy.yml            # tests → build image → push to GHCR → SSH → docker compose pull && up -d
├── src/wealthtax_agent/
│   ├── main.py               # Streamlit UI (~800 lines)
│   ├── graph.py              # LangGraph pipeline assembly
│   ├── state.py              # Pydantic state types (GraphState, FormExtract, DraftReturn, ...)
│   ├── parse_docs.py         # OCR + .xlsx/.csv ingestion
│   ├── classify_forms.py     # Form-code classification
│   ├── extract_forms.py      # Field extraction
│   ├── clarify.py            # Clarifying-question generation
│   ├── corrections/          # NL intake + per-field corrections
│   │   ├── intake.py         # parse_intake_narrative() — single-shot NL → extracts
│   │   └── ...
│   ├── ingest/
│   │   └── dedupe.py         # content_fingerprint + form_fingerprint + dedupe_extracts_node
│   ├── engines/
│   │   ├── ca_engine.py      # Canada engine
│   │   ├── us_engine.py      # United States engine
│   │   ├── in_engine.py      # India engine (old + new regime, 87A, surcharge, cess)
│   │   ├── residency.py      # US SPT + CA 183-day + India §6 + treaty hints
│   │   └── cross_border.py   # Student-loan single-claim, RSU sourcing, FTC hints
│   ├── forms/
│   │   ├── ca/               # T4, T5, T3, T5008, T2202, ...
│   │   ├── us/               # W-2, 1099-*, 1098-*, ...
│   │   └── in_/              # Form 16, 16A, 26AS, AIS, STOCK-GAIN
│   ├── filing/
│   │   ├── ca_t1.py, us_1040.py, in_itr.py
│   ├── intake/
│   │   └── wizard.py         # Manual-intake field specs per form
│   ├── reason_tax.py         # Engine dispatcher + cross-border node
│   ├── optimize.py           # Optimization suggestions
│   ├── explain_return.py     # LLM-generated explanations
│   ├── build_return.py       # Artifact-generation dispatcher
│   ├── db/                   # SQLAlchemy models + engine factory
│   ├── llm.py                # Groq client + retries + sanitization
│   └── config/tax_tables/    # YAML brackets/credits per jurisdiction × year
├── tests/
│   ├── unit/                 # Per-module unit tests (forms, engines, ingest, ...)
│   └── integration/
│       ├── scenarios/        # 8 real-world cross-border scenarios in test_scenarios_all.py
│       └── test_streamlit_smoke.py  # AppTest UI smoke (added post-v0.5.0)
├── alembic/versions/         # Database migrations
├── docs/
│   ├── DEPLOY.md             # CI/CD + VPS + Cloudflare runbook
│   ├── architecture.md       # Deeper architectural notes
│   ├── run_history.md        # Auto-updated by validate.sh
│   └── ...
├── scripts/
│   ├── validate.sh           # pytest + Streamlit boot check
│   ├── validate_real_flow.py # CA-only legacy E2E (covered by pytest)
│   ├── validate_live_graph.py# CA-only legacy E2E (covered by pytest)
│   └── ui_screenshot_playwright.py  # ⚠️ BROKEN: SyntaxError + pre-Round F UI selectors
├── sample_tax_slips/         # CA fixtures only — no IN samples
├── Dockerfile                # Python 3.11-slim, ~250 MB image
├── docker-compose.yml        # Dev compose (builds locally)
├── docker-compose.prod.yml   # Prod compose (pulls from GHCR + cloudflared sidecar)
├── pyproject.toml            # v0.5.0
├── CHANGELOG.md              # Keep-a-Changelog history
├── README.md                 # User-facing project overview
└── CLAUDE.md                 # ← this file
```

---

## Multi-repo context

Currently a single-repo project. **If you start spanning repos**, add an entry below using this template:

```
### <owner>/<repo-name>
- **Purpose:** one-line description.
- **Latest interesting commit:** `<sha>` — what it did.
- **Cross-repo coupling:** what wealthtax-agent depends on from this repo, or vice versa.
- **Local clone path:** if cloned locally.
- **Open work:** what's in flight for this repo this session.
```

### (no other repos active yet)

---

## Active threads

(What's in flight *right now*. Empty section is fine.)

- None — v0.5.0 is shipped; CI/CD pipeline is configured but not yet fired against a real VPS.

---

## Backlog / punch-list

Items deliberately deferred. Each entry should be self-contained — a future Claude must be able to pick one up cold.

**Operational (user-controlled, blocking first prod deploy):**

1. Add 4 GitHub Secrets under a `production` environment: `SSH_DEPLOY_KEY`, `SSH_HOST`, `SSH_USER`, `SSH_KNOWN_HOSTS`. Full runbook in `docs/DEPLOY.md`.
2. Create the Cloudflare Tunnel (Zero Trust → Networks → Tunnels → create "wealthtax" → pick Docker connector → copy `eyJh...` token).
3. VPS prep: `mkdir -p /opt/wealthtax-agent && chown deploy:deploy` and create `/opt/wealthtax-agent/.env` with `GROQ_API_KEY`, `WEALTHTAX_FERNET_KEY`, `POSTGRES_PASSWORD`, `CLOUDFLARE_TUNNEL_TOKEN`. Template in `docs/DEPLOY.md`.
4. Push the local `v0.5.0` tag from a machine outside the sandbox: `git fetch origin && git push origin v0.5.0`. Sandbox relays 403 on tag refs; standard origins accept them.

**Code (for v0.5.1 or later):**

- Dedicated unit tests: `tests/unit/test_in_itr_serializer.py`, `tests/unit/engines/test_student_loan_cross_border.py`. Currently covered indirectly via the cross-border scenario tests.
- Split `tests/integration/scenarios/test_scenarios_all.py` into 8 named files so a failure points at a single named scenario rather than the parametrized aggregate.
- India sample slips: `sample_tax_slips/` only has CA T4/T5/RRSP samples. Add Form 16 / Form 16A samples for parity.
- A GitHub Release object built from the `v0.5.0` tag, with the CHANGELOG entry as the release notes.

---

## Operational state

### GitHub Secrets (repo: `vikenparikh/wealthtax-agent`)

| Secret | Where | Status |
|---|---|---|
| `SSH_DEPLOY_KEY` | Environment `production` | ❌ not set |
| `SSH_HOST` | Environment `production` | ❌ not set |
| `SSH_USER` | Environment `production` | ❌ not set |
| `SSH_KNOWN_HOSTS` | Environment `production` | ❌ not set |
| `GITHUB_TOKEN` | provided automatically by Actions | ✅ |

### VPS

- **Provider:** unknown (user-managed). To be confirmed.
- **Hostname:** unknown.
- **Deploy directory:** target is `/opt/wealthtax-agent/` on the VPS.
- **Provisioned?** user said "already provisioned, just deploy" — assume Docker + docker-compose v2 installed and the deploy user can run `docker` without sudo.

### Cloudflare

- **Tunnel name:** to be created (recommended name: `wealthtax`).
- **Hostname mapping:** to be added (e.g. `app.your-domain.tld` → `HTTP` → `app:8501`).
- **Tunnel token:** must live in the VPS `/opt/wealthtax-agent/.env` as `CLOUDFLARE_TUNNEL_TOKEN`, **not** in GitHub Secrets.

### Branches

- `main` — production line. Direct pushes have been authorized by the user for this session sequence.
- `claude/tax-filing-agent-mJITD` — the assigned feature branch per session instructions. Currently in sync with `main` after the v0.5.0 merge.

---

## Sandbox quirks & gotchas

Hard-won knowledge — please respect.

- **The sandbox Git relay (`http://127.0.0.1:*/git/...`) 403s tag pushes.** Branch pushes work. To push a tag, the user must do it from outside the sandbox. Do not waste cycles retrying `git push origin <tag>` — it will keep failing.
- **No `gh` CLI is available.** Use the `mcp__github__*` tools for any GitHub API interaction.
- **The GitHub MCP layer has no `list_workflow_runs` or `list_check_runs` tool.** You cannot observe CI status from this sandbox. The Actions tab in browser is the source of truth.
- **MCP repo scope is restricted to `vikenparikh/wealthtax-agent`.** Calls targeting any other repo will be denied.
- **No real network access to Groq.** Use the `LLM_PROVIDER` and `GROQ_API_KEY=gsk-test-key` test stub; tests mock the LLM at module level.
- **No `tesseract` binary in this sandbox.** `LOCAL_OCR_ONLY=true` makes `validate_real_flow.py` fall back to pytest's mocked path for PDFs. Don't read a tesseract failure as a code regression.
- **No browser / Playwright available.** UI verification has to go through `streamlit.testing.v1.AppTest`. `scripts/ui_screenshot_playwright.py` is broken anyway (see backlog).
- **Pushing to `main` is sensitive.** It requires explicit user authorization per push (the user has been giving it for this session sequence — re-confirm if a future session is unclear).
- **Never `--force` push to `main`.** Never skip hooks (`--no-verify`, `--no-gpg-sign`) unless the user asks.

---

## Commands cheatsheet

```bash
# === Tests ===
PYTHONPATH=src .venv/bin/python -m pytest --no-cov -q
PYTHONPATH=src .venv/bin/python -m pytest tests/integration/scenarios/ -v  # cross-border scenarios
PYTHONPATH=src .venv/bin/python -m pytest tests/integration/test_streamlit_smoke.py -v  # UI smoke

# === Local validate (pytest + Streamlit boot, logged to docs/run_history.md) ===
./scripts/validate.sh

# === Run Streamlit locally ===
WEALTHTAX_MODE=self_hosted \
WEALTHTAX_FERNET_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") \
GROQ_API_KEY=gsk-... \
PYTHONPATH=src .venv/bin/python -m streamlit run src/wealthtax_agent/main.py

# === Docker dev (local source) ===
docker compose up -d
# === Docker prod (VPS — pulls from GHCR) ===
docker compose -f docker-compose.prod.yml up -d

# === Database migrations ===
PYTHONPATH=src alembic upgrade head

# === Trigger a deploy manually (after secrets are set) ===
# In GitHub: Actions → deploy → Run workflow → leave image_tag blank → Run
# Or push a tag: git tag -a vX.Y.Z -m "..." && git push origin vX.Y.Z

# === Rollback ===
gh workflow run deploy.yml -f image_tag=v0.4.0   # or any prior :sha tag from GHCR
```

---

## Update protocol

This file is alive. Keep it accurate.

**Triggers to update during a session:**

- After every `git push` to `main` → update **Current state** (HEAD SHA, test count).
- After closing a backlog item → strike it from **Backlog**; mention in the next **Session log** entry.
- After discovering a new sandbox quirk → add to **Sandbox quirks & gotchas**.
- After making an architectural decision → add a one-paragraph note in **Architecture** or **Active threads**.
- After running the test suite with a different count → update **Current state** test count.
- After ~5-10 substantial tool uses or every ~30 minutes of work → quick audit, refresh whatever is stale.

**Always update before ending a turn** when any of the above happened. The user shouldn't have to ask.

**What NOT to update:**

- Tool-use noise (`git status`, exploratory `Read`s, failed experiments that didn't produce a commit).
- Speculative plans the user hasn't approved.
- Information you didn't verify in-session — qualify it instead.

---

## Session log

Newest at the top. Format per entry:

```
### YYYY-MM-DD — Headline
- HEAD on main: `<sha>` (was `<prev>`)
- Tests: `<count>` passing
- 2-4 bullets describing the change
- Any decisions worth carrying forward
```

### 2026-05-25 — S2 transmission guard (Ralph loop #2)

- HEAD on main: pending commit (was `37f7f9b`)
- Tests: **485 passing** (was 478 → +7 from `tests/unit/test_transmission_guard.py`)
- Added `TransmissionBlockedError` in `state.py` and guarded `FilingArtifact` at `__init__`, `__setattr__`, and `model_copy` so `transmissible=True` is impossible to set from any code path.
- Decision: enforced at the model boundary (single guard, single test) rather than per-production-site asserts as the PRD suggested — same blast radius, half the code, impossible to forget on new artifact sites.
- AC2 from `.ralph/fix_plan.md` is now green; 9 ACs remain.

### 2026-05-21 — Security & correctness audit (PII, safe-harbour, reconnect, wash-sale, CPA chat)

- HEAD on main: `37f7f9b` (was `c99062f`)
- Tests: **478 passing** (was 462 → added 16 tests)
- HIGH fixes: replaced SSN-shaped value in `tests/unit/db/test_crypto.py` (was `"123-45-6789"`) with synthetic `"SYNTH-TAX-ID-0000"`; added `tests/unit/test_cpa_chat.py` (18 tests) asserting disclaimer always present + system prompt never claims to file a return.
- MED fixes: `engines/estimated_tax.py` §6654 boundary comment clarified; boundary test for AGI == $150,000 uses 100% not 110%; `workers/event_consumer.py` reconnect loop fixed (`<= MAX_RETRIES` → `< MAX_RETRIES`); `TestReconnectRetry` added.
- MED additions: `tests/test_wash_sale.py` three new edge-case classes — short-against-the-box (covering buy), DRIP partial replacement, options caller-contract documentation.
- No Anthropic SDK imports found anywhere. Fernet encryption confirmed on all User PII columns (`full_name_enc`, `sin_or_ssn_enc`, `dob_enc`, `address_enc`).

### 2026-05-21 — Remove broken Playwright screenshot script (PR #5)

- HEAD on main: `c99062f` (was `da7514b`)
- Tests: **390 passing** (unchanged)
- Closed v0.5.1 backlog item: removed `scripts/ui_screenshot_playwright.py` (SyntaxError, missing `playwright` dep, pre-Round F UI selectors). AppTest smoke supersedes it.
- Path: created `claude/cleanup-broken-screenshot-script` branch, opened PR #5, squash-merged. CHANGELOG `[Unreleased]` now has a `### Removed` subsection capturing the deletion.
- First "real" PR landed in this session sequence — earlier v0.5.0 work was direct-pushed to `main` under explicit user authorization.

### 2026-05-20 — Handoff doc, AppTest smoke, CI/CD pipeline, v0.5.0 release

- HEAD on main: `9cf72ad` (was `80396cc` at session start)
- Tests: **390 passing** (was 386 → added 4 AppTest smoke tests)
- Shipped sequentially as five commits:
  - `445d3d8` — v0.5.0 release prep (`pyproject.toml` 0.1.0→0.5.0, new `CHANGELOG.md`, README refreshed for CA/US/IN multi-jurisdiction).
  - `025692a` — CI/CD pipeline (`.github/workflows/deploy.yml`, `docker-compose.prod.yml` with cloudflared sidecar, `docs/DEPLOY.md` runbook).
  - `57ea250` — Continuous deploy on `main` push + concurrency guard (`deploy-production` group).
  - `9d032f7` — AppTest UI smoke (4 tests in `tests/integration/test_streamlit_smoke.py`).
  - `9cf72ad` — This handoff doc (`CLAUDE.md`).
- Local tag `v0.5.0` exists at `445d3d8` but is NOT pushed (sandbox 403s tag refs). User must push from outside.
- CI/CD is configured but inert — pending 4 GitHub Secrets + Cloudflare Tunnel + VPS `.env`. Full runbook in `docs/DEPLOY.md`.
- Verified end-to-end: pytest green, `validate.sh` green, AppTest both modes clean, multi-jurisdiction scenarios all pass.
- Decisions: (1) chose GHCR + SSH-pull deploy over rsync + systemd — image tags give clean rollback. (2) chose Cloudflare Tunnel over public-port + Origin Cert — no inbound ports = smaller attack surface, no cert management. (3) chose continuous deploy on main push (gated by tests + optional `production` environment review rule) over tag-only — faster feedback loop.

### 2026-05-20 — Round F merge to main

- HEAD on main: `80396cc` (was `81c5b2b`)
- Tests: **386 passing** (was 290)
- Shipped: India jurisdiction (full engine, old+new regime, 87A, surcharge, cess, LTCG split, ITR JSON), residency tests (US SPT, CA 183, India §6, treaty hints), cross-border guardrails (student-loan single-claim, RSU sourcing, FTC hints), multi-source ingestion (.xlsx + .csv + dedupe), natural-language intake (`parse_intake_narrative`), 7 real-world cross-border scenarios.
- UI fully wired: auth sidebar, manual intake expander, correction chat tab, inline edit, revision history, residency-days input, NL intake textbox.
- Force-pushed `claude/tax-filing-agent-mJITD` to absorb 3 pre-PR-#1 commits that were superseded; then fast-forward merged to `main`.

---

*End of handoff. Edit me freely; preserve the structure.*
