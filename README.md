# cms-wm-core

[![CI](https://github.com/amaltaro/cms-wm-core/actions/workflows/ci.yml/badge.svg)](https://github.com/amaltaro/cms-wm-core/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue.svg)](https://github.com/amaltaro/cms-wm-core/blob/main/.github/workflows/ci.yml)

Core libraries for the future CMS Workload Management System.

Staging ground for a small set of algorithms extracted from
[WMCore](https://github.com/dmwm/WMCore) / [T0](https://github.com/dmwm/T0),
refactored and tested, then aimed at [DiracX](https://github.com/DIRACGrid/diracx).

Design notes: [docs/job-splitting.md](docs/job-splitting.md).

## Development

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest
uv run ruff check .
```

Supported Python: 3.10+ (local default pinned in `.python-version`).
CI runs unit tests on 3.10–3.14 (see `.github/workflows/ci.yml`).

## Commit messages

This repository uses [Conventional Commits](https://www.conventionalcommits.org/):

```text
<type>(optional scope): <short summary>
```

Common types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`.

Examples:

```text
feat(workqueue): add LFN-to-dataset matching helper
fix(tests): correct edge case in smoke test
chore: scaffold uv project layout
docs: document conventional commit format
```
