---
name: python-desktop-ux
description: >-
  Odświeżanie i projektowanie UX/UI desktopowych aplikacji Python: PySide6/PyQt6, Tkinter/ttk, CustomTkinter, ttkbootstrap. Prowadzi przez audyt istniejącego GUI (checklista A-K, raport z wagami P0-P2), tokeny projektowe (paleta neutralna z jednym akcentem, siatka 4/8 px, fonty, stany), motyw ciemny i jasny (QPalette + QSS albo ttk.Style na bazie clam), layout inspektor + podgląd, dobór kontrolek, stany i feedback, HiDPI 100-200 %, klawiaturę i fokus, oś czasu i podgląd wideo; daje gotowe skrypty motywu i widżetów. Używaj, gdy użytkownik mówi, że aplikacja "trąci myszką", "wygląda staro/przestarzale", prosi "odśwież UI/GUI", chce "nowoczesny wygląd" lub "motyw ciemny", pyta o "layout/układ okna", "QSS/QPalette", "ttk style", zamawia "audyt UX", "zaprojektuj panel/dialog/okno" albo prosi "popraw czytelność/odstępy/typografię" w aplikacji desktopowej w Pythonie. Nie dotyczy stron WWW (do tego skill frontend-design).
---

# python-desktop-ux

Skill do odświeżania i projektowania UX/UI desktopowych aplikacji w Pythonie. Prowadzi od audytu przez tokeny i plan iteracji do implementacji i weryfikacji zrzutami. Ten plik jest mapą i procedurą; szczegóły są w `references/`, gotowy kod w `scripts/`.

## Kiedy używać i czego ten skill nie robi

Używaj, gdy:

- użytkownik ocenia istniejące GUI ("trąci myszką", "wygląda staro", "przestarzałe", "jak Windows 7") i chce je odświeżyć,
- prosi o motyw ciemny/jasny, nowy układ okna, poprawę czytelności, odstępów, typografii lub hierarchii przycisków,
- pyta, jak coś ostylować w QSS/QPalette albo `ttk.Style`,
- zamawia audyt UX lub projekt nowego panelu, dialogu, okna (także od zera),
- aplikacja to narzędzie z podglądem wideo/audio i osią czasu (wzorce w `component-patterns.md` §8, §9).

Obsługiwane frameworki: PySide6/PyQt6 (przewodnik `qt-pyside6.md`, skrypty `qt_theme.py` i `qt_widgets.py`), Tkinter/ttk (przewodnik `tkinter-ttk.md`, skrypty `theme_template.py` i `widgets.py`), CustomTkinter, ttkbootstrap, sv-ttk (decyzje w `migration-options.md`). Wzorce i tokeny są neutralne, więc pomagają też przy wx, Flet czy DearPyGui, ale bez gotowych skryptów.

Czego skill nie robi:

- nie zmienia logiki domenowej ani formatu zapisywanych ustawień; dotyka wyłącznie warstwy prezentacji,
- nie projektuje stron ani aplikacji WWW (do tego skill `frontend-design`),
- nie wybiera frameworka za użytkownika przy nowej aplikacji bez rozmowy o wymaganiach (`migration-options.md` §3 daje regułę, decyzję podejmuje użytkownik),
- nie buduje paczek .exe w trakcie prac nad UI.

## Zasady nadrzędne

Sześć twardych zasad; każda rekomendacja i każdy commit musi je spełniać.

