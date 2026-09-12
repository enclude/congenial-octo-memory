# PySide6: odświeżenie UI aplikacji desktopowej

Przewodnik wdrożeniowy dla aplikacji już napisanych w PySide6 (przykład: Piro Overlay, `src/piro_overlay/gui.py`). Kolory, odstępy, promienie i fonty pochodzą z `design-tokens.md`; gotowy kod z `scripts/qt_theme.py` (motyw) i `scripts/qt_widgets.py` (własne widżety). Wzorce ogólne (kiedy jaka kontrolka, układ inspektor + podgląd) są w `component-patterns.md`; ten plik mówi, jak zrobić to w Qt.

Zasady nadrzędne skilla obowiązują bez wyjątku: (1) odświeżenie nie zmienia logiki ani formatu ustawień, (2) praca przyrostowa, każdy krok potwierdzony zrzutem, (3) i18n PL/EN zachowane, (4) HiDPI 100/125/150/200 %, (5) klawiatura i fokus, (6) UI nie zamiera.

## §1 Diagnoza: dlaczego aplikacja PySide6 wygląda przestarzale

Typowy obraz: aplikacja działa, ale wygląda jak formularz z 2005 roku. Przyczyny są zwykle te same i da się je wykryć grepem, zanim ktoś uruchomi program.

| Objaw | Przyczyna w kodzie | Jak wykryć |
|---|---|---|
| Natywne kontrolki Windows w stylu klasycznym, szare tło | brak `app.setStyle(...)`, Qt bierze styl "windowsvista" (Qt 6: "windows11" tylko w nowszych wersjach) | `grep -n "setStyle(" gui.py` nic nie zwraca |
| Sekcje w ramkach z tytułem wciętym w linię ramki | `QGroupBox("...")` z domyślnym rysowaniem | `grep -n 'QGroupBox("' gui.py` (Piro: linie 1042, 1953, 2012, 2069, 2321) |
| Kolory rozjeżdżają się między oknami, ciemny podgląd na jasnym tle | brak wspólnej QPalette i globalnego QSS; kolory wpisane na sztywno w wielu miejscach | `grep -n "setStyleSheet" gui.py` (Piro: 19 wystąpień, m.in. `"color:#aaaaaa;"` linie 905, 1093, 2001, 3216; `"background:#222;color:#aaa;"` linia 1907; `#44cc88`, `#e05555`, `#f0c040`, `#aa7733` linie 935-953; `#3ad17a`, `#e0a030` linie 3310-3317) |
| Przycisk koloru pokazuje tekst "RGBA 0,0,0,170" i pasek koloru na lewej krawędzi | `ColorButton._refresh` buduje QSS f-stringiem z `border-left: 20px solid rgba(...)` | `sed -n '1779,1812p' gui.py` |
| Brak ikon, brak paska akcji; "Wykryj", "Renderuj" ukryte w środku formularza | brak `QToolBar` / `QAction`; wszystkie akcje jako `QPushButton` w `QFormLayout` | `grep -n "QToolBar\|QAction\|QMenuBar" gui.py` nic nie zwraca |
| Rozmyte lub za małe elementy przy 125/150 % | brak `setHighDpiScaleFactorRoundingPolicy`, bitmapy PNG zamiast SVG | `grep -n "HighDpi\|devicePixelRatio" gui.py` |
| Okno zawsze startuje w tym samym rozmiarze i miejscu, splitter resetuje się | brak `QSettings`, `saveGeometry`, `saveState` | `grep -n "QSettings\|saveGeometry\|restoreState" gui.py` |
| Kółko myszy nad spinboxem zmienia wartość zamiast przewijać | brak filtra zdarzeń (Piro ma `WheelGuard`, linia 3525: to zachowaj) | `grep -n "eventFilter\|QEvent.Wheel" gui.py` |
| Tytuł okna jasny, gdy aplikacja jest ciemna | brak `DwmSetWindowAttribute` | `grep -n "dwmapi\|DwmSetWindowAttribute" gui.py` |

Szybki audyt jednym poleceniem:

```bash
cd /path/to/repo
grep -n "setStyle(\|setPalette\|setStyleSheet\|QGroupBox(\"\|QToolBar\|QSettings\|HighDpi\|dwmapi" src/piro_overlay/gui.py
```

Wynik audytu dla Piro Overlay jest w `audit-example-piro-overlay.md`. Wnioski z niego przekładają się na kroki w §2 (fundament), §4 (receptury per widżet) i §7 (rysowanie własne).

## §2 Fundament: `main()` w dobrej kolejności

Kolejność ma znaczenie: polityka HiDPI musi być ustawiona przed utworzeniem `QApplication`, fonty z assets przed `apply_theme` (żeby QSS mógł się do nich odwołać), ciemny pasek tytułu dopiero po `show()` (natywny uchwyt okna musi istnieć).

```python
# gui.py
import sys
from PySide6.QtCore import QSettings
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import __version__, resources
from .ui_theme import (apply_theme, load_app_fonts, restore_window_state,
                       save_window_state, set_app_user_model_id,
                       set_windows_dark_titlebar, setup_hidpi, system_prefers_dark)


def main():
    _install_crash_logging()
    setup_hidpi()                                   # 1. before QApplication
    set_app_user_model_id("Piro.Overlay")           # 2. taskbar icon/grouping in .exe
    app = QApplication(sys.argv)
    app.setApplicationName("PiroOverlay")
    app.setOrganizationName("Piro")                 # QSettings needs org + app name
    app.setApplicationVersion(__version__)
    app.setWindowIcon(QIcon(resources.icon_path()))
    load_app_fonts(resources.fonts_dir())           # 3. assets/fonts/*.ttf -> QFontDatabase
    mode = "dark" if system_prefers_dark() else "light"
    theme = apply_theme(app, mode)                  # 4. Fusion + QPalette + QSS + font
    app._wheel_guard = WheelGuard(app)              # keep: wheel over spinbox scrolls page
    app.installEventFilter(app._wheel_guard)

    settings = QSettings()
    win = MainWindow()
    if not restore_window_state(win, settings, win.splitter):
        win.resize(1180, 760)                       # fallback for first run
    win.show()
    set_windows_dark_titlebar(win, theme["mode"] == "dark")   # 5. after show()
    app.aboutToQuit.connect(lambda: save_window_state(win, settings, win.splitter))

    checker = UpdateChecker()
    checker.update_available.connect(lambda v: _show_update_dialog(win, v))
    checker.start()
    return app.exec()
```

Co robi każdy krok i dlaczego tak:

