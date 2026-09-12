# Checklista audytu UX/UI aplikacji desktopowej w Pythonie

Używana w kroku "Audyt" skilla `python-desktop-ux`. Przechodzisz grupy A-K, każdy punkt odhaczasz lub zapisujesz jako problem w szablonie raportu na końcu tego pliku. Nie zgaduj: jeśli czegoś nie da się stwierdzić ze zrzutu ani z kodu, oznacz punkt jako "do potwierdzenia" i wskaż, jak to sprawdzić.

Format punktu: `- [ ] treść`, pod nim dwa podpunkty: "Jak sprawdzić" i "Naprawa" (-> odwołanie do pliku referencyjnego skilla i numeru sekcji). Checklista jest neutralna wobec frameworka: gdzie naprawa zależy od biblioteki, odwołanie wskazuje oba przewodniki (`qt-pyside6.md` dla PySide6/PyQt6, `tkinter-ttk.md` dla Tkinter/ttk); polecenia `grep` w "Jak sprawdzić" podają wzorce dla obu.

Zasady nadrzędne, które audyt ma wspierać: odświeżenie UI nie zmienia logiki ani formatu ustawień; praca przyrostowa weryfikowana zrzutem; i18n PL/EN zachowane; HiDPI 100/125/150/200 %; klawiatura i fokus działają; UI nie zamiera.

## Jak przeprowadzić audyt

1. Zrób zrzuty: okno w rozmiarze domyślnym, w minimalnym, na 125 % i 150 % DPI, w obu językach, z otwartym dialogiem.
2. Ustal framework, Qt i Tk równorzędnie: `grep -rln "PySide6\|PyQt6\|PyQt5" --include=*.py .` oraz `grep -rln "import tkinter\|from tkinter\|customtkinter\|ttkbootstrap\|sv_ttk" --include=*.py .`. Potem stan UI: dla Qt `grep -rn "setStyle(\|setPalette\|setStyleSheet\|QSettings\|HighDpi\|QGroupBox(\"" --include=*.py .`, dla Tk `grep -rn "theme_use\|LabelFrame\|SetProcessDpiAwareness\|tk.call(\"tk\", \"scaling\"\|font=(" --include=*.py .`. Bez tego nie formułuj rekomendacji implementacyjnych; przy naprawach czytaj przewodnik wykrytego frameworka (`qt-pyside6.md` albo `tkinter-ttk.md`).
3. Przejdź grupy A-K poniżej. Każde odkrycie zapisz w tabeli raportu z dowodem (nazwa sekcji/kontrolki z ekranu, współrzędne lub opis miejsca).
4. Nadaj wagi P0/P1/P2 wg reguł na końcu. Posortuj: P0, potem P1, potem P2.
5. Zakończ sekcją "Kierunek redesignu" (układ, zamiany kontrolek, plan iteracji, czego nie zmieniamy). Wzór: `audit-example-piro-overlay.md`.

## A. Hierarchia wizualna i layout

- [ ] Wszystkie odstępy leżą na siatce 4/8 px (padding sekcji 16, między kontrolkami 8, między sekcjami 24).
  - Jak sprawdzić: zmierz na zrzucie (linijka w edytorze grafiki) lub `grep -n "setContentsMargins\|setSpacing\|padding"` (Qt) / `grep -n "padx\|pady\|padding"` (Tk) i szukaj wartości spoza {0,2,4,8,12,16,20,24,32}.
  - Naprawa: użyj `SPACING` z -> design-tokens.md §Skala odstępów; marginesy na kontenerach sekcji, nie na każdym widżecie osobno -> qt-pyside6.md §5 / tkinter-ttk.md §5.
- [ ] Kolumna etykiet ma jedną szerokość w całym panelu, kontrolki zaczynają się w jednej linii pionowej we wszystkich sekcjach.
  - Jak sprawdzić: przyłóż pionową linię do lewej krawędzi pierwszej kontrolki w każdej sekcji.
  - Naprawa: Qt: `QLabel.setMinimumWidth` na etykietach `QFormLayout` lub `FormSection`; Tk: wspólny `columnconfigure(0, minsize=...)` lub `uniform` w gridzie -> component-patterns.md §3.
- [ ] Kontrolki tej samej roli (np. wszystkie pola czasu) mają tę samą szerokość.
  - Jak sprawdzić: porównaj szerokości spinboxów i comboboxów na zrzucie.
  - Naprawa: Qt: `setMinimumWidth` + `QSizePolicy.Fixed` dla pól liczbowych, `Expanding` tylko dla tekstowych; Tk: `width=` w znakach dla liczbowych, `sticky="ew"` + `weight` tylko dla tekstowych -> component-patterns.md §3.
- [ ] Gęstość: wiersz formularza 28-32 px wysokości plus 8 px odstępu; brak pustych dziur i brak ściśniętych rzędów.
  - Jak sprawdzić: policz wiersze na wysokość sekcji.
  - Naprawa: stała wysokość kontrolek (Qt `min-height` w QSS, Tk `padding` w stylu), odstępy tylko z `SPACING` -> design-tokens.md §Skala odstępów.
- [ ] Sekcje odpowiadają etapom pracy i są w kolejności przepływu (wejście -> analiza -> wygląd -> eksport); żadna sekcja nie ma więcej niż ok. 7-9 kontrolek.
  - Jak sprawdzić: opisz zadanie użytkownika krok po kroku i porównaj z kolejnością sekcji.
  - Naprawa: podział na podsekcje, sekcje zwijane albo zakładki -> component-patterns.md §2.
