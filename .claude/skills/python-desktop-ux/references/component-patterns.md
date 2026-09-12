# Wzorce komponentów: narzędzia "inspektor + podgląd"

Dokument opisuje wzorce UX dla desktopowych narzędzi w Pythonie, w których po lewej jest panel ustawień (inspektor), a po prawej obszar roboczy (podgląd wideo, oś czasu). Przykładem odniesienia jest Piro Overlay (nakładka timera strzeleckiego na wideo), ale wzorce są ogólne: edytory wideo/audio, konfiguratory, narzędzia batch.

Każdy wzorzec ma cztery części: **Kiedy** (warunek użycia), **Jak** (zasady i wymiary w tokenach z `design-tokens.md`), **Anty-wzorce** (co widać w starych aplikacjach Tk) oraz **Implementacja** (klasa z `scripts/widgets.py`, styl z `scripts/theme_template.py`, odpowiednik Qt z `qt-pyside6.md`). Sekcje są numerowane (§1..§14); inne pliki skilla odwołują się do tych numerów.

Dla aplikacji Qt (PySide6/PyQt6) czytaj w każdej "Implementacji" wariant Qt jako pierwszy: klasy pochodzą z `scripts/qt_widgets.py`, właściwości `kind`/`role`/`invalid` z arkusza w `scripts/qt_theme.py`, szczegóły API w `qt-pyside6.md`. Wariant Tk (`scripts/widgets.py`, `scripts/theme_template.py`, `tkinter-ttk.md`) jest drugi.

Zasady nadrzędne obowiązują we wszystkich wzorcach: odświeżenie UI nie zmienia logiki ani formatu ustawień, praca przyrostowa ze zrzutem po każdym kroku, i18n PL/EN, HiDPI 100/125/150/200%, klawiatura i fokus, UI nie zamiera.

## §1 Układ aplikacji

**Kiedy.** Aplikacja ma jeden główny dokument (wideo, projekt) i kilkanaście do kilkudziesięciu ustawień, które wpływają na podgląd.

**Jak.**

| Strefa | Rozmiar | Zachowanie przy zmianie okna |
|---|---|---|
| Inspektor (lewa) | szerokość stała 320..380 px przy 100% (`px(340)` jako start), przewijany w pionie | nie rozciąga się; użytkownik może zmienić szerokość uchwytem PanedWindow w zakresie 280..480 px |
| Podgląd (prawa, góra) | wypełnia resztę | rozciąga się w obu osiach, zachowuje proporcje wideo (§9) |
| Oś czasu (prawa, dół) | wysokość stała 120..160 px (§8) | rozciąga się tylko w poziomie |
| Pasek transportu | wysokość 40 px (kontrolki 32 px + 2 x sp_1) | tylko w poziomie |
| Pasek stanu | wysokość 24..28 px, `font_ui_small` | tylko w poziomie |

Kolejność od góry w prawej kolumnie: pasek narzędzi trybu (np. "Edytuj pozycję"), podgląd, pasek transportu, oś czasu. Pasek stanu leży pod obiema kolumnami, na całą szerokość okna.

Minimalny rozmiar okna: `root.minsize(px(960), px(600))` (Qt: `win.setMinimumSize(960, 600)`). Poniżej tej wartości oś czasu i inspektor przestają być użyteczne. Zapamiętuj geometrię między sesjami tylko jeśli aplikacja już to robi; nie dodawaj nowych kluczy do pliku ustawień bez uzgodnienia (zasada 1).

Warianty inspektora:

- **Przewijany, sekcje jedna pod drugą** (domyślny, do 5 sekcji). Nagłówki sekcji (§2) są zawsze widoczne w toku przewijania, bo mają kontrastowy styl.
- **Zwijane sekcje** (5..8 sekcji). Każdy nagłówek ma strzałkę i kliknięcie zwija treść. Stan zwinięcia trzymaj w pamięci procesu; do pliku ustawień zapisuj tylko, jeśli aplikacja ma już sekcję "ui" w ustawieniach.
- **Zakładki** (powyżej 5 sekcji, gdy sekcje są niezależne, np. "Wejście", "Nakładka", "Eksport"). `ttk.Notebook` (Qt: `QTabWidget`) w inspektorze, każda zakładka to własny przewijany panel. Nie mieszaj zakładek i zwijania w jednym panelu.

**Anty-wzorce.**

- Inspektor rozciągany razem z oknem: pola formularza stają się szerokie na 400 px, a podgląd traci miejsce.
- Podgląd w stałym rozmiarze i oś czasu rozciągana w pionie: fala audio "puchnie", a wideo jest małe.
- Brak paska stanu i transportu: użytkownik nie wie, w jakim trybie jest aplikacja ani jak przewinąć wideo.
- `pack(side=LEFT)` dla całego układu bez `PanedWindow`: szerokość inspektora nie daje się zmienić.

**Implementacja.** Qt: `QSplitter(Qt.Horizontal)` z `setStretchFactor(0, 0)` / `(1, 1)` i `setChildrenCollapsible(False)`; lewy panel to `QScrollArea` (`setWidgetResizable(True)`, bez ramki) z widgetem `role=inspector`, prawy `QVBoxLayout` z podglądem `stretch=1`; `QStatusBar` z helperem `status_message` z `scripts/qt_widgets.py`; geometria okna i splittera przez `save_window_state` / `restore_window_state` z `scripts/qt_theme.py` (qt-pyside6.md §2, §5). Tk: `ttk.PanedWindow(orient="horizontal")` z dwoma panelami; lewy to `ScrollableFrame` w `Sidebar.TFrame`, prawy to `ttk.Frame` z `grid` (wiersz podglądu `weight=1`, pozostałe `weight=0`); `StatusBar` gridowany pod PanedWindow (tkinter-ttk.md §5).

## §2 Sekcje inspektora

**Kiedy.** Zawsze, gdy w panelu jest więcej niż ok. 6 kontrolek.

**Jak.**

- Nagłówek sekcji to etykieta w `font_section` (11 bold), kolor `text`, opcjonalnie cienka linia 1 px w `border` pod nagłówkiem lub po prawej stronie tekstu. Nie używaj `ttk.LabelFrame` ani `QGroupBox` z ramką: ramka dookoła treści dodaje wizualny szum i źle wygląda w ciemnym motywie (vista rysuje jasną ramkę systemową).
- Odstęp między sekcjami: `sp_6` (24 px). Odstęp między wierszami w sekcji: `sp_2` (8 px); między grupami wierszy w tej samej sekcji (np. "Czas" i "Pozycja"): `sp_3` (12 px).
- Kolejność sekcji odpowiada przepływowi pracy, od źródła do wyniku: **Wejście** (plik wideo, plik audio, ścieżki) -> **Synchronizacja i przycięcie** (T0, Od, Do, wykrywanie) -> **Wygląd nakładki** (pozycja, kolory, czcionka) -> **Eksport** (format, ścieżka wyjściowa, przycisk główny).
- Rzadko używane opcje (offsety kalibracyjne, progi detekcji) idą do sekcji "Zaawansowane" na końcu, domyślnie zwiniętej. Kryterium: opcja zmieniana rzadziej niż raz na projekt.
- Zwijanie: strzałka `▸/▾` po lewej nagłówka, cały nagłówek jest klikalny (cel min. 24 px wysokości), fokus klawiaturą i Spacja/Enter przełącza.

**Anty-wzorce.**

