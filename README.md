# Gym Management System Backend

This repository contains the Django REST API for the gym management system.

The backend uses django-tenants with PostgreSQL for schema-based multi-tenancy. In production it is served through Daphne behind Traefik, with Redis and Celery handling background work.

## Tech Stack

- Django
- Django REST Framework
- django-tenants
- PostgreSQL
- Redis
- Celery
- Daphne

## Requirements

- Python 3.12+
- PostgreSQL 17+
- Redis 7+
- Docker and Docker Compose for container-based development or production builds

## Environment Variables

Use [.env.example](.env.example) as the starting point for local development. Copy it to `.env.local` for local Docker runs or to `.env.prod` for production deployment, then adjust the values for your environment.

- `DATABASE_URL` or the `DB_*` variables for PostgreSQL connectivity
- `SECRET_KEY`
- `DEBUG`
- `ALLOWED_HOSTS`
- `PUBLIC_DOMAIN`
- `TENANT_BASE_DOMAIN`
- `PUBLIC_FRONTEND_URL` and `TENANT_FRONTEND_BASE_DOMAIN` for frontend routing
- `CORS_ALLOW_ALL_ORIGINS`, `CORS_ALLOWED_ORIGINS`, `CORS_ALLOWED_ORIGIN_REGEXES`
- `CSRF_TRUSTED_ORIGINS`, `SECURE_SSL_REDIRECT`
- `GYM_DEVICE_API_KEY`

## Folder Structure

```text
gym_app_back_end/
├── apps/
│   ├── access/
│   ├── attendance/
│   ├── audit/
│   ├── billing/
│   ├── catalog/
│   ├── cms/
│   ├── crm/
│   ├── dashboard/
│   ├── gym_class/
│   ├── identity/
│   ├── locations/
│   ├── membership/
│   ├── quick_action/
│   ├── tenancy/
│   └── trainer/
├── config/
├── media/
├── scripts/
├── static/
├── staticfiles/
├── utils/
├── Dockerfile
├── docker-compose.local.yml
├── docker-compose.prod.yml
├── entrypoint.sh
├── manage.py
└── requirements.txt
```

## Run Locally

### Docker development

The local compose file starts the API, Redis, PostgreSQL, Celery worker, and Celery beat scheduler.

```bash
docker compose -f docker-compose.local.yml up --build
```

This setup exposes the backend on port `8021` and the PostgreSQL container on port `5451`.

### Manual development

If you want to run the backend without Docker, create a virtual environment, install dependencies, run migrations, and start Daphne directly:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
daphne -b 0.0.0.0 -p 8021 config.asgi:application
```

Useful management commands:

```bash
python manage.py test
python manage.py makemigrations <app_name>
python manage.py migrate <app_name>
python manage.py collectstatic
```

## Run in Production

The production compose file runs PgBouncer, PostgreSQL, Redis, the ASGI backend (Hypercorn with 2 workers), Celery worker, and Celery beat. The backend sits behind Traefik on port `8021` inside the Docker network.

**Startup order:** Traefik → backend stack → frontend stack.

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Before starting, ensure the external `traefik_proxy` network exists.

### Memory budget (Contabo VPS 10 — 8 GB RAM)

| Service | Limit |
|---------|-------|
| PostgreSQL | 2560 MB |
| Backend (ASGI) | 1536 MB |
| Celery worker | 1024 MB (concurrency 2) |
| Redis | 512 MB |
| PgBouncer | 128 MB |
| Celery beat | 256 MB |

### Database connections

- Application traffic uses **PgBouncer** (`pgbouncer:6432`, session mode) — set `DATABASE_URL` in `.env.prod`.
- Migrations use **DIRECT_DATABASE_URL** (`db:5432`) — the entrypoint applies it when `RUN_MIGRATIONS=1`:

  ```bash
  docker compose -f docker-compose.prod.yml run --rm \
    -e RUN_MIGRATIONS=1 \
    backend python manage.py migrate_schemas --noinput
  ```

- When `USE_PGBOUNCER=1`, Django `CONN_MAX_AGE` is forced to `0`.

### Health checks

- Liveness: `GET /api/v1/health/tenant/`
- Readiness: `GET /api/v1/health/ready/` (PostgreSQL + Redis, returns 503 on failure)

### ADMS biometric devices

Devices use **HTTP only** on port 80 (not HTTPS). Configure firmware with:

```
http://{tenant}.fitssort.com/iclock/cdata
```

See [traefik/README.md](../traefik/README.md) for routing details.

## Notes

- Production ASGI uses Hypercorn with 2 workers (`scripts/run-asgi-prod.sh`).
- The app is multi-tenant — tenant and domain settings must be configured before deployment.
- Static and media volumes are mounted separately in production.
- Backups: see [docs/production-backup-restore.md](docs/production-backup-restore.md).


## Paymnent Integration Testing

Sandbox Environment

All the transaction made using this environment are counted as test transaction and has no effect with accounting, URL starts with https://sandbox.sslcommerz.com.

Test Credit Card Account Numbers

VISA:

Card Number: 4111111111111111
Exp: 12/26
CVV: 111
Mastercard:

Card Number: 5111111111111111
Exp: 12/26
CVV: 111
American Express:

Card Number: 371111111111111
Exp: 12/26
CVV: 111
Mobile OTP: 111111 or 123456
