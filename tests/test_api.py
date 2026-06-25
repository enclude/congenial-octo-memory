import pytest

from piro_overlay.api import ApiError, session_from_payload

# Odpowiedź wzorowana na dokumentacji API, z dodanym polem `opis` zawierającym oś czasu.
PAYLOAD_OK = {
    "ok": True,
    "data": {
        "id": 1,
        "nazwa_toru": "Tor 1",
        "uczestnik": "Jan Kowalski",
        "opis": "1: 1.55s | 2: 2.16s (+0.61s) | 3: 2.55s (+0.39s)",
        "liczba_strzalow": 3,
        "czasy": {"czas_bazowy": 12.34, "suma_kar": 4, "czas_koncowy": 16.34},
        "hit_factor": 3.0599,
    },
}


def test_session_from_payload_maps_fields():
    session = session_from_payload(PAYLOAD_OK)
    assert session.nazwa_toru == "Tor 1"
    assert session.uczestnik == "Jan Kowalski"
    assert session.liczba_strzalow == 3
    assert session.czas_bazowy == 12.34
    assert session.suma_kar == 4
    assert session.czas_koncowy == 16.34
    assert session.hit_factor == 3.0599
    assert len(session.shots) == 3
    assert session.shots[2].czas == 2.55
    assert session.total_shots == 3


def test_ok_false_raises():
    with pytest.raises(ApiError):
        session_from_payload({"ok": False})


def test_bad_opis_raises():
    bad = {"ok": True, "data": {"opis": "to nie jest oś czasu"}}
    with pytest.raises(ApiError):
        session_from_payload(bad)


def test_base_time_falls_back_to_last_shot():
    payload = {"ok": True, "data": {"opis": "1: 1.0s | 2: 2.5s (+1.5s)"}}
    session = session_from_payload(payload)
    assert session.czas_bazowy is None
    assert session.base_time == 2.5  # fallback na czas ostatniego strzału