- [ ] Przy zmianie rozmiaru okna rozciągają się właściwe elementy (podgląd, oś czasu, pola tekstowe), a inspektor zachowuje stałą lub ograniczoną szerokość.
  - Jak sprawdzić: zmień rozmiar okna od minimum do pełnego ekranu; obserwuj, co się rozjeżdża.
  - Naprawa: Qt: `QSplitter.setStretchFactor(0, 0)` / `(1, 1)`; Tk: `rowconfigure/columnconfigure(weight=1)` tylko dla obszaru roboczego, `ttk.PanedWindow` między inspektorem i podglądem -> qt-pyside6.md §5 / tkinter-ttk.md §5.
- [ ] Minimalny rozmiar okna ustawiony tak, że nic się nie ucina (`minsize`), a przy 1366x768 i 125 % DPI aplikacja jest używalna.
  - Jak sprawdzić: `wm minsize`, test na małej rozdzielczości.
  - Naprawa: Qt `win.setMinimumSize(w, h)`; Tk `root.minsize(w, h)` liczone od rozmiaru wymaganego (`winfo_reqwidth`) -> qt-pyside6.md §5 / tkinter-ttk.md §5.
- [ ] Jeśli inspektor się przewija: pasek przylega do treści, kółko myszy działa nad całą zawartością, nie ma podwójnych pasków (panel + pole tekstowe).
  - Jak sprawdzić: przewiń kółkiem nad etykietą, nad spinboxem i nad polem tekstowym.
  - Naprawa: Qt: `QScrollArea` bez ramki + filtr kółka nad spinboxami (w Piro `WheelGuard`); Tk: `ScrollableFrame` z `bind_mousewheel` i ochroną spinboxów -> qt-pyside6.md §5 / tkinter-ttk.md §5.
- [ ] Jest miejsce na akcje globalne (pasek narzędzi lub menu) i na komunikaty (pasek stanu).
  - Jak sprawdzić: gdzie użytkownik widzi wynik ostatniej operacji?
  - Naprawa: -> component-patterns.md §10 (pasek stanu), qt-pyside6.md §5 (pasek akcji).

## B. Typografia

- [ ] Jedna rodzina UI (`font_ui`) i najwyżej 4 nazwane rozmiary (`font_ui_small`, `font_ui`, `font_section`, `font_title`) plus `font_mono` dla wartości technicznych.
  - Jak sprawdzić: `grep -n "font=\|setFont\|QFont(\|font-size"` i policz odmienne definicje.
  - Naprawa: Qt `app.setFont(make_font("font_ui"))` + role `title|section|muted|mono` w QSS; Tk nazwane fonty (`tkinter.font.nametofont`, `font.Font(name=...)`) -> design-tokens.md §Typografia; qt-pyside6.md §6 / tkinter-ttk.md §2.
- [ ] Rozmiar bazowy co najmniej 10 pt (domyślne 9 pt Segoe UI w Tk na Windows wygląda drobno).
  - Jak sprawdzić: Qt `QApplication.font().pointSize()`; Tk `font.nametofont("TkDefaultFont").actual()`.
  - Naprawa: Qt `apply_theme` ustawia font 10 pt na aplikacji i w QSS; Tk nadpisz `TkDefaultFont`, `TkTextFont`, `TkMenuFont` na starcie -> qt-pyside6.md §2 / tkinter-ttk.md §2.
- [ ] Nagłówki sekcji odróżnia waga i rozmiar (`font_section`), nie ramka wokół sekcji.
  - Jak sprawdzić: czy tytuł sekcji ma ten sam font co etykiety pól?
  - Naprawa: `FormSection`/`SectionHeader` zamiast `QGroupBox` z ramką lub `ttk.LabelFrame` -> component-patterns.md §2; scripts/qt_widgets.py / scripts/widgets.py.
- [ ] Wartości liczbowe i czasy wyrównane (do prawej lub `font_mono`), tak by cyfry tworzyły kolumny.
  - Jak sprawdzić: porównaj kilka spinboxów czasu w pionie.
  - Naprawa: Qt `setAlignment(Qt.AlignRight)` na spinboxach lub `role=mono`; Tk `justify="right"` w Entry/Spinbox lub `font_mono` -> design-tokens.md §Typografia.
- [ ] Długie teksty (ścieżki) skracane z elipsą na początku lub w środku i pokazywane w całości w tooltipie; etykiety przycisków nie są ucinane.
  - Jak sprawdzić: wczytaj plik z bardzo długiej ścieżki; przełącz język.
  - Naprawa: `PathField` (Qt: `QFontMetrics.elidedText`; Tk: pomiar `font.measure`) + tooltip z pełną wartością -> component-patterns.md §6.
- [ ] Teksty PL i EN mieszczą się w tych samych kontrolkach (PL zwykle o 20-30 % dłuższy).
  - Jak sprawdzić: przełącz język w aplikacji i porównaj zrzuty.
  - Naprawa: szerokości od treści (Qt bez `setFixedWidth` na przyciskach; Tk bez `width=` w znakach), rozciąganie tylko pól tekstowych -> component-patterns.md §12.
- [ ] Kontrast tekstu co najmniej 4.5:1 (małe teksty), 3:1 dla tekstu 18 pt+ lub 14 pt bold.
  - Jak sprawdzić: -> C.
  - Naprawa: tokeny `text`, `text_muted` -> design-tokens.md §Weryfikacja kontrastu.