1. **Bez zmian logiki i formatu ustawień.** Konwersje (RGBA <-> hex, sekundy <-> `m:ss.d`, klucz `bottom-left` <-> etykieta) żyją w warstwie widoku. Test: plik ustawień zapisany po zmianie ma te same klucze i typy co przed (`diff`).
2. **Przyrostowo, ze zrzutem po każdym kroku.** Jeden krok = jedna zmiana widoczna na ekranie + zrzut przed/po w tym samym rozmiarze okna. Bez zrzutu nie ma kolejnego kroku.
3. **i18n PL/EN zachowane.** Każdy nowy tekst przechodzi przez istniejący mechanizm tłumaczeń aplikacji i jest dodany w obu językach w tym samym commicie. Wartości list też są tłumaczone: klucz techniczny zapisywany, etykieta pokazywana.
4. **HiDPI 100/125/150/200 %.** Rozmiary w pikselach logicznych (Qt) lub przez `px()` (Tk), fonty w punktach, ikony SVG lub glify fontowe. Zrzuty przy 100 % i co najmniej jednym skalowaniu ułamkowym.
5. **Klawiatura i fokus.** Tab w kolejności wizualnej, widoczny pierścień fokusu na każdej kontrolce (także własnej), Enter/Escape w dialogach, skróty w tooltipach.
6. **UI nie zamiera.** Długie operacje w wątku (Qt: `QThread` + sygnały; Tk: `threading` + `queue` + `after`), przycisk w stanie busy, pasek postępu, anulowanie. Nigdy `processEvents()` ani `update()` w pętli roboczej.

### Zasady projektu Piro Overlay

Aktywne, gdy w repozytorium istnieje `src/piro_overlay` (sprawdź `ls src/piro_overlay/gui.py`). Uzupełniają zasady nadrzędne o wymogi z `CLAUDE.md` i `AGENTS.md` tego repo:

- Separacja warstw: moduły domenowe (`models`, `parser`, `api`, `i18n`, `audio_sync`, `overlay`, `render`, `ffmpeg`, `resources`, `pipeline`, `preview`) nie importują PySide6. Kod UI tylko w `gui.py` i w nowych modułach UI obok niego (`ui_theme.py`, `ui_widgets.py`).
- i18n przez `i18n.Translator` i `_STRINGS`: każdy klucz ma PL i EN, `tests/test_i18n.py` to sprawdza. Część tekstów GUI jest dziś wpisana w `gui.py` po polsku na sztywno; przed dodaniem nowego klucza sprawdź, czy tekst już istnieje.
- Każda zmiana funkcjonalna = bump wersji w `src/piro_overlay/__init__.py` i `pyproject.toml` (odświeżenie UI: MINOR po każdej iteracji).
- WSL nie ma PySide6: `PYTHONPATH=src pytest tests/test_syntax.py` kompiluje moduły przez `py_compile` (nowe pliki `ui_*.py` wchodzą do testu automatycznie); pełne testy `PYTHONPATH=src pytest`.
- GUI i zrzuty uruchamiaj interpreterem Windows z katalogu repo: `./.venv-win/Scripts/python.exe "$(wslpath -w src/piro_overlay/gui.py)"`; ścieżki argumentów przez `wslpath -w`; bezgłowo z `QT_QPA_PLATFORM=offscreen` i `QT_QPA_FONTDIR=C:\Windows\Fonts`.
- `WheelGuard` (filtr kółka nad spinboxami w `QScrollArea`) zostaje; nowe `NumberField.spin` też mu podlega.
- Nie ruszaj kluczy ustawień z `config.py` (`last_style.json`, `ui_settings.json`, `file_settings.json`, `last_dirs.json`, `render_queue.json`); geometria okna to nowa przestrzeń `QSettings`.
- Nie buduj .exe podczas prac; nie używaj `git push --force` ani `git reset --hard`. Zrzuty "przed" są w `pictures/*.png`.

## Przebieg pracy

### Krok 0. Rozpoznanie

Wykryj framework i stan UI, zanim cokolwiek zaproponujesz:

```bash
# framework (Qt i Tk równorzędnie)
grep -rln "PySide6\|PyQt6\|PyQt5" --include=*.py .
grep -rln "import tkinter\|from tkinter\|customtkinter\|ttkbootstrap\|sv_ttk" --include=*.py .
grep -rln "import wx\|import flet\|dearpygui" --include=*.py .
# stan UI w Qt
grep -rn "setStyle(\|setPalette\|setStyleSheet\|QSettings\|HighDpi\|QGroupBox(\"\|QToolBar\|dwmapi" --include=*.py .
# stan UI w Tk
grep -rn "theme_use\|LabelFrame\|SetProcessDpiAwareness\|tk.call(\"tk\", \"scaling\"\|option_add\|font=(" --include=*.py .
```

