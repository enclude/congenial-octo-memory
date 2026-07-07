"""Identyfikacja sesji przeglądarki — cookie `piro_sid`.

Bez kont i logowania: pierwszy zapis (upload) nadaje losowy identyfikator,
a każdy dostęp do zadania weryfikuje `job.sid == sid`. Cudze/nieistniejące
zadania zwracają 404 (nie 403), żeby nie dało się enumerować identyfikatorów.
"""

from __future__ import annotations

import re
import secrets

from fastapi import HTTPException, Request, Response

SID_COOKIE = "piro_sid"
_SID_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_SID_MAX_AGE = 7 * 24 * 3600


def _cookie_sid(request: Request) -> str | None:
    sid = request.cookies.get(SID_COOKIE)
    return sid if sid and _SID_RE.match(sid) else None


def ensure_sid(request: Request, response: Response) -> str:
    """Sid z cookie; gdy brak — nadaje nowy (cookie w odpowiedzi)."""
    sid = _cookie_sid(request)
    if sid:
        return sid
    sid = secrets.token_urlsafe(32)
    response.set_cookie(SID_COOKIE, sid, httponly=True, samesite="lax",
                        max_age=_SID_MAX_AGE, path="/")
    return sid


def require_sid(request: Request) -> str:
    """Sid z cookie; brak = na pewno nie ma zadań → 404 jak przy cudzym zadaniu."""
    sid = _cookie_sid(request)
    if not sid:
        raise HTTPException(status_code=404, detail="Nie znaleziono zadania.")
    return sid