- [ ] Spójna konwencja etykiet: wszystkie z dwukropkiem albo żadna; ta sama wielkość liter; jednostki w jednym miejscu.
  - Jak sprawdzić: przejrzyj etykiety sekcja po sekcji.
  - Naprawa: słownik i18n porządkuje teksty; zmiana bez modyfikacji kluczy -> component-patterns.md §12.

## C. Kolor i motyw

- [ ] Paleta neutralna (szarości) plus jeden akcent; akcent tylko dla akcji primary, zaznaczenia, fokusu, aktywnych markerów.
  - Jak sprawdzić: policz odmienne kolory na zrzucie poza obrazem wideo.
  - Naprawa: tokeny -> design-tokens.md §Paleta DARK / §Paleta LIGHT.
- [ ] Jedna estetyka w całym oknie (nie: jasny inspektor obok czarnej osi czasu i czarnego podglądu).
  - Jak sprawdzić: porównaj tło inspektora, tło osi czasu i pasy letterboxu.
  - Naprawa: ciemny motyw domyślny dla narzędzia wideo; letterbox w `bg` -> design-tokens.md §Zasady.
- [ ] Kontrast WCAG AA: tekst 4.5:1, elementy UI (ramki pól, ikony, fokus, markery) 3:1.
  - Jak sprawdzić: próbnik koloru + kalkulator kontrastu; wynik dla tokenów jest w -> design-tokens.md §Weryfikacja kontrastu.
  - Naprawa: użyj tylko zweryfikowanych par tokenów.
- [ ] Oba motywy (dark/light) działają, przełączanie nie wymaga restartu lub restart jest komunikowany.
  - Jak sprawdzić: przełącz motyw; szukaj kolorów zaszytych na stałe: `grep -n "setStyleSheet\|QColor(\|#[0-9A-Fa-f]\{6\}\|\"white\"\|\"black\""`.
  - Naprawa: wszystkie kolory z `TOKENS[mode]` (Qt: `current_tokens(app)` w rysowaniu, role/kind w QSS) -> scripts/qt_theme.py / scripts/theme_template.py.
- [ ] Elementy poza zasięgiem stylu bazowego mają kolory z tokenów: w Qt popup `QComboBox`, viewport `QScrollArea`, `QToolTip`, `QMenu` (reguły w globalnym QSS); w Tk widżety klasyczne (`tk.Text`, `tk.Canvas`, `tk.Listbox`, `tk.Menu`, `tk.Toplevel`) z `bg`, `fg`, `insertbackground`, `selectbackground`, `highlightthickness`.
  - Jak sprawdzić: w motywie ciemnym szukaj białych prostokątów.
  - Naprawa: Qt reguły `QComboBox QAbstractItemView`, `QScrollArea > QWidget > QWidget` w `build_qss`; Tk `option_add` w `apply_theme` i `_retint_tk_widgets` dla już istniejących -> qt-pyside6.md §3 / tkinter-ttk.md §2, §4.
- [ ] Kolory semantyczne (`danger`, `success`, `warning`, `info`) użyte wyłącznie dla znaczenia, nigdy jako dekoracja; czerwony nie oznacza "koniec zakresu".
  - Jak sprawdzić: dla każdego czerwonego/zielonego elementu zapytaj "co komunikuje?".
  - Naprawa: markery zakresu w neutralnym lub akcencie, semantyka tylko dla stanów -> design-tokens.md §Stany; component-patterns.md §8.
- [ ] Akcent aplikacji zgodny z brandem produktu (tu: bursztyn nakładki), ale w motywie jasnym w odmianie ciemniejszej do tekstu i ramek.
  - Jak sprawdzić: żółty tekst na białym tle to zawsze błąd kontrastu.
  - Naprawa: `accent` per motyw -> design-tokens.md §Paleta LIGHT (sekcja "Dlaczego akcent w LIGHT nie jest żółty").

## D. Kontrolki i formularze

- [ ] Kontrolka pasuje do zadania: 2-3 opcje wykluczające -> segmented control lub radio w jednym rzędzie; 4+ opcji -> Combobox readonly; wartość ciągła z zakresem -> Scale plus pole; wartość precyzyjna -> Spinbox.
  - Jak sprawdzić: dla każdej kontrolki spisz liczbę i typ wartości.
  - Naprawa: -> component-patterns.md §4.
- [ ] Jednostki są widoczne przy polu (sufiks "s", "px", "%") i spójne; format czasu jest jeden w całej aplikacji (np. `m:ss.d`) z jednym separatorem dziesiętnym.
  - Jak sprawdzić: wypisz wszystkie wystąpienia czasu z ekranu i porównaj zapisy.
  - Naprawa: pole czasu (`NumberField` z sufiksem " s" i locale lub własne pole `m:ss.d`) z parserem akceptującym "37,6", "37.6", "0:37.6" i formaterem jednego wyjścia -> component-patterns.md §4, §12.
- [ ] Wartości domyślne sensowne dla typowego przypadku; puste pola mają placeholder lub podpowiedź.
  - Jak sprawdzić: uruchom aplikację bez zapisanych ustawień.
  - Naprawa: defaults w jednym miejscu, bez zmiany nazw kluczy ustawień.