| Wykryty framework | Czytaj | Skrypty |
|---|---|---|
| PySide6 / PyQt6 | `qt-pyside6.md` (§1 diagnoza, §2 fundament, §4 receptury), `component-patterns.md`, `design-tokens.md`, `migration-options.md` §3.1 | `scripts/qt_theme.py`, `scripts/qt_widgets.py` |
| Tkinter / ttk | `tkinter-ttk.md` (§1, §2, §4), `component-patterns.md`, `design-tokens.md`, `migration-options.md` §3 | `scripts/theme_template.py`, `scripts/widgets.py` |
| CustomTkinter / ttkbootstrap / sv-ttk | `migration-options.md` §2.2-2.4 (zostań w bibliotece, popraw jej motyw), `design-tokens.md`, `component-patterns.md` | tokeny jako wartości do motywu biblioteki |
| wx / Flet / DearPyGui | `component-patterns.md` i `design-tokens.md` (neutralne), `migration-options.md` §2.6-2.7 | brak gotowych skryptów; powiedz to użytkownikowi |

Ustal też (pytaj, jeśli nie wynika z repo): jak uruchomić aplikację i zrobić zrzut (headless? osobny interpreter?), mechanizm i18n, gdzie i w jakim formacie są ustawienia, jak działają wątki, jakie testy istnieją i jak je odpalić, czy repo wymaga wersjonowania zmian.

### Krok 1. Audyt

- Przejdź `references/audit-checklist.md` (grupy A-K). Każdy problem = jeden wiersz tabeli z dowodem (nazwa sekcji lub kontrolki z ekranu), wagą P0/P1/P2, rekomendacją weryfikowalną zrzutem i odwołaniem do pliku i sekcji skilla.
- Format raportu: szablon na końcu checklisty; wzór kompletnego raportu z potwierdzeniem faktów z kodu: `references/audit-example-piro-overlay.md`.
- Zrzut "przed": jeśli aplikacja ma tryb headless screenshot, zrób go teraz w domyślnym rozmiarze okna; jeśli nie ma, poproś użytkownika o zrzut albo dodaj tymczasową flagę `--screenshot` (wzorzec w `qt-pyside6.md` §10 lub `migration-options.md` §4 pkt 7).
- Czego nie da się stwierdzić ze zrzutu ani z kodu, oznacz "do potwierdzenia" i napisz, jak sprawdzić.

### Krok 2. Kierunek i tokeny

- Paleta, odstępy, fonty i stany są gotowe w `references/design-tokens.md`; blok Python na końcu to źródło prawdy, skrypty mają identyczne wartości. Jeśli aplikacja ma własny kolor marki, podmień `accent`, `accent_hover`, `accent_pressed`, `accent_text` i policz kontrast (tekst 4.5:1, elementy UI 3:1) osobno dla DARK i LIGHT; jasny akcent w jasnym motywie zwykle wymaga ciemniejszej odmiany (sekcja "Dlaczego akcent w LIGHT nie jest żółty").
- Decyzja odświeżenie vs migracja: `references/migration-options.md` §3 (drzewo decyzyjne); dla aplikacji już w PySide6 sekcja 3.1 (warianty A/B/C; domyślnie A: Fusion + QPalette + QSS + kilka własnych widżetów).
- Zapytaj użytkownika tylko, gdy warianty różnią się istotnie nakładem lub ryzykiem (np. A vs C w §3.1, opcja 1 vs 5 w macierzy). Gdy różnica jest kosmetyczna, wybierz wariant o najniższym ryzyku regresji i powiedz, dlaczego.

### Krok 3. Plan w iteracjach

Plan zapisz w odpowiedzi (lub w pliku planu repo, jeśli taki istnieje). Każda iteracja ma kryterium akceptacji, kończy się zrzutem i testami; w repo z wymogiem wersjonowania także bumpem wersji.

