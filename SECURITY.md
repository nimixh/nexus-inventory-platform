# Security Policy

## Reporting A Vulnerability

Do not open a public issue for a suspected vulnerability. Report it privately
to the repository owner or through the private security-reporting channel shown
on the repository hosting page. Include affected versions, reproduction steps,
impact, and any suggested mitigation. Do not include real customer data or
credentials.

The owner will acknowledge a complete report when practical, investigate it,
and coordinate disclosure after a fix is available. No bug-bounty program or
response-time commitment is currently offered.

## Deployment Baseline

- Generate unique JWT, database, Redis, and seed-owner secrets.
- Keep `.env`, uploads, backups, tokens, and logs out of version control.
- Run the API behind TLS and leave `COOKIE_SECURE=true`.
- Do not expose PostgreSQL or Redis to untrusted networks.
- Preserve the split between migration/admin and RLS-enforced runtime roles.
- Keep public self-registration disabled; provision viewers as an owner/admin.
- Restrict upload size and monitor retained/orphaned files.
- Treat Marg footer automation as experimental until serialized at the site.

The values in `docker-compose.yml` are for loopback-only development and are
not production credentials.
