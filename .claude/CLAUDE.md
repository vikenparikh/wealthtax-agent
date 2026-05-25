# wealthtax-agent — Claude router

> Tight router (target <2 KB). Lazy-load everything else.

## Read order (session start)

1. This file (you're here).
2. [.claude/INDEX.md](.claude/INDEX.md) — top-level topic graph for this repo.
3. [.claude/memory-bank/activeContext.md](.claude/memory-bank/activeContext.md) — what's in flight.
4. [.claude/kg/index.md](.claude/kg/index.md) — knowledge graph entry (if seeded).
5. Stop. Use INDEX + KG to route to specific files. Do NOT speculatively read.

## How to find things (cheapest → most expensive)

1. **INDEX.md** — file map (~3 KB)
2. **KG** — `.claude/kg/concepts/<concept>.md` for atomic summaries with backlinks
3. `grep -rl <kw> src/` for unindexed code
4. `bash .claude/scripts/build-rag.sh query "<question>"` — semantic search (if built)
5. Last resort: speculative Read

## Skills available (via Skill tool — lazy-loaded)

- **graphify** — context-graph + multi-task + memory mechanism (session-start protocol)
- **knowledge-graph** — Karpathy-style atomic-concept KG under `.claude/kg/`
- **kg-update** — incremental KG maintenance after code changes
- **log-prompt** — append every material prompt to `.claude/memory-bank/prompts.md` (forever)
- **tdd** — Matt Pocock's TDD workflow
- **handoff** — end-of-session memory-bank update
- **improve-codebase-architecture** — structural review
- **triage / diagnose / zoom-out / prototype / to-prd** — engineering loops
- **ralph-loop** — autonomous "do until done" runs (frankbria/ralph-claude-code)

Full list: [.claude/skills-shared/](.claude/skills-shared/)

## Plugins (49 curated, lazy-loaded)

python-development, frontend-mobile-development, backend-development, tdd-workflows,
debugging-toolkit, security-compliance, kubernetes-operations, llm-application-dev,
machine-learning-ops, agent-orchestration, comprehensive-review, git-pr-workflows
+ 37 others. See [.claude/plugins/](.claude/plugins/).

## Safety (enforced by hooks, see [.claude/rules/00-safety.md](.claude/rules/00-safety.md))

- `rm -rf` on home/root/project blocked
- `git push --force` to main/master/production blocked
- `git commit` containing secrets (AWS/Anthropic/OpenAI/JWT/PEM) blocked
- Production DB resets blocked

Override sentinels (append to the command, use sparingly):

- `# ACK-DANGEROUS` — bypass block-dangerous.sh for one specific command. Example:
  `rm -rf .claude/rag # ACK-DANGEROUS`
- `# ACK-SECRET` — bypass block-secret-commit.sh when the matched string is a
  fixture or placeholder. Example: `git commit -m "add docs" # ACK-SECRET`
- For raw git outside Claude Code: `GIT_SECRET_ACK=1 git commit ...` (the
  pre-commit hook installed at `.git/hooks/pre-commit` also enforces secret
  scanning — bypass with `--no-verify` only if you're certain).

## Style (see [.claude/rules/10-style.md](.claude/rules/10-style.md))

- Terse. 1-3 sentences default. No preamble, no trailing filler.
- Code comments: only when WHY is non-obvious.
- Markdown links for file refs, no backticks.

## End of session

Run the **handoff** skill — updates `.claude/memory-bank/{activeContext,progress,decisions}.md`.
