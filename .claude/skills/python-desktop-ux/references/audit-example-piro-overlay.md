# Przykładowy audyt: Piro Overlay (zrzut v0.21.2, kod v0.43.0, Windows 11, PySide6)

Wzorzec raportu z audytu wykonanego według `audit-checklist.md`. Pokazuje oczekiwany poziom precyzji: każdy problem ma dowód wskazany po nazwie sekcji lub kontrolki z ekranu, wagę i rekomendację weryfikowalną zrzutem.

## Potwierdzenie po wglądzie w kod

Audyt powstał na podstawie jednego zrzutu ekranu (v0.21.2, okno ok. 1920x1030 px, UI po polsku, motyw domyślny Windows). Po wglądzie w kod (`src/piro_overlay/gui.py`, ok. 3600 linii, wersja 0.43.0; układ sekcji ten sam co na zrzucie) hipotezy zostały sprawdzone:

| Co | Stan w kodzie | Skutek dla audytu |
|---|---|---|
| Framework | PySide6 (nie Tkinter, jak sugerował wygląd kontrolek) | rekomendacje implementacyjne wg `qt-pyside6.md`; klasy z `scripts/qt_widgets.py`, motyw z `scripts/qt_theme.py` |
| Okno | `MainWindow(QMainWindow)`, `QSplitter(Qt.Horizontal)`, lewy `QScrollArea` z inspektorem, `statusBar()` istnieje | układ zostaje; przycisk "Renderuj" siedzi w `QGroupBox("Wyjście")` na dole przewijanego inspektora, więc problem 5 to P0 |
| Sekcje | `QGroupBox("Wejście")`, `("Synchronizacja i przycięcie")`, `("Wygląd nakładki")`, `("Wyjście")` (+ `"Ustawienia wspólne"` w dialogu wsadu) | problem 6 potwierdzony: ramki z tytułem w linii ramki, domyślny styl "windowsvista" |
| Podgląd i oś | `PreviewLabel(QLabel)`, `WaveformWidget(QWidget)` z `paintEvent` i kolorami `QColor(...)` na sztywno | problemy 7, 16, 17, 21, 29, 30 potwierdzone; rysowanie do przeniesienia na tokeny (`qt-pyside6.md` §7) |
| Kolory | `ColorButton(QPushButton)` z tekstem "RGBA r,g,b,a" i QSS budowanym f-stringiem | problem 12 potwierdzony; `ColorSwatchButton` ma zgodny konstruktor, `rgba()` i sygnał `changed` |
| Stylowanie | brak `app.setStyle`, `QPalette`, globalnego QSS, polityki HiDPI i `QSettings`; ok. 19 rozproszonych `setStyleSheet` z kolorami | fundament (iteracja I) to Fusion + paleta + QSS z tokenów; `setStyleSheet` do zamiany na `role`/`kind` |
| Wątki | workery `QThread` z sygnałami (render, klatki, fala, detekcja startu, wsad, aktualizacje) | problem 3 zmienia wagę na P1: UI nie zamiera, brakuje widocznego postępu i anulowania przy każdej operacji |
| Kółko myszy | `WheelGuard` (filtr zdarzeń: kółko nad spinboxami w `QScrollArea` przewija stronę) | zachować bez zmian; obejmie też `NumberField.spin` |
| Akcje i skróty | brak `QToolBar`, `QAction`, `QMenuBar` | problem 20 potwierdzony (P1) |
| Wersja | 0.43.0 w `src/piro_overlay/__init__.py` i `pyproject.toml` | numery linii w `qt-pyside6.md` dotyczą tej wersji; każda iteracja kończy się bumpem MINOR |

Zasady repo, które audyt respektuje: moduły domenowe nie importują PySide6 (nowe moduły UI `ui_theme.py` i `ui_widgets.py` leżą obok `gui.py`); teksty przez `i18n.Translator` i `_STRINGS` w PL i EN (część etykiet GUI jest dziś wpisana w `gui.py` na sztywno, sprawdź przed dodaniem klucza); `tests/test_syntax.py` kompiluje `gui.py`, bo WSL nie ma PySide6; GUI i zrzuty uruchamiane interpreterem Windows z `.venv-win` (`QT_QPA_PLATFORM=offscreen`, `QT_QPA_FONTDIR=C:\Windows\Fonts`); zrzuty "przed" są w `pictures/*.png`; klucze ustawień z `config.py` bez zmian.

| Pole | Wartość |
|---|---|
| Aplikacja | Piro Overlay (nakładka timera strzeleckiego na nagranie wideo); zrzut v0.21.2, kod v0.43.0 |
| Źródła | 1 zrzut ekranu + opis + wgląd w kod `gui.py` |
| Framework | PySide6 (potwierdzone w kodzie) |
| Rozdzielczość zrzutu | ok. 1920x1030 px, DPI nieznane (proporcje kontrolek sugerują 100 %) |
| Język UI | polski, z jedną wartością po angielsku ("bottom-left") |