- `setup_hidpi()`: `QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)`. Qt 6 skaluje domyślnie; polityka PassThrough zachowuje ułamkowe współczynniki (125 %, 150 %), żeby UI nie było ani rozmyte, ani przeskalowane do 200 %.
- `app.setStyle("Fusion")`: styl neutralny, rysowany w całości przez Qt, więc w pełni sterowany paletą i QSS. Styl "windowsvista" ignoruje część QPalette i miesza natywne bitmapy z QSS. Styl "windows11" (zależny od wersji Qt, sprawdź w dokumentacji) daje wygląd Fluent, ale też nie wszędzie respektuje QSS; jako baza pod własny arkusz Fusion jest przewidywalny.
- `app.setPalette(build_palette(tokens))`: role Window, WindowText, Base, AlternateBase, Text, Button, ButtonText, Highlight, HighlightedText, ToolTipBase, ToolTipText, PlaceholderText, Link plus grupa Disabled. Fusion czyta paletę tam, gdzie QSS nic nie ustawia (np. strzałki, ramki fokusu w listach), więc paleta i QSS muszą pochodzić z tych samych tokenów.
- `app.setStyleSheet(build_qss(...))`: jeden arkusz na QApplication. Każdy `setStyleSheet` na pojedynczym widżecie tworzy wyjątek od kaskady; docelowo ma ich nie być (§10).
- `app.setFont(make_font("font_ui"))`: rodzina wybrana przez `pick_font_family(["Segoe UI Variable Text", "Segoe UI", ...])` sprawdzającą `QFontDatabase.families()`. Nieistniejącą rodzinę Qt zastępuje cicho, więc sprawdzaj obecność jawnie.
- `load_app_fonts(dir)`: `QFontDatabase.addApplicationFont(path)` dla każdego `.ttf` z `assets/fonts` (Piro: DejaVuSans, używane w nakładce; w UI potrzebne tylko, jeśli QSS ma się do nich odwołać). Musi być po utworzeniu `QApplication`.
- `set_windows_dark_titlebar(win, True)`: `DwmSetWindowAttribute(hwnd, 20, &1, 4)` z fallbackiem na atrybut 19 (§6). Wywołaj po `show()` i po każdej zmianie motywu; `apply_theme` robi to dla widocznych okien.
- `QSettings` + `save_window_state` / `restore_window_state`: `saveGeometry()/restoreGeometry()` dla okna, `saveState()/restoreState()` dla `QSplitter` (Piro: splitter tworzony w `_build_ui`, linie 1922-1928; zapisz go jako `self.splitter`). Klucze QSettings to nowa przestrzeń (`ui/geometry`, `ui/splitter`), nie dotykają `ui_settings.json` z `config.py`.
- `set_app_user_model_id("Piro.Overlay")`: `ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(...)`. Bez tego pasek zadań w .exe czasem pokazuje ikonę Pythona lub nie grupuje okien. Wywołaj przed pokazaniem pierwszego okna.

Przełączanie motywu w locie: ponowne `apply_theme(app, "light")` podmienia paletę i QSS na QApplication; `repolish(widget)` (rekurencyjne `style().unpolish(w); style().polish(w)`) wymusza ponowną ewaluację selektorów atrybutowych. Własne widżety malowane w `paintEvent` czytają kolory przez `current_tokens(app)` przy każdym rysowaniu, więc podążają za motywem bez dodatkowej pracy.

## §3 QSS od podszewki

QSS (Qt Style Sheets) to CSS-podobny język stylowania widżetów. Różni się od CSS w kilku miejscach, które regularnie kosztują godziny.

### Selektory

| Selektor | Znaczenie | Przykład |
|---|---|---|
| `QPushButton` | typ i podklasy | `QPushButton { ... }` obejmuje też `ColorButton(QPushButton)` |
| `.QPushButton` | dokładnie ten typ, bez podklas | rzadko potrzebne |
| `#objectName` | `widget.setObjectName("renderBtn")` | `QPushButton#renderBtn` |
| `QGroupBox QLabel` | potomek (dowolna głębokość) | etykiety wewnątrz sekcji |
| `QScrollArea > QWidget` | bezpośrednie dziecko | tło viewportu |
| `QPushButton[kind="primary"]` | właściwość dynamiczna | `btn.setProperty("kind", "primary")` |
| `QLineEdit:focus` | pseudo-stan | `:hover :pressed :checked :disabled :focus :read-only :selected :default :flat :editable :on :off` |
| `QComboBox::drop-down` | sub-kontrolka | patrz tabela niżej |

Sub-kontrolki używane w `qt_theme.py`: `::indicator` (QCheckBox, QRadioButton, QMenu), `::drop-down` i `::down-arrow` (QComboBox), `::up-button`, `::down-button`, `::up-arrow`, `::down-arrow` (QAbstractSpinBox), `::handle`, `::groove`, `::sub-page`, `::add-page` (QSlider, QScrollBar), `::add-line`, `::sub-line` (QScrollBar), `::chunk` (QProgressBar), `::tab` (QTabBar), `::pane` (QTabWidget), `::title` (QGroupBox), `::section` (QHeaderView), `::item` (QMenu, widoki), `::separator` (QMenu, QToolBar), `::handle` (QSplitter).

### Box model i pozycjonowanie sub-kontrolek

Każdy widżet ma `margin`, `border`, `padding`, `border-radius`, `min-width`, `min-height`, `max-height`. Sub-kontrolki pozycjonuje się przez `subcontrol-origin` (margin | border | padding | content) i `subcontrol-position` (np. `top right`), a przesuwa przez `left`, `top`, `width`, `height`.

```css
QComboBox::drop-down {
    subcontrol-origin: border;       /* rectangle to align against */
    subcontrol-position: top right;  /* where inside that rectangle */
    width: 24px;
    border: none;
    border-left: 1px solid #3F3F43;
}
QGroupBox::title {
    subcontrol-origin: margin;       /* required: title lives in the margin band */
    subcontrol-position: top left;
    left: 0;
}
```

### Właściwości dynamiczne (kluczowy mechanizm tego skilla)

Zamiast klas per wariant, jeden typ widżetu i atrybut: `btn.setProperty("kind", "primary")` + selektor `QPushButton[kind="primary"]`. Qt ewaluuje selektory atrybutowe przy polish, więc po zmianie właściwości na już pokazanym widżecie trzeba wymusić odświeżenie:

```python
btn.setProperty("kind", "primary")
btn.style().unpolish(btn)
btn.style().polish(btn)
btn.update()
```

W `qt_theme.py` robi to `set_property_and_repolish(widget, name, value)`, a `repolish(widget)` odświeża całe poddrzewo (po zmianie motywu). Wartość porównywana jest jako tekst: `setProperty("invalid", True)` da `[invalid="true"]`, ale bezpieczniej zawsze ustawiać łańcuch `"true"` / `"false"`.

Inne mechanizmy:

- `qproperty-<name>: value;` ustawia właściwość Qt z arkusza (np. `qproperty-alignment: AlignRight;`, `qproperty-iconSize: 20px 20px;`). Działa raz, przy polish; do stanów użyj pseudo-stanów.
- Obrazy: `image: url(path/to/file.svg);` w sub-kontrolkach (`::indicator:checked`, `::down-arrow`). `url()` przyjmuje ścieżkę pliku lub zasób Qt `:/...`; **`data:` URL nie działa**. `qt_theme.write_indicator_svgs` zapisuje małe SVG do katalogu tymczasowego i wstawia ścieżki do arkusza. Renderowanie wymaga pluginu formatu SVG (§10).
- Kolory: `#RRGGBB`, `rgba(r,g,b,a)`, `palette(highlight)` (odwołanie do bieżącej QPalette), gradienty `qlineargradient(...)`.

### QSS a QPalette

