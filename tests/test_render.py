from piro_overlay import overlay, render
from piro_overlay.models import AnchorMode, OverlayStyle, Session, Shot
from piro_overlay.render import auto_trim_window


def test_clock_text_format():
    assert overlay.clock_text(0.0) == "T+0.0s"
    assert overlay.clock_text(3.47) == "T+3.5s"
    assert overlay.clock_text(-1.0) == "T+0.0s"   # przed STARTEM klamrujemy do 0


def test_prepare_clock_disabled():
    style = OverlayStyle(show_running_clock=False)
    use_dt, evs = render.prepare_clock(style, (640, 360), [], 0.5, 0.0, 8.0)
    assert use_dt is False and evs == []


def test_clock_png_fallback_events():
    # Wymuś brak drawtext → fallback PNG co sekundę, panele nad nakładką.
    sess = Session(shots=[Shot(1, 1.0), Shot(2, 2.5, 1.5)])
    style = OverlayStyle(show_running_clock=True, position="bottom-left")
    events = render.build_events(sess, 0.5, style, AnchorMode.START_SIGNAL, (640, 360), 8.0)
    evs = render._clock_png_events(style, (640, 360), events, t0=0.5, src_start=0.0, src_end=8.0)
    assert evs, "powinny powstać panele zegara"
    assert all(e.xy is not None for e in evs)       # własna pozycja (nad panelem)
    assert evs[0].start >= 0.5                       # zegar nie startuje przed T0
    assert evs[-1].end <= 8.0                        # i nie wychodzi poza źródło


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
