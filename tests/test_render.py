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
    # Fallback bez drawtext: sekwencja PNG w kadencji wideo, ZAMROŻONA na ostatnim
    # strzale (2.5 s), jako 1 wejście. fps = fps wideo (równa kadencja, brak dudnienia).
    sess = Session(shots=[Shot(1, 1.0), Shot(2, 2.5, 1.5)])
    style = OverlayStyle(show_running_clock=True, position="bottom-left")
    events = render.build_events(sess, 0.5, style, (640, 360), 8.0)
    seq = render._write_clock_sequence(
        tmp_path, style, (640, 360), events, t0=0.5, src_start=0.0, src_end=8.0,
        video_fps=30.0, last_shot_time=2.5)
    assert seq is not None
    assert seq.fps == 30.0                           # = fps wideo (1:1 z klatkami wyjścia)
    # Zegar płynie tylko do ostatniego strzału: clock_end_out = (0.5+2.5)-0 = 3.0 s.
    # 3.0 s × 30 fps (+1) = 91 klatek; potem klatka jest powtarzana (eof_action=repeat).
    assert seq.nframes == 91
    written = sorted(tmp_path.glob("clock/clk_*.png"))
    assert len(written) == 91


def test_clock_sequence_freezes_at_last_shot(tmp_path):
    # Bez podanego last_shot_time zegar płynie do końca okna (zachowanie awaryjne).
    style = OverlayStyle(show_running_clock=True)
    seq_full = render._write_clock_sequence(
        tmp_path / "a", style, (640, 360), [], t0=0.0, src_start=0.0, src_end=8.0,
        video_fps=10.0, last_shot_time=None)
    # Z last_shot_time=2.0 sekwencja jest krótsza (zamarza po 2 s).
    seq_frozen = render._write_clock_sequence(
        tmp_path / "b", style, (640, 360), [], t0=0.0, src_start=0.0, src_end=8.0,
        video_fps=10.0, last_shot_time=2.0)
    assert seq_full.nframes > seq_frozen.nframes
    assert seq_frozen.nframes == 21                  # 2.0 s × 10 fps (+1)


def test_clock_sequence_caps_frames(tmp_path):
    # Bardzo długie okno → fps zredukowany całkowitym dzielnikiem, by nie przekroczyć limitu.
    style = OverlayStyle(show_running_clock=True)
    seq = render._write_clock_sequence(
        tmp_path, style, (640, 360), [], t0=0.0, src_start=0.0, src_end=100000.0,
        video_fps=30.0, last_shot_time=None)
    assert seq is not None
    assert seq.nframes <= render._CLOCK_SEQ_MAX_FRAMES
    assert seq.fps < 30.0


def test_clock_sequence_none_when_outside_window(tmp_path):
    # T0 po końcu okna → zegar się nie pojawia.
    style = OverlayStyle(show_running_clock=True)
    seq = render._write_clock_sequence(
        tmp_path, style, (640, 360), [], t0=20.0, src_start=0.0, src_end=10.0,
        video_fps=30.0, last_shot_time=5.0)
    assert seq is None


def test_clock_drawtext_freezes_at_last_shot():
    # drawtext: wyrażenie czasu zamrożone przez min(t-c, last_shot).
    style = OverlayStyle(show_running_clock=True, position="bottom-left")
    seg, label = render._clock_drawtext_seg(
        "0:v", style, (640, 360), [], t0=0.5, src_start=0.0, last_shot_time=2.5)
    assert label == "vclock"
    assert "min(t-0.500,2.500)" in seg


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