- [ ] Walidacja inline: ramka w kolorze `danger` i krótki komunikat pod polem; nie messagebox przy każdej literówce.
  - Jak sprawdzić: wpisz "abc" w pole liczbowe.
  - Naprawa: Qt `QDoubleValidator` + właściwość `invalid="true"` + `InlineMessage`; Tk `validatecommand` + styl `Invalid.TEntry` -> qt-pyside6.md §8 / tkinter-ttk.md §8; component-patterns.md §3.
- [ ] Spinbox ma ustawione `from_`, `to`, `increment`, `format`, obsługuje wpisywanie i kółko myszy, ale kółko nad spinboxem nie zmienia wartości podczas przewijania panelu.
  - Jak sprawdzić: przewiń panel kółkiem, gdy kursor mija spinbox.
  - Naprawa: zmiana wartości kółkiem tylko gdy spinbox ma fokus (Qt: filtr zdarzeń `QEvent.Wheel`, w Piro `WheelGuard`; Tk: `bind_mousewheel`) -> qt-pyside6.md §8 / tkinter-ttk.md §5.
- [ ] Hierarchia przycisków: jeden primary (akcent) na widok lub sekcję, pozostałe secondary, pomocnicze jako ghost/link; akcje destrukcyjne z potwierdzeniem.
  - Jak sprawdzić: czy na pierwszy rzut oka wiadomo, który przycisk jest "następnym krokiem"?
  - Naprawa: Qt `kind=primary|secondary|ghost|danger`; Tk style `Accent.TButton`, `TButton`, `Ghost.TButton`, `Danger.TButton` -> qt-pyside6.md §4 / tkinter-ttk.md §4; component-patterns.md §7.
- [ ] Etykiety przycisków to czasowniki z dopełnieniem ("Wybierz plik", "Wykryj sygnał"), bez "OK", "..." ani skrótów technicznych.
  - Jak sprawdzić: przeczytaj same etykiety przycisków bez kontekstu.
  - Naprawa: ikona folderu + tooltip zamiast "..." -> design-tokens.md §Ikony.
- [ ] Wybór koloru: próbka (swatch), zapis hex, alfa jako procent, przycisk otwierający `colorchooser`; nie tekst "RGBA 0,0,0,170" na przycisku.
  - Jak sprawdzić: czy widać kolor bez czytania liczb?
  - Naprawa: `ColorSwatchButton` -> component-patterns.md §5; scripts/qt_widgets.py / scripts/widgets.py.
- [ ] Pola tylko do odczytu odróżnione (`state="readonly"`, tło `surface_alt`, brak kursora) od edytowalnych.
  - Jak sprawdzić: kliknij w pole i spróbuj pisać.
  - Naprawa: Qt `:read-only` w QSS (`setReadOnly(True)`); Tk styl readonly -> qt-pyside6.md §4 / tkinter-ttk.md §4.
- [ ] Pary powiązanych pól (od/do, X/Y) w jednym wierszu z własnymi krótkimi etykietami ("Od", "Do"), nie jedna etykieta "Przytnij od / do" dla dwóch pól.
  - Jak sprawdzić: czy da się pomylić, które pole jest które?
  - Naprawa: para pól w jednym wierszu z podetykietami (Qt `FormSection.add_pair_row`; Tk `FormGrid`) -> component-patterns.md §3.
- [ ] Kontrolki zależne są wyłączane, gdy nadrzędna opcja jest wyłączona (np. grubość obramowania przy odznaczonym "Włącz obramowanie").
  - Jak sprawdzić: odznacz opcje nadrzędne i obserwuj pola zależne.
  - Naprawa: Qt `setEnabled(False)` w slocie `toggled`; Tk `state(["disabled"])` w callbacku zmiennej -> qt-pyside6.md §8 / tkinter-ttk.md §3.
- [ ] Rozmiary: wysokość kontrolki 28-32 px, min. szerokość przycisku 80 px, padding poziomy 12 px, cel kliknięcia >= 24 px.
  - Jak sprawdzić: zmierz na zrzucie w 100 % DPI.
  - Naprawa: Qt `min-height`/`padding` w QSS; Tk `padding` w stylach -> design-tokens.md §Skala odstępów.

## E. Stany i feedback

- [ ] Stany hover, pressed, focus, disabled są widoczne i zgodne z tabelą stanów.
  - Jak sprawdzić: najedź, przytrzymaj, tabuluj, wyłącz kontrolkę; zrób zrzut każdego stanu.
  - Naprawa: Qt pseudo-stany `:hover :pressed :focus :disabled` w QSS; Tk `style.map(...)` -> design-tokens.md §Stany; qt-pyside6.md §3 / tkinter-ttk.md §3.
- [ ] Długie operacje (pobieranie z API, analiza audio, wykrywanie, render) pokazują postęp: Progressbar determinate, gdy znany procent, indeterminate w przeciwnym razie; przycisk anulowania; przyciski wywołujące są wtedy disabled.
  - Jak sprawdzić: uruchom operację i spróbuj przesunąć okno; poszukaj `QThread`, `QRunnable`, `threading`, `after`, `queue` w kodzie.
  - Naprawa: Qt `QThread` + sygnały + `set_busy` + `QProgressBar.setRange(0, 0)`; Tk worker + `queue.Queue` + `after(50, poll)` -> component-patterns.md §10; qt-pyside6.md §9 / tkinter-ttk.md §9.
