#!/usr/bin/env bash
set -euo pipefail

# One-command post-deploy verification:
# - public health route resolves to public schema
# - tenant health route resolves to tenant schema
# - superadmin login succeeds on tenant API domain
#
# Usage:
#   ./scripts/post_deploy_verify.sh
#
# Optional overrides:
#   ENV_FILE=.env.prod
#   VERIFY_SCHEME=https
#   VERIFY_CURL_INSECURE=false
#   PUBLIC_HOST=<host>
#   TENANT_HOST=<host>
#   EXPECTED_TENANT_SCHEMA=<schema>
#   API_PREFIX=/api/v1

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.prod}"
VERIFY_SCHEME="${VERIFY_SCHEME:-https}"
VERIFY_CURL_INSECURE="${VERIFY_CURL_INSECURE:-false}"
API_PREFIX="${API_PREFIX:-/api/v1}"
REQUEST_TIMEOUT="${REQUEST_TIMEOUT:-20}"
VERIFY_PORT="${VERIFY_PORT:-}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[FAIL] Env file not found: $ENV_FILE"
  exit 1
fi

load_env_file() {
  local file_path="$1"
  local line
  local trimmed
  local key
  local value

  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    trimmed="${line#"${line%%[![:space:]]*}"}"

    if [[ -z "$trimmed" || "${trimmed:0:1}" == "#" ]]; then
      continue
    fi

    if [[ "$trimmed" != *=* ]]; then
      continue
    fi

    key="${trimmed%%=*}"
    value="${trimmed#*=}"
    key="${key%"${key##*[![:space:]]}"}"

    if [[ -n "$key" ]]; then
      export "$key=$value"
    fi
  done < "$file_path"
}

load_env_file "$ENV_FILE"

if [[ -z "$VERIFY_PORT" && "$VERIFY_SCHEME" == "http" ]]; then
  VERIFY_PORT="${PORT:-}"
fi

PUBLIC_HOST="${PUBLIC_HOST:-${PUBLIC_DOMAIN:-}}"
DEFAULT_TENANT_DOMAINS="${DEFAULT_TENANT_DOMAINS:-}"
TENANT_HOST_DEFAULT="${DEFAULT_TENANT_DOMAINS%%,*}"
TENANT_HOST="${TENANT_HOST:-$TENANT_HOST_DEFAULT}"
EXPECTED_TENANT_SCHEMA="${EXPECTED_TENANT_SCHEMA:-${DEFAULT_TENANT_SCHEMA:-}}"

if [[ -z "$PUBLIC_HOST" ]]; then
  echo "[FAIL] PUBLIC_HOST is empty. Set PUBLIC_DOMAIN in env or PUBLIC_HOST override."
  exit 1
fi

if [[ -z "$TENANT_HOST" ]]; then
  echo "[FAIL] TENANT_HOST is empty. Set DEFAULT_TENANT_DOMAINS in env or TENANT_HOST override."
  exit 1
fi

if [[ -z "$EXPECTED_TENANT_SCHEMA" ]]; then
  echo "[FAIL] EXPECTED_TENANT_SCHEMA is empty. Set DEFAULT_TENANT_SCHEMA in env or EXPECTED_TENANT_SCHEMA override."
  exit 1
fi

if [[ -z "${SUPERADMIN_EMAIL:-}" || -z "${SUPERADMIN_PASSWORD:-}" ]]; then
  echo "[FAIL] SUPERADMIN_EMAIL or SUPERADMIN_PASSWORD missing in env file."
  exit 1
fi

CURL_FLAGS=("-sS" "--max-time" "$REQUEST_TIMEOUT" "-H" "Accept: application/json")
if [[ "$VERIFY_CURL_INSECURE" == "true" ]]; then
  CURL_FLAGS+=("-k")
fi

health_url() {
  local host="$1"
  echo "$(origin_for_host "$host")${API_PREFIX}/health/tenant/"
}

login_url() {
  local host="$1"
  echo "$(origin_for_host "$host")${API_PREFIX}/identity/login/"
}

origin_for_host() {
  local host="$1"
  if [[ "$host" == *:* || -z "$VERIFY_PORT" ]]; then
    echo "${VERIFY_SCHEME}://${host}"
  else
    echo "${VERIFY_SCHEME}://${host}:${VERIFY_PORT}"
  fi
}

check_health() {
  local label="$1"
  local host="$2"
  local expected_schema="$3"
  local expected_scope="$4"

  local url
  url="$(health_url "$host")"

  local body
  if ! body="$(curl "${CURL_FLAGS[@]}" -H "Host: ${host}" "$url")"; then
    echo "[FAIL] ${label}: request failed -> $url"
    exit 1
  fi

  CHECK_JSON="$body" CHECK_SCHEMA="$expected_schema" CHECK_SCOPE="$expected_scope" CHECK_HOST="$host" CHECK_LABEL="$label" python3 - <<'PY'
import json
import os
import sys

label = os.environ["CHECK_LABEL"]
expected_schema = os.environ["CHECK_SCHEMA"]
expected_scope = os.environ["CHECK_SCOPE"]
expected_host = os.environ["CHECK_HOST"]
raw = os.environ["CHECK_JSON"]

try:
    data = json.loads(raw)
except Exception:
    print(f"[FAIL] {label}: invalid JSON response")
    print(raw)
    sys.exit(1)

problems = []
if data.get("ok") is not True:
    problems.append("ok is not true")
if data.get("schema_name") != expected_schema:
    problems.append(f"schema_name expected {expected_schema} got {data.get('schema_name')}")
if data.get("scope") != expected_scope:
    problems.append(f"scope expected {expected_scope} got {data.get('scope')}")
if data.get("host") != expected_host:
    problems.append(f"host expected {expected_host} got {data.get('host')}")

if problems:
    print(f"[FAIL] {label}: " + "; ".join(problems))
    print(raw)
    sys.exit(1)

print(f"[OK] {label}: schema={data.get('schema_name')} scope={data.get('scope')} host={data.get('host')}")
PY
}

check_login() {
  local host="$1"
  local expected_schema="$2"
  local url
  local payload
  local tmp_file
  local status_code

  url="$(login_url "$host")"
  payload="{\"email\":\"${SUPERADMIN_EMAIL}\",\"password\":\"${SUPERADMIN_PASSWORD}\"}"
  tmp_file="$(mktemp)"

  status_code="$(curl "${CURL_FLAGS[@]}" -o "$tmp_file" -w "%{http_code}" \
    -X POST "$url" \
    -H "Host: ${host}" \
    -H "Content-Type: application/json" \
    -d "$payload")"

  if [[ "$status_code" != "200" ]]; then
    echo "[FAIL] tenant login: HTTP $status_code"
    cat "$tmp_file"
    rm -f "$tmp_file"
    exit 1
  fi

  LOGIN_JSON="$(cat "$tmp_file")" EXPECTED_SCHEMA="$expected_schema" python3 - <<'PY'
import base64
import json
import os
import sys

raw = os.environ["LOGIN_JSON"]
expected_schema = os.environ["EXPECTED_SCHEMA"]

try:
    data = json.loads(raw)
except Exception:
    print("[FAIL] tenant login: invalid JSON")
    print(raw)
    sys.exit(1)

access = data.get("access")
if not access:
    print("[FAIL] tenant login: missing access token")
    print(raw)
    sys.exit(1)

parts = access.split(".")
if len(parts) != 3:
    print("[FAIL] tenant login: malformed JWT")
    sys.exit(1)

payload = parts[1]
padding = "=" * (-len(payload) % 4)
try:
    decoded = base64.urlsafe_b64decode(payload + padding).decode("utf-8")
    claims = json.loads(decoded)
except Exception as exc:
    print(f"[FAIL] tenant login: cannot decode JWT payload ({exc})")
    sys.exit(1)

tenant_schema = claims.get("tenant_schema")
if tenant_schema != expected_schema:
    print(f"[FAIL] tenant login: tenant_schema expected {expected_schema} got {tenant_schema}")
    sys.exit(1)

print(f"[OK] tenant login: tenant_schema={tenant_schema}")
PY

  rm -f "$tmp_file"
}

echo "Post-deploy verification starting"
echo "Env file: $ENV_FILE"
echo "Public host: $PUBLIC_HOST"
echo "Tenant host: $TENANT_HOST"
echo "Expected tenant schema: $EXPECTED_TENANT_SCHEMA"

echo ""
check_health "public health" "$PUBLIC_HOST" "public" "public"
check_health "tenant health" "$TENANT_HOST" "$EXPECTED_TENANT_SCHEMA" "tenant"
check_login "$TENANT_HOST" "$EXPECTED_TENANT_SCHEMA"

echo ""
echo "[OK] Post-deploy verification passed"
