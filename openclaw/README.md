# OpenClaw setup for DocsApp

OpenClaw reads `AGENTS.md` from the configured workspace, rather than recursively discovering arbitrary project directories. Configure the DocsApp OpenClaw agent's workspace to this repository root:

```text
D:\Projects\Systems\DocsApp
```

With that workspace, OpenClaw loads the root [`AGENTS.md`](../AGENTS.md), which delegates to the canonical [`.agents/AGENTS.md`](../.agents/AGENTS.md).

Do not copy the project rules to an OpenClaw home workspace: that would create a divergent source of truth. Keep OpenClaw identity, memory, and channel-specific configuration outside this repository; project engineering instructions remain in `.agents/`.
