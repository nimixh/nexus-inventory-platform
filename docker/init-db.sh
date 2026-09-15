#!/bin/bash
set -e

# Create runtime role (non-superuser, no BYPASSRLS)
# Used by the app for normal request traffic — RLS enforced
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'nexus_runtime') THEN
            CREATE ROLE nexus_runtime LOGIN PASSWORD 'nexus_runtime';
        END IF;
    END
    \$\$;

    GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO nexus_runtime;
    GRANT USAGE ON SCHEMA public TO nexus_runtime;
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO nexus_runtime;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO nexus_runtime;
    GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO nexus_runtime;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE ON SEQUENCES TO nexus_runtime;
EOSQL

# Create and grant the integration-test database used by the documented test command.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 'CREATE DATABASE nexus_test'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'nexus_test')\gexec
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "nexus_test" <<-EOSQL
    GRANT CONNECT ON DATABASE nexus_test TO nexus_runtime;
    GRANT USAGE ON SCHEMA public TO nexus_runtime;
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO nexus_runtime;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO nexus_runtime;
    GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO nexus_runtime;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE ON SEQUENCES TO nexus_runtime;
EOSQL
