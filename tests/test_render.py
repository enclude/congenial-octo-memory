from piro_overlay import overlay, render
from piro_overlay.models import AnchorMode, OverlayStyle, Session, Shot
from piro_overlay.render import auto_trim_window


def test_clock_text_format():
    assert overlay.clock_text(0.0) == "T+0.0s"
    assert overlay.clock_text(3.47) == "T+3.5s"
    assert overlay.clock_text(-1.0) == "T+0.0s"   # przed STARTEM klamrujemy do 0


def test_prepare_clock_disabled():
    style = OverlayStyle(show_running_clock=False)
    assert render.prepare_clock(style) is False


def test_clock_sequence_fallback(tmp_path):
    # Fallback bez drawtext: sekwencja PNG 10 fps (dziesiąte sekundy) jako 1 wejście.
    sess = Session(shots=[Shot(1, 1.0), Shot(2, 2.5, 1.5)])
    style = OverlayStyle(show_running_clock=True, position="bottom-left")
    events = render.build_events(sess, 0.5, style, AnchorMode.START_SIGNAL, (640, 360), 8.0)
    seq = render._write_clock_sequence(
        tmp_path, style, (640, 360), events, t0=0.5, src_start=0.0, src_end=8.0)
    assert seq is not None
    assert seq.fps == render._CLOCK_SEQ_FPS          # 10 fps → krok 0.1 s
    # Okno wyjścia 8 s × 10 fps (+1) = 81 klatek; wszystkie zapisane na dysk.
    assert seq.nframes == 81
    written = sorted(tmp_path.glob("clock/clk_*.png"))
    assert len(written) == 81


def test_clock_sequence_caps_frames(tmp_path):
    # Bardzo długie okno → fps zredukowany tak, by nie przekroczyć limitu klatek.
    style = OverlayStyle(show_running_clock=True)
    seq = render._write_clock_sequence(
        tmp_path, style, (640, 360), [], t0=0.0, src_start=0.0, src_end=100000.0)
    assert seq is not None
    assert seq.nframes == render._CLOCK_SEQ_MAX_FRAMES
    assert seq.fps < render._CLOCK_SEQ_FPS


def test_clock_sequence_none_when_outside_window(tmp_path):
    # T0 po końcu okna → zegar się nie pojawia.
    style = OverlayStyle(show_running_clock=True)
    seq = render._write_clock_sequence(
        tmp_path, style, (640, 360), [], t0=20.0, src_start=0.0, src_end=10.0)
    assert seq is None


def test_clock_position_explicit():
    # Pozycja niezależna (top-right) — zegar w rogu wg własnego offsetu, nie nad panelem.
    style = OverlayStyle(show_running_clock=True, clock_position="top-right",
                         clock_offset_x=10, clock_offset_y=20)
    x, y = render._clock_xy(style, (640, 360), (100, 30), max_panel_h=200, gap=5)
    assert (x, y) == (640 - 100 - 10, 20)


def test_clock_position_auto_above_panel():
    style = OverlayStyle(show_running_clock=True, clock_position="auto", position="bottom-left")
    # auto + bottom → tuż nad najwyższym panelem strzału
    _, y = render._clock_xy(style, (640, 360), (100, 30), max_panel_h=120, gap=6)
    assert y == 360 - 30 - 32 - 120 - 6   # h - clock_h - offset_y - panel_h - gap


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
