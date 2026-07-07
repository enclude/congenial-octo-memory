"""Prosty rate limiting in-memory (token bucket) — bez zewnętrznych zależności.

Klucz = sid z cookie, a gdy go brak — adres klienta. `X-Forwarded-For` jest
w pełni kontrolowany przez klienta, dopóki nie ma między nim a aplikacją
zaufanego reverse proxy, który go nadpisuje/dokłada na podstawie realnego
adresu peera — bez takiego proxy ufanie temu nagłówkowi pozwala obejść limit
(inny "adres" na każde żądanie). Dlatego jest używany TYLKO gdy
`settings.trust_proxy_headers` jest jawnie włączone (patrz settings.py), a
wtedy bierzemy OSTATNI wpis (dokładany przez najbliższy, zaufany hop), nie
pierwszy (ten może być spreparowany przez klienta i doklejony przed prawdziwym
adresem). Bez zaufanego proxy używamy bezpośrednio adresu z gniazda TCP.
"""

from __future__ import annotations

import threading
import time

from fastapi import HTTPException, Request

from .sessions import SID_COOKIE


class TokenBucket:
    """Wiadro tokenów per klucz: `rate` zdarzeń na `per_seconds`."""

    def __init__(self, rate: int, per_seconds: float) -> None:
        self.rate = rate
        self.per_seconds = per_seconds
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, ts)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            tokens, ts = self._buckets.get(key, (float(self.rate), now))
            tokens = min(float(self.rate),
                         tokens + (now - ts) * self.rate / self.per_seconds)
            if tokens < 1.0:
                self._buckets[key] = (tokens, now)
                return False
            self._buckets[key] = (tokens - 1.0, now)
            return True

    def prune(self, older_than_s: float = 3600.0) -> None:
        """Usuwa wiadra nieaktywne od dawna (wołane przez pętlę sprzątania)."""
        cutoff = time.monotonic() - older_than_s
        with self._lock:
            stale = [k for k, (_, ts) in self._buckets.items() if ts < cutoff]
            for k in stale:
                del self._buckets[k]


def client_key(request: Request) -> str:
    sid = request.cookies.get(SID_COOKIE)
    if sid:
        return f"sid:{sid}"
    trust_proxy = bool(getattr(request.app.state, "settings", None)
                       and request.app.state.settings.trust_proxy_headers)
    if trust_proxy:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return f"ip:{fwd.split(',')[-1].strip()}"
    return f"ip:{request.client.host if request.client else 'unknown'}"


def check_rate(request: Request, bucket: TokenBucket,
               retry_after_s: int) -> None:
    if not bucket.allow(client_key(request)):
        raise HTTPException(status_code=429, detail="Za dużo żądań — zwolnij.",
                            headers={"Retry-After": str(retry_after_s)})


def general_rate(request: Request) -> None:
    """Dependency: ogólny limit żądań /api/* na sesję."""
    check_rate(request, request.app.state.general_bucket, 30)


def render_rate(request: Request) -> None:
    """Dependency: limit uruchomień renderu na sesję."""
    check_rate(request, request.app.state.render_bucket, 600)