| Iteracja | Zakres | Kryterium akceptacji |
|---|---|---|
| I. Fundament | polityka HiDPI, styl bazowy (Fusion / clam), paleta i QSS lub `ttk.Style` z tokenów, fonty nazwane, ciemny pasek tytułu, geometria okna (min. rozmiar, zapis/odczyt) | całe okno w jednej estetyce, nic się nie rozjechało, ustawienia wczytują się jak wcześniej; zrzut 100 % i 150 % |
| II. Layout i sekcje | nagłówki sekcji zamiast ramek, jedna kolumna etykiet, formularze z jednostkami, splitter inspektor/obszar roboczy, pasek akcji z jednym primary | Tab w kolejności wizualnej, resize od minimum do pełnego ekranu, EN nie ucina etykiet |
| III. Komponenty | swatch koloru, segmenty zamiast radio, pola liczbowe z jednostką i locale, pole ścieżki z elipsą, przełączniki | wartości w pliku ustawień identyczne jak przed; każda kontrolka obsługuje klawiaturę |
| IV. Stany i feedback | busy na przyciskach, walidacja inline, komunikaty trzyczęściowe, pasek stanu z kolorem stanu i postępem, stany puste | podczas długiej operacji okno da się przesuwać, anulowanie działa, błąd mówi co zrobić |
| V. Oś czasu, podgląd, polish | kolory z tokenów w rysowaniu własnym, cache, etykiety bez kolizji, playhead i zoom, letterbox w `bg`, ikony, tooltipy ze skrótami | zrzut z markerami i zakresem naraz; dark i light; 100/150/200 % |

Nie łącz iteracji w jeden commit. Jeśli użytkownik chce "tylko motyw ciemny", zrób I i zatrzymaj się.

### Krok 4. Implementacja

Wprowadzenie skryptów do projektu:

| Framework | Skopiuj | Jako | Popraw |
|---|---|---|---|
| Qt | `scripts/qt_theme.py` | `src/<pakiet>/ui_theme.py` | nic (moduł samodzielny) |
| Qt | `scripts/qt_widgets.py` | `src/<pakiet>/ui_widgets.py` | `from qt_theme import ...` -> `from .ui_theme import ...` |
| Tk | `scripts/theme_template.py` | `<pakiet>/ui_theme.py` | nic |
| Tk | `scripts/widgets.py` | `<pakiet>/ui_widgets.py` | `from theme_template import ...` -> `from .ui_theme import ...` |

Skrypty są wyłącznie warstwą UI (importują Qt lub Tk), więc w repo z separacją warstw leżą obok `gui.py`, nie w modułach domenowych. Z kopii usuń sekcje demo (`_build_demo`, `_build_gallery`, `_main`) albo zostaw je jako narzędzie do zrzutów.

Kolejność w kodzie dla Qt (Tk analogicznie wg `tkinter-ttk.md` §2 i listy kontrolnej w §10):

1. `main()`: `setup_hidpi()` przed `QApplication`, `apply_theme(app, mode)` przed tworzeniem okien, `set_windows_dark_titlebar(win, dark)` po `win.show()`, `QSettings` + `save_window_state`/`restore_window_state` (`qt-pyside6.md` §2).
2. Rozproszone `setStyleSheet` z kolorami -> właściwości: `label.setProperty("role", "muted")`, `btn.setProperty("kind", "primary")`, `edit.setProperty("invalid", "true")` + `repolish` (helpery `set_role`, `set_kind` w `qt_widgets.py`); reguły `[role=...]` i `[kind=...]` już są w `build_qss`. Cel: `grep -c setStyleSheet` == 0 poza `app.setStyleSheet` w `ui_theme.py` (`qt-pyside6.md` §3, §4, §10).
3. `QGroupBox("Tytuł")` -> najpierw reguła QSS bez ramki (zero zmian w kodzie), potem sekcja po sekcji `FormSection("Tytuł", collapsible=True)` z `add_row(label, field, unit, help_text)` i `add_pair_row` (`qt-pyside6.md` §4; `component-patterns.md` §2, §3).
4. `ColorButton(rgba)` -> `ColorSwatchButton(rgba)`: ten sam konstruktor, `rgba()` i sygnał `changed`, zamiana jeden do jednego (`qt-pyside6.md` §7; `component-patterns.md` §5).
5. Para `QRadioButton` -> `SegmentedControl([(klucz, etykieta)])`; `QComboBox.addItems(klucze)` -> `addItem(tr(klucz), klucz)` + `currentData()` (`component-patterns.md` §4, §12).
6. Rysowanie własne (`paintEvent`): kolory przez `current_tokens(app)`, cache w `QPixmap` z `setDevicePixelRatio`, fokus i klawiatura (`qt-pyside6.md` §7; `component-patterns.md` §8, §9).
7. Feedback: `set_busy(btn, True, "Wykrywanie...")`, `QProgressBar.setRange(0, 0)`, `status_message(statusbar, text, kind, ms)`, `InlineMessage.show_message(text, kind)` (`component-patterns.md` §10; `qt-pyside6.md` §8, §9).

