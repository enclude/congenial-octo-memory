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


def test_start_delay_extracted_from_opis():
    # Nowy format piro-kalkulatora: "opoznienie startu Xs" przed listą strzałów.
    payload = {"ok": True, "data": {
        "opis": "opoznienie startu 2.1s | 1: 2.28s | 2: 2.76s (+0.48s) | "
                "3: 3.20s (+0.44s) | 4: 3.59s (+0.39s) | 5: 4.02s (+0.43s)"}}
    session = session_from_payload(payload)
    assert session.start_delay == 2.1
    assert len(session.shots) == 5
    assert session.shots[0].czas == 2.28
    assert session.shots[0].split is None


def test_start_delay_none_when_absent():
    session = session_from_payload(PAYLOAD_OK)
    assert session.start_delay is None
