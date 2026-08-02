#!/bin/sh
set -e

# Database connectivity:
# - Normal app traffic: DATABASE_URL → PgBouncer (USE_PGBOUNCER=1 in .env.prod)
# - Bootstrap/migrations: DIRECT_DATABASE_URL → PostgreSQL (db:5432)
#
# Production (SKIP_DB_BOOTSTRAP=1) runs migrations manually:
#   docker compose -f docker-compose.prod.yml run --rm \
#     -e RUN_MIGRATIONS=1 backend python manage.py migrate_schemas --noinput

apply_direct_database_url() {
    if [ -n "${DIRECT_DATABASE_URL:-}" ]; then
        echo "Using DIRECT_DATABASE_URL for bootstrap/migrations (bypassing PgBouncer)."
        export DATABASE_URL="${DIRECT_DATABASE_URL}"
        export USE_PGBOUNCER=0
        export DB_CONN_MAX_AGE=0
        return 0
    fi

    if [ "${USE_PGBOUNCER:-0}" != "1" ] && [ -n "${DATABASE_URL:-}" ]; then
        echo "PgBouncer disabled; using DATABASE_URL directly for bootstrap/migrations."
        export USE_PGBOUNCER=0
        export DB_CONN_MAX_AGE=0
        return 0
    fi

    echo "ERROR: DIRECT_DATABASE_URL is not set. Migrations must connect to PostgreSQL directly (db:5432), not PgBouncer." >&2
    echo "Add DIRECT_DATABASE_URL to .env.local or .env.prod, e.g. postgresql://user:pass%40word@db:5432/gym_db" >&2
    exit 1
}

# True when this container is invoked for schema migrations.
is_migration_invocation() {
    if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
        return 0
    fi
    case " $* " in
        *" migrate_schemas "*|*" migrate "*) return 0 ;;
    esac
    return 1
}

if [ "${SKIP_DB_BOOTSTRAP:-0}" = "1" ]; then
    if is_migration_invocation "$@"; then
        apply_direct_database_url
    else
        echo "Skipping DB bootstrap/migrations (SKIP_DB_BOOTSTRAP=1)."
        echo "To migrate production, run: ./scripts/migrate-prod.sh"
    fi
    exec "$@"
fi

apply_direct_database_url

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Repairing shared-schema migration drift (applied history, missing tables)..."
python manage.py repair_shared_schema_drift

echo "Running shared schema migrations (Tenant, Domain, auth, etc.)..."
python manage.py migrate_schemas --shared --noinput

echo "Ensuring public/default tenant domains exist..."
python manage.py shell -c "
from django.db import connection as _conn
from django_tenants.utils import get_tenant_model, get_tenant_domain_model
import os

# Acquire a session-level advisory lock so that concurrent container startups
# (e.g. rolling deploys, Docker Compose scale) do not race on migrate_schemas
# for the same tenant schema and deadlock on DDL locks.
# The lock is released automatically when this process exits (connection closes).
_BOOTSTRAP_LOCK_KEY = 5432109876
with _conn.cursor() as _c:
    _c.execute('SELECT pg_advisory_lock(%s)', [_BOOTSTRAP_LOCK_KEY])
print('Bootstrap advisory lock acquired.')


def to_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


TenantModel = get_tenant_model()
DomainModel = get_tenant_domain_model()
public_domain = os.environ.get('PUBLIC_DOMAIN', 'localhost').strip().lower()


def ensure_domain(domain, tenant, *, is_primary=False, label='domain'):
    existing_domain = DomainModel.objects.filter(domain=domain).first()
    if existing_domain is None:
        DomainModel.objects.create(domain=domain, tenant=tenant, is_primary=is_primary)
        print(f'Added {label}: {domain}')
        return

    changed_fields = []
    if existing_domain.tenant_id != tenant.id:
        existing_domain.tenant = tenant
        changed_fields.append('tenant')

    if existing_domain.is_primary != is_primary:
        existing_domain.is_primary = is_primary
        changed_fields.append('is_primary')

    if changed_fields:
        existing_domain.save(update_fields=changed_fields)
        print(f'Reassigned {label}: {domain} -> {tenant.schema_name}')
    else:
        print(f'{label.capitalize()} already mapped: {domain}')

public_tenant, public_created = TenantModel.objects.get_or_create(
    schema_name='public',
    defaults={
        'name': 'Public',
        'slug': 'public',
        'code': 'PUBLIC',
        'status': 'active',
        'is_trial': False,
        'plan': 'free',
    },
)

if public_created:
    print('Public tenant created.')
else:
    print('Public tenant already exists.')

if public_domain:
    ensure_domain(public_domain, public_tenant, is_primary=True, label='public domain')

auto_create_default_tenant = to_bool(os.environ.get('AUTO_CREATE_DEFAULT_TENANT'), default=False)

if auto_create_default_tenant:
    default_schema = os.environ.get('DEFAULT_TENANT_SCHEMA', 'main').strip()
    default_name = os.environ.get('DEFAULT_TENANT_NAME', 'Main Gym').strip()
    default_slug = os.environ.get('DEFAULT_TENANT_SLUG', 'main-gym').strip()
    default_code = os.environ.get('DEFAULT_TENANT_CODE', 'MAIN').strip()
    default_domains_raw = os.environ.get('DEFAULT_TENANT_DOMAINS', 'gym-backend-local')
    default_domains = [d.strip().lower() for d in default_domains_raw.split(',') if d.strip()]

    if default_schema == 'public':
        print('Skipping default tenant bootstrap: DEFAULT_TENANT_SCHEMA cannot be public.')
    elif public_domain and public_domain in default_domains:
        raise SystemExit(
            'Invalid tenant bootstrap config: DEFAULT_TENANT_DOMAINS must not include PUBLIC_DOMAIN. '
            f'{public_domain} belongs to the public schema.'
        )
    else:
        default_tenant, default_created = TenantModel.objects.get_or_create(
            schema_name=default_schema,
            defaults={
                'name': default_name,
                'slug': default_slug,
                'code': default_code,
                'status': 'active',
                'is_trial': False,
                'plan': 'pro',
            },
        )

        if default_created:
            print(f'Default tenant created: schema={default_schema}')
        else:
            print(f'Default tenant already exists: schema={default_schema}')

        for idx, domain in enumerate(default_domains):
            ensure_domain(
                domain,
                default_tenant,
                is_primary=(idx == 0),
                label='default tenant domain',
            )
else:
    print('Default tenant bootstrap is disabled (AUTO_CREATE_DEFAULT_TENANT=false).')
"

echo "Running tenant schema migrations (identity, dashboard, membership, etc.)..."
python manage.py migrate_schemas --noinput

echo "Seeding predefined roles for all tenant schemas (idempotent)..."
python manage.py all_tenants_command seed_tenant_roles

echo "Syncing canonical feature registry into Feature table..."
python manage.py sync_features

# echo "Seeding platform packages and re-syncing tenant feature flags..."
# python manage.py seed_platform_packages --resync-tenants

echo "Ensuring superadmin account exists..."
python manage.py create_superadmin

echo "Starting server..."
exec "$@"
