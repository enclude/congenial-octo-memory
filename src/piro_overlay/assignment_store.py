"""Trwały zapis przypisań ujęcie → wpis kalkulatora (O8, `DOPASOWANIE-WIDEO.md` §3.4 krok 6).

Plik boczny JSON obok wideo: `<rdzeń>.piro-match.json` (przenosi się razem z nagraniem
między komputerami). Gdy katalogu nie da się zapisać (karta tylko do odczytu, dysk
sieciowy), zapis idzie do cache aplikacji (`config_dir()/match_assignments.json`, klucz
= bezwzględna ścieżka). Odczyt: najpierw plik boczny, potem cache.

Blokada: przypisanie `picked` i każda decyzja ręczna są `locked` — ponowny przebieg
wsadowy ich nie przelicza (błędne automatyczne przestawienie ręcznej decyzji byłoby
gorsze niż brak automatu). Stan `ambiguous`/`none` zapisujemy tylko informacyjnie.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import config

SIDECAR_SUFFIX = ".piro-match.json"
_CACHE_NAME = "match_assignments.json"
_VERSION = 1


@dataclass(frozen=True)
class StoredAssignment:
    entry_id: int | None
    state: str                  # picked | ambiguous | none
    source: str = "auto"        # auto | manual
    score: int = 0
    reasons: tuple[str, ...] = ()
    updated: str = ""

    @property
    def locked(self) -> bool:
        return self.source == "manual" or (self.state == "picked" and self.entry_id is not None)


def sidecar_path(video: str | Path) -> Path:
    p = Path(video)
    return p.with_name(p.stem + SIDECAR_SUFFIX)


def _cache_path() -> Path:
    return config.config_dir() / _CACHE_NAME


def _key(video: str | Path) -> str:
    try:
        return str(Path(video).resolve())
    except OSError:
        return str(video)


def _from_dict(d: object) -> StoredAssignment | None:
    if not isinstance(d, dict) or d.get("version") != _VERSION:
        return None
    eid = d.get("entry_id")
    state = d.get("state")
    if state not in ("picked", "ambiguous", "none"):
        return None
    if eid is not None and not (isinstance(eid, int) and eid > 0):
        return None
    return StoredAssignment(
        entry_id=eid, state=state,
        source="manual" if d.get("source") == "manual" else "auto",
        score=int(d.get("score") or 0),
        reasons=tuple(str(r) for r in (d.get("reasons") or ())),
        updated=str(d.get("updated") or ""))


def _to_dict(video: str | Path, a: StoredAssignment) -> dict:
    return {"version": _VERSION, "file": Path(video).name, "entry_id": a.entry_id,
            "state": a.state, "source": a.source, "score": a.score,
            "reasons": list(a.reasons),
            "updated": a.updated or datetime.now(timezone.utc).isoformat(timespec="seconds")}


def _load_cache() -> dict:
    try:
        data = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load(video: str | Path) -> StoredAssignment | None:
    """Zapisane przypisanie dla pliku albo None."""
    try:
        rec = _from_dict(json.loads(sidecar_path(video).read_text(encoding="utf-8")))
        if rec is not None:
            return rec
    except (OSError, ValueError):
        pass
    return _from_dict(_load_cache().get(_key(video)))


def save(video: str | Path, a: StoredAssignment) -> Path:
    """Zapis atomowy (`.tmp` + rename) do pliku bocznego; przy błędzie — do cache.

    Zwraca ścieżkę, pod którą faktycznie zapisano."""
    data = _to_dict(video, a)
    side = sidecar_path(video)
    tmp = side.with_name(side.name + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(side)
        return side
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
    store = _load_cache()
    store[_key(video)] = data
    cache = _cache_path()
    ctmp = cache.with_name(cache.name + ".tmp")
    ctmp.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    ctmp.replace(cache)
    return cache


def save_manual(video: str | Path, entry_id: int | None) -> Path:
    """Decyzja człowieka — zawsze zablokowana (`None` = „to nagranie nie ma wpisu")."""
    return save(video, StoredAssignment(entry_id, "picked" if entry_id else "none", "manual",
                                        reasons=("decyzja ręczna",)))