QSS ma pierwszeństwo: właściwość ustawiona w arkuszu wygrywa z paletą. Fusion czyta paletę wszędzie tam, gdzie arkusz milczy (np. `QPalette.Highlight` w widokach bez reguły `::item:selected`, kolor strzałek). Stąd wymóg: paleta i QSS z tych samych tokenów, a `build_palette` ustawia też grupę `Disabled`, bo `:disabled` w QSS nie obejmuje elementów rysowanych przez styl (np. ikon).

Kaskada: arkusz na `QApplication` obowiązuje wszędzie; `widget.setStyleSheet(...)` dokłada reguły dla tego widżetu i jego potomków, a przy konflikcie wygrywa reguła bliższa widżetowi. To dlatego rozproszone `setStyleSheet("color:#aaaaaa;")` psują motyw: przy przełączeniu na jasny zostają szare napisy na białym. Migracja: zamiast koloru wpisz rolę (`label.setProperty("role", "muted")`) i pozwól działać arkuszowi globalnemu.

### Pułapki QSS, które trafiają każdego

- `border` na `QPushButton` wyłącza natywny rysunek przycisku: od tej chwili trzeba podać `padding`, `min-height`, `border-radius`, tło dla `:hover`, `:pressed`, `:disabled`, `:checked`. W `qt_theme.py` przycisk ma `min-height: 30px` + 1 px ramki = 32 px.
- Popup `QComboBox` to osobny widżet: stylizuje się selektorem `QComboBox QAbstractItemView { ... }`; kolor zaznaczenia przez `selection-background-color`, wysokość pozycji przez `::item { min-height }`.
- `QScrollArea` maluje własne tło i ramkę na wierzchu: `QScrollArea { border: none; background: transparent; } QScrollArea > QWidget > QWidget { background: transparent; }` (viewport i widget wewnętrzny).
- `QGroupBox::title` bez `subcontrol-origin: margin` ląduje w ramce i jest ucinany; QGroupBox musi mieć `margin-top` co najmniej wysokości tytułu.
- `font-weight: bold` w stanie `:checked` zmienia szerokość tekstu i ucina napis (przycisk nie rośnie). Wyróżniaj stan tłem i ramką, nie grubością.
- `QLabel` z `word-wrap` i `min-height` w QSS potrafi nadpisać `sizeHint`; ustawiaj rozmiary etykiet w Pythonie.
- Zmiana `font-size` w arkuszu na `QWidget` nie zmienia `app.font()`: `QFontMetrics` w `paintEvent` liczone z `self.font()` będą zgodne, ale `QApplication.font()` nie. Ustaw font zarówno w `app.setFont`, jak i w arkuszu (tak robi `apply_theme`).
- Nazwa rodziny ze spacjami w QSS wymaga cudzysłowu: `font-family: "Segoe UI Variable Text";`.

## §4 Receptury per widżet

Każda receptura: cel, kod (QSS z `qt_theme.build_qss` albo Python), pułapki, odniesienie do miejsca w `gui.py`. Kolory w przykładach QSS są tokenami DARK; w kodzie zawsze przez `TOKENS[mode]`.

### QGroupBox: sekcja bez ramki

Cel: tytuł jako nagłówek (bold, `font_section`) z linią 1 px pod spodem; brak ramki wokół zawartości (`design-tokens.md` §Promienie: separator zamiast ramki).

```css
QGroupBox {
    border: none; border-top: 1px solid #3F3F43;
    margin-top: 20px; padding: 12px 0 0 0;
    font-weight: bold; font-size: 11pt;
}
QGroupBox::title {
    subcontrol-origin: margin; subcontrol-position: top left; left: 0;
    padding: 0 4px 0 0; background: #2A2A2C;
}
```

To zmienia wygląd wszystkich `QGroupBox("Wejście")`, `("Synchronizacja i przycięcie")`, `("Wygląd nakładki")`, `("Wyjście")` i `("Ustawienia wspólne")` w `BatchDialog` bez dotykania kodu. Krok drugi (opcjonalny, sekcja po sekcji): zamiana na `FormSection(title)` z `qt_widgets.py`, która daje zwijanie (chevron) i `add_row(label, field, unit, help_text)`. Pułapka: `font-size` na QGroupBox dziedziczą dzieci, jeśli same nie mają fontu; w `qt_theme.py` reguła `QWidget { font-size }` przywraca rozmiar bazowy.

### QFormLayout

Cel: etykiety wyrównane do lewej, jedna szerokość kolumny etykiet w całym inspektorze, pola rosną do prawej krawędzi.

```python
form = QFormLayout(box)
form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
form.setRowWrapPolicy(QFormLayout.DontWrapRows)
form.setHorizontalSpacing(SPACING["sp_2"])
form.setVerticalSpacing(SPACING["sp_2"])
form.setContentsMargins(SPACING["sp_4"], 0, 0, 0)
# one label width for all sections: QLabel.setMinimumWidth(132) on every label
```

Pary w jednym wierszu (Piro: "Przytnij od / do" linia 2051, "Offset X / Y" linia 2092): `QHBoxLayout` z dwoma polami i etykietą "/" w `role=muted` między nimi; helper `_wrap(layout)` z gui.py (linia 3493) zostaje, `FormSection.add_pair_row` robi to samo. Pułapka: `QDoubleSpinBox` liczy minimalną szerokość z najszerszego tekstu zakresu ("100000,00 s"), więc para spinboxów z zakresem 0..100000 rozpycha lewy panel; ustaw `setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)` + `setMinimumWidth(64)` (tak robi `NumberField`) albo zawęź zakres do długości nagrania po analizie audio.

### QPushButton: primary / secondary / ghost / danger

Cel: jeden przycisk primary na widok (Piro: "Renderuj", linia 2361), reszta secondary, akcje pomocnicze ghost, destrukcyjne danger. Wysokość 32 px, promień `r_md`, padding `sp_3`.

```python
render_btn.setProperty("kind", "primary")
nextc.setProperty("kind", "ghost")
delete_btn.setProperty("kind", "danger")
```

QSS w `build_qss`: `QPushButton[kind="primary"] { background: accent; color: accent_text; border: none; font-weight: bold; }` ze stanami `:hover` (accent_hover), `:pressed` (accent_pressed), `:disabled` (surface_alt + text_disabled), `:focus` (ramka 2 px `focus`, padding pomniejszony o 2 px, żeby tekst nie skoczył). Pułapki: `setDefault(True)` na primary daje Enter w dialogach; `setAutoDefault(False)` na pozostałych, żeby Enter nie odpalał pierwszego lepszego przycisku. Ikony: `btn.setIcon(QIcon("assets/icons/play.svg"))` + `setIconSize(QSize(16, 16))`; kolor ikony przez podmianę `currentColor` w SVG (§7).

### QLineEdit

QSS: `padding: 0 8px; border: 1px solid border_strong; border-radius: r_sm; min-height: 30px`. Fokus: `border: 2px solid focus; padding: 0 7px` (geometria bez zmian, bo suma ramka+padding stała). `:read-only` tło `surface`, ramka `border`. Błąd: `edit.setProperty("invalid", "true")` + repolish daje ramkę 2 px `danger`; komunikat pod polem przez `InlineMessage.show_message(text, "danger")`. Placeholder w `text_muted` przez `QPalette.PlaceholderText` (w Qt 6 selektor `::placeholder` może być ignorowany, sprawdź w dokumentacji; paleta działa zawsze).

