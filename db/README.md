# LEASH database migrations

Rishi owns this schema. PostgreSQL is the durable source of truth; the API is the
only application writer. Preserve Cameron's existing `users` table and UUID auth
IDs. LEASH-prefixed identities are a separate mapping.

From `api/`, run `python manage.py migrate` with `DATABASE_URL` configured.
API startup runs the same migration runner. Applied file checksums are recorded
in `schema_migrations`; add a new ordered SQL file rather than changing an applied
one. Migrations serialize across replicas and commit atomically. Do not apply
migrations to the shared deployment merely to run tests.

`0001_users.sql` adopts the existing auth table. `0002_mandate_authority.sql`
adds scoped identities/agents, mandate versions/confirmations/transitions, bound
runs, append-only audit records and separate pending delivery state.

See [the R02 handoff](../api/r02-handoff.md) for provisioning, request examples,
signature format, transactions, tests, deployment requirements and remaining
grant/Valkey integration. Database history triggers prevent application mutation;
they do not replace database access control or backup policies.
