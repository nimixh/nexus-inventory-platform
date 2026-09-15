# Nexus Inventory Platform

A tenant-aware inventory synchronization backend built with FastAPI,
PostgreSQL row-level security, Redis, Celery, and Alembic. It accepts CSV or
XLSX product, batch, and transaction imports, normalizes them into a shared
inventory model, and exposes job status and product APIs.

The repository also includes a Marg ERP integration built on Marg ERP's
official hook mechanism under `integrations/marg_hook`. It is maintained by
this project and is not an official or endorsed Marg ERP integration.

> **License status:** No license is granted for this repository. The code is
> source-available for review, but it is **not open source** and may not be
> copied, modified, distributed, or used except with the copyright owner's
> explicit permission.

## Capabilities

- Tenant isolation using PostgreSQL row-level security (RLS)
- JWT access tokens and rotating, Redis-backed refresh tokens
- Authenticated, tenant-bound viewer provisioning by owners and admins
- Owner, admin, operations, and viewer roles
- Asynchronous CSV/XLSX ingestion with retry-aware file retention
- Products, batches, and inventory transactions
- Marg ERP export transformation and upload tooling
- OpenAPI documentation at `/docs`

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for component boundaries,
data flow, tenancy, and retry behavior. See
[`docs/marg-integration.md`](docs/marg-integration.md) for the supported Marg
workflow and its current automation limitation.

## Requirements

- Docker Engine with Docker Compose v2.24 or newer
- For host development: Python 3.14 and [uv](https://docs.astral.sh/uv/)

## Quick Start

1. Create local configuration:

   ```bash
   cp .env.example .env
   openssl rand -hex 32
   ```

2. Put the generated value in `JWT_SECRET_KEY`. Set unique initial owner
   values in `SEED_OWNER_EMAIL` and `SEED_OWNER_PASSWORD`. The example file
   intentionally contains no usable application credentials.

3. Start PostgreSQL and Redis:

   ```bash
   docker compose up -d postgres redis
   ```

4. Build the application image and apply migrations once:

   ```bash
   docker compose build app
   docker compose run --rm app alembic upgrade head
   ```

5. Start the API and worker:

   ```bash
   docker compose up -d app worker
   curl http://localhost:8000/api/v1/health
   ```

Migrations are intentionally a separate operation to avoid startup races when
multiple API or worker replicas start concurrently. PostgreSQL and Redis are
bound to loopback in the development Compose file.

## Configuration

Required application settings:

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Privileged connection used by Alembic and administrative queries |
| `RUNTIME_DATABASE_URL` | Non-bypass connection used for RLS-scoped traffic |
| `REDIS_URL` | Refresh-token store and default Celery broker/backend |
| `JWT_SECRET_KEY` | Signing secret, at least 32 characters |

Bootstrap-only settings:

| Variable | Purpose |
| --- | --- |
| `SEED_OWNER_EMAIL` | Initial owner email required by the seed migration |
| `SEED_OWNER_PASSWORD` | Initial owner password required by the seed migration |

## User Provisioning

Public self-registration is disabled; `/api/v1/auth/register` does not exist.
The bootstrap migration creates the first owner from explicit
`SEED_OWNER_EMAIL` and `SEED_OWNER_PASSWORD` values. After logging in, an owner
or admin can provision a viewer with:

```bash
curl -X POST http://localhost:8000/api/v1/auth/users \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email":"viewer@example.com","password":"replace-with-a-strong-password"}'
```

The endpoint derives the new account's tenant from the authenticated caller.
It does not accept a tenant ID or role, preventing cross-tenant enrollment or
privilege selection. Elevated roles require a controlled administrative
process outside this public API.

## Local Development

Install locked dependencies and run checks:

```bash
uv sync --frozen
uv run pytest
uv run ruff check .
uv run mypy app tests integrations
```

Integration tests expect PostgreSQL on `127.0.0.1:5432` and Redis on
`127.0.0.1:6379`. Start them with `docker compose up -d postgres redis`.

## Packaging

The Python distribution is explicitly configured in `pyproject.toml` as
`nexus-inventory`; the wheel contains the `app` package. Build it with:

```bash
uv build
```

Marg deployment scripts are operational assets and are not included in the
Python wheel.

## Trademark And Affiliation

This project is independent and is not affiliated with, sponsored by, or
endorsed by Marg ERP or its owners. Marg ERP and related names and marks belong
to their respective owners. References identify interoperability only.

## Security

Read [`SECURITY.md`](SECURITY.md) before deployment. Do not expose the
development database credentials or Compose services publicly. Production
deployments must use unique database credentials, TLS, secure cookies, a
managed secret store, and restricted network access.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). By submitting a contribution, you
confirm that the owner may use it in this source-available project; submission
does not grant a license to the repository.