### QSpinBox / QDoubleSpinBox

Dwie drogi:

1. Zostawić natywne przyciski i ostylować: `QAbstractSpinBox::up-button / ::down-button { width: 18px; border: none; background: transparent; }` + strzałki SVG (`::up-arrow`, `::down-arrow`); tak jest w `build_qss`. Pole `padding-right: 18px`, żeby tekst nie wchodził pod przyciski.
2. `setButtonSymbols(QAbstractSpinBox.NoButtons)` + własne QToolButton "-" / "+" po bokach: `NumberField` w `qt_widgets.py`. Większe cele dotykowe, wyrównane do wysokości 32 px, `setAutoRepeat(True)` na przyciskach.

Zawsze: `setSuffix(" s")` / `(" px")` zamiast osobnej etykiety jednostki (Piro robi to w `_dspin`, linia 3497), `setAlignment(Qt.AlignRight | Qt.AlignVCenter)` dla cyfr w kolumnie, `setKeyboardTracking(False)` żeby `valueChanged` szło raz po edycji, a nie po każdym znaku. Przecinek dziesiętny: `spin.setLocale(QLocale(QLocale.Polish))`; wartość w `value()` zawsze float, format ustawień się nie zmienia. `WheelGuard` (gui.py 3525) filtruje `QAbstractSpinBox`, więc obejmuje też `NumberField.spin`.

### QComboBox

QSS: `::drop-down { width: 24px; border-left: 1px solid border }`, `::down-arrow { image: url(down.svg) }`, popup `QComboBox QAbstractItemView { background: surface; selection-background-color: accent_subtle; }` + `::item { min-height: 26px }`. Wartości techniczne tłumacz przez `addItem(text, userData)`: Piro robi to dla trybu kotwicy (`addItem("Sygnał startu", AnchorMode.START_SIGNAL.value)`, linia 2019), ale `pos_combo.addItems(list(ANCHOR_POSITIONS))` (linia 2082) pokazuje surowe "bottom-left". Zamień na pętlę `addItem(tr(key), key)` i czytaj `currentData()`; klucze zapisywane do ustawień zostają identyczne.

### QCheckBox / QRadioButton

`::indicator { width: 18px; height: 18px; border: 1px solid border_strong; background: field_bg; border-radius: r_sm }` (radio: `border-radius: 9px`), `:checked { background: accent; border-color: accent; image: url(check.svg) }`. Bez pluginu SVG stan nadal widać po kolorze wypełnienia. Fokus: `::indicator:focus { border: 2px solid focus }` i `QCheckBox:focus { outline: none }` (usuwa kropkowaną ramkę Fusion). Para radio "Tekst / ID (API)" (linie 1961-1966) to kandydat na `SegmentedControl([("text", "Tekst"), ("id", "ID (API)")])`: zwraca klucz, nie etykietę, więc i18n i ustawienia są nienaruszone; `rb_id.toggled` zamień na `currentChanged` i porównanie z `"id"`.

### QSlider

`::groove:horizontal { height: 4px; background: border_strong; border-radius: 2px }`, `::sub-page:horizontal { background: accent }`, `::handle:horizontal { width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; background: text; border: 2px solid surface }`. Ujemny `margin` na uchwycie jest konieczny, żeby wystawał ponad rowek.

### QProgressBar

`QProgressBar { min-height: 8px; max-height: 8px; border: none; border-radius: r_sm; background: surface_alt }`, `::chunk { background: accent; border-radius: r_sm }`. Stan błędu: zamiast `setStyleSheet("QProgressBar::chunk { background: #e05555; }")` (gui.py 538) ustaw `bar.setProperty("role", "danger")` + repolish; QSS ma `QProgressBar[role="danger"]::chunk`. Tryb nieokreślony (czas nieznany, np. detekcja sygnału): `bar.setRange(0, 0)`; powrót: `bar.setRange(0, 100)`. `setTextVisible(False)`, procent pokazuj w etykiecie obok lub w pasku stanu.

### QScrollBar

Cienki, 8 px, bez strzałek: `QScrollBar:vertical { width: 8px; background: transparent }`, `::handle:vertical { background: border_strong; border-radius: 4px; min-height: 24px }`, `::handle:hover { background: text_muted }`, `::add-line, ::sub-line { width: 0; height: 0 }`, `::add-page, ::sub-page { background: none }`. To samo dla `:horizontal`.

### QSplitter::handle

`QSplitter::handle { background: border } QSplitter::handle:horizontal { width: 1px; margin: 0 4px } QSplitter::handle:hover { background: accent }`. Margines daje 9 px strefy chwytu przy 1 px linii. W Pythonie `splitter.setHandleWidth(9)` musi się zgadzać z QSS.

### QTabWidget / QTabBar

Zakładki "podkreślone": `QTabBar::tab { background: transparent; color: text_muted; border-bottom: 2px solid transparent; padding: 8px 12px }`, `:selected { color: text; border-bottom-color: accent }`, `QTabWidget::pane { border: none; border-top: 1px solid border }`.

### QToolTip

`QToolTip { background: surface_alt; color: text; border: 1px solid border_strong; border-radius: r_md; padding: 4px 8px }`. QToolTip czyta też `QPalette.ToolTipBase/ToolTipText`; oba ustawione. Skrót klawiszowy w treści: `btn.setToolTip("Wykryj kotwicę (Ctrl+D)")`.

### QMenu

`QMenu { background: surface; border: 1px solid border_strong; border-radius: r_lg; padding: 4px }`, `::item { padding: 4px 24px 4px 12px; border-radius: r_sm }`, `::item:selected { background: accent_subtle }`, `::separator { height: 1px; background: border }`. Zaokrąglone menu na Windows wymaga `Qt.FramelessWindowHint` + przezroczystości tła popupu; jeśli narożniki są czarne, zrezygnuj z `border-radius` na QMenu.

### QStatusBar

`QStatusBar { background: surface; color: text_muted; border-top: 1px solid border }`, `::item { border: none }`. `statusBar().showMessage(text, ms)` (Piro: linie 2494, 2593, 2643, 2712, 2943, 3223) nie ma koloru per komunikat; helper `status_message(statusbar, text, kind, timeout_ms)` z `qt_widgets.py` używa etykiety `role=kind` (`QStatusBar QLabel[role="success"]`). Widżety stałe (wersja, enkoder NVENC) przez `addPermanentWidget(label)` z `role=muted`; `nvenc_label.setStyleSheet("color:#3ad17a;")` (linia 3310) zamień na `set_role(nvenc_label, "success")`.

### QPlainTextEdit

Oś czasu tekstowa "1: 2.81s | 2: 4.63s (+1.82s)" (linia 1968) czytelniejsza w `font_mono`: QSS `QPlainTextEdit { font-family: "Cascadia Mono" }` (rodzina z `pick_font_family`, w `build_qss` jako `$mono_family`) lub `edit.setFont(make_font("font_mono"))`. `setMaximumHeight(80)` zostaje; dodaj `setTabChangesFocus(True)`, żeby Tab przechodził do następnego pola.

### QMessageBox / QDialog

