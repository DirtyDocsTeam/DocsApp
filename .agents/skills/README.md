# Project skill registry

Skills contain scoped instructions or reusable workflows for agents. Prefer an installed local skill when it matches the task.

## Status

The project has the following installed skills. When an agent needs a capability that is not available locally or globally, use `find-skills` first to search the open skills ecosystem. Verify the source and quality of a result, recommend the candidate to the user, and do not install it without approval.

## Installed skills

### `find-skills`

- **Purpose:** Discover relevant agent skills and guide safe installation decisions.
- **Location:** `find-skills/SKILL.md`
- **Use for:** A user requests an ability that may be provided by an installable skill, or the agent identifies a missing specialized workflow.
- **Prerequisites / dependencies:** Node.js 22.20+ to run the upstream `npx skills` CLI. The present environment has an older Node.js version; upgrade it before using CLI search/install commands.
- **Invocation notes:** Search with `npx skills find <specific-query>` after checking well-known sources; evaluate install count and source reputation. Keep any installed project skill under `.agents/skills/` and register it here.

| Skill | Purpose | Source |
| --- | --- | --- |
| `grill-with-docs` | Reconcile plans with repository code and documentation before multi-stage work. | [mattpocock/skills](https://github.com/mattpocock/skills) |
| `domain-modeling` | Define product entities, relationships, terminology, and invariants. | [mattpocock/skills](https://github.com/mattpocock/skills) |
| `codebase-design` | Design coherent module boundaries before implementation. | [mattpocock/skills](https://github.com/mattpocock/skills) |
| `to-spec` | Convert an early idea into an implementable technical specification. | [mattpocock/skills](https://github.com/mattpocock/skills) |
| `implement` | Execute an approved plan and verify its results. | [mattpocock/skills](https://github.com/mattpocock/skills) |
| `code-review` | Review changes for defects, risks, clarity, and missing tests. | [mattpocock/skills](https://github.com/mattpocock/skills) |
| `diagnosing-bugs` | Reproduce a defect and test hypotheses before changing code. | [mattpocock/skills](https://github.com/mattpocock/skills) |
| `frontend-design` | Design product UI with deliberate visual direction and accessible interaction. | [anthropics/skills](https://github.com/anthropics/skills) |
| `web-design-guidelines` | Review usability, responsive behavior, and accessibility. | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) |
| `vercel-react-best-practices` | Improve React/Next.js performance and data-loading behavior. Installed at `react-best-practices/SKILL.md` to match the upstream folder name. | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) |

Add every future installed skill using this format:

```md
## <Name>

- **Purpose:**
- **Location:**
- **Use for:**
- **Prerequisites / dependencies:**
- **Invocation notes:**
```

If a needed capability is unavailable, use `find-skills` to discover one rather than silently assuming it exists.