- LabelFrame w LabelFrame (ramki zagnieżdżone).
- Sekcje w kolejności dodawania funkcji, nie w kolejności pracy.
- Sekcja "Inne" z 15 kontrolkami; jeśli sekcja przekracza ok. 10 wierszy, podziel ją.
- Nagłówek tym samym fontem co etykiety pól: użytkownik nie widzi struktury przy przewijaniu.

**Implementacja.** Qt: `FormSection(title, collapsible=True)` z `scripts/qt_widgets.py` zamiast `QGroupBox` (nagłówek `SectionHeader` + `QFormLayout` z odstępami z tokenów; metody `add_row`, `add_pair_row`, `add_widget_row`); sam nagłówek to `SectionHeader(title, collapsible)` z `set_content(widget)` i sygnałem `toggled`, etykieta ma `role=section`. Ścieżka minimalna bez zmian w kodzie: reguła QSS dla `QGroupBox` bez ramki z `build_qss` (qt-pyside6.md §4). Tk: `SectionHeader(parent, text, collapsible=True, content=frame)` z `scripts/widgets.py`, styl `Section.TLabel`; treść sekcji w `FormGrid`.

## §3 Formularze

**Kiedy.** Każda sekcja inspektora.

**Jak.**

- Dwie kolumny: etykieta po lewej w stałej kolumnie (szerokość ok. 120..140 px przy 100%, wyrównanie do lewej, `sticky="w"`), kontrolka po prawej. Etykieta i kontrolka w tej samej linii bazowej (`sticky="ew"` dla kontrolki, `pady=sp_1`).
- Jednostki jako sufiks po kontrolce, w `Muted.TLabel`: "s", "px", "%", "kl./s". Nie wpisuj jednostki do etykiety ("Offset (s)") ani do wartości ("37,60 s" w polu Entry; pole ma zawierać liczbę, jednostka jest obok).
- Pola liczbowe mają krok, zakres i wartość domyślną (§4). Spinbox z krokiem 0,1 s dla czasu, 1 px dla pozycji, 1 % dla skali.
- Help-text pod kontrolką tylko dla pól, które tego wymagają (np. "T0 = moment sygnału startu w nagraniu"), w `Muted.TLabel`, `font_ui_small`, max 2 linie, `wraplength` równy szerokości kolumny kontrolek.
- Walidacja inline: pole w stylu `Invalid.TEntry` (Qt: właściwość `invalid="true"`; obramowanie `danger`) + komunikat w `InlineMessage` z `kind="danger"` pod polem. Walidacja przy utracie fokusu (`<FocusOut>`) i przy zatwierdzeniu, nie po każdym znaku. Zakres komunikatu: co jest źle i jaki jest dopuszczalny zakres ("Wartość 0..3600 s").
- Zależności między polami: kontrolka zależna dostaje `state="disabled"`, gdy warunek nie jest spełniony (np. "Plik audio" wyłączony, gdy źródło dźwięku = "Z wideo"). Ukrywanie (`grid_remove`) stosuj tylko dla całych trybów, gdy ukryty zestaw ma więcej niż ok. 4 pola i nie ma sensu w danym trybie.
- Pary wartości w jednym wierszu: "Pozycja X / Y", "Od / Do", "Szerokość / Wysokość". Jedna etykieta, dwa pola z krótkimi podetykietami lub sufiksami.
- Szerokość pola dopasowana do treści: czas w sekundach `width=8`, piksele `width=6`, procent `width=5`, ścieżka pliku `sticky="ew"` (rozciągana). Pole nie musi wypełniać kolumny.
- Kolejność Tab zgodna z kolejnością wizualną (kolejność tworzenia widżetów w Tk).

**Anty-wzorce.**

- Etykiety nad kontrolkami w wąskim panelu: formularz robi się dwa razy wyższy.
- Wszystkie pola `sticky="ew"`: pole na "0,5" ma 250 px szerokości.
- Wartość z jednostką w polu tekstowym ("37,60 s"): parsowanie i lokalizacja się psują.
- Walidacja przez `messagebox.showerror` po każdym niepoprawnym znaku.
- Ukrywanie pojedynczej kontrolki: układ "skacze", użytkownik nie wie, że opcja istnieje.

**Implementacja.** Qt: `FormSection.add_row(label, field, unit=None, help_text=None)` i `add_pair_row(label, first, second)` z `scripts/qt_widgets.py` (pod spodem `QFormLayout` z `setLabelAlignment(Qt.AlignLeft)` i `ExpandingFieldsGrow`); `NumberField` dla liczb (`setSuffix`, `setInvalid`); `InlineMessage.show_message(text, kind)` pod polem; stan błędu przez `setProperty("invalid", "true")` + `repolish` (reguła `[invalid="true"]` w `scripts/qt_theme.py`); walidatory `QDoubleValidator` z `QLocale` (qt-pyside6.md §4, §8). Tk: `FormGrid(parent, label_width=130)` z metodami `row(label, widget_or_factory, unit=None, help_text=None)` i `full(widget)`; `NumberField` dla liczb; `InlineMessage.show(text, kind)` dla walidacji; styl `Invalid.TEntry`.

## §4 Dobór kontrolki

**Kiedy.** Przy każdym nowym polu i przy audycie istniejących.

**Jak.** Tabela decyzyjna:

| Typ wartości | Kontrolka | Uwagi |
|---|---|---|
| 2..3 opcje wykluczające, krótkie etykiety | `SegmentedControl` | wszystkie opcje widoczne bez klikania; np. "Źródło dźwięku: Wideo / Plik", "Format czasu: s / mm:ss" |
| 4..8 opcji | `ttk.Combobox(state="readonly")` | wartości tłumaczone (§12); szerokość wg najdłuższej opcji |
| więcej niż 8 opcji | Combobox z filtrowaniem po wpisaniu lub `ttk.Treeview` z jedną kolumną | np. lista czcionek, urządzeń |
| bool, efekt natychmiastowy, jedna opcja "włącz/wyłącz" | `Switch` | np. "Pokaż strzały na osi" |
| bool w grupie kilku niezależnych flag, zatwierdzane razem | `ttk.Checkbutton` | np. lista elementów eksportu |
| liczba, wąski zakres (do ok. 100 kroków), potrzebny podgląd na żywo | `ttk.Scale` + `NumberField` obok | suwak do zgrubnego, pole do dokładnego; np. przezroczystość 0..100 % |
| liczba, szeroki zakres lub wymagana precyzja | `NumberField` (Spinbox z walidacją) | krok, min, max, format; np. offset -10,0..10,0 s |
| czas | `NumberField` z sufiksem " s" (Qt `setSuffix`, Tk `unit="s"`) albo własne pole `m:ss.d` | jeden format w całej aplikacji (§12); pole akceptuje oba przy wpisywaniu, wyświetla jeden |
| kolor z alfą | `ColorSwatchButton` | §5 |
| ścieżka pliku/katalogu | `PathField` | §6 |
| wybór z podglądem (styl nakładki, szablon) | lista z miniaturami (Canvas lub Treeview z obrazkami) | miniatury 64..96 px, podpis pod miniaturą |
| pozycja nakładki (9 punktów: góra-lewo..dół-prawo) | siatka 3x3 przycisków przełączanych lub Combobox z tłumaczonymi nazwami | siatka jest czytelniejsza niż "bottom-left" w Comboboxie |

Reguły pomocnicze:

- Radiobuttony w pionie tylko wtedy, gdy etykiety są długie (ponad ok. 20 znaków) lub opcje wymagają opisu pod każdą.
- Combobox edytowalny (`state="normal"`) tylko gdy użytkownik naprawdę może wpisać własną wartość.
- Scale bez pola liczbowego nie pozwala wpisać dokładnej wartości; zawsze paruj z polem.

**Anty-wzorce.**

- Trzy Radiobuttony w pionie na "tak/nie/auto": zajmują 3 wiersze, SegmentedControl zajmuje jeden.
- Combobox na 2 wartości.
- Checkbutton z etykietą będącą negacją ("Nie pokazuj podglądu").
- Spinbox bez `from_`/`to`: użytkownik może wpisać -999.

**Implementacja.** Qt: `SegmentedControl([(klucz, etykieta), ...])` (`value()`, `set_value`, `set_label`, sygnał `currentChanged`), `Switch(text)`, `NumberField(minimum, maximum, step, decimals, suffix, value, locale)`, `ColorSwatchButton(rgba)`, `PathField(mode, filter, placeholder)` z `scripts/qt_widgets.py`; `QComboBox.addItem(etykieta, klucz)` z odczytem `currentData()`; `QSlider` + `NumberField`; `QListWidget` w trybie `IconMode` dla miniatur (qt-pyside6.md §4). Tk: klasy `SegmentedControl`, `Switch`, `NumberField`, `ColorSwatchButton`, `PathField` z `scripts/widgets.py` (każda przyjmuje zmienną Tk).

## §5 Kolor z kanałem alfa

**Kiedy.** Kolor tła nakładki, kolor tekstu, kolor akcentu; wszędzie, gdzie użytkownik ustawia RGBA.

**Jak.**

- Kontrolka to przycisk-swatch o wysokości 32 px i szerokości ok. 96..120 px: po lewej próbka koloru (kwadrat 20 x 20 px z promieniem `r_sm`), po prawej tekst hex `#FFC400` i alfa jako procent `67 %` w `font_mono`. Pod półprzezroczystą próbką rysuj szachownicę (kwadraty 4 px, `surface` i `surface_alt`), inaczej alfa jest niewidoczna.
- Kliknięcie otwiera dialog: `tkinter.colorchooser.askcolor` nie obsługuje alfy, więc dialog własny (Toplevel) lub askcolor dla RGB + `Scale` 0..255 dla alfy w popoverze pod przyciskiem. Suwak alfy z podglądem próbki na żywo.
- Presety: 6..8 kolorów w rzędzie (czarny 67 %, biały, akcent `#FFC400`, czerwony, zielony, przezroczysty). Presety odpowiadają zestawom, które użytkownicy wybierają najczęściej; zmieniaj je tylko za zgodą właściciela aplikacji.
- Pole hex edytowalne (akceptuj `#RRGGBB`, `#RRGGBBAA`, `RRGGBB`), alfa jako procent lub 0..255, ale wyświetlaj jedno (procent jest czytelniejszy dla użytkownika końcowego, 0..255 dla technicznego; wybierz zgodnie z resztą aplikacji).
- Kontrast: pod próbką pokazuj miniaturę "tekst na tle" (np. "START" w kolorze tekstu na kolorze tła nakładki), aby użytkownik zobaczył czytelność bez patrzenia na podgląd. Opcjonalnie wskaźnik współczynnika kontrastu WCAG (4,5:1 jako próg ostrzeżenia w `warning`).
- Format zapisu w ustawieniach pozostaje bez zmian (np. `0,0,0,170`); konwersja tylko w warstwie widoku (zasada 1).

**Anty-wzorce.**

- Etykieta przycisku "RGBA 0,0,0,170": surowa reprezentacja techniczna, nie widać koloru.
- Cztery Spinboxy R, G, B, A obok siebie jako jedyny sposób edycji.
- Próbka bez szachownicy: `0,0,0,170` i `0,0,0,255` wyglądają tak samo.
- Próbka rysowana jako `bg=` widżetu Tk: nie pokazuje alfy i nie ma promienia.

**Implementacja.** Qt: `ColorSwatchButton(rgba)` z `scripts/qt_widgets.py` (`rgba()`, `set_rgba()`, sygnał `changed`; konstruktor zgodny z `gui.ColorButton` w Piro, więc zamiana jeden do jednego); próbka z szachownicą malowana w `paintEvent`, dialog `QColorDialog.getColor(..., options=QColorDialog.ShowAlphaChannel)` (qt-pyside6.md §7). Tk: `ColorSwatchButton(parent, variable, on_change=None)` z `scripts/widgets.py`, gdzie `variable` to `StringVar` w formacie "R,G,B,A" lub "#RRGGBBAA" (notacja wejściowa zachowana przy zapisie); próbka na `tk.Canvas`, alfa w Spinboxie 0..255. Presety i miniatura kontrastu z części "Jak" to rozszerzenia do dopisania; nie ma ich w klasach bazowych.

## §6 Ścieżka pliku

**Kiedy.** Plik wideo, plik audio, katalog eksportu, plik ustawień.

**Jak.**

- Wiersz: `ttk.Entry` rozciągany (`sticky="ew"`) + przycisk "Przeglądaj..." (Ghost, szerokość wg tekstu) + opcjonalnie ikona "otwórz katalog". Wysokość 32 px.
- Skracanie od lewej z ellipsis, gdy ścieżka nie mieści się: `...\Nagrania\tor3_2025-05-10.mp4`. Zachowaj nazwę pliku w całości, skracaj katalogi. Skracanie tylko w wyświetlaniu; pełna ścieżka w zmiennej. Realizacja: pomiar `font.measure()` na zdarzenie `<Configure>` i podmiana tekstu w Entry ustawionym jako `state="readonly"` lub w Label stylizowanym na Entry (wtedy edycja przez dialog). Jeśli pole ma być edytowalne, skracaj tylko gdy nie ma fokusu.
- Tooltip z pełną ścieżką po najechaniu (`Tooltip`).
- Ostatnio używane: przycisk ze strzałką w dół obok "Przeglądaj..." otwiera `tk.Menu` z 5..8 ostatnimi ścieżkami. Listę trzymaj tam, gdzie aplikacja już trzyma ustawienia; jeśli nie ma takiego miejsca, trzymaj w pamięci sesji (zasada 1).
- Drag and drop: jeśli dostępny pakiet `tkinterdnd2` (`try: from tkinterdnd2 import DND_FILES, TkinterDnD`), zarejestruj pole jako cel upuszczania. Bez pakietu funkcja jest po prostu niedostępna; nie dodawaj twardej zależności. Sprawdź, że okno główne jest wtedy tworzone przez `TkinterDnD.Tk()` zamiast `tk.Tk()`; to zmiana w bootstrapie aplikacji, więc rób ją jako osobny krok z własnym zrzutem.
- Walidacja: gdy plik nie istnieje, styl `Invalid.TEntry` + `InlineMessage` "Plik nie istnieje". Stan pusty pokazuj jako placeholder w `text_muted` ("Wybierz plik wideo...").
- `filedialog.askopenfilename(filetypes=[...], initialdir=...)` z `initialdir` ustawionym na katalog ostatniego pliku.

**Anty-wzorce.**

- Entry o stałej `width=40` i ścieżka przewijana w prawo: widoczna jest tylko końcówka nazwy, początek znika.
- Przycisk "..." bez etykiety: niejasne, co robi, i cel kliknięcia ma 20 px.
- Ścieżka wklejana do etykiety tytułu sekcji.

