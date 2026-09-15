#!/bin/bash
set -e

# Ensure uploads directory exists and is writable by appuser.
# The shared named volume may be root-owned on first mount.
mkdir -p /app/uploads
chown appuser:appuser /app/uploads 2>/dev/null || true

# Drop privileges to appuser and run the actual command
exec runuser -u appuser -- "$@"