## Tabela problemów

| # | Problem | Dowód (gdzie na ekranie) | Waga | Rekomendacja | Odwołanie |
|---|---|---|---|---|---|
| 1 | Brak paska transportu: nie da się odtworzyć fragmentu ani sprawdzić synchronizacji nakładki z sygnałem startu bez renderu | Prawa część okna: pasek "Edytuj pozycje (przeciąganie)", podgląd z nakładką "START", oś czasu; brak Odtwarzaj/Pauza i czasu bieżącego | P0 | Pasek transportu pod podglądem (`QToolBar` z `QAction` lub `QHBoxLayout` z `QToolButton(kind=ghost)`): odtwarzaj/pauza, klatka -/+, skok do markerów Start/T0/Od/Do, "0:37.6 / 2:25" w `role=mono`, Spacja jako skrót | component-patterns.md §9; qt-pyside6.md §5; checklista I |
| 2 | Brak paska stanu i miejsca na komunikaty; wynik operacji widoczny tylko jako szara etykieta | Sekcja "Wejście", pod wierszem "ID": "Tor: Tor 1 #2 (z niespodzianką) \| Zawodnik: Bartek"; dół okna pusty | P0 | Istniejący `QStatusBar` z helperem `status_message(statusbar, text, kind, ms)` (kolor stanu), `QProgressBar` jako widżet stały; błędy z akcją ("Spróbuj ponownie") | component-patterns.md §10; qt-pyside6.md §4 (QStatusBar); E |
| 3 | Brak wskaźnika postępu i przycisku anulowania przy pobieraniu z API, wykrywaniu i auto-przycięciu (workery `QThread` istnieją, więc UI nie zamiera, ale użytkownik nie widzi, że coś trwa) | Przyciski "Pobierz", "Pobierz i przytnij" ("Wejście"); "Wykryj kotwice", "Następny kandydat", "Wykryj sygnał startu", "Auto-przycięcie" ("Synchronizacja i przycięcie") | P1 (po wglądzie w kod) | `set_busy(btn, True, "Wykrywanie...")` na przycisku wywołującym, `QProgressBar.setRange(0, 0)` w pasku stanu, przycisk "Anuluj" `kind=ghost` z flagą sprawdzaną w `run()` workera | component-patterns.md §10; qt-pyside6.md §8, §9; J |
| 4 | Niespójny format czasu i separator dziesiętny: przecinek w polach, kropka na osi, format m:ss tylko dla dłuższych wartości, podziałka miesza "45s" z "1:00" | "Kotwica (czas) 37,60 s", "Przytnij od / do 32,60 s / 112,60 s", "Margines końcowy 5,00 s" vs pole "Oś czasu": "7.82s", "(+0.90s)" vs markery "T0 37.6s", "Od 32.6s", "Do 1:53", "Koniec 2:25" vs podziałka "0s ... 45s, 1:00 ... 2:15" | P0 | Jeden format w polach, markerach i podziałce (pola: `QDoubleSpinBox`/`NumberField` z `setSuffix(" s")` i `QLocale(Polish)`; oś: ta sama funkcja formatująca); parser akceptujący "37,6", "37.6", "0:37.6"; zapis ustawień bez zmian (float sekund) | component-patterns.md §4, §12; qt-pyside6.md §4 (QSpinBox); D |
| 5 | Akcja końcowa (render/eksport) niewidoczna; inspektor nie mieści się w oknie i jest ucięty | Dół lewego panelu: etykieta "Offset zegara X / Y" ucięta w połowie; pasek przewijania po prawej stronie inspektora | P0 (potwierdzone: "Renderuj" w `QGroupBox("Wyjście")` na dole przewijanego inspektora) | `QToolBar` z `QAction` "Renderuj" (Ctrl+R) poza obszarem przewijania, przycisk w formularzu jako drugie wejście do tej samej akcji; sekcje `FormSection(collapsible=True)`, by całość mieściła się w 1030 px | qt-pyside6.md §5; component-patterns.md §7; A |
| 6 | Ramki `QGroupBox` w domyślnym stylu Windows: linia z tytułem wciętym w krawędź, wygląd Windows 7 | Tytuły "Wejście", "Synchronizacja i przycięcie", "Wygląd nakładki", "Wyjście" | P1 | Krok 1: reguła QSS `QGroupBox { border: none; border-top: 1px ... }` (zero zmian w kodzie); krok 2: `FormSection(title, collapsible=True)` z `role=section` na tytule | component-patterns.md §2; qt-pyside6.md §4 (QGroupBox); scripts/qt_widgets.py |
| 7 | Dwie estetyki w jednym oknie: jasny systemowy inspektor obok czarnego podglądu i czarnej osi czasu | Lewy panel: tło jasnoszare, białe pola; prawa część: czarne pasy letterbox, czarne tło osi czasu | P1 | `apply_theme(app, "dark")` z `ui_theme.py` (Fusion + QPalette + QSS) jako domyślny dla całego okna; letterbox `PreviewLabel` i tło `WaveformWidget` z tokenów `bg`/`surface`; LIGHT jako opcja | design-tokens.md §Zasady; qt-pyside6.md §2; C |
| 8 | Kolumny etykiet niewyrównane między sekcjami; kontrolki zaczynają się w trzech różnych liniach | "Wideo", "ID": kontrolki od ok. 95 px; "Typ kotwicy", "Kotwica (czas)": od ok. 140 px; "Język", "Pozycja", "Tło": od ok. 195 px | P1 | Jedna kolumna etykiet dla całego inspektora: `QLabel.setMinimumWidth(132)` na etykietach każdego `QFormLayout` lub `FormSection` | component-patterns.md §3; qt-pyside6.md §4 (QFormLayout); A |
| 9 | Szerokości kontrolek przypadkowe: pola na 1-4 cyfry rozciągnięte na całą szerokość, pole ID krótkie, przycisk w miejscu wartości | "Kotwica (czas)" na pełną szerokość panelu; "ID 163" krótki; "Margines końcowy 5,00 s" krótki obok szerokiego "Auto-przycięcie"; "Rozmiar (skala) 0,80" i "Grubość obramowania 3" na pełną szerokość | P1 | Pola liczbowe z `QSizePolicy.Fixed`/`setMinimumWidth(64)` i zakresem z długości nagrania (nie 0..100000), wyrównane do lewej krawędzi kolumny kontrolek; przyciski akcji w osobnym wierszu, do prawej | component-patterns.md §3; qt-pyside6.md §4 (QSpinBox); A, D |
| 10 | Domyślny font Tk (Segoe UI 9 pt); tytuły sekcji nie różnią się od etykiet pól | Cały inspektor; tytuły "Wejście" itd. w tym samym kroju i rozmiarze co "Wideo", "Źródło" | P1 | `app.setFont(make_font("font_ui"))` 10 pt, tytuły sekcji `role=section` (11 pt bold), `role=mono` dla wartości czasu i współrzędnych | design-tokens.md §Typografia; qt-pyside6.md §4 (QLabel z rolą); B |
| 11 | Angielska wartość w polskim UI | "Wygląd nakładki": "Pozycja: bottom-left" | P1 | `pos_combo.addItem(tr(key), key)` zamiast `addItems(ANCHOR_POSITIONS)`, odczyt `currentData()`; zapisywany klucz `bottom-left` bez zmian | component-patterns.md §12; qt-pyside6.md §4 (QComboBox); B, D |
| 12 | Kolory jako paski z tekstem "RGBA ..."; kolor trzeba odczytać z liczb, próbka mała, alfa w skali 0-255 | "Tło: RGBA 0,0,0,170", "Tekst: RGBA 255,255,255,255", "Akcent: RGBA 255,196,0,255", "Obramowanie: RGBA 255,255,255,220" | P1 | `ColorSwatchButton(rgba)` zamiast `ColorButton`: próbka z szachownicą pod alfą, hex "#FFC400", alfa "67 %", `QColorDialog` z `ShowAlphaChannel`; ten sam konstruktor i `rgba()`, zapis nadal RGBA 0-255 | component-patterns.md §5; qt-pyside6.md §7; D |
| 13 | Trzy przyciski równej wagi bez primary; akcja wtórna wygląda jak główna | "Wykryj kotwice" \| "Następny kandydat" \| "Wykryj sygnał startu" w jednym rzędzie sekcji "Synchronizacja i przycięcie" | P1 | Jeden `kind=primary` "Wykryj" zależny od "Typ kotwicy"; "Następny kandydat" `kind=ghost` z licznikiem "2/5", `setEnabled(False)` bez wyników | component-patterns.md §7; qt-pyside6.md §4 (QPushButton); D |
| 14 | Surowy zrzut danych w wieloliniowym polu tekstowym; wynik analizy pokazany jak pole do edycji | "Oś czasu": Text 3 linie z paskiem: "1: 7.82s \| 2: 8.72s (+0.90s) \| 3: 9.64s (+0.92s) \| ... \| 13: 26.14s" | P1 | `QPlainTextEdit` w `role=mono` + podsumowanie "13 strzałów, 7.82-26.14 s" w `role=muted`; opcjonalnie zwijana tabela (`QTableView`: #, czas, odstęp); strzały jako warstwa na osi czasu | component-patterns.md §2; qt-pyside6.md §4 (QPlainTextEdit); D |
| 15 | Tryb przeciągania wygląda jak etykieta; nie widać, czy jest przełącznikiem ani czy jest aktywny | Pasek nad podglądem: wyśrodkowany tekst "Edytuj pozycje (przeciąganie)" na jasnym pasku | P1 | `QToolButton.setCheckable(True)` z ikoną przesuwania i stanem `:checked` w pasku transportu; Escape wychodzi z trybu; kursor `Qt.OpenHandCursor`/`ClosedHandCursor` | component-patterns.md §9; qt-pyside6.md §5, §7 (PreviewLabel); I |
| 16 | Oś czasu zaśmiecona: gęste bursztynowe linie pionowe na całej długości zlewają się z falą; brak legendy i przełącznika warstwy | Oś czasu: fala w kolorze cyjanowym, dziesiątki bursztynowych linii od 0s do 2:25 | P1 | Warstwy w `WaveformWidget.paintEvent`: fala (`text_muted`), detekcje (`success`, 1 px, przełączalne), markery; legenda w rogu osi; kolory przez `current_tokens(app)` | component-patterns.md §8; qt-pyside6.md §7 (WaveformWidget); I |
| 17 | Brak wskaźnika czasu bieżącego i zoomu; precyzja myszy poniżej kroku pól | Oś czasu: 2:25 nagrania na ok. 1330 px (1 px = ok. 0.11 s) przy polach z krokiem 0,01 s; brak playheada | P1 | Playhead zsynchronizowany z podglądem, zoom Ctrl+kółko i przyciski (`wheelEvent` z `modifiers()`), przewijanie poziome, snapping do detekcji i sekund | component-patterns.md §8; qt-pyside6.md §7; I |
| 18 | To samo pojęcie pod trzema nazwami | "Kotwica (czas) 37,60 s" (inspektor), "T0 37.6s" (oś czasu), "START" (nakładka), "Płynący czas od T0 (nad nakładką, od STARTU)" | P1 | Jeden termin w UI, np. "Sygnał startu (T0)", zmieniany tylko w słowniku i18n; klucze ustawień bez zmian | B, D |
| 19 | Zależności kontrolek niewidoczne: pola zależne aktywne przy wyłączonej opcji nadrzędnej | "Grubość obramowania" przy "Włącz obramowanie"; "Pozycja zegara" i "Offset zegara X / Y" przy odznaczonym "Płynący czas od T0" (wszystkie wyglądają na aktywne) | P1 (do potwierdzenia w działaniu) | `setEnabled(False)` pól zależnych w slocie `toggled` checkboxa | component-patterns.md §3; qt-pyside6.md §8; D |
| 20 | Brak widocznych skrótów i menu; wszystkie akcje tylko myszą | Brak paska menu, podkreśleń mnemoników i tooltipów na zrzucie | P1 (potwierdzone: brak `QToolBar`/`QAction`/`QMenuBar`) | `QAction` z `setShortcut`: Ctrl+O, Ctrl+D wykryj, Ctrl+R render; `QShortcut` Spacja i strzałki/Home/End na osi; skróty w tooltipach; menu lub przycisk "..." dla ustawień i "O programie" | component-patterns.md §11; qt-pyside6.md §5, §8; F |
| 21 | Kolory markerów bez semantyki i legendy; czerwonawy "Do" sugeruje błąd | Oś czasu: "T0 37.6s" cyjan (góra), "Od 32.6s" zielony (dół), "Do 1:53" łososiowy (dół), "Start 0s" i "Koniec 2:25" szare tagi | P1 | T0 w `accent`, Od/Do w `info` z etykietami, Start/Koniec `text_muted` przerywane bez tagów (podziałka wystarcza) | design-tokens.md §Stany; component-patterns.md §8; C, K |
| 22 | Radio rozstrzelone, brak wizualnego związku opcji | "Źródło": "Tekst" ok. 105 px i "ID (API)" ok. 325 px od lewej | P2 | `SegmentedControl([("text", "Tekst"), ("id", "ID (API)")])`, `currentChanged` zamiast `rb_id.toggled` | component-patterns.md §4; qt-pyside6.md §4 (QCheckBox / QRadioButton); D |
| 23 | Nieopisowy przycisk "..." | "Wideo": przycisk "..." po prawej od pola ścieżki | P2 | `PathField(mode="open")` z ikoną folderu (SVG) i tooltipem "Wybierz plik wideo (Ctrl+O)" | component-patterns.md §6; design-tokens.md §Ikony; D |
| 24 | Ścieżka ucięta z lewej bez tooltipa | "Wideo": "enty/Media/20260624 PiRO/DJI_20260624185208_0029_D.MP4" | P2 | `PathField` (elipsa od lewej przez `QFontMetrics.elidedText`, tooltip z pełną ścieżką); nazwa pliku w tytule okna | component-patterns.md §6; qt-pyside6.md §4 (QLineEdit); B |
| 25 | Jedna etykieta dla dwóch pól bez oznaczenia, które jest które | "Przytnij od / do" (32,60 s, 112,60 s), "Offset X / Y" (32, 32), "Offset zegara X / Y" | P2 | `FormSection.add_pair_row` z krótkimi etykietami "Od", "Do" oraz "X", "Y" bezpośrednio przy polach | component-patterns.md §3; D |
| 26 | Wartość bez jednostki | "Rozmiar (skala): 0,80" | P2 | "80 %" (`QSlider` + `NumberField`) w UI; zapis nadal 0.80 | component-patterns.md §4; D |
| 27 | Spinbox dla identyfikatora; strzałki nie mają sensu dla ID z API | "ID: 163" ze strzałkami góra/dół | P2 | `QLineEdit` z `QIntValidator` (lub `NumberField(buttons=False)`); "Pobierz" `kind=primary`, "Pobierz i przytnij" secondary lub opcja "przytnij po pobraniu" | component-patterns.md §4, §7; D |
| 28 | Checkboxy wcięte inaczej niż etykiety pól; długa etykieta z technicznym nawiasem | "Włącz obramowanie", "Płynący czas od T0 (nad nakładką, od STARTU)" ok. 13 px w prawo od kolumny etykiet | P2 | Checkbox (lub `Switch`) w kolumnie kontrolek; etykieta "Pokaż płynący czas" + tooltip z wyjaśnieniem | component-patterns.md §3, §4; B |
| 29 | Czarne pasy letterbox po obu stronach klatki na jasnym UI | Podgląd: pasy ok. 200 px po lewej i prawej stronie klatki | P2 | Letterbox w `bg` (tło `PreviewLabel` z tokenu zamiast `setStyleSheet("background:#222;...")`); obszar podglądu dopasowany proporcjami do źródła | component-patterns.md §9; qt-pyside6.md §7 (PreviewLabel); I |
| 30 | Etykiety markerów mogą nachodzić na siebie przy zbliżeniu | "T0 37.6s" (góra) i "Od 32.6s" (dół) 5 s od siebie; brak reguły kolizji przy Od bliżej T0 | P2 | Rozkład etykiet w wierszach z unikaniem kolizji (`QFontMetrics.horizontalAdvance`), skracanie do samego symbolu przy braku miejsca | component-patterns.md §8; qt-pyside6.md §7; I |
| 31 | Wersja w tytule okna, brak nazwy pliku | Pasek tytułu: "Piro Overlay v0.21.2" | P2 | `setWindowTitle("DJI_20260624185208_0029_D.MP4 - Piro Overlay")` po wczytaniu pliku; wersja w "O programie" | H |
| 32 | Klasyczny pasek przewijania oddzielony od treści | Prawa krawędź inspektora: przerwa ok. 15 px między ramkami sekcji a paskiem | P2 | `QScrollBar` 8 px bez strzałek z QSS, przylegający do treści, `ScrollBarAsNeeded` | qt-pyside6.md §4 (QScrollBar), §5; A |
| 33 | Przycisk w miejscu wartości formularza | "Margines końcowy 5,00 s" i "Auto-przycięcie" w jednym wierszu | P2 | Przycisk secondary w wierszu akcji sekcji (`add_widget_row`), wyrównany do prawej | component-patterns.md §7; D |

## Podsumowanie wag

| Waga | Liczba | Numery | Co daje naprawa |
|---|---|---|---|
| P0 | 4 | 1, 2, 4, 5 | Użytkownik widzi, co robi aplikacja (transport, pasek stanu), wpisuje czas bez pomyłek, zawsze widzi akcję główną |
| P1 | 17 | 3, 6-21 | Widoczny postęp i anulowanie; nowoczesny, spójny wygląd (sekcje, motyw, fonty, wyrównanie), czytelna oś czasu, poprawna lokalizacja |
| P2 | 12 | 22-33 | Polish: ikony, etykiety, jednostki, tooltipy, letterbox, tytuł okna |

Szybkie wygrane (mały koszt, duży efekt, bez zmian logiki): 7 i 10 (`apply_theme`: motyw dark, paleta, QSS, fonty w jednym kroku), 6 (QSS dla `QGroupBox` bez ramki), 8 (jedna kolumna etykiet), 11 ("bottom-left" -> `addItem(tr(key), key)`), 31 (tytuł okna), 23 (ikona folderu). Można je zrobić w pierwszej iteracji planu poniżej.

Pozycje oznaczone pierwotnie "do potwierdzenia" po wglądzie w kod: 3 obniżone do P1 (workery `QThread` są, brakuje feedbacku), 5 zostaje P0 ("Renderuj" na dole przewijanego inspektora), 20 potwierdzone jako P1 (brak `QToolBar`/`QAction`), 19 nadal do sprawdzenia w działającej aplikacji.

## Kierunek redesignu

### Proponowany układ

Zasada: lewy inspektor z nagłówkami sekcji (bez ramek), prawa strona jako obszar roboczy (podgląd, transport, oś czasu), akcje globalne w pasku narzędzi, komunikaty w pasku stanu. Układ w 100 % DPI, okno 1600x900 lub większe.

```
+------------------------------------------------------------------------------------+
| DJI_20260624185208_0029_D.MP4 - Piro Overlay                              _  []  X |
+------------------------------------------------------------------------------------+
| [Otwórz wideo] [Pobierz dane]                        [Motyw] [...]   [ Renderuj ]  |  pasek narzędzi
+----------------------------------+-------------------------------------------------+
| WEJŚCIE                          |                                                 |
| Wideo     [DJI_..._0029_D.MP4][o]|                                                 |
| Źródło    [ Tekst | ID (API) ]   |            PODGLĄD (letterbox w bg)             |
| ID        [163   ] [Pobierz]     |                 [ START ]                       |
|           Tor 1 #2 . Bartek      |                                                 |
| > Strzały (13)  7.82-26.14 s     |                                                 |
|                                  +-------------------------------------------------+
| SYNCHRONIZACJA                   | [|<] [<] [Play] [>] [>|]  0:37.6 / 2:25  [Przesuwaj]|  transport
| Typ kotwicy  [Sygnał startu  v]  +-------------------------------------------------+
| T0           [0:37.60] [Wykryj]  | 0:00      0:30      1:00      1:30      2:00 [-][+]|
|              Następny kandydat   | ~~~~~~~ fala ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ |
| Przytnij  Od [0:32.60] Do [1:52.60]|    |Od   |T0                     |Do      |  |  markery
| Margines     [5.0 s]             |         ^ playhead                              |
|              Auto-przycięcie     +-------------------------------------------------+
|                                  |
| WYGLĄD NAKŁADKI                  |
| Język        [Polski         v]  |
| Rozmiar      [====o====] 80 %    |
| Pozycja      [Lewy dolny     v]  |
| Offset    X  [32  ]  Y  [32  ]   |
| Tło          [#] #000000  67 %   |
| Tekst        [#] #FFFFFF 100 %   |
| Akcent       [#] #FFC400 100 %   |
| [x] Obramowanie  #FFFFFF 86 %  3 px |
| [ ] Płynący czas   Pozycja [Nad nakładką v] |
+----------------------------------+-------------------------------------------------+
| (i) Pobrano dane: Tor 1 #2, Bartek                              [==========] 100 % |  pasek stanu
+------------------------------------------------------------------------------------+
```

Jeśli inspektor nadal nie mieści się w 900 px wysokości: sekcje zwijane (`FormSection(collapsible=True)` z chevronem) lub `QTabWidget` (Tk: `ttk.Notebook`) z zakładkami "Wejście i synchronizacja" / "Wygląd". Zakładki dopiero wtedy, gdy zwijanie nie wystarcza, bo ukrywają kontekst.

### Zamiany kontrolek

Odpowiedniki Qt (aplikacja jest w PySide6) podane jako pierwsze; kolumna Tk dla aplikacji Tkinter korzystających z tego raportu jako wzoru. Klasy Qt pochodzą z `scripts/qt_widgets.py`, właściwości `kind`/`role`/`invalid` z arkusza w `scripts/qt_theme.py`.

| Dziś (w kodzie) | Docelowo Qt | Odpowiednik Tk | Uwagi |
|---|---|---|---|
| `QGroupBox("Wejście")` itd. | krok 1: reguła QSS bez ramki z `build_qss` (qt-pyside6.md §4); krok 2: `FormSection(title, collapsible=True)` z nagłówkiem `SectionHeader` (`role=section`) | `SectionHeader` + `FormGrid` | zawartość sekcji bez zmian |
| `QRadioButton` "Tekst" / "ID (API)" | `SegmentedControl([("text", "Tekst"), ("id", "ID (API)")])`, sygnał `currentChanged` zamiast `toggled`, `set_label` przy zmianie języka (qt-pyside6.md §4) | `SegmentedControl` z tą samą zmienną Tk | klucze stabilne, etykiety z `_STRINGS` |
| `ColorButton((r, g, b, a))` z tekstem "RGBA ..." | `ColorSwatchButton(rgba)`: ten sam konstruktor, `rgba()`, sygnał `changed`; siedem wywołań zamienia się jeden do jednego (qt-pyside6.md §7) | `ColorSwatchButton(parent, variable)` | zapis RGBA 0-255 bez zmian |
| `QDoubleSpinBox` czasu "37,60 s" | istniejący spinbox z `setSuffix(" s")`, `setAlignment(Qt.AlignRight)`, `setKeyboardTracking(False)`, `setLocale(QLocale.Polish)` lub `NumberField(0, dur, 0.05, 2, " s", value, QLocale(QLocale.Polish))` (qt-pyside6.md §4) | `NumberField(unit="s", decimal_comma=True)` | wartość float sekund bez zmian |
| "Przytnij od / do" dwa spinboxy | `FormSection.add_pair_row("Przytnij", od, do)` z walidacją od <= do przy `editingFinished` i `InlineMessage` | `FormGrid` z dwoma polami | |
| "Wykryj kotwice" / "Następny kandydat" / "Wykryj sygnał startu" | jeden `kind=primary` "Wykryj" zależny od "Typ kotwicy" + `kind=ghost` "Następny kandydat" z licznikiem; `set_busy` w trakcie (qt-pyside6.md §4, §8) | `Accent.TButton` + `Ghost.TButton` | logika wykrywania bez zmian |
| `QPlainTextEdit` "Oś czasu" z listą strzałów | `role=mono` + podsumowanie w `role=muted`; opcjonalnie zwijany `QTableView` (#, czas, odstęp) | `font_mono` + Treeview | dane te same |
| Przycisk "..." przy ścieżce | `PathField(mode="open", filter="Wideo (*.mp4 *.mov *.mkv)")` z ikoną i tooltipem; elipsa od lewej, drag and drop (qt-pyside6.md §4) | `PathField` | |
| `pos_combo.addItems(list(ANCHOR_POSITIONS))` "bottom-left" | pętla `addItem(tr(key), key)` + `currentData()` (qt-pyside6.md §4) | Combobox z mapą etykieta -> klucz | klucz `bottom-left` zapisywany bez zmian |
| "Rozmiar (skala) 0,80" | `QSlider` + `NumberField` "80 %" | Scale + `NumberField` | zapis 0.80 |
| Pasek "Edytuj pozycje (przeciąganie)" | `QToolButton.setCheckable(True)` z ikoną w pasku transportu, stan `:checked` z QSS (qt-pyside6.md §5) | Toolbutton | Escape wychodzi z trybu |
| ok. 19 `setStyleSheet` z kolorami | `setProperty("role", ...)` / `setProperty("kind", ...)` + `repolish`; jeden `app.setStyleSheet` w `apply_theme` (qt-pyside6.md §3, §4, §10) | style ttk z tokenów | docelowo `grep -c setStyleSheet gui.py` == 0 |
| `statusBar().showMessage(text)` | `status_message(statusbar, text, kind, timeout_ms)` + `QProgressBar` jako `addPermanentWidget` | `StatusBar.set(text, kind, ms)` | kolor stanu z tokenów |
| `WaveformWidget` z `QColor(...)` na sztywno | ten sam widżet, kolory przez `current_tokens(app)`, cache fali w `QPixmap`, etykiety bez kolizji, fokus (qt-pyside6.md §7) | Canvas z tokenami | interakcje bez zmian |
| brak | pasek transportu (`QToolBar` z `QAction`), playhead i zoom w `WaveformWidget`, `QSettings` dla geometrii okna i splittera | `Ghost.TButton` + Canvas | nowe komponenty widoku, bez zmian w modelu |

### Plan w iteracjach

Każda iteracja kończy się zrzutami z interpretera Windows (`QT_QPA_PLATFORM=offscreen`, `QT_QPA_FONTDIR=C:\Windows\Fonts`, `QT_SCALE_FACTOR=1.5` dla testu HiDPI) w PL i EN, dark (i light), porównanymi ze zrzutem odniesienia z `pictures/`, testami `PYTHONPATH=src pytest` i bumpem wersji MINOR. Kolejność zgodna z checklistą wdrożenia w `qt-pyside6.md` §10. Odpowiedniki Tk w nawiasach dla aplikacji Tkinter.

1. **Fundament (bez zmian układu).** Skopiować `scripts/qt_theme.py` jako `src/piro_overlay/ui_theme.py`; w `main()`: `setup_hidpi()` przed `QApplication`, `apply_theme(app, mode)` przed `MainWindow()`, `set_windows_dark_titlebar(win, dark)` po `show()`, `QSettings` + `save_window_state`/`restore_window_state` dla okna i splittera. Reguła QSS dla `QGroupBox` bez ramki działa od razu. (Tk: `enable_hidpi()` przed `Tk()`, `apply_theme(root, mode)` z `theme_template.py`, nazwane fonty, `set_windows_dark_titlebar`.) Test: całe okno w jednej estetyce, nic się nie rozjechało, ustawienia wczytują się jak wcześniej; `tests/test_syntax.py` widzi nowy moduł.
2. **Layout i sekcje.** Skopiować `scripts/qt_widgets.py` jako `ui_widgets.py`; `setStyleSheet` -> `role`/`kind`; `QToolBar` z `QAction` (Otwórz, Wykryj, Renderuj) ze skrótami; `QGroupBox` -> `FormSection` sekcja po sekcji; `QLabel.setMinimumWidth` dla jednej kolumny etykiet; `setChildrenCollapsible(False)` i `setMinimumSize(960, 600)`. (Tk: `SectionHeader` + `FormGrid`, `PanedWindow`, `StatusBar`.) Test: Tab w kolejności wizualnej, resize od minimum do pełnego ekranu, EN nie ucina etykiet, `grep -c setStyleSheet gui.py` == 0.
3. **Komponenty.** `ColorButton` -> `ColorSwatchButton`; radio -> `SegmentedControl`; `pos_combo` z `userData`; spinboxy z sufiksem, locale i zakresem z długości nagrania lub `NumberField`; `PathField` dla ścieżki wideo. (Tk: te same klasy z `widgets.py`.) Test: siedem próbek pokazuje kolor i alfę, `rgba()` daje te same krotki; plik ustawień po sesji identyczny z plikiem sprzed zmian.
4. **Stany i feedback.** `set_busy` na przyciskach detekcji i renderu, `QProgressBar.setRange(0, 0)` w pasku stanu, przycisk "Anuluj", `status_message` z kolorem stanu, `InlineMessage` dla walidacji od <= do, stan pusty w podglądzie. (Tk: `StatusBar.set`, `InlineMessage.show`, `Progressbar`.) Test: podczas "Pobierz" i "Wykryj" okno da się przesuwać, postęp widoczny, anulowanie działa, błąd mówi co zrobić.
5. **Oś czasu, podgląd, polish.** `WaveformWidget`: kolory z tokenów, cache fali, etykiety bez kolizji, playhead, fokus i klawiatura; `PreviewLabel`: letterbox w `bg`, uchwyty w trybie edycji; ikony SVG, tooltipy ze skrótami, tytuł okna z nazwą pliku. (Tk: Canvas z tokenami, `bind_mousewheel`.) Test: zrzut z kotwicą, zakresem i podglądem naraz; dark i light; 100/150/200 %; podgląd zgodny z klatką renderu.

### Czego NIE zmieniamy

- Logiki biznesowej: wykrywanie sygnału startu, kandydatów, auto-przycięcie, pobieranie z API, render nakładki.
- Nazw i formatu ustawień: klucze, typy (float sekund, RGBA 0-255, klucz pozycji `bottom-left`), lokalizacja pliku; konwersje do hex/%/`m:ss.d` żyją tylko w warstwie widoku.
- Istniejących skrótów klawiszowych (jeśli są): nowe skróty dodajemy, starych nie usuwamy bez zgody.
- Tekstów i18n poza poprawkami błędów: usunięcie angielskiej wartości "bottom-left" z widoku i ujednolicenie terminu T0 to poprawki; przeredagowanie całego słownika to osobne zadanie.
- Zachowania nakładki w renderze: podgląd ma odpowiadać wynikowi, nie odwrotnie.
- Kluczy `_STRINGS` w `i18n.py` ani kluczy i plików ustawień z `config.py`; nowe teksty tylko jako nowe klucze w PL i EN.
- `WheelGuard` i workerów `QThread` (`RenderWorker`, `FrameExtractWorker`, `WaveformWorker`, `StartDetectWorker`, `BatchPrepWorker`, `UpdateChecker`): UI podłącza się do istniejących sygnałów.
- Interakcji `WaveformWidget` (klik = kotwica ze snapem, Ctrl+klik = podgląd, przeciąganie uchwytów, zoom kółkiem, pan prawym przyciskiem): zmienia się tylko rysowanie.

### Weryfikacja po wdrożeniu (checklista akceptacji)

- [ ] Zrzuty przed/po przy 100 % i 125 % DPI, PL i EN: nic nie jest ucięte, kolumny wyrównane, fonty ostre.
- [ ] Plik ustawień zapisany po redesignie porównany z plikiem sprzed redesignu (`diff`): te same klucze i typy, różnice tylko w wartościach zmienionych świadomie.
- [ ] Wszystkie wartości czasu na ekranie w jednym formacie; wpisanie "37,6", "37.6" i "0:37.6" daje ten sam wynik.
- [ ] Podczas "Pobierz" i "Wykryj" okno da się przesuwać, pasek stanu pokazuje postęp, przycisk anulowania działa.
- [ ] Tab przechodzi przez inspektor w kolejności wizualnej; fokus widoczny na każdej kontrolce, także na Canvas osi czasu.
- [ ] Spacja odtwarza/pauzuje, klik na osi ustawia czas, przeciąganie markera jest płynne i snapuje do detekcji.
- [ ] Podgląd nakładki zgodny z klatką wyrenderowanego pliku (pozycja, skala, kolory, alfa).
- [ ] `PYTHONPATH=src pytest` zielone (w tym `test_syntax.py` dla `ui_theme.py`, `ui_widgets.py`, `gui.py` oraz `test_i18n.py` dla nowych kluczy); wersja podbita w `__init__.py` i `pyproject.toml`.
- [ ] `grep -n "setStyleSheet\|QColor(" src/piro_overlay/gui.py` zwraca tylko miejsca celowe (dane użytkownika, nakładka), nie kolory UI.
- [ ] Zrzuty offscreen przy `QT_SCALE_FACTOR=1.25`, `1.5`, `2`: fonty ostre, nic nie ucięte w inspektorze.
