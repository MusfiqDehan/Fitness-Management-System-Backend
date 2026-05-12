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

The production compose file runs the API, PostgreSQL, Redis, Celery worker, and Celery beat scheduler. The backend is designed to sit behind Traefik and exposes its ASGI service on port `8021` inside the Docker network.

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Before starting production containers, make sure the external Docker network referenced by the compose files exists, especially `traefik_proxy`.

## Notes

- The backend uses `daphne` as the ASGI server.
- The app is multi-tenant, so tenant and domain settings must be configured before deployment.
- Static and media volumes are mounted separately in production.
