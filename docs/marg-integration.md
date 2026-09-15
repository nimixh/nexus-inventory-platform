# Marg ERP Integration

`integrations/marg_hook` is this project's supported Marg integration. It is
built on Marg ERP's official hook mechanism, reads CSV exports produced by
Marg, converts Marg fields into the platform's product, batch, and transaction
templates, uploads them through the authenticated API, and polls each job.

This project is independent and is not affiliated with, sponsored by, or
endorsed by Marg ERP or its owners. Marg ERP and related names and marks belong
to their respective owners. References identify interoperability only.

## Supported Workflow

1. Configure `NEXUS_BASE_URL` and either `NEXUS_TOKEN` or both `NEXUS_EMAIL`
   and `NEXUS_PASSWORD` on the Marg workstation.
2. Install the kit with `install_local.ps1`.
3. Run an operator-initiated full or entity-specific synchronization.
4. Review the local log and API job result before scheduling repeated runs.

No credentials are bundled. Use a dedicated least-privilege operations account
and protect the workstation environment and logs.

## Scripting Support

Marg hook languages and available fields differ across installations. The
included snippets document only the integration points exercised by this
project; they are not a general Marg scripting SDK or compatibility guarantee.
Validate exports and field mappings against a non-production company first.

## Experimental Footer Automation

`marg_footer_end_hook.txt` is experimental. It may start overlapping processes
when bills are finalized concurrently and currently has no cross-process lock,
idempotency key, or durable local queue. Use operator-triggered synchronization
unless your deployment adds and validates concurrency control.
