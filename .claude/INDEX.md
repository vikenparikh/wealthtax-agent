# INDEX — wealthtax-agent

> One-page context graph. Read this BEFORE reading anything else in this repo.
> Rebuild with: `bash .claude/scripts/build-index.sh > .claude/INDEX.md`
>
> Generated 2026-05-28T22:41Z.

## About

**WealthTax Agent – Multi-Jurisdiction Tax Draft Assistant (CA / US / IN)**

This is a prototype built for the Wealthsimple builder challenge.

## Top-level layout

| Dir | Purpose |
|-----|---------|
| [WealthTaxDemoVideos](WealthTaxDemoVideos/) | — |
| [alembic](alembic/) | — |
| [docs](docs/) | docs (see Documents below) |
| [sample_tax_slips](sample_tax_slips/) | — |
| [scripts](scripts/) | operational scripts |
| [src](src/) | primary source |
| [tests](tests/) | test suite |

## Documents

| Path | Title |
|------|-------|
| [docs/DEPLOY.md](docs/DEPLOY.md) | Deploy |
| [docs/SUBMISSION.md](docs/SUBMISSION.md) | Wealthsimple AI Builder Submission – WealthTax Agent |
| [docs/SUBMISSION_CHECKLIST.md](docs/SUBMISSION_CHECKLIST.md) | Submission Checklist (Wealthsimple AI Builder) |
| [docs/architecture.md](docs/architecture.md) | Architecture |
| [docs/demo_runbook.md](docs/demo_runbook.md) | Demo Runbook (3 minutes) |
| [docs/demo_screenshots.md](docs/demo_screenshots.md) | Demo Screenshots Guide |
| [docs/demo_voiceover.md](docs/demo_voiceover.md) | Demo Voiceover Script (2:30) |
| [docs/groq-dpa-marker.md](docs/groq-dpa-marker.md) | Groq Data Processing Agreement — Marker |
| [docs/run_history.md](docs/run_history.md) | Validation Run History |

## Key files at root

- [README.md](README.md) — WealthTax Agent – Multi-Jurisdiction Tax Draft Assistant (CA / US / IN)
- [ARCHITECTURE.md](ARCHITECTURE.md) — WealthTax Agent — Architecture
- [CLAUDE.md](CLAUDE.md) — Claude session handoff — `wealthtax-agent`
- [CHANGELOG.md](CHANGELOG.md) — Changelog
- [docker-compose.yml](docker-compose.yml) — —
- [Dockerfile](Dockerfile) — —
- [pyproject.toml](pyproject.toml) — —
- [requirements.txt](requirements.txt) — —

## Code surface

- Python: 7791 files
- TypeScript: 1 files
- JavaScript: 164 files
- Shell: 11 files
- Markdown: 95 files

## Memory pointers

- Active focus: [.claude/memory-bank/activeContext.md](.claude/memory-bank/activeContext.md)
- Past sessions: [.claude/memory-bank/progress.md](.claude/memory-bank/progress.md)
- Decisions log: [.claude/memory-bank/decisions.md](.claude/memory-bank/decisions.md)
- Glossary: [.claude/memory-bank/glossary.md](.claude/memory-bank/glossary.md)

## How to run things

- Compose: `docker compose up -d` (see [docker-compose.yml](docker-compose.yml))
- Python: see [pyproject.toml](pyproject.toml)
- Python deps: [requirements.txt](requirements.txt)

## Claude shared content (symlinked from root)

- Hooks: [.claude/hooks/](.claude/hooks/) (block-dangerous, block-secret-commit)
- Rules: [.claude/rules/](.claude/rules/) (safety, style)
- Skills: [.claude/skills-shared/](.claude/skills-shared/) (graphify, tdd, handoff, …)
- Agents: [.claude/agents-shared/](.claude/agents-shared/)
- Plugins: [.claude/plugins/](.claude/plugins/) — 49 wshobson plugins covering python/frontend/k8s/security/ML/…

Edit the root copies at `~/Downloads/Projects/.claude/` to update every repo at once.
