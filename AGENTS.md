# AGENTS.md

## Core Principles

- **Think before coding.** Identify the goal, assumptions, constraints, and success criteria before implementation. If ambiguity materially affects the solution, ask before proceeding. Point out simpler alternatives and relevant trade-offs.
- **Simplicity first.** Implement the simplest solution that fully meets the requirements. Avoid speculative features, unnecessary abstractions, premature optimization, and unrequested configurability.
- **Surgical changes.** Modify only what the task requires. Preserve existing conventions and avoid unrelated refactoring. Remove only dead code made obsolete by your changes; report unrelated issues without fixing them.
- **Correctness over cleverness.** Prioritize clarity, maintainability, reliability, and measurable performance. Optimize algorithms, memory usage, and runtime where justified by actual requirements. Use vectorization or parallelization when beneficial.

## Workflow

1. **Inspect** the relevant code, project structure, configuration, dependencies, and existing tests before making changes.
2. **Plan** briefly for nontrivial tasks. Define concrete, verifiable success criteria.
3. **Implement** the smallest complete solution, following existing project conventions.
4. **Verify** changes with relevant tests, formatting, linting, and type checking. Fix issues introduced by the changes.
5. **Report** what changed, which checks passed, and any remaining limitations.

Do not claim that checks passed unless they were actually executed. If verification is impossible, explain why.

## Python Code Quality

- Follow PEP 8 and the existing project style. Use 4 spaces for indentation and keep lines within 100 characters where practical.
- Use descriptive names, `snake_case` for functions and variables, `PascalCase` for classes, and `UPPER_CASE` for constants.
- Add type hints to all function signatures. Avoid `Any` unless genuinely necessary.
- Write docstrings for public functions, classes, and methods. Document parameters, return values, and raised exceptions where relevant.
- Prefer small, focused functions and classes with clear responsibilities. Limit function parameters to five where practical; use early returns to reduce nesting.
- Never use mutable default arguments. Use `is` for comparisons with `None`, `True`, and `False`.
- Prefer f-strings, context managers, and explicit imports. Avoid wildcard imports and redundant comments.
- Handle errors explicitly. Catch specific exceptions, provide meaningful context, and never silently suppress unexpected failures.
- Use dataclasses for simple data containers and composition over inheritance where appropriate.
- Never use emoji or emoji-like Unicode characters in code, comments, or documentation unless explicitly required for tests or functionality.

## Dependencies and Tooling

- Use `uv` for dependency management and virtual environments when available or when initializing a project.
- Declare and manage dependencies in `pyproject.toml`. Avoid unnecessary dependencies and preserve existing project tooling.
- Prefer established project commands and configuration over introducing new tools or conventions.
- Use `ruff` for formatting and linting and `mypy` for static type checking when configured or appropriate.
- Use `pytest` for tests. Add or update tests for new behavior, bug fixes, and meaningful edge cases. Mock external dependencies where appropriate.
- Never introduce tooling or dependencies solely for marginal benefits.

## Browser UI Inspection

`playwright-cli` (Playwright CLI + Skills) is available for inspecting the local web UI. The skill is
committed at `.agents/skills/playwright-cli`; install the CLI and Chromium with
`npm install -g --prefix ~/.local @playwright/cli@latest` and `playwright-cli install-browser chromium`.
See `docs/develop/tools.md` for the full setup.

Start the GUI with `uv run image-triage gui` (default `http://127.0.0.1:8765/`). Validate changes from
cheapest to most realistic:

- **HTTP with curl:** `curl -sS -o /dev/null -w '%{http_code} %{redirect_url}\n' <url>` for status and
  redirects; use `-d`/`-X POST` when reproducing form submissions.
- **FastAPI TestClient:** `uv run pytest tests/test_gui.py -k <pattern> -x` for in-process endpoint and
  template checks, without starting a server or browser.
