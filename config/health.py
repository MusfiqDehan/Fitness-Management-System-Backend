from django.db import connection
from django.http import JsonResponse


def tenant_health(request):
    tenant = getattr(connection, "tenant", None)
    schema_name = connection.schema_name

    return JsonResponse(
        {
            "ok": True,
            "schema_name": schema_name,
            "tenant_name": getattr(tenant, "name", None),
            "host": request.get_host(),
            "scope": "public" if schema_name == "public" else "tenant",
        }
    )