- [ ] Komunikat błędu mówi, co się stało i co zrobić; szczegóły techniczne (traceback) schowane pod "Szczegóły"; nic nie znika cicho.
  - Jak sprawdzić: odłącz sieć i kliknij "Pobierz"; podaj nieistniejący plik.
  - Naprawa: komunikat trzyczęściowy (co, dlaczego, co zrobić) + szczegóły techniczne pod przyciskiem (Qt `QMessageBox.setDetailedText`) -> component-patterns.md §10.
- [ ] Wynik operacji jest komunikowany (pasek stanu lub toast), nie tylko przez cichą zmianę szarej etykiety.
  - Jak sprawdzić: po udanej operacji zapytaj "skąd wiem, że się udało?".
  - Naprawa: pasek stanu z kolorem stanu (Qt `status_message`, Tk `StatusBar`) -> component-patterns.md §10.
- [ ] Stany puste: brak wideo -> komunikat w obszarze podglądu z przyciskiem "Otwórz wideo"; brak danych -> wskazówka, co zrobić.
  - Jak sprawdzić: uruchom aplikację bez pliku.
  - Naprawa: stan pusty (ikona, tytuł `role=title`, podpowiedź `role=muted`, przycisk primary) -> component-patterns.md §10.
- [ ] Kursor odzwierciedla stan: `watch` w trakcie pracy, `fleur`/`hand2` przy przeciąganiu.
  - Jak sprawdzić: obserwuj kursor nad markerami i podczas operacji.
  - Naprawa: Qt `setCursor(Qt.SizeHorCursor)` / `Qt.ClosedHandCursor` w `mouseMoveEvent`; Tk `widget.configure(cursor=...)` w handlerach.
- [ ] Zmiany ustawień są zapisywane (autosave lub jawny zapis) i użytkownik o tym wie.
  - Jak sprawdzić: zmień wartość, zamknij, uruchom ponownie.
  - Naprawa: komunikat w pasku stanu; bez zmiany formatu pliku ustawień.

## F. Nawigacja i klawiatura

- [ ] Kolejność Tab zgodna z kolejnością wizualną (góra-dół, lewo-prawo) w każdej sekcji.
  - Jak sprawdzić: tabuluj przez cały panel od pierwszego pola.
  - Naprawa: Qt `QWidget.setTabOrder(a, b)`; Tk kolejność tworzenia widżetów lub `lift()` -> qt-pyside6.md §8 / tkinter-ttk.md §8.
- [ ] Skróty dla głównych akcji: Ctrl+O otwórz, Ctrl+S zapisz, Spacja odtwarzaj/pauza, strzałki i Home/End na osi czasu, Ctrl+R lub F5 render; skróty widoczne w menu i tooltipach.
  - Jak sprawdzić: `grep -n "setShortcut\|QShortcut\|bind(\"<"` i porównaj z listą.
  - Naprawa: Qt `QAction.setShortcut` w `QToolBar`/menu + `QShortcut`; Tk `root.bind_all` + akceleratory w `Menu` -> qt-pyside6.md §5, §8 / tkinter-ttk.md §8; component-patterns.md §11.
- [ ] Dialogi: Enter zatwierdza, Escape zamyka, przycisk domyślny wyróżniony (`default="active"`), fokus startowy w pierwszym polu.
  - Jak sprawdzić: otwórz każdy dialog i naciśnij Enter, Escape.
  - Naprawa: Qt `QDialog` + `QDialogButtonBox` (Enter/Escape automatycznie), OK jako `kind=primary`; Tk `Toplevel` z `transient` + `grab_set` + bind Return/Escape -> qt-pyside6.md §4 / tkinter-ttk.md §8.
- [ ] Fokus jest widoczny na każdej kontrolce (pierścień 2 px w kolorze `focus`), także na przyciskach akcentowych i na Canvas.
  - Jak sprawdzić: tabuluj przy motywie ciemnym i jasnym.
  - Naprawa: Qt reguły `:focus` (ramka 2 px `focus`) i `_focus_ring` w widżetach malowanych; Tk mapowanie `focuscolor`/`bordercolor` na stan `focus`, `highlightthickness` na Canvas -> qt-pyside6.md §8 / tkinter-ttk.md §8; design-tokens.md §Stany.
- [ ] Mnemoniki (`underline=`) w menu i najważniejszych przyciskach; Alt otwiera menu.
  - Jak sprawdzić: naciśnij Alt.
  - Naprawa: Qt `&` w tekście akcji/przycisku; Tk `underline` + `bind("<Alt-KeyPress-x>")` -> qt-pyside6.md §5 / tkinter-ttk.md §8.
- [ ] Combobox i Spinbox obsługują strzałki, PageUp/PageDown, wpisywanie z autouzupełnianiem; Combobox readonly nie pozwala na "dziwne" wartości.
  - Jak sprawdzić: klawiatura na każdej liście.
  - Naprawa: Qt `QComboBox` nieedytowalny (domyślnie) + `currentIndexChanged`; Tk `state="readonly"` + `bind("<<ComboboxSelected>>")`.
- [ ] Ustawienia i "O programie" dostępne z menu lub przycisku, nie tylko ukryte w przewijanym panelu.
  - Jak sprawdzić: znajdź w 5 sekund wersję aplikacji i preferencje.
  - Naprawa: menu główne lub przycisk "..." w pasku narzędzi (Qt `QToolBar` + `QAction`, qt-pyside6.md §5).

## G. Ikony i grafika

