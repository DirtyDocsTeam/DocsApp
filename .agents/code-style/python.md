# Python style

- Target the Python version declared by the project. Use `ruff`/`black`/`mypy` or project equivalents when configured; configuration overrides this guide.
- Use `snake_case` for modules, functions, variables, and parameters; `PascalCase` for classes; `UPPER_SNAKE_CASE` for constants.
- Add type hints to public functions, worker entry points, service boundaries, and non-trivial internal functions. Represent optional values explicitly with `T | None` (or the project's equivalent).
- Keep imports grouped and ordered by formatter/linter: standard library, third party, then project-local. Avoid `import *` and imports with side effects.
- Use `pathlib` for filesystem paths, context managers for resources, and parameterized database queries. Never interpolate untrusted values into shell commands, SQL, templates, or storage paths.
- Catch only expected exception types at a boundary, add useful context when re-raising, and preserve the original cause with `raise ... from exc` where appropriate. Do not use bare `except:` or silently ignore errors.
- Model worker payloads and configuration explicitly (for example, dataclasses or validated models) rather than passing untyped dictionaries through multiple layers.