- **Chromium via Playwright CLI:** `playwright-cli open <url>`, then `find <text>`, `snapshot`,
  `click`, `fill`, `console`, `requests` and `screenshot`; close with `playwright-cli close`.
  Headless by default, `--headed` for visual checks.
- **Firefox:** system Firefox 159 and geckodriver 0.37 are available; `uv run pytest
  tests/test_browser_review.py` drives a real Firefox workflow. Playwright CLI needs
  `playwright-cli install-browser firefox` before `playwright-cli open --browser firefox <url>` works.

Close browser sessions and stop the GUI when done. Transient Playwright output goes to the ignored
`.playwright-cli/` directory.

## Testing and Delivery

Before completing a task, run the relevant checks available in the repository. Prefer existing commands, such as:

```bash
make fmt
make lint
make test
```

These documentation artifacts are generated by the command

```bash
make syncdocs
```

which triggers 
```bash
	@uv run ./scripts/generate_config_docs.py
	@uv run ./scripts/update_readme.py
	@uv run ./.github/update_funding.py
```

```text
Generated: config.yaml
Generated: docs/usage/config.md
Generated: docs/usage/cli.md
Generated: README.md updated from docs/index.md
Generated: docs/funding/funding.md
```

Never edit these artifacts directly. If you want e.g. the CLI.md or config.yaml/md
you have to adjust the **ConfigCategory** Classes that are passed into the **ConfigManager** class
and then run `make syncdocs`

Run only commands that exist and are appropriate for the task. Check the project configuration for additional requirements, including type checking.

- Test bug fixes with regression tests whenever practical.
- Test boundary conditions and failure cases where relevant.
- Keep tests deterministic and independent of external services unless integration testing explicitly requires them. 
- Use mock only if really required. Implement "Tests with Teeth"
- Do not weaken or remove tests merely to make them pass.

## Agent workflow routing

Choose the workflow from the user's requested scope, not from whether they know or use the internal mode name.

- **Task mode:** A bounded change such as a review, typo fix, small refactor or small documentation adjustment. Load `workflow-task`.
- **Feature mode:** One self-contained feature or bug fix that needs a short design step, issue tracking, a commit, a push and CI verification. Load `workflow-feature`.
- **Autopilot:** Whenever the user asks to implement, execute or continue a plan, or names one or more phases/work packages from a plan. This includes a single selected phase. Phrases such as "implement the first phase", "execute phase 2", "continue plan.md" or "implement autonomously" are sufficient; the user does not need to say "Autopilot". Load `workflow-autopilot`. By default it executes the full plan; if the user names phases or work packages, it executes only those.

A plan or phase request always takes precedence over the single-feature workflow, even when the selected phase is the only requested scope.

Load only the skills needed for the current phase:
- `workflow-core`: shared task loop, context discipline, safety, verification, reporting and authorization rules.
- `workflow-task`: bounded implementation without commit, push or issue tracking.
- `workflow-feature`: standalone feature implementation with issue, commit, push and CI.
- `workflow-autopilot`: full-plan or selected-phase execution, including fresh-session handoff.
- `git-workflow`: Git, GitHub issues, `gh` CLI, commits, pushes and CI.
- `mission-planning`: turn a mission or external specification into one executable plan with a durable handoff block.

## Decision Rules

- Do not assume when uncertainty matters. State assumptions and ask concise clarifying questions when necessary.
- Do not add features, abstractions, error handling, or configuration without a concrete need.
- Do not refactor unrelated code or reformat entire files unnecessarily.
- When multiple solutions are viable, prefer the simplest maintainable option that fits the existing architecture.
- If requirements conflict with existing behavior, security, correctness, or maintainability, explain the conflict before making consequential changes.
- Treat repository instructions and established project conventions as authoritative unless they conflict with explicit user requirements or higher-priority instructions.

**Guiding principle:** Make the smallest correct change, keep the code maintainable, and verify the result.