**Implementacja.** Qt: `PathField(mode="open"|"save"|"dir", filter="Wideo (*.mp4 *.mov)", placeholder="...")` z `scripts/qt_widgets.py` (`path()`, `set_path()`, sygnał `changed`; skracanie `QFontMetrics.elidedText(..., Qt.ElideLeft, ...)` poza fokusem, tooltip z pełną ścieżką, `dragEnterEvent`/`dropEvent` gotowe). Tk: `PathField(parent, variable, title="", filetypes=[...], mode="open"|"save"|"dir")` z `scripts/widgets.py` plus `Tooltip`. Lista ostatnich ścieżek oraz drag and drop w Tk (`tkinterdnd2`) to rozszerzenia.

## §7 Przyciski

**Kiedy.** Każda akcja użytkownika, która nie jest zmianą wartości pola.

**Jak.**

- Hierarchia: jeden przycisk primary (Qt `kind=primary`, Tk `Accent.TButton`) na widok lub sekcję (np. "Eksportuj" w sekcji Eksport, "Wykryj" w Synchronizacji). Pozostałe akcje to secondary (Qt domyślny `QPushButton` lub `kind=secondary`, Tk `TButton`; obramowanie `border_strong`) lub ghost (Qt `kind=ghost`, Tk `Ghost.TButton`; bez tła, dla akcji drugorzędnych: "Przeglądaj...", "Resetuj").
- Etykiety czasownikowe, w bezokoliczniku lub rozkaźniku spójnie w całej aplikacji: "Wykryj kotwice", "Pobierz", "Eksportuj wideo". Nie "OK"/"Zastosuj" tam, gdzie można nazwać skutek.
- Ikona 16 px + tekst, ikona po lewej, odstęp `sp_2`. Ikona sama (bez tekstu) tylko w pasku transportu i przy akcjach o powszechnie znanym znaku (play, pauza, kosz), zawsze z tooltipem.
- Szerokość wg treści + padding `sp_4` z każdej strony (`padding=(16, 6)`), wysokość 32 px. Nie `sticky="ew"` na pojedynczym przycisku; wyjątek: przycisk primary na dole sekcji Eksport może być na pełną szerokość kolumny kontrolek.
- Grupowanie akcji powiązanych: trzy przyciski "Wykryj start", "Wykryj strzały", "Wykryj wszystko" zamieniaj na primary "Wykryj" (domyślna, najczęstsza akcja) + przycisk ze strzałką otwierający `tk.Menu` z wariantami. Alternatywa: jeden przycisk "Wykryj..." + Combobox "Co wykrywać" obok.
- Stan busy: po kliknięciu przycisk dostaje `state="disabled"` i tekst "Wykrywanie..." (ten sam czasownik w formie ciągłej), obok lub pod nim `ttk.Progressbar` (§10). Po zakończeniu przywróć tekst i stan. Zablokuj też przyciski, które zmieniałyby dane wejściowe operacji.
- Akcje destrukcyjne ("Usuń markery", "Resetuj ustawienia") jako danger (Qt `kind=danger`, Tk `Danger.TButton`), z potwierdzeniem `messagebox.askyesno` tylko, gdy nie ma cofania. Jeśli można cofnąć (Ctrl+Z), potwierdzenie pomiń, a w pasku stanu pokaż "Usunięto 3 markery. Cofnij: Ctrl+Z".
- Fokus klawiaturą widoczny (ramka `focus`), Enter aktywuje przycisk primary, gdy fokus jest w polu formularza tej sekcji (`bind("<Return>")` na ramce sekcji).

**Anty-wzorce.**

- Wszystkie przyciski `sticky="ew"` w kolumnie: ściana jednakowych szarych prostokątów, brak hierarchii.
- Trzy przyciski primary w jednej sekcji.
- Przycisk "Zastosuj" przy każdej sekcji zamiast podglądu na żywo (jeśli logika to umożliwia).
- Etykieta zmieniana na "..." podczas pracy, bez informacji, co się dzieje.

**Implementacja.** Qt: `btn.setProperty("kind", "primary"|"secondary"|"ghost"|"danger")` (helper `set_kind` z `scripts/qt_widgets.py`) z regułami `QPushButton[kind=...]` w `scripts/qt_theme.py`; stan busy przez `set_busy(button, True, "Wykrywanie...")` i `set_busy(button, False)`; primary w dialogu dodatkowo `setDefault(True)`; menu rozwijane `QToolButton.setMenu()` + `setPopupMode(QToolButton.MenuButtonPopup)` (qt-pyside6.md §4). Tk: style `Accent.TButton`, `Ghost.TButton`, `Danger.TButton` z `scripts/theme_template.py`; menu rozwijane `tk.Menu(tearoff=0)` + `post()` pod przyciskiem.

## §8 Oś czasu i fala audio

**Kiedy.** Aplikacja pracuje z czasem: synchronizacja, przycinanie, markery zdarzeń (strzały, sygnał startu).

**Jak.**

Wymiary i strefy (od góry):

| Strefa | Wysokość | Treść |
|---|---|---|
| Skala czasu | 20 px | podziałki co "ładny" interwał (1 s, 5 s, 10 s, 30 s, 1 min, zależnie od zoomu), etykiety `font_ui_small` w `text_muted`; główne podziałki dłuższe, pośrednie krótsze bez etykiet |
| Fala audio | 72..100 px | fala symetryczna względem osi środkowej |
| Pas markerów | 24 px | etykiety markerów |
| Razem | 120..160 px | plus pasek przewijania poziomego 8 px, gdy zoom > 1 |

Kolory (tokeny):