Dialogi własne z `QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)`: `accepted/rejected` podpięte do `accept/reject`, Enter i Escape działają automatycznie. Przycisk OK jako primary: `box.button(QDialogButtonBox.Ok).setProperty("kind", "primary")`. `QMessageBox` dziedziczy paletę i QSS z aplikacji; ikony standardowe zostają. Marginesy dialogu `sp_5`, odstęp nad przyciskami `sp_8`.

### QLabel z rolą

Zamiast `label.setStyleSheet("color:#aaaaaa;")` (linie 905, 1093, 2001, 3216): `label.setProperty("role", "muted")`. Role w `build_qss`: `title` (13 pt bold), `section` (11 pt bold), `muted` (text_muted, 9 pt), `mono`, `danger`, `success`, `warning`, `info`. Stan wiersza w `BatchRowWidget.update_row` (linie 927-953) to mapa status -> rola: READY `success`, FAILED `danger`, PREPARING/DETECTING `warning`, NEEDS_ID `warning`, domyślnie `muted`; kropka statusu `_status_icon` rysowana w `paintEvent` kolorem z tokenów zamiast `setStyleSheet(f"background:{color}; border-radius:7px;")`.

## §5 Layout

### QSplitter

```python
self.splitter = QSplitter(Qt.Horizontal)
self.splitter.addWidget(left_scroll)
self.splitter.addWidget(right_container)
self.splitter.setStretchFactor(0, 0)     # inspector keeps its width
self.splitter.setStretchFactor(1, 1)     # preview takes the rest
self.splitter.setChildrenCollapsible(False)   # nobody loses the inspector by accident
self.splitter.setHandleWidth(9)
self.splitter.setSizes([400, 780])       # fallback; QSettings overrides (§2)
```

Piro ma już `setStretchFactor` i `setSizes([380, 800])` (linie 1922-1928); dodaj `setChildrenCollapsible(False)`, zapisz jako `self.splitter` i podłącz do `save_window_state`.

### QScrollArea inspektora

```python
left_scroll = QScrollArea()
left_scroll.setWidgetResizable(True)
left_scroll.setFrameShape(QFrame.NoFrame)
left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
left_scroll.setMinimumWidth(360)
left_container.setProperty("role", "inspector")   # QSS: background surface
```

Bez poziomego paska treść musi mieścić się w szerokości viewportu: przyciski w wierszach `QSizePolicy.Ignored` w poziomie (Piro już to robi dla przycisków detekcji, linia 2038), spinboxy z ograniczoną minimalną szerokością (§4). Gdy zawartość i tak jest szersza od viewportu, `widgetResizable` rozszerza widget wewnętrzny i część znika za prawą krawędzią: to sygnał, że któryś `minimumSizeHint` jest za duży.

### QSizePolicy i odstępy

Marginesy i odstępy wyłącznie z `SPACING`: kolumna inspektora `setContentsMargins(sp_4, sp_4, sp_4, sp_4)` i `setSpacing(sp_6)` między sekcjami; wiersze formularza `sp_2`; pasek przycisków `sp_2` między przyciskami, `sp_4` między grupami. Minimalny rozmiar okna: `win.setMinimumSize(960, 600)` (inspektor 360 + podgląd 480 + uchwyt + marginesy). Podgląd `PreviewLabel.setMinimumSize(480, 270)` (linia 1906) zostaje, `WaveformWidget.setMinimumHeight(140)` (linia 1454) zostaje.

### Pasek akcji i pasek transportu

Główne akcje jako `QAction` w `QToolBar` u góry okna (nie w formularzu): Otwórz wideo (Ctrl+O), Wykryj sygnał startu (Ctrl+D), Auto-przycięcie (Ctrl+T), Renderuj (Ctrl+R), Kolejka renderów, Wsad. Te same `QAction` można wstawić do menu kontekstowego i przycisków (`QToolButton.setDefaultAction`), więc skrót, ikona i stan `enabled` są w jednym miejscu.

```python
tb = QToolBar("Główny")
tb.setMovable(False)
tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
tb.setIconSize(QSize(20, 20))
self.addToolBar(tb)
act_render = QAction(QIcon("assets/icons/render.svg"), "Renderuj", self)
act_render.setShortcut(QKeySequence("Ctrl+R"))
act_render.setToolTip("Renderuj (Ctrl+R)")
act_render.triggered.connect(self._start_render)
tb.addAction(act_render)
```

Pasek transportu pod podglądem (`QHBoxLayout`): przycisk "Edytuj pozycje" (obecnie nad podglądem, linia 1897) jako `QToolButton` checkable z ikoną, czas bieżący w `font_mono`, przyciski "Dopasuj" / "Zoom do zakresu" dla `WaveformWidget`. Kolejność sekcji inspektora zgodna z przepływem pracy: Wejście -> Synchronizacja i przycięcie -> Wygląd nakładki -> Wyjście (Piro ma już tę kolejność w `_build_ui`, linie 1878-1881).

## §6 Windows: pasek tytułu, motyw systemu, HiDPI, fonty, ikona

### Ciemny pasek tytułu

Qt nie przełącza koloru natywnej belki okna. Robi to DWM przez atrybut `DWMWA_USE_IMMERSIVE_DARK_MODE` (wartość 20 od Windows 10 20H1; 19 w starszych buildach):

```python
def set_windows_dark_titlebar(widget, enabled=True) -> bool:
    if sys.platform != "win32":
        return False
    hwnd = int(widget.winId())                 # native handle: exists after show()
    value = ctypes.c_int(1 if enabled else 0)
    for attr in (20, 19):
        if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd), ctypes.c_uint(attr),
                ctypes.byref(value), ctypes.sizeof(value)) == 0:
            return True
    return False
```

Wywołaj po `show()` każdego okna najwyższego poziomu (główne, `RenderQueueWindow`, `BatchDialog`, dialogi) i po każdej zmianie motywu (`apply_theme` przechodzi przez `app.topLevelWidgets()`). Okna tworzone później: wywołanie w `showEvent` lub w miejscu tworzenia. Na Windows 11 belka przyjmuje od razu kolor; na Windows 10 czasem dopiero po utracie i odzyskaniu fokusu (znane zachowanie DWM).

### Wykrycie motywu systemu

`QGuiApplication.styleHints().colorScheme()` zwraca `Qt.ColorScheme.Dark/Light/Unknown` (dostępne od Qt 6.5; zależne od wersji, sprawdź w dokumentacji Qt). Fallback: rejestr `HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize`, wartość `AppsUseLightTheme` (0 = ciemny). Implementacja: `system_prefers_dark()` w `qt_theme.py`. Reakcja na zmianę w trakcie działania: sygnał `styleHints().colorSchemeChanged` (również zależny od wersji) podłączony do `apply_theme(app, ...)`. Domyślny motyw narzędzia wideo to ciemny (`design-tokens.md` §Zasady), więc przy braku informacji wybierz "dark".

### HiDPI w Qt 6

