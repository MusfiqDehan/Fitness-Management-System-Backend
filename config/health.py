from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from django.conf import settings
from django.core.cache import cache
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


def _check_database() -> dict:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return {"ok": True}


def _check_redis() -> dict:
    cache.set("_health_probe", "1", 5)
    if cache.get("_health_probe") != "1":
        raise RuntimeError("Redis read/write probe failed")
    return {"ok": True}


def _run_with_timeout(fn, timeout_seconds: float) -> dict:
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn)
        try:
            return future.result(timeout=timeout_seconds)
        except FuturesTimeoutError as exc:
            raise TimeoutError(f"{fn.__name__} timed out after {timeout_seconds}s") from exc


def liveness_health(request):
    """Fast probe for container orchestration — no dependency checks."""
    return JsonResponse({"ok": True, "host": request.get_host()})


def readiness_health(request):
    timeout_seconds = float(getattr(settings, "READINESS_CHECK_TIMEOUT", 2))
    checks = {
        "database": {"ok": False, "error": None},
        "redis": {"ok": False, "error": None},
    }

    for name, fn in (("database", _check_database), ("redis", _check_redis)):
        try:
            checks[name] = _run_with_timeout(fn, timeout_seconds)
        except Exception as exc:  # noqa: BLE001 — health endpoint must surface any dependency failure
            checks[name] = {"ok": False, "error": str(exc)}

    all_ok = all(check.get("ok") for check in checks.values())
    payload = {
        "ok": all_ok,
        "checks": checks,
        "host": request.get_host(),
    }
    return JsonResponse(payload, status=200 if all_ok else 503)
