#!/bin/sh
set -e

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Running shared schema migrations (Tenant, Domain, auth, etc.)..."
python manage.py migrate_schemas --shared --noinput

echo "Ensuring public/default tenant domains exist..."
python manage.py shell -c "
from django_tenants.utils import get_tenant_model, get_tenant_domain_model
import os


def to_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


TenantModel = get_tenant_model()
DomainModel = get_tenant_domain_model()
public_domain = os.environ.get('PUBLIC_DOMAIN', 'localhost').strip()


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
    default_domains = [d.strip() for d in default_domains_raw.split(',') if d.strip()]

    if default_schema == 'public':
        print('Skipping default tenant bootstrap: DEFAULT_TENANT_SCHEMA cannot be public.')
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

echo "Seeding platform packages and re-syncing tenant feature flags..."
python manage.py seed_platform_packages --resync-tenants

echo "Ensuring superadmin account exists..."
python manage.py create_superadmin

echo "Starting server..."
exec "$@"
