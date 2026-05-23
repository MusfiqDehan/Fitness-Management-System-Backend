"""
Custom DRF throttle classes and exception handler.

- BurstAnonRateThrottle / BurstUserRateThrottle  : short-window burst guards.
- SustainedAnonRateThrottle / SustainedUserRateThrottle : longer-window guards.
- throttle_exception_handler: wraps DRF's default handler to attach a
  standards-compliant Retry-After header and a consistent JSON body on 429s.
"""

import math
from rest_framework import throttling
from rest_framework.exceptions import Throttled
from rest_framework.views import exception_handler as drf_exception_handler


# ---------------------------------------------------------------------------
# Burst throttle classes (short window — blocks rapid automated requests)
# ---------------------------------------------------------------------------

class BurstAnonRateThrottle(throttling.AnonRateThrottle):
    """Short-window anonymous burst guard (default: 20/min)."""
    scope = 'burst_anon'


class BurstUserRateThrottle(throttling.UserRateThrottle):
    """Short-window authenticated burst guard (default: 60/min)."""
    scope = 'burst_user'


# ---------------------------------------------------------------------------
# Sustained throttle classes (longer window — limits overall hourly volume)
# ---------------------------------------------------------------------------

class SustainedAnonRateThrottle(throttling.AnonRateThrottle):
    """Long-window anonymous sustained guard (default: 500/hour)."""
    scope = 'sustained_anon'


class SustainedUserRateThrottle(throttling.UserRateThrottle):
    """Long-window authenticated sustained guard (default: 2000/hour)."""
    scope = 'sustained_user'


# ---------------------------------------------------------------------------
# Custom exception handler — adds Retry-After + consistent 429 body
# ---------------------------------------------------------------------------

def throttle_exception_handler(exc, context):
    """
    Extends DRF's default exception handler so that Throttled exceptions
    also include:
      - A Retry-After response header (seconds until next allowed request).
      - A consistent JSON body with 'detail', 'retry_after', and 'code' keys.
    """
    response = drf_exception_handler(exc, context)

    if response is None:
        return response

    if isinstance(exc, Throttled):
        wait = exc.wait
        retry_after = math.ceil(wait) if wait is not None else 1
        response['Retry-After'] = str(retry_after)
        response.data = {
            'detail': (
                f'Request was throttled. Expected available in {retry_after} second'
                f'{"s" if retry_after != 1 else ""}.'
            ),
            'retry_after': retry_after,
            'code': 'throttled',
        }

    return response