- [ ] Jeden spójny zestaw ikon (glify Segoe Fluent Icons albo jeden pakiet PNG/SVG); nie mieszamy emoji, symboli Unicode i bitmap.
  - Jak sprawdzić: spisz wszystkie ikony i ich źródło.
  - Naprawa: -> design-tokens.md §Ikony.
- [ ] Rozmiary ikon: 16 px inline i w menu, 20 px w paskach narzędzi, 24 px dla dużych akcji; ikona wyśrodkowana w pionie z tekstem.
  - Jak sprawdzić: zmierz na zrzucie 100 %.
  - Naprawa: Qt `setIconSize(QSize(16, 16))` i SVG; Tk rozmiar fontu glifów w pt przeliczony z px (-> design-tokens.md §Typografia).
- [ ] HiDPI: ikony nie są rozmyte przy 125/150/200 %; glify skalują się przez `tk scaling`, bitmapy mają warianty lub są renderowane z SVG przy starcie.
  - Jak sprawdzić: zrzuty na 150 % i 200 %.
  - Naprawa: -> design-tokens.md §Ikony; qt-pyside6.md §6, §7 (SVG) / tkinter-ttk.md §6.
- [ ] Brak pikselozy z `PhotoImage.zoom/subsample` o ułamkowych współczynnikach.
  - Jak sprawdzić: `grep -n "zoom(\|subsample("`.
  - Naprawa: skalowanie w Pillow (`Image.resize` z LANCZOS) przed `ImageTk`.
- [ ] Każda ikona bez tekstu ma tooltip; ikona-tylko dopuszczalna dla transportu (odtwarzaj, pauza, klatka) i akcji standardowych (zamknij, ustawienia).
  - Jak sprawdzić: najedź na każdą ikonę.
  - Naprawa: Qt `setToolTip`; Tk `Tooltip` -> component-patterns.md §11.
- [ ] Ikona aplikacji w tytule i na pasku zadań w rozmiarach 16/32/48/256 (`iconbitmap` z .ico lub `iconphoto` z kilkoma PNG).
  - Jak sprawdzić: pasek zadań i Alt+Tab.
  - Naprawa: -> qt-pyside6.md §6 / tkinter-ttk.md §6.

## H. Okno i platforma

- [ ] Tytuł okna: "Nazwa pliku - Aplikacja" lub sama nazwa aplikacji; numer wersji w "O programie", nie w tytule.
  - Jak sprawdzić: pasek tytułu.
  - Naprawa: `root.title(f"{filename} - Piro Overlay")` aktualizowany po wczytaniu pliku.
- [ ] Ciemny pasek tytułu przy motywie ciemnym (Windows: `DwmSetWindowAttribute` z atrybutem immersive dark mode; szczegóły i pułapki w -> qt-pyside6.md §6 / tkinter-ttk.md §6).
  - Jak sprawdzić: zrzut przy motywie ciemnym.
  - Naprawa: `set_windows_dark_titlebar` po `show()` (Qt) lub `update_idletasks()` (Tk), z obsługą wyjątku na starszych Windows.
- [ ] Geometria okna zapamiętywana i przywracana z walidacją (monitor odłączony, okno poza ekranem, stan zmaksymalizowany).
  - Jak sprawdzić: przenieś okno na drugi monitor, zamknij, odłącz monitor, uruchom.
  - Naprawa: Qt `saveGeometry`/`restoreGeometry` + `QSettings` (`save_window_state`); Tk zapis `geometry()` + `state()` z walidacją `winfo_screenwidth/height` -> qt-pyside6.md §2 / tkinter-ttk.md §5.
- [ ] HiDPI ustawione przed utworzeniem aplikacji: Qt `setHighDpiScaleFactorRoundingPolicy(PassThrough)` przed `QApplication`; Tk `SetProcessDpiAwareness` przed `Tk()` i `tk scaling` zgodne z DPI. Test 100/125/150/200 %.
  - Jak sprawdzić: zrzuty przy każdym DPI; rozmyte fonty oznaczają brak awareness.
  - Naprawa: -> qt-pyside6.md §6 / tkinter-ttk.md §6.
- [ ] Dialogi natywne (Qt `QFileDialog`, `QColorDialog`, `QMessageBox`; Tk `filedialog`, `colorchooser`, `messagebox`) tam, gdzie istnieją; własne dialogi są modalne, wyśrodkowane nad rodzicem, zamykane Escape.
  - Jak sprawdzić: otwórz każdy dialog.
  - Naprawa: Qt `QDialog` + `QDialogButtonBox`; Tk `Toplevel` z `transient` + `grab_set` -> qt-pyside6.md §4 / tkinter-ttk.md §8.
- [ ] Konwencje Windows 11 Fluent: subtelne ramki 1 px, zaokrąglenia 4-8 px tam, gdzie framework pozwala, brak efektów 3D, domyślnego stylu "windowsvista" (Qt) i motywu "vista" w LabelFrame (Tk), ciche kolory powierzchni.
  - Jak sprawdzić: porównaj z Ustawieniami Windows 11.
  - Naprawa: Qt styl `Fusion` + QPalette + QSS z tokenów; Tk motyw `clam` jako baza + tokeny -> qt-pyside6.md §2 / tkinter-ttk.md §2, §3; component-patterns.md §14; migration-options.md, gdy framework nie wystarcza.
- [ ] Zamykanie okna z niezapisanymi zmianami pyta o potwierdzenie; `WM_DELETE_WINDOW` obsłużone; wątki robocze kończone.
  - Jak sprawdzić: zmień ustawienie i zamknij krzyżykiem.
  - Naprawa: Qt `closeEvent` (zatrzymanie workerów, `wait`); Tk `protocol("WM_DELETE_WINDOW", on_close)`.
