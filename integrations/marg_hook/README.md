# Marg ERP Integration

This is the project's supported Marg ERP integration path, built on Marg ERP's
official hook mechanism. It converts Marg CSV exports to the Nexus Inventory
Platform import format and submits them through the documented API. It is not
an official or endorsed Marg ERP integration.

## Install locally

```powershell
powershell -ExecutionPolicy Bypass -File .\integrations\marg_hook\install_local.ps1
```

This copies the kit to:

```text
C:\nexus-inventory\marg-hook
```

## Marg setup

Use `marg_full_sync_commands.txt` for an operator-initiated initial import.
Detailed Marg scripting guidance is intentionally limited because hook syntax
and execution behavior vary by Marg deployment and version.

> **Experimental:** `marg_footer_end_hook.txt` demonstrates automatic footer
> sync, but it does not serialize overlapping bill events. Do not deploy it
> unattended until you add a site-specific lock or queue and validate it in a
> non-production company.

## Configuration

Set credentials as environment variables on the client machine. The kit has no
default username, password, or token.

```text
NEXUS_BASE_URL=http://127.0.0.1:8000/api/v1
NEXUS_EMAIL=<service-account-email>
NEXUS_PASSWORD=<service-account-password>
MARG_SYNC_DIR=C:\marg-sync
MARG_DEFAULT_LOCATION=Main
```

Prefer `NEXUS_TOKEN` where an appropriately scoped short-lived token can be
provisioned. Never embed credentials in Marg scripts or commit them to source.

## Commands

```powershell
C:\nexus-inventory\marg-hook\nexus_marg_sync.ps1 sync-all
C:\nexus-inventory\marg-hook\nexus_marg_sync.ps1 sync-products
C:\nexus-inventory\marg-hook\nexus_marg_sync.ps1 sync-batches
C:\nexus-inventory\marg-hook\nexus_marg_sync.ps1 sync-transactions
```

Logs are written to:

```text
C:\nexus-inventory\logs
C:\marg-sync\logs\nexus-inventory-marg-sync.log
```

## Trademark And Affiliation

This project is independent and is not affiliated with, sponsored by, or
endorsed by Marg ERP or its owners. Marg ERP and related names and marks belong
to their respective owners. References identify interoperability only.