- Skalowanie jest włączone domyślnie i per ekran; nie ustawiaj `QT_SCALE_FACTOR` ani `AA_EnableHighDpiScaling` (atrybut Qt 5, w Qt 6 bez skutku).
- Polityka zaokrąglania: `PassThrough` (ułamkowe współczynniki) przed `QApplication` (`setup_hidpi()`). Bez tego Qt zaokrągla 125 % do 100 % lub 150 % do 200 %, zależnie od wersji.
- Wszystkie rozmiary w kodzie i QSS są w pikselach logicznych: `min-height: 30px` daje 45 px fizycznych przy 150 %. Fonty w punktach (`10pt`) skalują się same.
- Ikony jako SVG (`QIcon("x.svg")` renderuje w potrzebnej rozdzielczości). Bitmapy PNG rozmywają się przy 125/150 %; jeśli muszą być, dostarcz `@2x` i użyj `QIcon.addFile` z różnymi rozmiarami.
- Własne widżety z cache w `QPixmap`: twórz bufor w rozmiarze `size() * devicePixelRatio()` i ustaw `pixmap.setDevicePixelRatio(dpr)`; inaczej fala audio i markery są rozmyte na ekranach 150 % (§7).
- Test: `QT_SCALE_FACTOR=1.5 python -m piro_overlay.gui` na monitorze 100 % symuluje 150 % (tylko do testów; w produkcji zmienna nieustawiona).

### Fonty

"Segoe UI Variable Text" jest w Windows 11, "Segoe UI" w Windows 10 i 11; "Cascadia Mono" bywa nieobecna na Windows 10 (fallback "Consolas"). `pick_font_family(candidates)` sprawdza `QFontDatabase.families()` i zwraca pierwszą obecną rodzinę; wynik trafia do `app.setFont` i do arkusza (`font-family: "..."`). Platforma `offscreen` na Windows nie widzi fontów systemowych bez `QT_QPA_FONTDIR=C:\Windows\Fonts` (tekst renderuje się jako prostokąty); skrypty skilla ustawiają to w trybie `--screenshot`.

### Ikona okna i paska zadań

`app.setWindowIcon(QIcon(resources.icon_path()))` ustawia ikonę okna (Piro już to robi). Pasek zadań w .exe: `SetCurrentProcessExplicitAppUserModelID("Piro.Overlay")` przed pierwszym oknem, ikona `.ico` w `build_exe.spec` (`icon=...` w `EXE(...)`). Plik `.ico` powinien zawierać rozmiary 16, 24, 32, 48, 256.

## §7 Rysowanie własnych widżetów

Wspólne źródło kolorów: ten sam słownik tokenów zasila QSS i `QPainter`: `QColor(tokens["accent"])`. Widżet nie trzyma kopii kolorów, tylko czyta `current_tokens(QApplication.instance())` w `paintEvent`; zmiana motywu wymaga wtedy tylko `update()`.

### WaveformWidget (gui.py 1439-1727)

Stan obecny: `paintEvent` rysuje falę linią na kubełek (`p.drawLine` w pętli po `env`), kolory wpisane na sztywno (`QColor(24, 26, 34)`, `QColor(90, 170, 230)`, zielony/czerwony dla uchwytów, cyjan dla T0, pomarańcz dla podglądu), etykiety markerów `_tag` w dwóch rzędach, oś czasu z podziałką. Interakcje (klik = kotwica ze snapem, Ctrl+klik = podgląd, przeciąganie uchwytów, zoom kółkiem, pan prawym przyciskiem, dwuklik = reset) zostają bez zmian.

Zmiany rysowania:

1. Kolory z tokenów, mapowanie zgodne z `component-patterns.md` §8: tło osi `surface`, tło poza zakresem Od..Do `bg` z alfą (obecne przyciemnienie `QColor(0,0,0,120)` zostaje jako technika), fala w zakresie `text_muted`, poza zakresem `text_disabled`, tło zakresu `accent_subtle`, onsety `success` 1 px z alfą, marker T0/T1 `accent` 2 px, uchwyty Od/Do `info` 2 px, krawędzie Start/Koniec `text_muted` przerywane, wskaźnik podglądu (Ctrl+klik) `text` 1 px przerywany z trójkątem na osi, podziałka `border`, etykiety osi `text_muted` w `font_ui_small`. Zieleń i czerwień znikają z zakresu przycięcia (semantyka tylko dla stanów).
2. Cache obwiedni: fala zależy od `env`, `view_start/view_end`, `width()`, `height()` i motywu. Renderuj ją do `QPixmap` (lub `QPainterPath`) tylko gdy któraś z tych wartości się zmieni; markery, uchwyty, kursor rysuj na wierzchu przy każdym `paintEvent`.

```python
def _ensure_wave_cache(self, tokens):
    key = (len(self.env), self.view_start, self.view_end, self.width(), self.height(),
           tokens["text_muted"])
    if self._cache_key == key:
        return
    dpr = self.devicePixelRatioF()
    pm = QPixmap(int(self.width() * dpr), int(self._plot_h() * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, False)   # 1 px columns stay crisp
    path = QPainterPath()
    # one column per pixel: min/max over the samples that map to that column
    ...
    p.fillPath(path, QColor(tokens["text_muted"]))
    p.end()
    self._wave_cache, self._cache_key = pm, key
```

3. Etykiety markerów bez kolizji: policz `QRect` każdej etykiety przez `QFontMetrics.horizontalAdvance` + padding `sp_1`; jeśli prostokąt przecina poprzedni w tym samym rzędzie, przenieś do drugiego rzędu (naprzemiennie góra/dół), a przy trzeciej kolizji pokaż etykietę tylko w tooltipie. Priorytet: T0 > Od/Do > Start/Koniec. Pastylka: prostokąt `r_sm`, tło w kolorze markera, tekst `accent_text` dla T0 i `text` dla pozostałych (kontrast policzony w `design-tokens.md`).
4. Kursor: `setCursor(Qt.SizeHorCursor)` w `mouseMoveEvent`, gdy kursor jest w strefie uchwytu (`_HANDLE_PX`), `Qt.CrossCursor` poza nią; podczas panowania `Qt.ClosedHandCursor`.
5. Fokus i klawiatura: `setFocusPolicy(Qt.StrongFocus)`, ramka fokusu 2 px `focus` w `paintEvent` gdy `hasFocus()`, `keyPressEvent`: strzałki przesuwają kotwicę o 0,05 s (Shift: 1 s), Home/End do granic zakresu.

### PreviewLabel (gui.py 1727-1779)

Skalowanie klatki: `pixmap.scaled(label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)`; letterbox w kolorze `bg` (zamiast `setStyleSheet("background:#222;color:#aaa;")`, linia 1907: tło z tokenu w `paintEvent` albo nowa rola QSS, np. reguła `QLabel[role="preview"] { background: $bg; }` dopisana do `_QSS_TEMPLATE` w `ui_theme.py`). W trybie edycji pozycji (`edit_mode`) rysuj na wierzchu ramki uchwyconych paneli 1 px `accent` z narożnikami 6 px i podpisem "panel strzału" / "zegar" w `font_ui_small`; poza trybem edycji podgląd jest czysty. Kursor `Qt.OpenHandCursor` nad panelem, `Qt.ClosedHandCursor` podczas przeciągania. Pusty stan (brak wideo): ikona 48 px + tytuł `role=title` + podpowiedź `role=muted` ("Przeciągnij tu plik wideo lub użyj Ctrl+O"), wyśrodkowane.

### ColorButton -> ColorSwatchButton (gui.py 1779-1812)