- [ ] Tk: znane ograniczenie, Tk 8.6 nie obsługuje płynnie różnych DPI na wielu monitorach; udokumentowane w README lub w "O programie" (Qt 6 skaluje per ekran).
  - Jak sprawdzić: przeciągnij okno między monitorami o różnym DPI.
  - Naprawa: dokumentacja ograniczenia; rozważ -> migration-options.md.

## I. Specyfika narzędzi mediowych (podgląd wideo, oś czasu)

- [ ] Podgląd zachowuje proporcje źródła, letterbox w kolorze `bg` (nie czysta czerń na jasnym UI), brak rozciągania, klatka wyśrodkowana.
  - Jak sprawdzić: wczytaj wideo 16:9 i 9:16.
  - Naprawa: Qt `pixmap.scaled(size, KeepAspectRatio)` w `resizeEvent` z `QTimer` debounce; Tk obliczanie `fit` w `<Configure>` z debounce -> component-patterns.md §9.
- [ ] Nakładka w podglądzie odpowiada wynikowi renderu (WYSIWYG): skala, pozycja, font, alfa; skala UI (DPI) nie wpływa na skalę nakładki.
  - Jak sprawdzić: porównaj podgląd z klatką wyrenderowanego pliku.
  - Naprawa: rysowanie nakładki w współrzędnych wideo i skalowanie całości.
- [ ] Pasek transportu: odtwarzaj/pauza, klatka wstecz/naprzód, skok do markera, czas bieżący / całkowity w jednym formacie, suwak lub klik na osi.
  - Jak sprawdzić: czy da się obejrzeć moment startu bez renderu?
  - Naprawa: pasek transportu (Qt `QToolBar` z `QAction` lub `QToolButton(kind=ghost)`; Tk `Ghost.TButton` z ikonami) -> component-patterns.md §9; qt-pyside6.md §5.
- [ ] Oś czasu ma wskaźnik bieżącego czasu (playhead) zsynchronizowany z podglądem; klik na osi ustawia czas.
  - Jak sprawdzić: kliknij na osi.
  - Naprawa: warstwy (tło, fala, detekcje, markery, playhead) w `paintEvent` (Qt) lub na Canvas (Tk) -> component-patterns.md §8; qt-pyside6.md §7 / tkinter-ttk.md §7.
- [ ] Markery są nazwane, mają etykietę tekstową (nie tylko kolor), etykiety nie nachodzą na siebie (przesunięcie w pionie lub skrócenie), uchwyty do przeciągania >= 8 px, snapping do detekcji i do sekund.
  - Jak sprawdzić: ustaw dwa markery blisko siebie.
  - Naprawa: algorytm rozkładu etykiet w wierszach -> component-patterns.md §8; qt-pyside6.md §7.
- [ ] Zoom osi (Ctrl+kółko, przyciski +/-), przewijanie poziome, podziałka z sensownymi krokami (1/5/10/15/30/60 s) zależnie od zoomu.
  - Jak sprawdzić: czy da się ustawić marker z dokładnością 0.1 s przy 2-minutowym nagraniu?
  - Naprawa: -> component-patterns.md §8.
- [ ] Fala audio ma kontrast >= 3:1 względem tła; detekcje (strzały, kandydaci) to osobna warstwa z możliwością ukrycia; oś nie jest zaśmiecona setkami linii.
  - Jak sprawdzić: policz elementy na osi; zapytaj, które są potrzebne teraz.
  - Naprawa: warstwy + legenda + przełącznik -> component-patterns.md §8.
- [ ] Format czasu na osi, w polach i w markerach jest ten sam.
  - Jak sprawdzić: -> D.
  - Naprawa: jedna funkcja `format_time` używana wszędzie.
- [ ] Tryb edycji przez przeciąganie (pozycje nakładki) jest jawnym przełącznikiem z ikoną i widocznym stanem wciśniętym; Escape wychodzi; kursor się zmienia.
  - Jak sprawdzić: czy widać, że tryb jest aktywny?
  - Naprawa: przycisk przełączany (Qt `QToolButton.setCheckable(True)`; Tk `Toolbutton`) -> component-patterns.md §9.

## J. Wydajność UI

- [ ] UI nie zamiera: dekodowanie klatek, analiza audio, zapytania HTTP i render działają w wątku lub procesie; wynik wraca przez sygnały `QThread` (Qt) albo `queue` i `after` (Tk).
  - Jak sprawdzić: uruchom operację i przesuwaj okno; `grep -n "QThread\|QRunnable\|threading\|concurrent\|subprocess\|after("`.
  - Naprawa: -> component-patterns.md §10; qt-pyside6.md §9 / tkinter-ttk.md §9.
- [ ] Rysowanie własne odświeża tylko to, co trzeba: fala audio prerenderowana do obrazu (Qt cache `QPixmap`; Tk `PhotoImage`), markery i playhead na wierzchu; Tk Canvas przez `coords`/`itemconfigure`, nie `delete("all")` przy każdym ruchu myszy.
  - Jak sprawdzić: przeciągnij marker i obserwuj płynność; przejrzyj `paintEvent`/`mouseMoveEvent` (Qt) lub handler `<B1-Motion>` (Tk).
  - Naprawa: -> component-patterns.md §8; qt-pyside6.md §7 / tkinter-ttk.md §7.