Odpowiedniki Tk: `enable_hidpi()` przed `Tk()`, `apply_theme(root, mode)`, `SectionHeader` + `FormGrid` zamiast `LabelFrame`, `ColorSwatchButton(parent, variable)`, `NumberField`, `PathField`, `StatusBar.set`, `InlineMessage.show` (`tkinter-ttk.md` §2, §4, §5, §10).

Po każdym kroku: zrzut, testy, commit z opisem "co widać inaczej".

### Krok 5. Weryfikacja

Checklista przed oddaniem iteracji:

- [ ] `python -m py_compile` na zmienionych plikach (gdy środowisko nie ma Qt/Tk) lub pełne testy projektu (`PYTHONPATH=src pytest`).
- [ ] Zrzuty przed/po w tym samym rozmiarze okna, ten sam plik wejściowy i ustawienia; DPI 100 %, 150 %, 200 % (Qt: `QT_SCALE_FACTOR=1.5` wyłącznie do testu).
- [ ] Oba motywy (dark/light) i oba języki (PL/EN); żaden tekst nie jest ucięty, kolumny wyrównane, polskie znaki renderują się.
- [ ] Tab przechodzi przez cały panel w kolejności wizualnej; skróty działają; Enter/Escape w dialogach.
- [ ] Resize od minimalnego rozmiaru do pełnego ekranu: rozciąga się podgląd/oś, nie inspektor.
- [ ] Długa operacja: okno reaguje, postęp widoczny, anulowanie działa.
- [ ] Brak kolorów na sztywno: `grep -rn "setStyleSheet\|#[0-9A-Fa-f]\{6\}" src/<pakiet>/gui.py` (Qt) albo `grep -rn "bg=\|fg=\|#[0-9A-Fa-f]\{6\}"` (Tk) zwraca tylko miejsca celowe (moduł motywu, dane użytkownika).
- [ ] Plik ustawień po sesji: te same klucze i typy (`diff`).
- [ ] Repo z wersjonowaniem: bump wersji, testy i18n zielone.

Zrzut bezgłowy z WSL przez interpreter Windows (skrypty skilla ustawiają `QT_QPA_PLATFORM=offscreen` i `QT_QPA_FONTDIR` same w trybie `--screenshot`; dla aplikacji ustaw zmienne jawnie):

```bash
PY="/mnt/c/<sciezka>/.venv-win/Scripts/python.exe"          # interpreter Windows z PySide6
"$PY" "$(wslpath -w scripts/qt_widgets.py)" --screenshot "$(wslpath -w out/widgets_dark.png)"   # + _full.png
"$PY" "$(wslpath -w scripts/qt_widgets.py)" --light --screenshot "$(wslpath -w out/widgets_light.png)"
"$PY" "$(wslpath -w scripts/qt_theme.py)" --screenshot "$(wslpath -w out/gallery.png)"           # + _sections.png
QT_QPA_PLATFORM=offscreen QT_QPA_FONTDIR='C:\Windows\Fonts' QT_SCALE_FACTOR=1.5 \
  "$PY" "$(wslpath -w src/<pakiet>/gui.py)" --screenshot "$(wslpath -w out/app_150.png)"      # flaga dodana w main()
```

Tk nie ma trybu offscreen: zrzut przez `PIL.ImageGrab.grab(bbox)` po `update_idletasks()` na widocznym oknie (`migration-options.md` §4 pkt 7).

Porównanie: otwórz oba zrzuty (Read) i sprawdź te same elementy w tej samej kolejności: nagłówki sekcji, kolumnę etykiet, szerokości pól, kolory stanów, polskie znaki, fokus. Różnice pikselowe oceniaj wzrokiem; próg pikselowy ma sens tylko dla "nic nie miało się zmienić" (np. podgląd wideo po zmianie motywu).