`ColorSwatchButton(rgba)` z `qt_widgets.py` ma ten sam konstruktor, `rgba()` i sygnał `changed`, więc siedem wywołań `ColorButton((...))` (linie 2148-2151, 2199-2207) zamienia się jeden do jednego. Rysowanie w `paintEvent`: szachownica 5 px (`text_muted`/`border`) pod próbką z alfą, próbka 16 px z promieniem `r_sm`, tekst `#RRGGBB` i alfa w procentach `67 %` w `text_muted`, ramka `border_strong`, fokus 2 px. Dialog: `QColorDialog.getColor(QColor(*rgba), self, options=QColorDialog.ShowAlphaChannel)` bez zmian. Format ustawień (`OverlayStyle` z krotkami RGBA) nietknięty.

### Ikony SVG

`QIcon("assets/icons/play.svg")` wymaga pluginu SVG (§10). Kolor: SVG z `stroke="currentColor"` nie odczytuje koloru z Qt; podmień tekst przed załadowaniem:

```python
def tinted_icon(path: str, color: str) -> QIcon:
    svg = Path(path).read_text(encoding="utf-8").replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pm = QPixmap(QSize(64, 64)); pm.fill(Qt.transparent)
    p = QPainter(pm); renderer.render(p); p.end()
    return QIcon(pm)
```

Ikony w kolorze `text` dla stanu normalnego i `text_disabled` dla wyłączonego (`QIcon.addPixmap(pm, QIcon.Disabled)`). Alternatywa: pakiet `qtawesome` (ikony fontowe, kolor przez parametr; sprawdź licencję i zgodność z PySide6 przed dodaniem zależności).

## §8 Interakcje

- Widoczny fokus: każdy stan `:focus` w `build_qss` daje ramkę 2 px `focus`; własne widżety rysują pierścień przez `_focus_ring` z `qt_widgets.py`. Nie wyłączaj fokusu na przyciskach (`Qt.NoFocus`) poza przyciskami "-" / "+" w `NumberField`, które są pomocnicze do pola.
- Kolejność Tab: `QWidget.setTabOrder(a, b)` po zbudowaniu sekcji, zgodnie z przepływem (ścieżka wideo -> źródło -> oś czasu/ID -> kotwica -> przycięcie -> wygląd -> wyjście -> Renderuj). `QFormLayout` domyślnie idzie w kolejności dodawania, więc zwykle wystarczy dodawać w dobrym porządku.
- Skróty: `QAction.setShortcut(QKeySequence("Ctrl+R"))` w pasku akcji (§5), `QShortcut(QKeySequence("Space"), self.waveform, self._toggle_preview)` dla akcji bez przycisku. Skrót w tooltipie: "Renderuj (Ctrl+R)". Nie używaj samych liter bez modyfikatora, gdy fokus może być w polu tekstowym.
- WheelGuard (gui.py 3525-3545) zostaje: kółko nad `QAbstractSpinBox` / `QComboBox` w `QScrollArea` przewija stronę zamiast zmieniać wartość (zasada z `audit-checklist.md`). Filtr działa na `QApplication`, więc obejmuje też `NumberField.spin` i nowe okna.
- Dialogi: `QDialogButtonBox` daje Enter = OK, Escape = Anuluj; w oknach nie-dialogowych (`RenderQueueWindow`, `BatchDialog` to `QWidget`) dodaj `QShortcut(QKeySequence.Cancel, self, self.close)`.
- Walidacja: `QDoubleValidator` z `setLocale(QLocale(QLocale.Polish))` i `setNotation(QDoubleValidator.StandardNotation)` na polach tekstowych czasu; stan błędu przez `setProperty("invalid", "true")` + `InlineMessage.show_message("...", "danger")` pod polem; walidacja przy `editingFinished`, nie przy każdym znaku.
- Stan zajętości: `set_busy(btn, True, "Wykrywanie...")` wyłącza przycisk i zmienia tekst, `set_busy(btn, False)` przywraca; obok `QProgressBar.setRange(0, 0)`. Anulowanie: flaga (`self._cancelled = True`) sprawdzana w `run()` workera między krokami (Piro: `RenderWorker._is_cancelled`, linia ok. 170), przycisk "Anuluj" `kind=ghost` widoczny tylko podczas pracy.
- Debounce: `QTimer` z `setSingleShot(True)` i `start(ms)` restartowany przy każdej zmianie (Piro: `_preview_timer`, `_scrubber_timer`, `_autosave_timer`, linie 1841-1855; wzorzec zostaje). Dla jednorazowego opóźnienia `QTimer.singleShot(0, fn)` (np. `_show_elided` po `Resize` w `PathField`).

## §9 Wątki i responsywność

Obecny wzorzec Piro jest poprawny i zostaje: `QThread` z sygnałami (`RenderWorker.progress`, `FrameExtractWorker`, `WaveformWorker`, `StartDetectWorker`, `BatchPrepWorker`, `UpdateChecker`), GUI reaguje w slotach. Zasady:

- Widżety tylko z wątku GUI. Worker emituje sygnał z danymi (float, str, obiekt Pillow), slot w `MainWindow` aktualizuje widżety. Nigdy `label.setText` z `run()`.
- Postęp: `progress = Signal(float)` 0..1, slot `bar.setValue(int(p * 100))`; gdy czas nieznany, `setRange(0, 0)` na start i `setRange(0, 100)` po pierwszym raporcie.
- Bez `QApplication.processEvents()` w pętlach roboczych: to maskuje blokadę i wprowadza reentrancję (klik "Renderuj" w trakcie renderu). Jedyne dopuszczalne użycie: tryb `--screenshot` bez pętli zdarzeń w skryptach skilla.
- Zamykanie: `closeEvent` czeka na workery (`wait(_THREAD_JOIN_MS)`) albo ustawia flagę anulowania; "QThread: Destroyed while thread is still running" to crash natywny, który Piro loguje przez `faulthandler`.
- Alternatywa dla krótkich zadań: `QThreadPool.globalInstance().start(QRunnable)` z własnym `QObject` sygnałów (QRunnable nie ma sygnałów), bez tworzenia QThread per zadanie; przy wielu równoległych renderach ogranicz `setMaxThreadCount`.
- Sygnały między wątkami są kolejkowane automatycznie (`Qt.QueuedConnection` dla obiektów w różnych wątkach); nie przekazuj przez sygnał widżetów ani `QPixmap` (QPixmap tylko w wątku GUI; z workera wysyłaj `QImage` lub obraz Pillow).

## §10 Pułapki i checklista wdrożenia

### Pułapki

