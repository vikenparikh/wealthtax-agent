# Prompts log — wealthtax-agent

> Append-only record of every user prompt directed at Claude in this repo,
> with timestamp + outcome. The point: years from now, "what did I ask for?"
> is answerable by reading this file alone.
>
> Updated by the `log-prompt` skill at the END of each user turn, and by the
> `handoff` skill at session close. Never delete entries — only append.

## Format

```
## YYYY-MM-DD HH:MM — short label
**Prompt:** verbatim or paraphrased to ≤ 200 chars
**Intent:** one line — what the user actually wanted
**Outcome:** done / partial / blocked / abandoned
**Touched:** path/a.py, path/b.md  (key files changed; omit if none)
**Notes:** anything non-obvious (constraints, why we chose X over Y)
```

<!-- prompts below, newest at top -->

## 2026-05-25 12:00 — bootstrap .claude/ framework across all repos

**Prompt:** "Add these setups to all repos and root folder" + follow-ups (graphify, KG, log-prompt, Matt Pocock skills, Ralph loop, marketplace plugins)
**Intent:** Stand up a uniform Claude Code config across all 9 repos with safety hooks, lazy-loaded skills, a context graph for token-efficient Opus use, and append-only prompt history.
**Outcome:** done
**Touched:**
- /Users/vikenparikh/Downloads/Projects/.claude/{hooks,rules,skills-shared,agents-shared,plugins,scripts,templates,vendor}/ (root canonical)
- 9 repos: AnyCompanyAgentFramework, Future-Human, Personal-AI-assistant, Trad-Platform, ai-agents-platform, betPlanet, medmind-ai, platform-infra, wealthtax-agent
**Notes:**
- Symlink design: edits at root propagate everywhere; per-repo CLAUDE.md/memory-bank stay editable in isolation
- Skills: graphify, knowledge-graph (Karpathy KG), kg-update, log-prompt, ralph-loop + 16 from mattpocock/skills
- 49 wshobson/agents plugins symlinked covering python/frontend/k8s/security/ML/agent-orchestration
- Hooks: block-dangerous (rm -rf, force push to main, prod DB resets) + block-secret-commit (AWS/Anthropic/OpenAI/GitHub/Slack/JWT/PEM). All 5 smoke tests pass.
- RAG fallback uses local Ollama + numpy. Optional; build when INDEX+KG don't suffice.
- Marketplace plugins available via .claude/scripts/install-marketplace-plugins.sh