## Mapa plików

| Plik | Kiedy czytać | Co zawiera | Linie |
|---|---|---|---|
| `references/audit-checklist.md` | Krok 1, zawsze | grupy A-K (layout, typografia, kolor, kontrolki, stany, klawiatura, ikony, okno, media, wydajność, dostępność); każdy punkt z "Jak sprawdzić" (grep dla Qt i Tk) i "Naprawa" z odwołaniem do obu przewodników; szablon raportu; reguły wag | ok. 320 |
| `references/audit-example-piro-overlay.md` | Krok 1 jako wzór raportu; zawsze w repo Piro | potwierdzenie faktów z kodu (PySide6, klasy, brak palety/QSS/HiDPI), 33 problemy z dowodami i wagami, wireframe, tabela zamian kontrolek Qt-first, plan w 5 iteracjach, czego nie zmieniamy, checklista akceptacji | ok. 180 |
| `references/design-tokens.md` | Krok 2 i przy każdej decyzji o kolorze, odstępie, foncie | palety DARK/LIGHT z policzonym kontrastem, mapowanie tokenów na role, skala odstępów, fonty, promienie, tabela stanów, glify ikon, blok Python (źródło prawdy) | ok. 370 |
| `references/component-patterns.md` | Kroki 3-4, przy projektowaniu każdego elementu | §1-§14: układ, sekcje, formularze, dobór kontrolki, kolor z alfą, ścieżka, przyciski, oś czasu, podgląd, feedback, klawiatura, i18n, motywy, Fluent; każdy wzorzec z implementacją Qt (pierwszą) i Tk | ok. 455 |
| `references/migration-options.md` | Krok 2, gdy framework lub głębokość zmian jest do ustalenia | macierz 7 opcji (ttk + motyw, sv-ttk, ttkbootstrap, CustomTkinter, Qt, Flet, DearPyGui), drzewo decyzyjne, §3.1 warianty A/B/C dla aplikacji już w Qt, playbook strangler, szacunki nakładu | ok. 150 |
| `references/qt-pyside6.md` | Kroki 4-5 dla Qt | §1 diagnoza grepem, §2 `main()`, §3 QSS (selektory, właściwości dynamiczne, pułapki), §4 receptury per widżet, §5 layout, §6 Windows (pasek tytułu, HiDPI, fonty), §7 rysowanie własne, §8 interakcje, §9 wątki, §10 pułapki, PyInstaller, praca WSL+Windows, checklista wdrożenia; numery linii dotyczą `gui.py` Piro v0.43.0 | ok. 510 |
| `references/tkinter-ttk.md` | Kroki 4-5 dla Tk | §1 diagnoza, §2 start aplikacji, §3 `ttk.Style`, §4 receptury per widżet, §5 layout, §6 Windows, §7 Canvas, §8 interakcje, §9 responsywność, §10 pułapki i lista kontrolna | ok. 730 |
| `scripts/qt_theme.py` | Krok 4 dla Qt (kopiuj jako `ui_theme.py`) | `TOKENS`, `SPACING`, `RADIUS`, `FONT_FAMILIES`; `setup_hidpi`, `pick_font_family`, `make_font`, `load_app_fonts`, `build_palette`, `build_qss`, `apply_theme`, `current_tokens`, `repolish`, `set_property_and_repolish`, `set_windows_dark_titlebar`, `set_app_user_model_id`, `system_prefers_dark`, `save_window_state`, `restore_window_state`; galeria demo (`--screenshot PATH`, `--light`) | ok. 1020 |
| `scripts/qt_widgets.py` | Krok 4 dla Qt (kopiuj jako `ui_widgets.py`) | `SectionHeader`, `FormSection`, `Switch`, `SegmentedControl`, `ColorSwatchButton`, `NumberField`, `PathField`, `InlineMessage`; helpery `set_role`, `set_kind`, `set_busy`, `status_message`; demo inspektora (`--screenshot PATH`, `--light`) | ok. 920 |
| `scripts/theme_template.py` | Krok 4 dla Tk | `TOKENS` (te same wartości co w Qt), `enable_hidpi`, `px`, `apply_tk_scaling`, `configure_named_fonts`, `apply_theme` (clam + style + `option_add`), `current_tokens`, `set_windows_dark_titlebar`, `system_prefers_dark`, `set_window_icon`, `bind_mousewheel`, `register_rounded_button_style`; demo | ok. 830 |
| `scripts/widgets.py` | Krok 4 dla Tk | `Tooltip`, `ScrollableFrame`, `SectionHeader`, `FormGrid`, `Switch`, `SegmentedControl`, `ColorSwatchButton`, `NumberField`, `PathField`, `StatusBar`, `InlineMessage`, `parse_color`, `format_color`; demo inspektora | ok. 940 |

