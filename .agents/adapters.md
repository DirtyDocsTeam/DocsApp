# Agent and harness adapters

`.agents/` is the single source of truth. The following small adapter files make the same rules discoverable by common coding agents without copying them.

| Tool / harness | Project adapter | How it uses `.agents/` |
| --- | --- | --- |
| Codex | [`../AGENTS.md`](../AGENTS.md) | Reads the root entry point, which delegates to `.agents/AGENTS.md`. |
| DeepSeek Harness | [`../AGENTS.md`](../AGENTS.md) | Uses `AGENTS.md`-compatible project instructions; the root entry point delegates to `.agents/`. |
| Reasonix | [`../AGENTS.md`](../AGENTS.md) | Discovers `AGENTS.md` project memory/instructions natively and also recognizes project `.agents/skills/`. |
| Claude Code | [`../CLAUDE.md`](../CLAUDE.md) | Native `CLAUDE.md` adapter that delegates to `.agents/AGENTS.md`. |
| Cursor | [`../.cursor/rules/docsapp-agents.mdc`](../.cursor/rules/docsapp-agents.mdc) | Always-applied Cursor rule that delegates to `.agents/AGENTS.md`. |
| Roo Code | [`../.roo/rules/docsapp-agents.md`](../.roo/rules/docsapp-agents.md) | Project rule that delegates to `.agents/AGENTS.md`. |
| Cline | [`../.clinerules`](../.clinerules) | Project instruction adapter that delegates to `.agents/AGENTS.md`. |
| Windsurf | [`../.windsurfrules`](../.windsurfrules) | Project instruction adapter that delegates to `.agents/AGENTS.md`. |
| OpenClaw | [`../openclaw/README.md`](../openclaw/README.md) | Configure the OpenClaw agent workspace to the repository root; it then reads the root `AGENTS.md`. |
| Other AGENTS-compatible harness | [`../AGENTS.md`](../AGENTS.md) | Use the root entry point if the harness supports `AGENTS.md`. For a different native format, add a thin adapter here after verifying its documentation. |

## Maintenance rule

When a project rule changes, edit only the relevant file under `.agents/`. An adapter may change only to fix the path or satisfy the consuming tool's required metadata. If an adapter format cannot express a direct link, keep its body minimal and direct the agent to read `.agents/AGENTS.md` first.