- [ ] Debounce przy zmianie rozmiaru (Qt `QTimer.setSingleShot` restartowany w `resizeEvent`; Tk `after(60)` z anulowaniem poprzedniego w `<Configure>`) dla przeskalowania podglądu i osi.
  - Jak sprawdzić: szybko zmieniaj rozmiar okna.
  - Naprawa: jeden `QTimer` per widżet (Qt) lub helper `debounce(widget, ms, fn)` na `after` (Tk).
- [ ] Start aplikacji do pierwszego okna poniżej 2 s; ciężkie biblioteki (OpenCV, numpy, moviepy) importowane leniwie lub po pokazaniu okna.
  - Jak sprawdzić: `python -X importtime -m <moduł startowy>`.
  - Naprawa: import w funkcji, ekran startowy z paskiem stanu.
- [ ] Przeciąganie markerów i suwaka jest płynne (>= 30 aktualizacji/s); aktualizacja klatki podglądu throttlowana.
  - Jak sprawdzić: przeciągaj przez 5 s i obserwuj.
  - Naprawa: aktualizacja klatki dopiero po zatrzymaniu lub co N ms.

## K. Dostępność

- [ ] Cel kliknięcia >= 24x24 px: checkboxy, przyciski strzałek spinboxa, uchwyty markerów, przyciski transportu.
  - Jak sprawdzić: zmierz na zrzucie 100 %.
  - Naprawa: `min-height`/`padding` w QSS lub stylach ttk; uchwyty markerów jako niewidoczne prostokąty 12 px szerokości.
- [ ] Informacja nie jest przekazywana wyłącznie kolorem: markery mają etykiety, błędy ikonę i tekst, stany aktywne także zmianę kształtu lub tekstu.
  - Jak sprawdzić: zrzut w skali szarości.
  - Naprawa: -> design-tokens.md §Ikony (glify stanu).
- [ ] Kontrast tekstu i elementów UI spełnia AA (-> C).
  - Jak sprawdzić: -> design-tokens.md §Weryfikacja kontrastu.
  - Naprawa: tokeny.
- [ ] Rozmiar fontu systemowego i skalowanie DPI są respektowane (rozmiary w pt, nie w ujemnych pikselach; brak `tk scaling` zaszytego na stałe).
  - Jak sprawdzić: zmień skalowanie Windows na 150 %.
  - Naprawa: -> design-tokens.md §Typografia; qt-pyside6.md §6 / tkinter-ttk.md §6.
- [ ] Tooltipy dla ikon i skróconych etykiet; teksty pomocy dla pól o nieoczywistym znaczeniu ("Margines końcowy").
  - Jak sprawdzić: najedź na każdą kontrolkę.
  - Naprawa: Qt `setToolTip`; Tk `Tooltip` -> component-patterns.md §11.
- [ ] Tryb wysokiego kontrastu Windows nie łamie aplikacji (przynajmniej czytelna).
  - Jak sprawdzić: włącz motyw wysokiego kontrastu i zrób zrzut.
  - Naprawa: nie zaszywaj kolorów w rysowaniu własnym; przetestuj oba motywy.

## Szablon raportu z audytu

Nagłówek raportu: nazwa aplikacji i wersja, data, źródła (zrzuty, kod lub tylko zrzut), wykryty framework (PySide6/PyQt6, Tkinter/ttk, inny, albo "do potwierdzenia"), rozdzielczość i DPI zrzutów, język UI.

| # | Problem | Dowód (gdzie na ekranie) | Waga | Rekomendacja | Odwołanie |
|---|---|---|---|---|---|
| 1 | Krótki opis problemu (co i dlaczego to problem) | Sekcja / kontrolka po nazwie z ekranu, ewentualnie współrzędne | P0 / P1 / P2 | Konkretna zmiana, weryfikowalna zrzutem | np. component-patterns.md §3, qt-pyside6.md §4 lub litera grupy checklisty |

Po tabeli zawsze: "Kierunek redesignu" (wireframe ASCII, lista zamian kontrolek, plan w 3 iteracjach, czego nie zmieniamy). Wzór: `audit-example-piro-overlay.md`.

### Reguły ważenia

| Waga | Kryterium | Przykłady |
|---|---|---|
| P0 | Utrudnia wykonanie zadania lub powoduje błędy: brak feedbacku o wyniku, zamieranie UI, niespójny format wprowadzania danych, ukryta akcja główna, ucięte kontrolki | Brak paska transportu w narzędziu do synchronizacji; "37,60 s" obok "37.6s"; brak wskaźnika postępu przy pobieraniu |
| P1 | Wyraźnie przestarzałe lub niespójne, obniża zaufanie i czytelność, ale zadanie da się wykonać | LabelFrame w motywie vista; niewyrównane kolumny; angielska wartość w polskim UI; brak hierarchii przycisków |
| P2 | Polish: drobne niespójności, mikrotypografia, ikony, tooltipy, zaokrąglenia | Przycisk "..." zamiast ikony; etykieta z nawiasem; mieszane wcięcia checkboxów |

Zasady dodatkowe: problem oznaczony "do potwierdzenia w kodzie" dostaje wagę warunkową (np. "P0 jeśli potwierdzone"); jeden problem = jeden wiersz (nie łącz "kolory i fonty"); każdy wiersz ma dowód, który da się odnaleźć na zrzucie po nazwie kontrolki.
