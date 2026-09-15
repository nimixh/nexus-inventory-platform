# Architecture

## Components

```text
Client / Marg export
        |
        v
FastAPI API ---- Redis (refresh tokens, Celery broker/results)
        |                         |
        v                         v
PostgreSQL <---------------- Celery worker
   RLS                         CSV/XLSX normalization
```

- `app/routes` defines HTTP boundaries and role checks.
- `app/services` coordinates authentication and synchronization workflows.
- `app/repositories` contains persistence operations.
- `app/integrations` defines connector and file-storage abstractions.
- `app/models` and `alembic` define the relational model and migrations.
- `integrations/marg_hook` uses Marg ERP's official hook mechanism to adapt Marg
  exports. The adapter is maintained by this project and is not endorsed by
  Marg ERP.

## Tenancy And Trust Boundaries

Every domain row carries a tenant identifier. Normal request traffic uses the
runtime database role after setting `app.current_tenant_id`; PostgreSQL RLS is
the final isolation boundary. Administrative sessions are reserved for login,
bootstrap, upload orchestration, and migration operations where tenant context
is established or checked explicitly.

The Compose database credentials are development-only. A production deployment
must create separate owner and runtime credentials and prevent the runtime role
from bypassing RLS.

## Authentication

Access tokens are short-lived JWTs. Refresh tokens are HTTP-only cookies and
their identifiers are stored in Redis; refresh rotates them atomically with
`GETDEL`. There is no public registration endpoint. The bootstrap migration
requires explicit initial owner credentials and stores only the password hash.
An authenticated owner or admin may provision viewer accounts; the tenant ID
comes from the authenticated user rather than request data.

## Import Lifecycle

1. An authorized owner, admin, or operations user uploads `.csv` or `.xlsx`.
2. The API validates size/type, writes a UUID-prefixed file, creates a pending
   sync log, and enqueues `sync_erp_data`.
3. A worker sets tenant context, parses and normalizes rows, persists valid
   records, and records bounded API-visible errors.
4. Successful jobs delete their source upload.
5. Fatal failures are marked failed and raised to Celery. The source upload is
   retained for exponential-backoff retries and deleted after the last attempt.

An abrupt worker or host failure can leave an orphaned upload. Operators should
monitor the upload volume and apply an age-based cleanup policy only after
reconciling files against nonterminal sync logs.

## Deployment

Migrations are a one-off deployment step and never run in API startup. This
avoids races between replicas. API and workers share the upload volume in the
local Compose deployment; production deployments should use durable shared
object storage by implementing the existing `FileStorage` protocol.
