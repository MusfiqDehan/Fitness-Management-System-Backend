# AGENTS.md

## Cursor Cloud specific instructions

This is the Django REST API for the FitPulse multi-tenant gym SaaS
(schema-per-tenant via `django-tenants`, JWT auth, Celery, Channels/WebSockets).
It is developed here **natively (no Docker)** against a locally-installed
PostgreSQL and Redis. The web frontend lives in a sibling repo
(`Fitness-Management-System-Frontend`) and talks to this API on port `8021`.

Dependencies (system: PostgreSQL, Redis; Python venv + `pip install -r requirements.txt`)
are provisioned by the environment/update script — do not reinstall them here.
The following are the non-obvious things you need to run and develop the app.

### Start the backing services (not auto-started)

The update script never starts services. On a fresh session start Postgres and Redis:

```bash
sudo pg_ctlcluster 16 main start          # PostgreSQL 16 on :5432
sudo redis-server /etc/redis/redis.conf   # Redis on :6379 (see Redis caveat below)
```

- Local DB: database `gym_db`, role `gym_user` / password `gym_password` (superuser,
  needed so `django-tenants` can create per-tenant schemas).
- The Postgres data dir and Redis dump persist in the VM snapshot, so the schema
  migrations, seeded packages/features, superadmin, and demo tenants below are
  already present — you normally do NOT need to re-run migrations.

### Environment variables (critical gotcha)

`config/settings.py` reads `os.environ` directly — there is **no dotenv autoload**.
`.env.local` (gitignored) exists for native dev, but you must export it into the
process yourself before running any `manage.py` / `daphne` / `celery` command:

```bash
source .venv/bin/activate
set -a && . ./.env.local && set +a
```

`.env.local` is tuned for native dev: it leaves `DATABASE_URL` unset so settings
falls back to the `DB_*` vars pointing at `localhost:5432`. Do NOT set the
Docker-style `DATABASE_URL`/`DIRECT_DATABASE_URL` (they point at `pgbouncer`/`db`
hostnames that don't resolve natively).

### Run the API

```bash
daphne -b 0.0.0.0 -p 8021 config.asgi:application
```

Health: `curl http://localhost:8021/api/v1/health/ready/` → `{"ok": true, ...}`.
API docs: `/api/v1/docs/` (Swagger), `/api/v1/schema/`. Celery worker/beat are
optional for most work (`celery -A config.celery:app worker` / `beat`).

### Multi-tenancy / how to reach a tenant

Tenant is resolved from the request host. `localhost` → the public/platform
schema (landing pages, platform admin, superadmin login at
`/api/v1/identity/login/`). A gym tenant is reached via its subdomain, e.g.
`hellogym.localhost`. `*.localhost` hosts are mapped to `127.0.0.1` in
`/etc/hosts` (and Chrome resolves `.localhost` to loopback automatically).

Seed data already present (for manual testing / demos):
- Superadmin (public schema): `admin@fitpulse.local` / `Admin@12345`
- Demo tenant `hellogym` (subdomain `hellogym.localhost`), owner
  `owner@hellogym.test` / `Owner@12345`
- Default tenant `gym_local` (`local-gym.localhost`) auto-created on bootstrap.

Tenant feature access is package-gated: even a tenant superuser is denied
feature endpoints (e.g. `/api/v1/membership/members/`) unless platform packages
+ per-tenant feature flags are seeded. This is done via
`python manage.py seed_platform_packages --resync-tenants` (already run; re-run
if you create new tenants and their features look empty).

### Lint & tests

- Lint (matches CI): `ruff check .` and `ruff format --check .` (ruff 0.9.0).
  The repo currently has many pre-existing ruff findings — expect non-zero exit.
- Tests need Postgres + Redis running and CI-style env:
  `SKIP_DB_BOOTSTRAP=1`, `DATABASE_URL=postgresql://gym_user:gym_password@localhost:5432/gym_db`, `USE_PGBOUNCER=0`.
- Test discovery gotcha: a bare `python manage.py test` fails at import time
  because `apps/attendance/` contains BOTH a `tests.py` module and a `tests/`
  package (ambiguous `tests` import). Run per app instead, e.g.
  `python manage.py test apps.tenancy`.

### Redis caveat

Start Redis via its packaged config (`/etc/redis/redis.conf`) so its data dir is
the writable `/var/lib/redis`. If Redis is started from an arbitrary working
directory, RDB snapshotting fails and it starts rejecting writes with
`MISCONF ... unable to persist to disk`, which surfaces as errors in tests and
cache/Channels operations.
