# Contributing

## Before You Start

Open an issue describing the change before substantial work. Security reports
must follow `SECURITY.md` and must not be filed publicly.

This repository has no license grant. By submitting a contribution, you state
that you have the right to submit it and permit the repository owner to use and
redistribute it as part of this project. Contact the owner before contributing
if those terms are unsuitable.

## Development

```bash
uv sync --frozen
docker compose up -d postgres redis
uv run pytest
uv run ruff check .
uv run mypy app tests integrations
```

Keep changes focused, add tests for behavior changes, and update public docs
when configuration or API contracts change. Never commit `.env`, credentials,
customer exports, generated uploads, caches, virtual environments, or local
agent/editor configuration.

## Pull Requests

Describe the problem, the chosen behavior, security or migration implications,
and the commands used to verify the change. Keep generated lockfile changes in
the same pull request as dependency changes.