| Element | Token | Uwaga |
|---|---|---|
| tło osi | `surface` | odróżnia oś od `bg` okna |
| fala poza zakresem Od..Do | `text_disabled` | przyciemniona, ale widoczna |
| fala w zakresie Od..Do | `text_muted` lub `info` | jeden z dwóch, spójnie |
| tło zakresu Od..Do | `accent_subtle` | prostokąt pod falą |
| marker Start (początek nagrania) | `text_muted` | linia przerywana |
| marker T0 (sygnał startu) | `accent` (#FFC400) | najważniejszy marker, linia 2 px |
| markery Od / Do | `info` | linie 1 px z uchwytami na krawędziach zakresu |
| marker Koniec | `text_muted` | linia przerywana |
| strzały wykryte | `success` | krótkie kreski na dole fali, bez etykiet |
| wskaźnik bieżącego czasu (playhead) | `text` (jasny na ciemnym) lub `danger` | linia 1 px na całą wysokość + trójkąt na skali |
| siatka podziałek | `border` | linie 1 px |

Etykiety markerów: tekst w `font_ui_small`, na pastylce (prostokąt `r_sm`, tło w kolorze markera z alfą lub `surface_alt`, tekst `text`). Kolizje: układaj naprzemiennie w dwu rzędach pasa markerów (góra/dół), gdy odległość między markerami jest mniejsza niż szerokość etykiety; jeśli nadal nachodzą, przesuń etykietę w bok od linii (linia pozostaje w miejscu, etykieta ma "nogę"); jeśli kolizji nie da się rozwiązać, ukryj etykietę mniej ważnego markera i pokaż ją w tooltipie po najechaniu. Priorytet: T0 > Od/Do > Start/Koniec.

Interakcje:

- Kliknięcie w skalę czasu lub falę przenosi playhead. Przeciąganie playheada przewija podgląd (scrub).
- Przeciąganie markera: kursor `sb_h_double_arrow` nad markerem, uchwyt min. 8 px szerokości (strefa chwytu szersza niż linia). Snapping do najbliższego wykrytego strzału lub klatki, gdy odległość poniżej 6 px; Alt wyłącza snapping. Pokazuj wartość czasu w tooltipie przy kursorze podczas przeciągania.
- Zoom: Ctrl + kółko względem pozycji kursora (punkt pod kursorem zostaje w miejscu). Zakres zoomu od "całe nagranie" do ok. 10 px na klatkę. Przewijanie poziome: Shift + kółko lub samo kółko, gdy kursor jest nad osią (decyzja spójna w całej aplikacji). Przycisk "Dopasuj" (zoom do całości) i "Zoom do zakresu Od..Do".
- Klawiatura (gdy oś ma fokus): strzałki lewo/prawo 0,1 s lub 1 klatka (zależnie od trybu wybranego w ustawieniach lub Ctrl dla klatki), Shift + strzałka 1 s, Home/End początek/koniec, I/O ustaw Od/Do w bieżącym czasie, T ustaw T0, M dodaj marker (§11). Oś musi przyjmować fokus (`takefocus=True`) i mieć widoczną ramkę fokusu.
- Fokus i tooltip nie mogą zasłaniać playheada.

Wydajność (Tk Canvas): rysuj falę jako jedną linię na kolumnę pikseli (min/max w oknie próbek), nie jako wszystkie próbki. Przy zmianie zoomu przelicz downsampling; przy przewijaniu przesuwaj gotowe elementy (`canvas.move` / `xview`) zamiast rysować od nowa. Przy długich nagraniach rozważ falę jako obraz (`PhotoImage` z bufora) i markery jako elementy Canvas nad nim. Szczegóły w `tkinter-ttk.md` §7.

**Anty-wzorce.**

- Fala w jaskrawym kolorze na czarnym tle bez rozróżnienia zakresu Od..Do.
- Etykiety markerów wszystkie na tej samej wysokości i nachodzące ("Od 32.6s" na "T0 37.6s").
- Brak playheada i brak sprzężenia z podglądem.
- Markery przeciągane bez snapu i bez podglądu wartości.
- Oś rysująca 500 000 linii przy każdym `<Configure>`.

**Implementacja.** Qt: własny `QWidget` z `paintEvent` (w Piro: `WaveformWidget`); kolory przez `current_tokens(app)` przy każdym rysowaniu, fala w cache `QPixmap` z `setDevicePixelRatio`, etykiety markerów bez kolizji, `wheelEvent` z `modifiers()`, `setFocusPolicy(Qt.StrongFocus)` i pierścień fokusu (qt-pyside6.md §7). Tk: własna klasa na `tk.Canvas` (nie ma gotowej w `widgets.py`); kolory z `current_tokens()` z `scripts/theme_template.py`, nie z literałów; `bind_mousewheel` dla kółka z modyfikatorami (tkinter-ttk.md §7).

## §9 Podgląd wideo

**Kiedy.** Główna strefa robocza; użytkownik ocenia wynik ustawień na klatce wideo.

**Jak.**

- Klatka wideo zachowuje proporcje (16:9, 9:16, 4:3 zależnie od pliku). Wolne pasy (letterbox/pillarbox) w kolorze `bg`, nie czarnym; czarny pas na ciemnoszarym tle wygląda jak błąd renderowania. Wyjątek: gdy motyw ma `bg` bardzo bliskie czerni, można użyć `surface` dla pasów, aby odróżnić obszar podglądu od tła okna.
- Cienka ramka 1 px `border` wokół klatki (nie wokół całej strefy), aby granica wideo była widoczna także dla ciemnych nagrań.
- Skalowanie: przelicz rozmiar klatki na zdarzenie `<Configure>` z debounce (`after(50, ...)`), skaluj miniaturę raz do rozmiaru docelowego (PIL `Image.resize` z `LANCZOS` dla stopklatki; `BILINEAR` przy odtwarzaniu). Nie skaluj przy każdym pikselu zmiany rozmiaru okna.
- Tryb "Edytuj pozycję": jawny przełącznik (`Switch` lub przycisk przełączany w pasku nad podglądem, etykieta "Edytuj pozycję nakładki"). W tym trybie: nakładka ma ramkę 1 px `accent` z 4 uchwytami narożnymi (kwadraty 8 px) do skalowania i możliwość przeciągania całości; kursor `fleur` nad nakładką; podgląd nie odtwarza (pauza). Poza trybem: brak ramki, kliknięcia w podgląd nie przesuwają nakładki (unika przypadkowych zmian).
- Podpowiedź w pasku stanu zależna od trybu: "Przeciągnij nakładkę, aby zmienić pozycję. Strzałki: 1 px, Shift+strzałki: 10 px. Esc kończy edycję."
- Prowadnice (opcjonalnie, `Switch` w menu Widok): linie środkowe i marginesy bezpieczne (np. 5 %) w `border_strong` z alfą; snapping nakładki do środka i marginesów przy przeciąganiu.
- Wartości X/Y w inspektorze aktualizują się na żywo podczas przeciągania (dwukierunkowe wiązanie z tymi samymi zmiennymi Tk). Pozycja zapisywana w tym samym układzie odniesienia i formacie, co dotąd (zasada 1).
- Pasek transportu pod podglądem (wysokość 40 px, od lewej): skok do początku (Home), poprzedni marker, klatka wstecz, **Play/Pauza** (jeden przycisk przełączany, 32 x 32 px, ikona zmienia się), klatka w przód, następny marker, skok do końca (End); po prawej czas "0:37,6 / 2:25,0" w `font_mono`, jeden format (§12); opcjonalnie regulacja głośności i prędkość (0,25x..2x) w Combobox.
- Przyciski transportu tylko z ikonami 16 px + tooltipy ze skrótem ("Odtwórz / Pauza (Spacja)").
- Gdy brak wideo: stan pusty (§10) zamiast szarego prostokąta.

**Anty-wzorce.**

- Podgląd rozciągnięty bez zachowania proporcji.
- Czarny letterbox na szarym tle.
- Edycja pozycji "zawsze włączona": każde kliknięcie w podgląd przesuwa nakładkę.
- Pasek "Edytuj pozycje (przeciąganie)" jako sam tekst bez widocznego stanu włączony/wyłączony.
- Brak transportu: użytkownik nie może sprawdzić nakładki w ruchu.

**Implementacja.** Qt: `QLabel` z `pixmap.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)` i letterboxem w `bg` (w Piro: `PreviewLabel`; tło z tokenu w `paintEvent` albo nowa rola QSS dopisana do `_QSS_TEMPLATE`) lub `QGraphicsView` + `QGraphicsVideoItem` z nakładką jako `QGraphicsRectItem(ItemIsMovable)`; tryb edycji jako `QToolButton` checkable albo `Switch`; pasek transportu z `QAction` w `QToolBar` albo `QHBoxLayout` z `QToolButton(kind=ghost)`; podpowiedź przez `status_message(statusbar, text, "info", 0)` (qt-pyside6.md §5, §7). Tk: podgląd na `tk.Canvas` (`create_image`, nakładka jako elementy Canvas lub obraz z alfą przez PIL), `Switch` dla trybu edycji, `StatusBar.set(text, "info")` dla podpowiedzi, `Ghost.TButton` z ikonami w pasku transportu (tkinter-ttk.md §7).

## §10 Feedback: postęp, błędy, stan pusty

**Kiedy.** Operacje dłuższe niż ok. 0,5 s, błędy, brak danych.

**Jak.**

Długie operacje ("Pobierz", "Wykryj kotwice", "Eksportuj"):

- Praca w wątku roboczym (`threading.Thread`) lub procesie; wyniki wracają do wątku UI przez `root.after(0, callback)` lub kolejkę `queue.Queue` odpytywaną `after(100, poll)`. Nigdy nie wywołuj metod widżetów z wątku roboczego (zasada 6). Szczegóły w `tkinter-ttk.md` §8.
- Przycisk w stanie busy (§7) + `ttk.Progressbar`: `mode="determinate"` gdy postęp jest znany (klatki, bajty), `mode="indeterminate"` + `start(15)` gdy nie jest. Pasek w tym samym wierszu co przycisk lub tuż pod nim, wysokość 4..6 px, kolor `accent` na `surface_alt`.
- Przycisk "Anuluj" (Ghost) obok paska; anulowanie przez `threading.Event`, operacja sprawdza flagę między krokami. Po anulowaniu przywróć poprzedni stan danych (nie pół-wyników), pasek stanu: "Anulowano".
- Tekst postępu w pasku stanu: "Eksport: 42 % (klatka 1 260 / 3 000), pozostało ok. 0:48".
- Po zakończeniu: krótki komunikat sukcesu w pasku stanu lub toast ("Eksport zakończony. Otwórz folder"), a nie modalny dialog, chyba że użytkownik musi podjąć decyzję.

Komunikaty błędów w trzech częściach:

1. Co się stało: "Nie udało się wykryć sygnału startu."
2. Dlaczego (jeśli wiadomo): "W zakresie Od..Do nie znaleziono impulsu głośniejszego niż próg -12 dB."
3. Co zrobić: "Zmniejsz próg w sekcji Zaawansowane lub ustaw T0 ręcznie, klikając na osi czasu."

Kanał komunikatu:

| Kanał | Kiedy | Czas życia |
|---|---|---|
| Pasek stanu (Qt `status_message`, Tk `StatusBar`) | informacja, postęp, potwierdzenie akcji odwracalnej | do następnego komunikatu lub 5 s |
| Toast (małe okno w rogu obszaru roboczego) | sukces operacji długiej, ostrzeżenie niewymagające decyzji | 4..6 s, zamykany kliknięciem |
| `InlineMessage` pod kontrolką | błąd walidacji pola, ostrzeżenie dotyczące jednego ustawienia | do poprawienia wartości |
| Dialog modalny (`QMessageBox` / `messagebox`) | błąd blokujący dalszą pracę, decyzja użytkownika (nadpisać plik?), utrata danych | do zamknięcia |

Stan pusty (brak wideo): w strefie podglądu ikona 48 px w `text_muted`, tytuł "Brak wideo" (`font_title`, Qt `role=title`), zdanie "Otwórz nagranie, aby rozpocząć" (`Muted.TLabel`, Qt `role=muted`) i przycisk primary (Qt `kind=primary`, Tk `Accent.TButton`) "Otwórz wideo..." (Ctrl+O); opcjonalnie lista ostatnich plików. Oś czasu w stanie pustym jest wyłączona (przyciemniona), nie znika, aby układ nie skakał po wczytaniu.

**Anty-wzorce.**

- UI zamiera na 30 s bez paska postępu ("Nie odpowiada" w tytule okna).
- `messagebox.showinfo("Gotowe")` po każdej operacji.
- Błąd jako traceback w dialogu; traceback idzie do logu, do użytkownika idzie zdanie w trzech częściach oraz przycisk "Szczegóły" rozwijający tekst techniczny.
- Pusty szary prostokąt bez informacji, co zrobić.

**Implementacja.** Qt: `set_busy(button, True, "Eksport...")`, `QProgressBar` (`setRange(0, 0)` dla trybu nieokreślonego, `role=danger` dla błędu), `status_message(statusbar, text, kind, timeout_ms)` zamiast gołego `showMessage`, `InlineMessage().show_message(text, kind)` pod polem, `QMessageBox` z `setDetailedText` dla szczegółów technicznych, praca w `QThread` z sygnałami (qt-pyside6.md §4, §9). Tk: `StatusBar.set(text, kind, timeout_ms)`, `InlineMessage.show(text, kind)` z `kind` w `info|success|warning|danger`, `ttk.Progressbar` (styl w `apply_theme`), toast jako `tk.Toplevel(overrideredirect=True)` pozycjonowany względem okna głównego (uwaga na HiDPI i wiele monitorów); wątek + `queue` + `after` (tkinter-ttk.md §9).

## §11 Klawiatura i skróty

**Kiedy.** Zawsze; narzędzia wideo są używane z ręką na klawiaturze.

**Jak.** Typowy zestaw dla narzędzia wideo/audio:

| Skrót | Akcja | Uwagi |
|---|---|---|
| Spacja | Play / Pauza | tylko gdy fokus nie jest w polu tekstowym (sprawdź `focus_get()`) |
| J / K / L | wstecz / pauza / naprzód (kolejne naciśnięcia zwiększają prędkość) | konwencja z edytorów wideo; opcjonalna |
| Lewo / Prawo | 1 klatka (lub 0,1 s wg ustawienia) | na osi i w podglądzie |
| Shift + Lewo / Prawo | 1 s | |
| Ctrl + Lewo / Prawo | poprzedni / następny marker | |
| Home / End | początek / koniec nagrania | |
| I / O | ustaw Od / Do w bieżącym czasie | in/out point |
| T | ustaw T0 w bieżącym czasie | specyficzne dla aplikacji |
| M | dodaj marker (strzał) w bieżącym czasie | |
| Delete | usuń zaznaczony marker | z cofaniem lub potwierdzeniem (§7) |
| Ctrl + Z / Ctrl + Y | cofnij / powtórz | jeśli aplikacja ma historię zmian |
| Ctrl + O | otwórz wideo | |
| Ctrl + S | zapisz ustawienia/projekt | |
| Ctrl + E | eksportuj | |
| Ctrl + D | wykryj (akcja domyślna sekcji Synchronizacja) | |
| Ctrl + kółko | zoom osi czasu | |
| Shift + kółko | przewijanie osi w poziomie | |
| E | przełącz tryb "Edytuj pozycję" | Esc wychodzi z trybu |
| F11 | pełny ekran podglądu | `root.attributes("-fullscreen", True)`; Esc wychodzi |
| F1 | pomoc / lista skrótów | dialog z tabelą skrótów |
| Ctrl + , | ustawienia aplikacji | jeśli istnieją |
| Ctrl + Q / Alt + F4 | zakończ | |

Zasady:

- Skróty jednoliterowe (I, O, T, M, E, J/K/L, Spacja) działają tylko, gdy fokus jest poza polami tekstowymi i Comboboxami; w przeciwnym razie użytkownik nie może wpisać litery. Sprawdzaj klasę widżetu z fokusem przed wykonaniem akcji.
- Skróty z Ctrl wiąż na `root.bind_all` (`<Control-o>`), skróty osi na samej osi (po fokusie).
- Tooltip każdego przycisku zawiera skrót w nawiasie: "Wykryj (Ctrl+D)". Menu aplikacji (jeśli jest) pokazuje skróty w kolumnie `accelerator=`.
- Kolejność Tab zgodna z układem: inspektor od góry do dołu, potem transport, potem oś. Widżety dekoracyjne (`Label`, Canvas podglądu) `takefocus=False`; oś czasu `takefocus=True`.
- Fokus widoczny: ramka `focus` 1..2 px na każdym widżecie fokusowalnym, także na własnych (SegmentedControl, Switch, ColorSwatchButton, oś).
- Klawisze skrótów w PL i EN takie same (skróty nie są tłumaczone), ale opisy w tooltipach są.

**Anty-wzorce.**

- Spacja odtwarza wideo, gdy użytkownik wpisuje wartość w Entry.
- Skróty tylko w kodzie, nigdzie nie pokazane.
- Własne widżety na Canvas/Frame bez `takefocus` i bez obsługi klawiatury.
- Tab przeskakujący z inspektora na oś i z powrotem w losowym porządku, bo widżety tworzono w innej kolejności niż układ.

**Implementacja.** Qt: `QAction` z `setShortcut(QKeySequence("Ctrl+D"))` i `setToolTip("Wykryj (Ctrl+D)")` w `QToolBar`, `QShortcut` dla akcji bez przycisku, `setTabOrder` po zbudowaniu sekcji, pierścień fokusu z reguł `:focus` w `scripts/qt_theme.py` i `_focus_ring` w widżetach własnych (qt-pyside6.md §5, §8). Tk: `Tooltip(widget, "Wykryj (Ctrl+D)")` z `scripts/widgets.py` (skrót dopisz do tekstu), wiązania w jednym module (np. `shortcuts.py`) z tabelą (klawisz, akcja, opis) używaną zarówno do `bind`, jak i do dialogu pomocy (tkinter-ttk.md §8).

## §12 Internacjonalizacja (PL/EN)

**Kiedy.** Aplikacja ma już dwa języki; odświeżenie nie może tego zepsuć (zasada 3).

**Jak.**

- Każdy tekst widoczny przechodzi przez istniejącą funkcję tłumaczenia aplikacji (nie twórz drugiego mechanizmu). Nowe teksty (podpowiedzi, tooltipy, komunikaty trzyczęściowe, stan pusty) dodawaj do obu słowników w tym samym commicie.
- Teksty EN -> PL wydłużają się o ok. 30 %, niemieckie i francuskie jeszcze bardziej. Nie ustawiaj `width=` na przyciskach i etykietach; pozwól im rosnąć od treści. Sprawdź zrzuty w obu językach po każdym kroku, szczególnie SegmentedControl (segmenty równej szerokości muszą pomieścić najdłuższą etykietę w obu językach) i pasek transportu.
- Wartości list też się tłumaczą: Combobox pozycji nakładki pokazuje "dół-lewo", nie "bottom-left". Wzorzec: lista par `(klucz_techniczny, etykieta)`, Combobox pokazuje etykiety, zmienna Tk trzyma etykietę, a przy odczycie mapuj na klucz; w pliku ustawień zapisuj klucz techniczny (zasada 1). Kolejność opcji może być inna w PL i EN, jeśli sortowanie alfabetyczne ma sens; dla list "przestrzennych" (pozycje) trzymaj stały porządek.
- Formatowanie liczb: jeden separator dziesiętny w całej aplikacji, zgodny z językiem UI (PL: przecinek "37,6"; EN: kropka "37.6"). Na wejściu akceptuj oba (`text.replace(",", ".")` przed `float()`), na wyjściu formatuj przez jedną funkcję `fmt_number(value, digits)`. Nie mieszaj "37,60 s" w polu i "37.6s" na osi czasu.
- Jeden format czasu w całej aplikacji: albo sekundy z jednym miejscem ("37,6 s"), albo "m:ss,d" ("0:37,6"). Zalecenie dla nagrań do kilku minut: "m:ss,d" na osi i w transporcie, sekundy w polach liczbowych, ale wtedy pole ma jednostkę "s" jako sufiks (§3), a etykiety osi nie mają jednostki. Spacja między liczbą i jednostką ("37,6 s"), nie "37.6s".
- Separator tysięcy: PL spacja (twarda, U+00A0), EN przecinek; używaj tylko w komunikatach postępu, nie w polach edycji.
- Skróty klawiszowe nie są tłumaczone; ich opisy tak.
- Fonty: `Segoe UI Variable Text` i `Segoe UI` mają pełne polskie znaki; `Cascadia Mono` również. Przy fallbacku na inne fonty sprawdź "ąćęłńóśźż" w zrzucie.
- Zmiana języka w locie (jeśli aplikacja ją ma) musi odświeżyć także nowe widżety: własne klasy z `widgets.py` powinny mieć metodę `retranslate()` lub przyjmować `tk.StringVar` na etykiety.

**Anty-wzorce.**

- Etykieta techniczna w UI ("bottom-left", "T0", "fps") bez tłumaczenia lub objaśnienia.
- `width=12` na przycisku, PL etykieta obcięta do "Wykryj kotw".
- Wartość Comboboxa zapisywana do ustawień w postaci przetłumaczonej (plik nieczytelny po zmianie języka).
- Dwa formaty czasu na jednym ekranie.

**Implementacja.** Qt: `QComboBox.addItem(etykieta, klucz)` + `currentData()`, `SegmentedControl.set_label(key, label)` i `SectionHeader.set_title` przy zmianie języka, `NumberField(..., locale=QLocale(QLocale.Polish))` oraz `QDoubleValidator.setLocale` dla separatora dziesiętnego; teksty przez istniejący mechanizm aplikacji (w Piro: `i18n.Translator` i `_STRINGS`, nie `QTranslator`) (qt-pyside6.md §4, §10). Tk: funkcje formatujące w jednym module (np. `fmt_time`, `fmt_number`, `parse_number`) używane przez `NumberField(fmt="{:.2f}", decimal_comma=True)` i przez oś czasu; `SegmentedControl` z listą par (klucz, etykieta); `SectionHeader.set_text` do retranslacji.

## §13 Motyw ciemny i jasny

**Kiedy.** Domyślnie ciemny (nakładka jest bursztynowa na ciemnym tle, użytkownicy pracują z wideo). Jasny na życzenie lub wg systemu.

**Jak.**

- Co się zmienia między trybami: wszystkie tokeny kolorów z `design-tokens.md`. Nie zmieniają się odstępy, promienie, fonty, rozmiary ikon ani kolory wewnątrz podglądu wideo (klatka i nakładka wyglądają tak samo w obu motywach; tylko letterbox przyjmuje `bg`).
- Akcent `#FFC400` w ciemnym motywie; w jasnym ten sam bursztyn na białym ma kontrast ok. 1.6:1, więc `accent` przyjmuje ciemny bursztyn `#8A6100` z białym `accent_text`, a brandowy żółty zostaje tylko w `selection_bg` (uzasadnienie i wariant żółtego primary w `design-tokens.md`, sekcja "Dlaczego akcent w LIGHT nie jest żółty"). Kolor nakładki w podglądzie pozostaje bez zmian, bo to dane użytkownika.
- Ikony w dwu wersjach: monochromatyczne PNG/SVG w kolorze `text` dla ciemnego i jasnego (dwa pliki lub barwienie w locie przez PIL: maska alfa + kolor tokenu). Wszystkie ikony przechodzą przez jedną funkcję `icon(name, size, color)` z cache, aby przełączenie motywu je odświeżyło.
- Fala audio i markery: kolory z tokenów (§8), więc przełączają się razem z motywem. Sprawdź kontrast: fala `text_muted` na `surface` musi być widoczna w obu trybach (min. ok. 3:1); markery `accent`, `info`, `success` czytelne na obu tłach; playhead `text`.
- Wykrywanie motywu systemowego: `system_prefers_dark()` z `qt_theme.py` lub `theme_template.py` (Qt 6.5+: `styleHints().colorScheme()`, fallback rejestr Windows `AppsUseLightTheme`). Domyślnie użyj wartości z ustawień aplikacji, jeśli istnieje; inaczej ciemny.
- Pasek tytułu okna zgodny z motywem: `set_windows_dark_titlebar(okno, True/False)` po `show()` (Qt) lub `root.update()` (Tk); ponowne wywołanie po przełączeniu.
- Przełączenie w locie: w Qt `apply_theme(app, mode)` podmienia paletę i arkusz, `repolish` odświeża selektory atrybutowe, a widżety malowane czytają `current_tokens(app)`. W Tk `apply_theme(root, mode)` przestawia style ttk, ale własne widżety na Canvas i kolory ustawione bezpośrednio (`bg=`, `fg=`) trzeba odświeżyć ręcznie; każda własna klasa ma metodę `apply_palette(palette)` lub nasłuchuje wirtualnego zdarzenia `<<ThemeChanged>>` wysyłanego po `apply_theme`.
- Dialogi systemowe (`filedialog`, `messagebox`, `colorchooser`) przyjmują motyw systemu, nie aplikacji; to akceptowalne, nie próbuj ich zastępować w pierwszym kroku.
- Zrzuty weryfikacyjne w obu motywach po każdym kroku (zasada 2).

**Anty-wzorce.**

- Motyw ciemny tylko dla ttk, a `tk.Canvas`, `tk.Text`, `tk.Listbox`, `tk.Menu` pozostają białe.
- Ikony czarne na ciemnym tle.
- Czarny letterbox w jasnym motywie.
- Kolor ustawiony literałem `#333333` w 40 miejscach kodu zamiast przez token.

**Implementacja.** Qt: `apply_theme(app, mode)` z `scripts/qt_theme.py` (Fusion + `build_palette` + `build_qss` z tych samych tokenów + font), `system_prefers_dark()`, `set_windows_dark_titlebar(win, dark)` po `show()`, `repolish(widget)` po zmianie motywu, `current_tokens(app)` w `paintEvent` widżetów własnych, ikony SVG barwione przez podmianę `currentColor` (qt-pyside6.md §2, §6, §7). Tk: `apply_theme(root, mode)`, `system_prefers_dark()`, `set_windows_dark_titlebar()` z `scripts/theme_template.py`; widżety klasyczne Tk wg `tkinter-ttk.md` §2 i §10; tokeny z `design-tokens.md`.

## §14 Konwencje Windows 11 (Fluent)

**Kiedy.** Docelowa platforma to Windows 10/11. Konwencje są celem wizualnym; ttk nie odtworzy ich w 100 % (brak prawdziwych zaokrągleń i cieni), ale proporcje, odstępy i kolory są osiągalne.

**Jak.**

| Cecha | Wartość | Token / uwaga |
|---|---|---|
| Siatka | 4 px | wszystkie odstępy jako wielokrotności `sp_1` |
| Wysokość kontrolek (Button, Entry, Combobox, Spinbox) | 32 px | `padding` w stylu ttk tak, aby wysokość wyniosła 32 px przy `font_ui`; sprawdź na zrzucie linijką |
| Wysokość wierszy list (Treeview) | 32..36 px | `rowheight` w stylu `Treeview` skalowany przez `px()` |
| Promień narożników kontrolek | 4 px | `r_sm`; w ttk nieosiągalny bez własnych elementów obrazkowych, więc prostokąt z obramowaniem 1 px jest akceptowalny |
| Promień kart / paneli | 8 px | `r_lg`; tylko w Canvas lub Qt |
| Obramowania | 1 px w `border`, przy fokusie 2 px w `focus` (lub 1 px `focus` + dolna krawędź 2 px dla pól tekstowych, jak Fluent) | subtelne; nie 2 px `border_strong` wszędzie |
| Font UI | Segoe UI Variable Text 10 pt -> Segoe UI 10 pt | `font_ui`; nagłówki `font_section`, `font_title` |
| Font mono | Cascadia Mono 10 -> Consolas 10 | `font_mono` dla czasu i hex |
| Ikony | 16 px w kontrolkach, 20 px w pasku narzędzi głównym, 48 px w stanie pustym | monochromatyczne, kolor `text` |
| Min. cel kliknięcia | 24 x 24 px myszą; 32..40 px dla ekranów dotykowych | uchwyty markerów i strzałki zwijania też |
| Akcent | oszczędnie: przycisk primary, zaznaczenie, fokus, aktywny segment, T0 na osi | reszta w skali szarości motywu |
| Cień | brak w ttk; w Qt subtelny na popoverach | nie rysuj cieni przez wielokrotne ramki |
| Pasek tytułu | ciemny w ciemnym motywie | `set_windows_dark_titlebar` (DwmSetWindowAttribute) |
| Odstęp od krawędzi okna do treści | `sp_4` (16 px) | inspektor i obszar roboczy |
| Odstęp między etykietą i kontrolką | `sp_3` (12 px) | |
| Kursor | systemowy; `hand2` na elementach klikalnych niebędących przyciskami (nagłówek zwijany, swatch) | |

Dodatkowe zasady:

- Kontrolki wyrównuj do wspólnych linii (lewa krawędź etykiet, lewa krawędź kontrolek, prawa krawędź kolumny); wyrównanie robi więcej dla "nowoczesności" niż zaokrąglenia.
- Hierarchia przez kolor tła: okno `bg`, panele/karty `surface`, pola wejściowe `surface_alt` (lub odwrotnie, spójnie); różnice subtelne (kilka procent jasności).
- Unikaj motywu `vista`/`winnative` jako bazy widocznej: użyj `clam` jako bazy dla `ttk.Style` (najbardziej konfigurowalny) i nałóż tokeny (`tkinter-ttk.md` §3).
- Tekst wyłączony `text_disabled`, nie "wyszarzony przez system" (ttk domyślnie używa własnego szarego; ustaw `map(foreground=[("disabled", text_disabled)])`).
- Menu aplikacji (`tk.Menu`) nie da się w pełni ostylować w Windows (pasek menu jest systemowy); jeśli menu jest, zostaw je systemowe albo zastąp paskiem narzędzi z przyciskami.

**Anty-wzorce.**

- Motyw vista (systemowe szare przyciski 23 px wysokości, biało-szare ramki LabelFrame) obok własnych ciemnych paneli.
- Odstępy 5, 7, 10, 13 px: brak siatki, elementy "pływają".
- Grube ramki 2..3 px jako sposób na uwidocznienie sekcji.
- Akcent na wszystkim (wszystkie przyciski bursztynowe).
- Jasny pasek tytułu nad ciemnym oknem.

**Implementacja.** Qt: `setup_hidpi()` przed `QApplication`, `apply_theme(app, mode)` (Fusion + QPalette + QSS z `border-radius` z `RADIUS` i `min-height` 30 px + ramka 1 px = 32 px), `set_windows_dark_titlebar` z `scripts/qt_theme.py`; receptury per widżet w `qt-pyside6.md` §4 i §6; alternatywnie PyQt-Fluent-Widgets (`migration-options.md` §3.1). Tk: `scripts/theme_template.py` (`apply_theme`, `px`, `enable_hidpi`, `set_windows_dark_titlebar`); szczegóły per widżet w `tkinter-ttk.md` §4 i §6.
