# Decisions log — wealthtax-agent

> ADR-lite. Record choices that should not be re-litigated. One block per decision.
> Format:
>
> ## YYYY-MM-DD — Short title
> **Context:** why we had to decide
> **Decision:** what we chose
> **Consequences:** what changed downstream

<!-- append new decisions below -->

## 2026-05-25 — Symlink-based shared `.claude/` framework

**Context:** Want one place to edit hooks/skills/plugins and have the change appear in every repo. Copying duplicates would drift; nested git submodules add overhead.

**Decision:** Root canonical at `~/Downloads/Projects/.claude/` holds hooks, rules, skills-shared, agents-shared, plugins, vendor, scripts, templates. Per-repo `.claude/` has those as symlinks plus its own real CLAUDE.md, INDEX.md, settings.json, memory-bank, kg, scripts. Edits at root propagate instantly.

**Consequences:** Cross-platform caveat — symlinks point to macOS-absolute paths so they dangle on the VPS unless replicated. Mitigated by `/opt/app/.claude-root/` on the VPS and a per-VPS-repo repointing pass.

## 2026-05-25 — RAG backend: `grep + claude -p`, not embeddings

**Context:** First version used Ollama + `nomic-embed-text` for semantic search. It needed 4 GB resident memory, ~20 min/repo build time, and 500-errored on files > ~2048 tokens. We already use the `claude` CLI everywhere.

**Decision:** Replace embedding-based RAG with a thin keyword-grep + `claude -p` ranking pass. `build-rag.sh build` writes a one-page listing (path | first-H1 | frontmatter-tags). `query` greps the listing by extracted keywords then hands matches to `claude -p` for ranking with rationale.

**Consequences:** Build time 10 sec instead of 20 min. No daemon, no model files. Query cost is one Claude turn (~$0.01). Less fuzzy-semantic recall, but at our repo sizes the keyword filter + KG already cover the gap. Ollama uninstalled (~380 MB freed).

## 2026-05-25 — Append-only `prompts.md` per repo

**Context:** Want to be able to answer "what did we ask Claude to do in this repo" years from now. Per-session memory in Claude is ephemeral. CLAUDE.md is for instructions, not history.

**Decision:** Each repo gets `.claude/memory-bank/prompts.md` with frontmatter (timestamp, intent, outcome, touched files, notes). The `log-prompt` skill appends to it after every material turn. Never edit or delete — only append.

**Consequences:** Permanent prompt history per repo. Reading it gives a future agent (or human) the full intent thread. Grows over time but stays human-scannable.

## 2026-05-25 — Karpathy-style KG over embedded indexes

**Context:** Need a way for an agent to navigate a repo without reading everything. Two patterns considered: vector RAG (semantic search) vs. atomic-concept knowledge graph (Karpathy / Andy Matuschak style).

**Decision:** Both, with KG as primary. Each repo has `.claude/kg/{index.md, concepts/<slug>.md}` — atomic concept files (≤80 lines each) with frontmatter linking `related:` concepts and `files:` paths. Validator (`kg-validate.sh`) enforces link integrity. RAG (now grep+claude) is the soft-search fallback.

**Consequences:** Traversable, human-readable, version-controlled context layer. 63 concept files total across 9 repos at bootstrap, all validating clean. Drift discipline required: `kg-update` skill must run after material code changes or the graph rots.

## 2026-05-25 — Hooks block, don't auto-fix

**Context:** Could implement secret-commit / dangerous-command hooks as autocorrect (e.g. strip the secret, rewrite the rm path) or as blockers.

**Decision:** Block (exit 2) with a clear reason + override sentinel. Never silently rewrite the user's command. Sentinels: `# ACK-DANGEROUS`, `# ACK-SECRET`, `GIT_SECRET_ACK=1` for the git pre-commit variant.

**Consequences:** User stays in control. Sentinels are deliberately ugly so they aren't reached for casually. The git pre-commit variant works outside Claude Code (CLI git, IDE git, GitHub Desktop) — defense in depth.

