from piro_overlay.render import auto_trim_window


def test_auto_trim_basic():
    # T0=10.0, ostatni strzał 55.68s, margines 5s, lead-in domyślny 5s
    start, end = auto_trim_window(10.0, 55.68, tail=5.0)
    assert start == 5.0            # 10.0 - 5.0 (domyślny lead-in)
    assert end == 10.0 + 55.68 + 5.0


def test_auto_trim_clamps_to_duration():
    start, end = auto_trim_window(10.0, 55.68, tail=5.0, duration=50.0)
    assert end == 50.0             # ograniczone długością źródła


def test_auto_trim_start_not_negative():
    start, _ = auto_trim_window(3.0, 10.0)   # 3.0 - 5.0 < 0
    assert start == 0.0            # nie schodzi poniżej zera
