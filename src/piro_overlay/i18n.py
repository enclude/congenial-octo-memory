"""Tłumaczenia etykiet (nakładka + GUI).

Teksty pojawiają się w dwóch miejscach (wypalana nakładka oraz interfejs GUI),
więc zamiast surowych słowników używamy klasy `Translator` z jawnym fallbackiem:
brakujący klucz w wybranym języku spada na angielski, a w ostateczności zwraca
`[klucz]` — dzięki czemu luka jest natychmiast widoczna w UI/na nakładce,
zamiast wywalać render wyjątkiem KeyError.
"""

from __future__ import annotations

from .models import Lang

# Pojedyncze źródło prawdy dla wszystkich etykiet.
# Każdy klucz musi mieć wpis dla obu języków; testy to weryfikują.
_STRINGS: dict[str, dict[Lang, str]] = {
    # --- nakładka ---
    "shot": {Lang.PL: "Strzał", Lang.EN: "Shot"},
    "split": {Lang.PL: "Split", Lang.EN: "Split"},
    "of": {Lang.PL: "z", Lang.EN: "of"},
    "start": {Lang.PL: "START", Lang.EN: "START"},
    "first_shot": {Lang.PL: "Pierwszy strzał", Lang.EN: "First shot"},
    "base_time": {Lang.PL: "Czas bazowy", Lang.EN: "Base time"},
    "penalties": {Lang.PL: "Suma kar", Lang.EN: "Penalties"},
    "final_time": {Lang.PL: "Czas końcowy", Lang.EN: "Final time"},
    "hit_factor": {Lang.PL: "Hit Factor", Lang.EN: "Hit Factor"},
    "summary": {Lang.PL: "Podsumowanie", Lang.EN: "Summary"},
    # dopełniacz po liczbie w nakładce metadanych ("9 strzałów" / "9 shots")
    "shots_label": {Lang.PL: "strzałów", Lang.EN: "shots"},
    # --- GUI ---
    "app_title": {Lang.PL: "Piro Overlay", Lang.EN: "Piro Overlay"},
    "site_tooltip": {Lang.PL: "Strona projektu: shothud.com", Lang.EN: "Project website: shothud.com"},
    "choose_video": {Lang.PL: "Wybierz wideo", Lang.EN: "Choose video"},
    "source_text": {Lang.PL: "Tekst", Lang.EN: "Text"},
    "source_id": {Lang.PL: "ID (API)", Lang.EN: "ID (API)"},
    "fetch": {Lang.PL: "Pobierz", Lang.EN: "Fetch"},
    "render": {Lang.PL: "Renderuj", Lang.EN: "Render"},
    "anchor_start_signal": {Lang.PL: "Sygnał startu", Lang.EN: "Start signal"},
    "anchor_first_shot": {Lang.PL: "Pierwszy strzał", Lang.EN: "First shot"},
    "offset": {Lang.PL: "Korekta T0", Lang.EN: "T0 offset"},
    "appearance": {Lang.PL: "Wygląd nakładki", Lang.EN: "Overlay appearance"},
    "language": {Lang.PL: "Język", Lang.EN: "Language"},
    "output": {Lang.PL: "Plik wyjściowy", Lang.EN: "Output file"},
    "done": {Lang.PL: "Gotowe", Lang.EN: "Done"},
    # --- pasek akcji (GUI) ---
    "act_open_video": {Lang.PL: "Otwórz wideo…", Lang.EN: "Open video…"},
    "act_fetch_api": {Lang.PL: "Pobierz z API", Lang.EN: "Fetch from API"},
    "act_detect_start": {Lang.PL: "Wykryj sygnał startu", Lang.EN: "Detect start signal"},
    "act_auto_trim": {Lang.PL: "Auto-przycięcie", Lang.EN: "Auto trim"},
    "act_add_queue": {Lang.PL: "Dodaj do kolejki", Lang.EN: "Add to queue"},
    "act_queue": {Lang.PL: "Kolejka…", Lang.EN: "Queue…"},
    "act_batch": {Lang.PL: "Wsadowo…", Lang.EN: "Batch…"},
    "act_cancel": {Lang.PL: "Zatrzymaj", Lang.EN: "Stop"},
    "act_theme": {Lang.PL: "Motyw", Lang.EN: "Theme"},
    "theme_dark": {Lang.PL: "ciemny", Lang.EN: "dark"},
    "theme_light": {Lang.PL: "jasny", Lang.EN: "light"},
    # --- sekcje inspektora (GUI) ---
    "sec_input": {Lang.PL: "Wejście", Lang.EN: "Input"},
    "sec_sync": {Lang.PL: "Synchronizacja i przycięcie", Lang.EN: "Sync and trim"},
    "sec_colors": {Lang.PL: "Kolory", Lang.EN: "Colours"},
    "sec_meta": {Lang.PL: "Nakładka metadanych", Lang.EN: "Metadata overlay"},
    "sec_clock": {Lang.PL: "Zegar", Lang.EN: "Clock"},
    "sec_banner": {Lang.PL: "Plansza START", Lang.EN: "START banner"},
    "sec_output": {Lang.PL: "Wyjście", Lang.EN: "Output"},
    # --- pola ścieżek i walidacja osi czasu (GUI, iteracja III) ---
    "path_video_placeholder": {Lang.PL: "Przeciągnij plik wideo…",
                               Lang.EN: "Drop a video file…"},
    "path_output_placeholder": {Lang.PL: "Plik wynikowy…", Lang.EN: "Output file…"},
    "tip_choose_video": {Lang.PL: "Wybierz plik wideo (Ctrl+O)",
                         Lang.EN: "Choose a video file (Ctrl+O)"},
    "tip_choose_output": {Lang.PL: "Wybierz plik wyjściowy",
                          Lang.EN: "Choose the output file"},
    "timeline_shots": {Lang.PL: "strzałów", Lang.EN: "shots"},
    "timeline_invalid": {Lang.PL: "Nie rozpoznano osi czasu",
                         Lang.EN: "Cannot parse the timeline"},
    "timeline_empty": {Lang.PL: "brak strzałów", Lang.EN: "no shots"},
    # --- wartości list: pozycja nakładki (klucz techniczny zostaje bez zmian) ---
    "pos_top_left": {Lang.PL: "Lewy górny", Lang.EN: "Top left"},
    "pos_top_center": {Lang.PL: "Górny środek", Lang.EN: "Top centre"},
    "pos_top_right": {Lang.PL: "Prawy górny", Lang.EN: "Top right"},
    "pos_bottom_left": {Lang.PL: "Lewy dolny", Lang.EN: "Bottom left"},
    "pos_bottom_center": {Lang.PL: "Dolny środek", Lang.EN: "Bottom centre"},
    "pos_bottom_right": {Lang.PL: "Prawy dolny", Lang.EN: "Bottom right"},
    "pos_clock_auto": {Lang.PL: "Nad nakładką (auto)", Lang.EN: "Above the overlay (auto)"},
    # --- stany i feedback (GUI, iteracja IV) ---
    "busy_fetch": {Lang.PL: "Pobieranie z API…", Lang.EN: "Fetching from the API…"},
    "busy_detect_start": {Lang.PL: "Wykrywanie sygnału startu…",
                          Lang.EN: "Detecting the start signal…"},
    "busy_detect_anchor": {Lang.PL: "Wykrywanie kotwicy…", Lang.EN: "Detecting the anchor…"},
    "busy_detect_id": {Lang.PL: "Wykrywanie ID z audio…", Lang.EN: "Detecting the ID from audio…"},
    "busy_temp_id_lookup": {Lang.PL: "Szukam kodu w bazie…",
                            Lang.EN: "Looking the code up in the database…"},
    "status_temp_id_lookup": {
        Lang.PL: "W audio jest kod tymczasowy {} — szukam wpisu w kalkulatorze…",
        Lang.EN: "The audio carries temporary code {} — looking for the entry…"},
    "op_cancel": {Lang.PL: "Anuluj", Lang.EN: "Cancel"},
    "op_cancelled": {Lang.PL: "Operacja anulowana.", Lang.EN: "Operation cancelled."},
    "op_busy": {Lang.PL: "Trwa inna operacja — poczekaj albo kliknij „Anuluj” w pasku stanu.",
                Lang.EN: "Another operation is running — wait or click “Cancel” in the status bar."},
    "op_failed": {Lang.PL: "Operacja nie powiodła się", Lang.EN: "The operation failed"},
    "msg_no_video": {
        Lang.PL: "Brak wideo. Detekcja i przycięcie czytają ścieżkę audio z pliku. "
                 "Wybierz nagranie (Ctrl+O) albo przeciągnij je do okna.",
        Lang.EN: "No video. Detection and trimming read the audio track from the file. "
                 "Choose a recording (Ctrl+O) or drop it onto the window."},
    "msg_no_start_signal": {
        Lang.PL: "Nie wykryto sygnału startu. W analizowanym zakresie nie ma ciągłego tonu "
                 "bzyczka (2000–4800 Hz). Ustaw T0 klikając na fali albo popraw zakres "
                 "przycięcia i spróbuj ponownie.",
        Lang.EN: "No start signal found. The analysed range has no continuous buzzer tone "
                 "(2000–4800 Hz). Set T0 by clicking the waveform, or fix the trim range "
                 "and try again."},
    "msg_no_anchor": {
        Lang.PL: "Nie wykryto kotwicy. W zakresie przycięcia nie ma wyraźnego onsetu. "
                 "Poszerz zakres, użyj „Następny kandydat” albo kliknij na fali.",
        Lang.EN: "No anchor found. The trim range has no clear onset. Widen the range, "
                 "use “Next candidate”, or click on the waveform."},
    "msg_no_candidates": {
        Lang.PL: "Brak kandydatów na kotwicę. Analiza audio nie wyznaczyła jeszcze onsetów. "
                 "Wczytaj wideo i poczekaj na koniec analizy ścieżki audio.",
        Lang.EN: "No anchor candidates. The audio analysis has not produced onsets yet. "
                 "Load a video and wait for the audio analysis to finish."},
    "msg_no_timeline": {
        Lang.PL: "Brak osi czasu. Auto-przycięcie liczy koniec od ostatniego strzału. "
                 "Wklej oś czasu w polu „Oś czasu” albo pobierz sesję po ID.",
        Lang.EN: "No timeline. Auto trim derives the end from the last shot. "
                 "Paste a timeline into the “Timeline” field or fetch a session by ID."},
    "msg_no_id_tone": {
        Lang.PL: "Nie wykryto ID w audio. Sygnał tonowy gra dopiero po zapisaniu sesji "
                 "w kalkulatorze, pod koniec nagrania. Wpisz ID ręcznie i kliknij „Pobierz”.",
        Lang.EN: "No ID tone found. The tone is played only after the session is saved, "
                 "near the end of the recording. Type the ID manually and click “Fetch”."},
    # --- dopasowanie sesji po czasie nagrania (gdy brak ID z audio) ---
    "match_time": {Lang.PL: "Dopasuj po czasie", Lang.EN: "Match by time"},
    "tip_match_time": {
        Lang.PL: "Szuka w kalkulatorze sesji zapisanej w czasie tego nagrania. Czas startu "
                 "nagrania bierze z nazwy pliku DJI (DJI_RRRRMMDDGGMMSS_…), z tagu "
                 "creation_time albo z daty modyfikacji pliku; po stronie bazy porównuje "
                 "start sesji na timerze i chwilę zapisu. Znany T0 zawęża dopasowanie do "
                 "sekund. Jednoznaczne trafienie od razu pobiera sesję i przycina film.",
        Lang.EN: "Looks up the calculator for a session saved during this recording. The "
                 "recording start comes from the DJI file name (DJI_YYYYMMDDHHMMSS_…), the "
                 "creation_time tag or the file's modification time; on the database side "
                 "the timer session start and the save time are compared. A known T0 "
                 "narrows the match to seconds. A unique hit fetches the session and trims."},
    "busy_match_time": {Lang.PL: "Dopasowywanie po czasie…", Lang.EN: "Matching by time…"},
    "status_no_tone_match_time": {
        Lang.PL: "Brak ID z audio — dopasowuję po czasie nagrania…",
        Lang.EN: "No ID tone — matching by recording time…"},
    "opt_match_time": {
        Lang.PL: "Brak ID z audio → dopasuj po czasie",
        Lang.EN: "No ID tone → match by time"},
    "tip_opt_match_time": {
        Lang.PL: "Po nieudanym „Wykryj ID z audio” aplikacja sama szuka w kalkulatorze "
                 "sesji z czasu nagrania (nazwa pliku DJI / creation_time / data pliku "
                 "vs start sesji na timerze i chwila zapisu). Przy kilku pasujących sesjach "
                 "pyta, którą wybrać.",
        Lang.EN: "After a failed “Detect ID from audio” the app looks up the calculator "
                 "for a session from the recording time (DJI file name / creation_time / "
                 "file date vs. timer session start and save time). With several matching "
                 "sessions it asks which one to use."},
    "msg_time_matched": {
        Lang.PL: "Dopasowano po czasie: ID {} — {} / {} ({}, Δ {} s)",
        Lang.EN: "Matched by time: ID {} — {} / {} ({}, Δ {} s)"},
    "msg_time_match_none": {
        Lang.PL: "Brak sesji pasującej do czasu nagrania (start {}, źródło: {}). Sesja "
                 "mogła nie zostać zapisana w kalkulatorze albo zegar kamery/timera jest "
                 "przestawiony. Wpisz ID ręcznie i kliknij „Pobierz”.",
        Lang.EN: "No session matches the recording time (start {}, source: {}). The session "
                 "may not have been saved in the calculator or the camera/timer clock is "
                 "off. Type the ID manually and click “Fetch”."},
    "msg_time_match_no_rec": {
        Lang.PL: "Nie udało się ustalić czasu nagrania. Nazwa pliku nie ma daty "
                 "(DJI_RRRRMMDDGGMMSS_…), a plik nie ma tagu creation_time ani daty "
                 "modyfikacji. Wpisz ID ręcznie i kliknij „Pobierz”.",
        Lang.EN: "Could not determine the recording time. The file name has no date "
                 "(DJI_YYYYMMDDHHMMSS_…) and the file has no creation_time tag or "
                 "modification date. Type the ID manually and click “Fetch”."},
    "msg_time_match_ambiguous": {
        Lang.PL: "Kilka sesji pasuje do czasu nagrania (start {}). Wybierz właściwą z listy "
                 "albo anuluj i wpisz ID ręcznie.",
        Lang.EN: "Several sessions match the recording time (start {}). Pick the right one "
                 "from the list or cancel and type the ID manually."},
    "msg_time_match_cancelled": {
        Lang.PL: "Nie wybrano sesji. Wpisz ID ręcznie i kliknij „Pobierz”.",
        Lang.EN: "No session chosen. Type the ID manually and click “Fetch”."},
    "time_match_dialog_title": {Lang.PL: "Sesje pasujące do czasu nagrania",
                                Lang.EN: "Sessions matching the recording time"},
    "time_match_basis_timer": {Lang.PL: "start na timerze", Lang.EN: "timer start"},
    "time_match_basis_saved": {Lang.PL: "chwila zapisu", Lang.EN: "save time"},
    "time_match_basis_video_file": {Lang.PL: "nazwa pliku nagrania",
                                    Lang.EN: "recording file name"},
    # odcisk strzałów: ile razy piki energii przy strzałach tej osi przebijają tło
    "time_match_score": {Lang.PL: " · odcisk {}×", Lang.EN: " · shot fit {}×"},
    "time_match_row": {
        Lang.PL: "ID {} · {} · {} · {} strz. · {} s · {} · Δ {} s",
        Lang.EN: "ID {} · {} · {} · {} shots · {} s · {} · Δ {} s"},
    "batch_match_time": {Lang.PL: "bez ID z audio: dopasuj po czasie",
                         Lang.EN: "no ID tone: match by time"},
    "batch_match_time_tip": {
        Lang.PL: "Gdy sygnał ID w audio jest nieczytelny, wiersz dostaje ID sesji "
                 "dopasowanej po czasie nagrania — tylko przy JEDNOZNACZNYM trafieniu. "
                 "Sprawdź takie ID przed „Przygotuj wszystkie” (podpowiedź w wierszu).",
        Lang.EN: "When the ID tone is unreadable, the row gets the ID of the session "
                 "matched by recording time — only for an UNAMBIGUOUS hit. Check such "
                 "IDs before “Prepare all” (hint on the row)."},
    "busy_recheck_t0": {Lang.PL: "Sprawdzanie zapisanego T0…",
                        Lang.EN: "Checking the saved T0…"},
    "msg_t0_stale": {
        Lang.PL: "T0 z pamięci pliku: {} s; nowa detekcja: {} s. Zapisany T0 pochodzi "
                 "ze starszej wersji detekcji sygnału startu — może być nieaktualny.",
        Lang.EN: "T0 from the file's memory: {} s; new detection: {} s. The saved T0 "
                 "comes from an older start-signal detection — it may be outdated."},
    "msg_t0_stale_use": {Lang.PL: "Użyj {} s", Lang.EN: "Use {} s"},
    "msg_t0_detected": {Lang.PL: "Wykryto T0 = {} s", Lang.EN: "Detected T0 = {} s"},
    "msg_anchor_detected": {Lang.PL: "Wykryto kotwicę = {} s", Lang.EN: "Detected anchor = {} s"},
    "msg_id_detected": {Lang.PL: "Wykryto ID z audio: {}", Lang.EN: "ID detected from audio: {}"},
    "msg_session_fetched": {Lang.PL: "Pobrano sesję {} — strzałów: {}",
                            Lang.EN: "Session {} fetched — shots: {}"},
    "msg_trimmed": {Lang.PL: "Przycięto: {} s – {} s", Lang.EN: "Trimmed: {} s – {} s"},
    "msg_trim_invalid": {
        Lang.PL: "Początek przycięcia jest po końcu. Zakres to 0–{} s. "
                 "Zmniejsz „od” albo zwiększ „do”.",
        Lang.EN: "The trim start is after the end. The valid range is 0–{} s. "
                 "Lower “from” or raise “to”."},
    "msg_render_busy": {
        Lang.PL: "Render już trwa (bezpośredni albo z kolejki). Poczekaj na koniec "
                 "albo zatrzymaj go przyciskiem „Zatrzymaj”.",
        Lang.EN: "A render is already running (direct or from the queue). Wait for it "
                 "to finish or stop it with “Stop”."},
    "msg_render_cancelled": {Lang.PL: "Renderowanie przerwane.", Lang.EN: "Rendering cancelled."},
    "msg_render_done": {Lang.PL: "Gotowe: {}", Lang.EN: "Done: {}"},
    "render_failed_title": {Lang.PL: "Błąd renderowania", Lang.EN: "Rendering error"},
    "render_failed_text": {
        Lang.PL: "Render nie został ukończony. FFmpeg zakończył się błędem — "
                 "szczegóły techniczne są pod „Pokaż szczegóły”.",
        Lang.EN: "The render did not finish. FFmpeg exited with an error — "
                 "technical details are under “Show Details”."},
    "act_open_folder": {Lang.PL: "Otwórz folder", Lang.EN: "Open folder"},
    "empty_title": {Lang.PL: "Brak wideo", Lang.EN: "No video"},
    "empty_hint": {Lang.PL: "Przeciągnij tu plik albo użyj Ctrl+O",
                   Lang.EN: "Drop a file here or press Ctrl+O"},
    # --- oś czasu, podgląd (iteracja V) ---
    "wave_empty": {Lang.PL: "Ścieżka audio pojawi się po wczytaniu wideo",
                   Lang.EN: "The audio track appears once a video is loaded"},
    "wave_tip": {
        Lang.PL: "Klik = ustaw kotwicę (snap do strzału) · Ctrl+klik = podgląd klatki · "
                 "kółko = zoom · prawy przycisk = przesuń · dwuklik = reset zoomu · "
                 "←/→ = kotwica o 0,05 s (Shift: 1 s) · Home/End = granice przycięcia · "
                 "+/− = zoom, 0 = reset · Shift+O = znaczniki onsetów · "
                 "I/O = Od/Do w bieżącym czasie · T = kotwica · M = dodaj strzał · "
                 "klik na strzale = zaznacz, przeciągnij = przesuń, "
                 "←/→ = przesuń o 0,05 s, Delete = usuń, Esc = odznacz",
        Lang.EN: "Click = set anchor (snaps to a shot) · Ctrl+click = frame preview · "
                 "wheel = zoom · right button = pan · double click = reset zoom · "
                 "←/→ = anchor by 0.05 s (Shift: 1 s) · Home/End = trim bounds · "
                 "+/− = zoom, 0 = reset · Shift+O = onset markers · "
                 "I/O = in/out at the current time · T = anchor · M = add shot · "
                 "click a shot = select, drag = move, ←/→ = nudge by 0.05 s, "
                 "Delete = remove, Esc = deselect"},
    # --- podgląd w ruchu: pasek transportu (iteracja VI) ---
    # Przyciski transportu są ikonowe (v0.51.0, `assets/icons/*.svg` przez
    # `ui_theme.icon`, `gui._apply_icon`) — te klucze `tr_*` (stare glify)
    # ZOSTAJĄ jako fallback, gdy SVG nie da się załadować (brak `Qt6Svg` w
    # bundlu): `_apply_icon` wtedy przełącza przycisk na `ToolButtonTextOnly`
    # i wpisuje ten tekst. Tooltip ze skrótem (`tip_tr_*`) opisuje przycisk
    # w obu przypadkach.
    "tr_t0": {Lang.PL: "|◀", Lang.EN: "|◀"},
    "tr_back": {Lang.PL: "◀◀", Lang.EN: "◀◀"},
    "tr_play": {Lang.PL: "▶", Lang.EN: "▶"},
    "tr_pause": {Lang.PL: "❚❚", Lang.EN: "❚❚"},
    "tr_fwd": {Lang.PL: "▶▶", Lang.EN: "▶▶"},
    "tr_to": {Lang.PL: "▶|", Lang.EN: "▶|"},
    "tr_loop": {Lang.PL: "↻", Lang.EN: "↻"},
    "tip_tr_t0": {Lang.PL: "Przeskocz do sygnału startu (T0)",
                  Lang.EN: "Jump to the start signal (T0)"},
    "tip_tr_back": {Lang.PL: "Cofnij o sekundę (J) · przecinek = klatka wstecz",
                    Lang.EN: "Back one second (J) · comma = one frame back"},
    "tip_tr_play": {Lang.PL: "Odtwórz / pauza podglądu z nakładką (Spacja) · K = pauza",
                    Lang.EN: "Play / pause the overlay preview (Space) · K = pause"},
    "tip_tr_pause": {Lang.PL: "Pauza podglądu z nakładką (Spacja) · K = pauza",
                     Lang.EN: "Pause the overlay preview (Space) · K = pause"},
    "tip_tr_fwd": {Lang.PL: "Do przodu o sekundę (L) · kropka = klatka w przód",
                   Lang.EN: "Forward one second (L) · period = one frame forward"},
    "tip_tr_to": {Lang.PL: "Przeskocz do końca zakresu („Do”)",
                  Lang.EN: "Jump to the end of the range (out point)"},
    "tip_tr_loop": {Lang.PL: "Pętla Od–Do: po dojściu do „Do” wróć do „Od” zamiast pauzować",
                    Lang.EN: "Loop in–out: at the out point return to the in point "
                             "instead of pausing"},
    "msg_no_multimedia": {
        Lang.PL: "Podgląd w ruchu jest niedostępny: brak modułu QtMultimedia. "
                 "Zostaje podgląd klatki (Ctrl+klik na osi).",
        Lang.EN: "Motion preview unavailable: QtMultimedia module missing. "
                 "The frame preview (Ctrl+click on the timeline) still works."},
    "msg_player_error": {
        Lang.PL: "Nie udało się odtworzyć nagrania w podglądzie ({}). "
                 "Backend multimediów nie obsługuje tego pliku — "
                 "podgląd klatki (Ctrl+klik na osi) działa dalej.",
        Lang.EN: "The recording cannot be played in the preview ({}). "
                 "The multimedia backend does not support this file — "
                 "the frame preview (Ctrl+click on the timeline) still works."},
    "msg_in_set": {Lang.PL: "„Od” ustawione na {}.", Lang.EN: "In point set to {}."},
    "msg_out_set": {Lang.PL: "„Do” ustawione na {}.", Lang.EN: "Out point set to {}."},
    "msg_shot_added": {Lang.PL: "Dodano strzał {} w czasie {} od T0.",
                       Lang.EN: "Shot {} added at {} after T0."},
    "msg_shot_moved": {Lang.PL: "Przesunięto strzał {} na {} od T0.",
                       Lang.EN: "Shot {} moved to {} after T0."},
    "msg_shot_deleted": {Lang.PL: "Usunięto strzał {} z osi czasu.",
                         Lang.EN: "Shot {} removed from the timeline."},
    "msg_shot_text_only": {
        Lang.PL: "Edycja strzałów działa tylko przy źródle „Tekst” "
                 "(oś z API jest tylko do odczytu).",
        Lang.EN: "Editing shots only works with the „Text” source "
                 "(the API timeline is read-only)."},
    "msg_shot_before_t0": {
        Lang.PL: "Ten czas jest przed T0 — strzał musi wypaść po sygnale startu.",
        Lang.EN: "This time is before T0 — a shot must fall after the start signal."},
    "act_edit_pos": {Lang.PL: "Edytuj pozycje", Lang.EN: "Edit positions"},
    "tip_edit_pos": {
        Lang.PL: "Tryb edycji: przeciągaj w podglądzie panel strzału, metadane i zegar, "
                 "by ustawić ich pozycję (offsety). Escape kończy edycję.",
        Lang.EN: "Edit mode: drag the shot panel, metadata and clock in the preview to "
                 "set their position (offsets). Escape leaves the mode."},
    "preview_fit": {Lang.PL: "Dopasuj", Lang.EN: "Fit"},
    "tip_preview_fit": {Lang.PL: "Pokaż całe nagranie na osi (reset zoomu)",
                        Lang.EN: "Show the whole recording on the timeline (reset zoom)"},
    "preview_zoom_range": {Lang.PL: "Zoom Od–Do", Lang.EN: "Zoom in–out"},
    "tip_preview_zoom_range": {
        Lang.PL: "Powiększ oś do zakresu przycięcia (Od…Do) z marginesem",
        Lang.EN: "Zoom the timeline to the trim range (From…To) with a margin"},
    "save_frame": {Lang.PL: "Zapisz klatkę", Lang.EN: "Save frame"},
    "tip_save_frame": {
        Lang.PL: "Zapisz bieżącą klatkę wideo z nakładką jako PNG w pełnej "
                 "rozdzielczości źródła",
        Lang.EN: "Save the current video frame with overlay as a PNG at the "
                 "source's full resolution"},
    "busy_save_frame": {Lang.PL: "Zapisuję klatkę…", Lang.EN: "Saving frame…"},
    "msg_frame_saved": {Lang.PL: "Zapisano klatkę: {}", Lang.EN: "Frame saved: {}"},
    "msg_save_frame_failed": {
        Lang.PL: "Nie udało się zapisać klatki: {}",
        Lang.EN: "Failed to save the frame: {}"},
    "rect_panel": {Lang.PL: "panel strzału", Lang.EN: "shot panel"},
    "rect_clock": {Lang.PL: "zegar", Lang.EN: "clock"},
    "rect_meta": {Lang.PL: "metadane", Lang.EN: "metadata"},
    "proxy_chk": {Lang.PL: "Proxy podglądu (auto)", Lang.EN: "Preview proxy (auto)"},
    "tip_proxy_chk": {
        Lang.PL: "Dla nagrań 4K i HEVC aplikacja buduje raz małe proxy 540p i to ono "
                 "gra w podglądzie oraz w podglądzie klatki. Bez niego odtwarzacz "
                 "dekoduje 4K programowo i pokazuje kilka klatek na sekundę. "
                 "Proxy leżą w katalogu konfiguracji (AppData → PiroOverlay → proxies) "
                 "i są kasowane od najstarszych; render zawsze idzie na oryginale.",
        Lang.EN: "For 4K and HEVC recordings the app builds a small 540p proxy once and "
                 "plays that in the motion and frame previews. Without it the player "
                 "decodes 4K in software and shows a few frames per second. "
                 "Proxies live in the config directory (AppData → PiroOverlay → proxies) "
                 "and the oldest are dropped first; rendering always uses the original."},
    "busy_proxy": {Lang.PL: "Przygotowuję proxy podglądu…",
                   Lang.EN: "Building the preview proxy…"},
    "tip_proxy_building": {Lang.PL: "Trwa przygotowanie proxy podglądu",
                           Lang.EN: "The preview proxy is being prepared"},
    "msg_proxy_ready": {Lang.PL: "Proxy podglądu gotowe ({} s).",
                        Lang.EN: "Preview proxy ready ({} s)."},
    "msg_proxy_failed": {
        Lang.PL: "Nie udało się zbudować proxy podglądu ({}). Podgląd w ruchu jest "
                 "wyłączony dla tego pliku. Zostaje podgląd klatki (Ctrl+klik na osi).",
        Lang.EN: "The preview proxy could not be built ({}). Motion preview is disabled "
                 "for this file. The frame preview (Ctrl+click on the timeline) still works."},
    "busy_audio": {Lang.PL: "Analiza audio…", Lang.EN: "Analysing audio…"},
    "busy_audio_lrf": {Lang.PL: "Analiza audio (proxy LRF)…",
                       Lang.EN: "Analysing audio (LRF proxy)…"},
    "audio_failed": {Lang.PL: "Błąd audio: {}", Lang.EN: "Audio error: {}"},
    # --- okna pomocnicze: kolejka renderów, wsad (iteracja odświeżenia UI v0.49.0) ---
    "queue_title": {Lang.PL: "Kolejka renderów", Lang.EN: "Render queue"},
    "queue_empty": {
        Lang.PL: "Kolejka jest pusta — dodaj zadanie przyciskiem „Dodaj do kolejki” "
                 "w głównym oknie.",
        Lang.EN: "The queue is empty — add a job with the “Add to queue” button "
                 "in the main window."},
    "queue_thumb_tooltip": {
        Lang.PL: "Klatka z {0} s", Lang.EN: "Frame at {0} s"},
    "batch_title": {Lang.PL: "Przetwarzanie wsadowe (auto + ID)",
                    Lang.EN: "Batch processing (auto + ID)"},
    "batch_empty": {
        Lang.PL: "Przeciągnij tu pliki wideo albo użyj „Dodaj pliki…”",
        Lang.EN: "Drop video files here or use “Add files…”"},
    # --- „Automat z folderu…" (wsad, v0.56.0) ---
    "batch_auto": {Lang.PL: "Automat z folderu…", Lang.EN: "Auto from folder…"},
    "batch_auto_tip": {
        Lang.PL: "Wskaż katalog z nagraniami: dodaje pliki wideo do listy, wykrywa "
                 "ID z audio, a dla plików z ID pobiera sesję i wykrywa T0. Do "
                 "kolejki NIC nie trafia automatycznie — najpierw sprawdź wyniki.",
        Lang.EN: "Pick a folder with recordings: adds the video files to the list, "
                 "detects IDs from audio and, for files with an ID, fetches the "
                 "session and detects T0. Nothing is queued automatically — review "
                 "the results first."},
    "batch_auto_recursive": {Lang.PL: "z podkatalogami",
                             Lang.EN: "include subfolders"},
    "batch_auto_pick_dir": {Lang.PL: "Wybierz katalog z nagraniami",
                            Lang.EN: "Choose a folder with recordings"},
    "batch_auto_busy": {Lang.PL: "Automat…", Lang.EN: "Auto…"},
    "batch_auto_scanning": {Lang.PL: "Skanuję katalog…", Lang.EN: "Scanning folder…"},
    "batch_auto_added": {Lang.PL: "Dodano {0} z {1} plików wideo z katalogu.",
                         Lang.EN: "Added {0} of {1} video files from the folder."},
    "batch_auto_no_files": {
        Lang.PL: "W katalogu nie ma plików wideo (.mp4, .mov, .mkv, .avi, .m4v).",
        Lang.EN: "No video files in the folder (.mp4, .mov, .mkv, .avi, .m4v)."},
    "batch_auto_scan_failed": {Lang.PL: "Nie udało się odczytać katalogu: {0}",
                               Lang.EN: "Could not read the folder: {0}"},
    "batch_auto_detecting": {Lang.PL: "Wykrywam ID: {0}/{1}",
                             Lang.EN: "Detecting IDs: {0}/{1}"},
    "batch_auto_preparing": {Lang.PL: "Przygotowuję: {0}/{1}",
                             Lang.EN: "Preparing: {0}/{1}"},
    "batch_auto_summary": {Lang.PL: "Gotowe: {0}, bez ID: {1}, błędy: {2}",
                           Lang.EN: "Ready: {0}, no ID: {1}, errors: {2}"},
}

_FALLBACK_LANG = Lang.EN


class Translator:
    """Tłumacz związany z konkretnym językiem, z łańcuchem fallbacku."""

    def __init__(self, lang: Lang = Lang.PL) -> None:
        self.lang = Lang(lang)

    def t(self, key: str) -> str:
        """Zwraca etykietę dla klucza; fallback: wybrany język → EN → [klucz]."""
        entry = _STRINGS.get(key)
        if entry is None:
            return f"[{key}]"
        if self.lang in entry:
            return entry[self.lang]
        if _FALLBACK_LANG in entry:
            return entry[_FALLBACK_LANG]
        return f"[{key}]"

    # Skrót: translator jest wywoływalny jak funkcja — tr("shot").
    __call__ = t


def get_translator(lang: Lang = Lang.PL) -> Translator:
    """Fabryka tłumacza dla danego języka."""
    return Translator(lang)


def available_keys() -> list[str]:
    """Lista wszystkich kluczy — używane w testach kompletności tłumaczeń."""
    return list(_STRINGS.keys())
