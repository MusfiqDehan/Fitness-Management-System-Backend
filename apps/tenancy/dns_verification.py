"""DNS verification helpers for tenant custom domains.

A tenant proves control of a custom domain by publishing a TXT record at
``_fitpulse-verify.<domain>`` whose value matches the generated token. This is
non-disruptive: it never affects the live site at the apex/host while the tenant
keeps using their existing subdomain.

The actual routable ``Domain`` row is only created once verification succeeds,
so unverified domains can never resolve to a tenant schema.

After TXT verification, the hostname must also point at the platform (A or
CNAME). That routing check is advisory — it does not block verification.
"""
from __future__ import annotations

import secrets

try:  # dnspython is an explicit dependency; guard so imports never hard-fail.
    import dns.resolver
    import dns.exception
    _DNS_AVAILABLE = True
except Exception:  # pragma: no cover - only hit if dependency missing
    _DNS_AVAILABLE = False


# Public DNS resolvers used for verification lookups. Using public resolvers
# avoids picking up any internal/split-horizon answers.
_PUBLIC_NAMESERVERS = ["1.1.1.1", "8.8.8.8"]
_LOOKUP_TIMEOUT_SECONDS = 5.0


def generate_verification_token() -> str:
    """Return a high-entropy, URL-safe token for a TXT challenge."""
    return secrets.token_hex(24)


def _strip_quotes(value: str) -> str:
    return value.strip().strip('"').strip()


def _make_resolver():
    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = list(_PUBLIC_NAMESERVERS)
    resolver.lifetime = _LOOKUP_TIMEOUT_SECONDS
    resolver.timeout = _LOOKUP_TIMEOUT_SECONDS
    return resolver


def verify_txt_record(record_name: str, expected_token: str) -> tuple[bool, str]:
    """Check whether ``record_name`` publishes a TXT record == ``expected_token``.

    Returns ``(ok, error)``. ``error`` is an empty string on success and a short,
    user-safe message describing the failure otherwise.
    """
    if not _DNS_AVAILABLE:
        return False, "DNS verification is temporarily unavailable. Please try again later."
    if not expected_token:
        return False, "Missing verification token."

    resolver = _make_resolver()

    try:
        answers = resolver.resolve(record_name, "TXT")
    except dns.resolver.NXDOMAIN:
        return False, "No TXT record found yet. DNS changes can take a few minutes to propagate."
    except dns.resolver.NoAnswer:
        return False, "No TXT record found yet. DNS changes can take a few minutes to propagate."
    except dns.exception.Timeout:
        return False, "DNS lookup timed out. Please try again in a moment."
    except dns.exception.DNSException:
        return False, "Could not look up the verification record. Please double-check your DNS settings."

    for rdata in answers:
        # A TXT record may be split into multiple character-strings.
        parts = [
            chunk.decode("utf-8", errors="ignore") if isinstance(chunk, (bytes, bytearray)) else str(chunk)
            for chunk in getattr(rdata, "strings", [])
        ]
        combined = _strip_quotes("".join(parts)) if parts else _strip_quotes(str(rdata))
        if combined == expected_token:
            return True, ""

    return False, "Verification record found but the token did not match. Please re-copy the exact value."


def _normalize_host(value: str) -> str:
    return (value or "").strip().lower().rstrip(".")


def check_domain_routing(
    domain: str,
    *,
    cname_target: str = "",
    a_target: str = "",
) -> tuple[bool, str]:
    """Soft-check whether ``domain`` already points at the platform.

    Returns ``(ready, message)``. ``ready`` is True when a CNAME matches
    ``cname_target`` or an A record matches ``a_target``. Failures are advisory
    (empty targets skip that check).
    """
    hostname = _normalize_host(domain)
    expected_cname = _normalize_host(cname_target)
    expected_a = (a_target or "").strip()

    if not hostname:
        return False, "Missing domain."
    if not expected_cname and not expected_a:
        return False, "Routing target is not configured."
    if not _DNS_AVAILABLE:
        return False, "DNS lookup is temporarily unavailable."

    resolver = _make_resolver()

    if expected_cname:
        try:
            answers = resolver.resolve(hostname, "CNAME")
            for rdata in answers:
                target = _normalize_host(str(rdata.target))
                if target == expected_cname:
                    return True, ""
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.exception.DNSException):
            pass

    if expected_a:
        try:
            answers = resolver.resolve(hostname, "A")
            for rdata in answers:
                if str(rdata).strip() == expected_a:
                    return True, ""
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.exception.DNSException):
            pass

    if expected_cname and expected_a:
        hint = f"Add a CNAME to {expected_cname} or an A record to {expected_a}."
    elif expected_cname:
        hint = f"Add a CNAME pointing to {expected_cname}."
    else:
        hint = f"Add an A record pointing to {expected_a}."

    return False, (
        "Ownership is verified, but this domain does not point at FitPulse yet. "
        f"{hint}"
    )
