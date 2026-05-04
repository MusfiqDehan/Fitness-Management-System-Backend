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
    existing_public_domain = DomainModel.objects.filter(domain=public_domain).first()
    if existing_public_domain is None:
        DomainModel.objects.create(domain=public_domain, tenant=public_tenant, is_primary=True)
        print(f'Added public domain: {public_domain}')
    elif existing_public_domain.tenant_id == public_tenant.id:
        if not existing_public_domain.is_primary:
            existing_public_domain.is_primary = True
            existing_public_domain.save(update_fields=['is_primary'])
        print(f'Public domain already mapped: {public_domain}')
    else:
        print(
            f'Skipping public domain {public_domain}: already mapped to schema '
            f'{existing_public_domain.tenant.schema_name}'
        )

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
            existing_domain = DomainModel.objects.filter(domain=domain).first()
            if existing_domain is None:
                DomainModel.objects.create(
                    domain=domain,
                    tenant=default_tenant,
                    is_primary=(idx == 0),
                )
                print(f'Added default tenant domain: {domain}')
            elif existing_domain.tenant_id == default_tenant.id:
                if idx == 0 and not existing_domain.is_primary:
                    existing_domain.is_primary = True
                    existing_domain.save(update_fields=['is_primary'])
                print(f'Default tenant domain already mapped: {domain}')
            else:
                print(
                    f'Skipping default tenant domain {domain}: already mapped to schema '
                    f'{existing_domain.tenant.schema_name}'
                )
else:
    print('Default tenant bootstrap is disabled (AUTO_CREATE_DEFAULT_TENANT=false).')
"

echo "Running tenant schema migrations (identity, dashboard, membership, etc.)..."
python manage.py migrate_schemas --noinput

echo "Ensuring superadmin account exists..."
python manage.py create_superadmin

echo "Starting server..."
exec "$@"
