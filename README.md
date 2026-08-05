# Fitness Management System - Backend

Django REST API for the Fitness Management System SaaS platform.

Schema-based multi-tenancy (`django-tenants` + PostgreSQL), JWT auth, Celery background jobs, Channels WebSockets, and ZKTeco ADMS device integration. In production, the API is served with Hypercorn behind Traefik.

---

## Table of contents

1. [Overview](#overview)
2. [Features](#features)
3. [Tech stack](#tech-stack)
4. [Architecture](#architecture)
5. [Requirements](#requirements)
6. [Environment variables](#environment-variables)
7. [Folder structure](#folder-structure)
8. [Run locally](#run-locally)
9. [Testing & quality](#testing--quality)
10. [API docs](#api-docs)
11. [Run in production](#run-in-production)
12. [Integrations](#integrations)
13. [Payment sandbox testing](#payment-sandbox-testing)
14. [Related packages](#related-packages)

---

## Overview

| Item | Detail |
|------|--------|
| Package | `gym_app_new_backend` |
| Role | Multi-tenant gym SaaS API |
| Default port | `8021` |
| API prefix | `/api/v1/` |
| Auth | JWT (SimpleJWT) — access 30m, refresh 7d |
| Tenancy | PostgreSQL schemas via `django-tenants` |

The backend serves:

- **Public / platform** APIs (tenant onboarding, pricing, platform admin)
- **Tenant** APIs (members, packages, attendance, billing, classes, trainers, CMS, CRM)
- **Device** ADMS endpoints for biometric hardware (`/iclock/*`)
- **WebSockets** for live attendance and notifications

---

## Features

| Domain app | Capabilities |
|------------|--------------|
| **tenancy** | Tenant self-register, login/logout, password flows, platform packages/pricing, feature registry, tenant admin, platform RBAC/invitations, feature flags |
| **identity** | User register, JWT login (email/phone), logout, refresh, `/me/`, instructors |
| **access** | Permissions, feature catalog, roles, role permissions, user-role assignment |
| **membership** | Packages, members (CRUD/import/invite/analytics), payments, subscriptions, attendance, gym classes/schedules/enrollments, public registration, discounts/coupons |
| **billing** | Platform features/packages, payment CRUD/export/stats/invoices, gateway config, SSLCommerz initiate + IPN/callbacks, subscription invoices |
| **attendance** | Access check, members-inside, logs/stats, fingerprints, cards, device profiles/registry (activate, sync-now, health), ZKTeco ADMS |
| **dashboard** | Contacts, support, classes/bookings/schedules, instructors, uploads, gym settings, reminder templates |
| **cms** | Banners, page content, blogs/categories |
| **crm** | Contact queries, tenant email configs |
| **trainer** | Profiles, documents, classes, schedules, bookings/check-in, ratings, invitations, public profile |
| **gym_branch** | Branches CRUD, public branches, shift requests |
| **reminder** | In-app notifications |
| **quick_action** | Public schedules, categories/classes, contact |

---

## Tech stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.12+ (CI); Docker image may use newer slim tags |
| Framework | Django 6.x |
| API | Django REST Framework 3.x |
| Auth | `djangorestframework-simplejwt` |
| Multi-tenancy | `django-tenants` |
| Database | PostgreSQL 17 |
| Cache / broker | Redis 7 |
| Tasks | Celery 5 (worker + beat) |
| ASGI | Daphne (local) / Hypercorn (prod) |
| Realtime | Django Channels + `channels-redis` |
| OpenAPI | `drf-spectacular` |
| Payments | SSLCommerz |
| Devices | ZKTeco ADMS (`/iclock/*`) |

---

## Architecture

```text
Client (Web / Mobile / Device)
        │
        ▼
   Traefik / Daphne
        │
        ▼
┌───────────────────────────────────────┐
│  Middleware (tenant resolve + JWT)    │
│  Views / ViewSets                     │
│  Application services                 │
│  Models / ORM                         │
└───────────────────────────────────────┘
        │                    │
        ▼                    ▼
   PostgreSQL             Redis
   (per-tenant schemas)   (cache, Celery, Channels)
```

### Multi-tenancy

- **Shared schema**: platform tenants, domains, shared identity/access metadata
- **Tenant schemas**: membership, attendance, billing, CMS, etc.
- Tenant resolution uses host subdomain **and** mobile-aware headers / JWT claims (`tenant_schema`, `X-Tenant-Subdomain`)

### Auth & permissions

- Bearer JWT via custom revocation-aware authentication
- Feature/permission gates through the `access` app and feature registry
- Branch-scoped list helpers for multi-branch tenants

### Background & realtime

- **Celery** worker + beat for scheduled and async work
- **WebSockets**: `ws/attendance/`, `ws/notifications/`

Business logic belongs in services; views stay thin.

---

## Requirements

- Python 3.12+
- PostgreSQL 17+
- Redis 7+
- Docker and Docker Compose (recommended for local/prod stacks)

---

## Environment variables

Copy [`.env.example`](.env.example) to `.env.local` (local) or `.env.prod` (production).

| Area | Key examples |
|------|----------------|
| Django | `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `PORT` |
| Database | `DATABASE_URL`, `DIRECT_DATABASE_URL`, `USE_PGBOUNCER`, `POSTGRES_*` |
| Redis / Celery | `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` |
| CORS / CSRF | `CORS_*`, `CSRF_TRUSTED_ORIGINS`, `SECURE_SSL_REDIRECT` |
| Tenancy | `PUBLIC_DOMAIN`, `TENANT_BASE_DOMAIN`, `FRONTEND_BASE_URL`, `BACKEND_BASE_URL`, `DEFAULT_TENANT_*` |
| Superadmin | `SUPERADMIN_EMAIL`, `SUPERADMIN_PASSWORD` |
| Devices | `GYM_DEVICE_API_KEY` |

`BACKEND_BASE_URL` must be reachable by SSLCommerz for IPN/callback URLs (local: `http://localhost:8021`).

---

## Folder structure

```text
gym_app_new_backend/
├── apps/
│   ├── access/
│   ├── attendance/
│   ├── billing/
│   ├── cms/
│   ├── crm/
│   ├── dashboard/
│   ├── gym_branch/
│   ├── identity/
│   ├── membership/
│   ├── quick_action/
│   ├── reminder/
│   ├── tenancy/
│   └── trainer/
├── config/                 # settings, urls, ASGI/WS
├── utils/                  # shared mixins, JWT, base views
├── tests/
├── scripts/
├── docs/
├── media/ / static/
├── Dockerfile
├── docker-compose.local.yml
├── docker-compose.prod.yml
├── manage.py
└── requirements.txt
```

---

## Run locally

### Docker (recommended)

Starts API, PostgreSQL, Redis, Celery worker, and Celery beat.

```bash
cp .env.example .env.local
# edit .env.local as needed

docker compose -f docker-compose.local.yml up --build
```

| Service | Host port |
|---------|-----------|
| API | `8021` |
| PostgreSQL | `5451` |
| Redis | `6379` |

### Manual (without Docker)

Requires local PostgreSQL and Redis matching your `.env`.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env.local

python manage.py migrate_schemas   # or migrate, depending on your tenancy setup
daphne -b 0.0.0.0 -p 8021 config.asgi:application
```

Useful commands:

```bash
python manage.py test
python manage.py makemigrations <app_name>
python manage.py migrate_schemas --noinput
python manage.py collectstatic
```

---

## Testing & quality

```bash
python manage.py test
# or pytest if configured in your environment
```

Project workflow targets: **Ruff**, **Black**, **MyPy**, **Pytest** / Django test runner. Prefer service-level tests for business rules.

---

## API docs

With the server running:

| Resource | Path |
|----------|------|
| OpenAPI schema | `/api/v1/schema/` |
| Swagger UI | `/api/v1/docs/` |
| ReDoc | `/api/v1/redoc/` |
| Liveness | `GET /api/v1/health/tenant/` |
| Readiness | `GET /api/v1/health/ready/` |

---

## Run in production

Production compose runs PgBouncer, PostgreSQL, Redis, ASGI (Hypercorn, 2 workers), Celery worker, and Celery beat behind Traefik on port `8021` in the Docker network.

**Startup order:** Traefik → backend stack → frontend stack.

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Ensure the external `traefik_proxy` network exists before starting.

### Memory budget (example: 8 GB VPS)

| Service | Limit |
|---------|-------|
| PostgreSQL | 2560 MB |
| Backend (ASGI) | 1536 MB |
| Celery worker | 1024 MB (concurrency 2) |
| Redis | 512 MB |
| PgBouncer | 128 MB |
| Celery beat | 256 MB |

### Database connections

- App traffic → **PgBouncer** (`pgbouncer:6432`) via `DATABASE_URL`
- Migrations → **DIRECT_DATABASE_URL** (`db:5432`) when `RUN_MIGRATIONS=1`:

```bash
docker compose -f docker-compose.prod.yml run --rm \
  -e RUN_MIGRATIONS=1 \
  backend python manage.py migrate_schemas --noinput
```

When `USE_PGBOUNCER=1`, Django `CONN_MAX_AGE` is forced to `0`.

Backups: [docs/production-backup-restore.md](docs/production-backup-restore.md).

---

## Integrations

### ZKTeco ADMS

Devices use **HTTP** on port 80 (not HTTPS). Firmware URL pattern:

```text
http://{tenant}.fitness.musfiqdehan.com/iclock/cdata
```

See [traefik/README.md](../traefik/README.md) for routing.

### SSLCommerz

Billing initiate + IPN/success/fail/cancel callbacks. Configure `BACKEND_BASE_URL` so the gateway can reach this API.

### WebSockets

Attendance and notification consumers under Channels routing (`ws/attendance/`, `ws/notifications/`).

---

## Payment sandbox testing

Sandbox URL base: `https://sandbox.sslcommerz.com` (test transactions only).

| Brand | Card | Exp | CVV |
|-------|------|-----|-----|
| VISA | `4111111111111111` | `12/26` | `111` |
| Mastercard | `5111111111111111` | `12/26` | `111` |
| American Express | `371111111111111` | `12/26` | `111` |

Mobile OTP: `111111` or `123456`.

---

## Related packages

| Package | Role |
|---------|------|
| [`gym_app_new_frontend`](../gym_app_new_frontend/) | Admin / platform web app (Vite + React) |
| [`GymMembershipMobileApp`](../GymMembershipMobileApp/) | Member mobile app (React Native) |
| [`traefik`](../traefik/) | Reverse proxy / TLS routing |
| [`zkteco_lan_agent`](../zkteco_lan_agent/) | Optional LAN device agent |