| Pułapka | Skutek | Rozwiązanie |
|---|---|---|
| QSS wygrywa z QPalette | kolor ustawiony w palecie "nie działa" | ustaw obie z tych samych tokenów (`apply_theme`); szukaj reguły QSS, która nadpisuje |
| `widget.setStyleSheet(...)` z kolorem | wyjątek od kaskady; po zmianie motywu zostaje stary kolor | `setProperty("role", ...)` + reguła w globalnym QSS; docelowo `grep -c setStyleSheet gui.py` == 0 poza `app.setStyleSheet` |
| zmiana property bez repolish | selektor `[kind="primary"]` nie zadziała na widocznym widżecie | `set_property_and_repolish` / `repolish` |
| `QGroupBox::title` bez `subcontrol-origin: margin` | tytuł ucięty lub w ramce | reguła jak w `build_qss`, `margin-top` >= wysokość tytułu |
| popup QComboBox bez stylu | jasna lista na ciemnym UI | `QComboBox QAbstractItemView { ... }` |
| `image: url(data:...)` | brak obrazka, bez błędu | plik na dysku lub zasób Qt (`write_indicator_svgs`) |
| SVG nie renderuje się (QIcon, QSS) | puste ikony, checkbox bez ptaszka | `import PySide6.QtSvg` przed użyciem (`ensure_svg_support`); w PyInstaller dołącz `PySide6/plugins/imageformats/qsvg.dll` i `iconengines/qsvgicon.dll`, `Qt6Svg.dll` |
| `font-weight: bold` w `:checked` / `:hover` | tekst ucięty, przycisk nie rośnie | wyróżniaj tłem i ramką |
| spinbox z zakresem 0..100000 | lewy panel rozpycha się, treść za krawędzią QScrollArea | `QSizePolicy.Ignored` + `setMinimumWidth`, albo zakres z długości nagrania |
| `QSizePolicy.Ignored` bez stretch | przycisk o szerokości 0 | `layout.addWidget(btn, stretch)` |
| animacja w widżecie niewidocznym | stan początkowy nie odpowiada `isChecked()` (offscreen, przed `show()`) | ustaw stan bez animacji, gdy `not isVisible()` (`Switch._animate`) |
| `QPixmap` w wątku roboczym | ostrzeżenie i crash | worker wysyła `QImage` / obraz Pillow, GUI konwertuje |
| `processEvents()` w pętli | reentrancja, podwójny render | sygnały z wątku, `set_busy` na przyciskach |
| offscreen na Windows bez fontów | tekst jako prostokąty na zrzucie | `QT_QPA_FONTDIR=C:\Windows\Fonts` |
| `setStyle("Fusion")` po utworzeniu widżetów | część widżetów w starym stylu do repolish | `setStyle` przed `MainWindow()`; `apply_theme` wywołuje `repolish` dla istniejących okien |

### PyInstaller (`build_exe.spec`, `build.ps1`)

- Pluginy Qt: hook PySide6 z PyInstaller zbiera większość, ale sprawdź w `dist/` obecność `PySide6/plugins/imageformats/qsvg.dll`, `PySide6/plugins/iconengines/qsvgicon.dll` i `PySide6/Qt6Svg.dll`. Jeśli brak, dodaj do `binaries` w spec. Test: w .exe `QImageReader.supportedImageFormats()` zawiera `svg`.
- Zasoby motywu: `ui_theme.py` generuje QSS w pamięci, więc nie potrzebuje pliku `.qss` w `datas`. Ikony SVG (`assets/icons/*.svg`) dodaj do `datas` jak fonty i czytaj przez `resources.py` (obsługa `sys._MEIPASS` już istnieje).
- Fonty: `addApplicationFont` ze ścieżek z `resources.fonts_dir()`; działa w .exe, bo `datas` kopiuje `assets/fonts`.
- Wyklucz nieużywane moduły Qt (`QtWebEngine`, `Qt3D`, `QtQuick`), żeby nie rosły rozmiar i czas budowania: `excludes=[...]` w `Analysis`.
- Ikona: `EXE(..., icon=os.path.join(_root, "assets", "icon.ico"))` plus `set_app_user_model_id` w `main()`.

### Praca w tym repozytorium (WSL + Windows)

- WSL nie ma PySide6: `tests/test_syntax.py` kompiluje każdy moduł przez `py_compile`; każdy nowy moduł UI (`ui_theme.py`, `ui_widgets.py`) automatycznie wchodzi w ten test (glob `src/piro_overlay/*.py`). Uruchom `PYTHONPATH=src pytest tests/test_syntax.py` po każdej zmianie.
- Uruchamianie GUI z WSL przez interpreter Windows: `"/mnt/c/.../.venv-win/Scripts/python.exe" "$(wslpath -w src/piro_overlay/gui.py)"`; ścieżki argumentów zawsze przez `wslpath -w`.
- Zrzuty bezgłowe: `QT_QPA_PLATFORM=offscreen` (+ `QT_QPA_FONTDIR` na Windows), `win.show(); app.processEvents(); win.grab().save(path)`; do całego inspektora `inner_widget.grab()` (bez przewijania). Skrypty skilla mają flagę `--screenshot PATH`; ten sam wzorzec dodaj do `gui.py` jako `--screenshot` w `main()` tylko na czas prac (nie zostawiaj w wydaniu bez potrzeby).
- Nie zmieniaj kluczy ustawień (`last_style.json`, `ui_settings.json`, `file_settings.json`, `last_dirs.json` w `config.py`) ani kluczy `_STRINGS`; geometria okna to nowa przestrzeń `QSettings`.
- Nowe teksty GUI (nagłówki sekcji, tooltipy ze skrótami, komunikaty `InlineMessage`) dodawaj do `_STRINGS` w `i18n.py` w PL i EN; `tests/test_i18n.py` wymaga obu języków. Klucze stabilne, etykiety tłumaczone (`SegmentedControl.set_label`, `QComboBox.setItemText`).
- Każda zmiana funkcjonalna = bump wersji w `src/piro_overlay/__init__.py` i `pyproject.toml` (odświeżenie UI: MINOR).

### Checklista wdrożenia (kolejność kroków, każdy ze zrzutem)

1. Skopiuj `scripts/qt_theme.py` jako `src/piro_overlay/ui_theme.py` (tylko UI, może importować PySide6). Uruchom galerię `python ui_theme.py --screenshot gallery.png` przez interpreter Windows; porównaj z tokenami.
2. `main()` wg §2: `setup_hidpi`, `apply_theme`, `set_windows_dark_titlebar`, `QSettings`. Zrzut głównego okna przed i po. Logika nietknięta.
3. Zamień `setStyleSheet` z kolorami na `role` (§4 QLabel, QProgressBar, QStatusBar). `grep -n setStyleSheet gui.py` ma zwrócić tylko `app.setStyleSheet` w `ui_theme`.
4. `ColorButton` -> `ColorSwatchButton` (§7), test: siedem próbek pokazuje kolor i alfę, `rgba()` daje te same krotki.
5. `WaveformWidget`: kolory z tokenów, cache fali, etykiety bez kolizji (§7). Zrzut z kotwicą, zakresem i podglądem naraz.
6. Pasek akcji `QToolBar` + `QAction` ze skrótami (§5, §8); przyciski w formularzu mogą zostać jako drugie wejście do tych samych `QAction`.
7. `QGroupBox` -> `FormSection` sekcja po sekcji (opcjonalnie), `pos_combo` z `userData`, para radio -> `SegmentedControl`.
8. Test HiDPI: `QT_SCALE_FACTOR=1.25`, `1.5`, `2` na zrzutach offscreen; klawiatura: Tab przez cały inspektor, Enter w dialogach, Escape zamyka okna pomocnicze.
9. Test i18n: przełącz `lang_combo` na EN i sprawdź, że nagłówki, segmenty i komunikaty zmieniają się; `PYTHONPATH=src pytest`.
10. Build `.exe` (`build.ps1`), sprawdź ikony SVG i fonty w paczce, bump wersji.