Kolejność czytania przy typowym zleceniu "odśwież GUI": ten plik -> Krok 0 -> `audit-checklist.md` -> przewodnik frameworka §1-§2 -> `design-tokens.md` (tabele palet i stanów) -> `component-patterns.md` tylko sekcje dotyczące problemów z audytu.

## Anty-wzorce

1. Redesign "big bang": przepisanie całego okna bez zrzutów pośrednich; po tygodniu nikt nie wie, która zmiana zepsuła układ.
2. Kolory w f-stringach i literałach (`setStyleSheet(f"background:{c}")`, `bg="#333"`) zamiast tokenów i ról; przełączenie motywu zostawia stare kolory.
3. QSS per widżet (`widget.setStyleSheet`) zamiast jednego arkusza na aplikację; każdy taki wpis to wyjątek od kaskady.
4. Ukrywanie kontrolek zależnych (`hide()`, `grid_remove`) zamiast `disabled`; układ skacze, użytkownik nie wie, że opcja istnieje.
5. Angielskie wartości list w polskim UI ("bottom-left") albo zapis przetłumaczonej etykiety do ustawień.
6. Dwa formaty czasu na jednym ekranie ("37,60 s" w polu, "37.6s" na osi) lub dwa separatory dziesiętne.
7. Zmiana kluczy lub typów konfiguracji "przy okazji" (np. RGBA -> hex w pliku ustawień).
8. Ignorowanie HiDPI: bitmapy PNG bez wariantów, rozmiary w pikselach fizycznych, testy tylko przy 100 %.
9. Rezygnacja z istniejących zabezpieczeń UX (np. `WheelGuard`), bo "nowy widżet ich nie potrzebuje".
10. Blokowanie wątku GUI: `processEvents()` w pętli, `time.sleep`, ffmpeg uruchamiany w slocie przycisku.
11. Zmiana geometrii w stanach (`font-weight: bold` w `:checked`, szersza ramka fokusu bez korekty paddingu); tekst się ucina.
12. Akcent na wszystkim: trzy przyciski primary w sekcji, kolorowe nagłówki, czerwony marker "Do" bez znaczenia błędu.
13. Drugi mechanizm i18n obok istniejącego lub teksty na sztywno w nowych widżetach.

## Raport końcowy dla użytkownika

Po zakończeniu prac (lub iteracji) przekaż:

1. Listę zmian per iteracja: co widać inaczej, które pliki, czy zmieniła się wersja aplikacji.
2. Zrzuty przed/po (ścieżki lub obrazy) w tym samym rozmiarze okna; przy zmianie motywu także light; przy HiDPI 100 % i 150 %.
3. Wyniki weryfikacji z Kroku 5: testy, `py_compile`, `grep setStyleSheet`, diff pliku ustawień.
4. Co pozostało: pozycje audytu bez naprawy z wagą i powodem (poza zakresem, wymaga decyzji, wymaga zmian w logice).
5. Jak uruchomić i sprawdzić: dokładne polecenia (interpreter, zmienne środowiskowe, flaga zrzutu) oraz przełącznik motywu, jeśli dodany.
6. Ryzyka i decyzje do podjęcia: np. licencja biblioteki motywu, zmiana minimalnego rozmiaru okna, wybór formatu czasu.

Raport ma być krótki: tabela zmian, lista zrzutów, lista "co dalej". Szczegóły techniczne zostają w commitach i w plikach referencyjnych skilla.
