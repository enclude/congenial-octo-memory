# Odświeżyć w miejscu czy migrować: opcje i reguła decyzyjna

Dokument pomaga podjąć decyzję, czym odświeżyć wygląd istniejącej aplikacji desktopowej w Pythonie (przykład: Piro Overlay, Tkinter/ttk, Windows 11). Zawiera macierz opcji, krótkie profile, drzewo decyzyjne, playbook migracji typu "strangler" i heurystykę nakładu. Fakty o bibliotekach, których nie da się potwierdzić bez sprawdzenia w dokumentacji lub na maszynie docelowej, są oznaczone "(sprawdź)".

Zasady nadrzędne skilla obowiązują niezależnie od wybranej opcji: logika i format ustawień bez zmian, praca przyrostowa ze zrzutami, i18n PL/EN, HiDPI 100..200 %, klawiatura i fokus, UI nie zamiera.

## 1. Macierz opcji

Skala nakładu: S (do 2 dni), M (3..7 dni), L (2..4 tygodnie), XL (ponad miesiąc) dla aplikacji wielkości Piro Overlay (jedno okno, inspektor ok. 30 kontrolek, podgląd, oś czasu). Oceny jakości i ryzyka są względne (1 = najgorzej, 5 = najlepiej) i orientacyjne.

| # | Opcja | Nakład | Ryzyko regresji | Jakość wyglądu | HiDPI | Elastyczność motywu | Wydajność Canvas (fala, podgląd) | Pakowanie PyInstaller (rozmiar, orientacyjnie) | Licencja | Dojrzałość / utrzymanie |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | ttk + własny motyw (`scripts/theme_template.py`) | S..M | niskie (te same widżety, zmiana stylów) | 3 (bez zaokrągleń i cieni, ale spójnie i "płasko") | 4 (własne `enable_hidpi` + `px()`; fonty i odstępy skalują się, bitmapy trzeba dostarczyć w 2 rozmiarach) | 5 (pełna kontrola tokenów, dark/light) | 3 (Tk Canvas, wystarczy z downsamplingiem) | mały, ok. 15..30 MB onedir bez numpy/PIL (sprawdź) | Tk/Tcl: BSD-podobna, bez ograniczeń | bardzo dojrzałe; utrzymanie własne (kilkaset linii) |
| 2 | sv-ttk (Sun Valley) | S | niskie..średnie (podmienia cały motyw ttk, mogą zmienić się wysokości kontrolek) | 4 (wygląd Win11, gotowe Switch, Accent) | 3..4 (motyw obrazkowy skaluje się przez `tk scaling`; sprawdź ostrość przy 125 %) | 2 (dark/light gotowe; akcent stały, zmiana wymaga edycji plików tcl motywu, sprawdź) | 3 (Tk Canvas, bez zmian) | mały, +ok. 1 MB | MIT (sprawdź) | popularne, jeden główny opiekun; stabilne |
| 3 | ttkbootstrap | S..M | średnie (własne API `bootstyle`, własna klasa `Window`; konflikty z ręcznym `ttk.Style`) | 4 (gotowe motywy w stylu Bootstrap, wiele wariantów kolorów) | 3..4 (własne skalowanie; sprawdź przy 150 %) | 3..4 (kilkanaście motywów, edytor własnych motywów; akcent jako kolor "primary") | 3 (Tk Canvas) | mały, +kilka MB | MIT (sprawdź) | aktywne, spora społeczność; API czasem się zmienia |
| 4 | CustomTkinter | M..L | wysokie (własny zestaw widżetów, nie ttk; przepisanie każdego widżetu) | 4 (zaokrąglenia, nowoczesny wygląd) | 4 (własne skalowanie widżetów i okna) | 4 (motywy JSON, dark/light, akcent) | 3 (widżety rysowane na Canvas, wiele widżetów spowalnia; własny Canvas fali bez zmian) | mały..średni, +kilka MB | MIT (sprawdź) | popularne, tempo rozwoju zmienne; brak niektórych widżetów (Treeview, Spinbox, Menu) |
| 5 | PySide6 / PyQt6 (+ QSS, qt-material, PyQt-Fluent-Widgets) | L..XL | wysokie (pełny rewrite warstwy UI) | 5 (natywny wygląd, pełne QSS, animacje) | 5 (skalowanie wbudowane w Qt6, ikony SVG) | 5 (QPalette + QSS, gotowe biblioteki motywów) | 5 (QPainter z cache, QGraphicsView, GPU przez RHI opcjonalnie) | duży, ok. 80..200 MB onedir zależnie od modułów (QtMultimedia dodaje sporo; sprawdź) | PySide6: LGPLv3 lub komercyjna; PyQt6: GPLv3 lub komercyjna; PyQt-Fluent-Widgets: GPLv3 lub komercyjna (sprawdź). Licencję weryfikuj dla konkretnego wdrożenia i sposobu dystrybucji | bardzo dojrzałe, korporacyjne utrzymanie (Qt Company / Riverbank) |
| 6 | Flet | XL | bardzo wysokie (inny model: UI jak w Flutterze, kontrolki deklaratywne; inny cykl życia) | 5 (Material 3) | 5 (Flutter) | 4 (motywy Material; wygląd "webowy", nie Fluent) | 2..3 (własne rysowanie przez kontrolkę Canvas Fleta; strumieniowanie klatek do UI jest kosztowne, sprawdź) | inne narzędzie pakowania (`flet build`, wymaga Flutter SDK) lub `flet pack` (sprawdź); ok. 40..80 MB | Apache 2.0 (sprawdź) | młode, szybko zmieniające się API |
| 7 | DearPyGui | XL | bardzo wysokie (inny model: retained-mode API na GPU, własne widżety) | 3 (wygląd "narzędziowy", nie natywny; motywy własne) | 3 (skalowanie globalne fontów i widżetów; sprawdź ostrość) | 3 (własny system motywów, kolory per element) | 5 (GPU; wykresy i fale z milionów punktów płynnie) | średni, ok. 20..40 MB (sprawdź) | MIT (sprawdź) | dojrzałe w niszy (narzędzia, wizualizacja), mniejsza społeczność |

Uwagi do kolumn:

- **Ryzyko regresji** dotyczy logiki i zapisu ustawień, nie tylko wyglądu. Opcje 1..3 zachowują ten sam graf widżetów i te same zmienne Tk, więc regresja logiki jest mało prawdopodobna; ryzyko to głównie zmiana wymiarów i kolizje stylów. Opcje 4..7 wymagają przepisania warstwy UI, więc każda zależność logiki od widżetu (np. logika w callbacku przycisku) jest ryzykiem.
- **HiDPI** ocenia zachowanie na 100/125/150/200 % bez rozmytych fontów i z poprawnymi rozmiarami kontrolek; obrazy rastrowe (ikony, miniatury) wymagają osobnej uwagi w każdej opcji.
- **Rozmiar pakietu** zależy od zależności aplikacji (numpy, PIL, OpenCV, ffmpeg) bardziej niż od biblioteki UI; podane liczby dotyczą samego UI. Zmierz na swojej maszynie po `pyinstaller --onedir`.
- **Licencja**: PySide6 (LGPL) pozwala dystrybuować zamknięte aplikacje pod warunkiem dynamicznego linkowania i możliwości podmiany bibliotek Qt przez użytkownika (onedir spełnia to łatwiej niż onefile; sprawdź wymagania LGPL). PyQt6 na GPL wymusza GPL na aplikacji, chyba że kupiono licencję komercyjną. Te uwagi nie zastępują weryfikacji prawnej.

## 2. Profile opcji

### 2.1 ttk + własny motyw

**Co daje.** Pełną kontrolę nad tokenami (kolory, odstępy, fonty) przez `ttk.Style` na bazie `clam`; dark/light i akcent aplikacji (#FFC400) bez zależności; te same widżety, więc kod logiki nie zmienia się. Własne widżety kompozytowe (`scripts/widgets.py`: SectionHeader, Switch, SegmentedControl, ColorSwatchButton, NumberField, PathField, ScrollableFrame, StatusBar, InlineMessage) zamykają lukę między ttk i wyglądem Fluent.

**Czego nie daje.** Prawdziwych zaokrągleń narożników (ttk `clam` rysuje prostokąty; zaokrąglenia tylko przez elementy obrazkowe lub Canvas), cieni, animacji, natywnego odtwarzania wideo (klatki przez PIL/OpenCV na Canvas), dostępności dla czytników ekranu (Tk nie eksponuje drzewa UI Automation w Windows).

**Pułapki.** Klasyczne widżety `tk.*` (Canvas, Text, Listbox, Menu, Toplevel) nie podlegają `ttk.Style`; trzeba ustawiać im kolory osobno. Motyw `vista` nadpisuje wiele opcji `configure` (np. tło przycisku), stąd baza `clam`. Wysokość kontrolek zależy od fontu i paddingu, mierz na zrzucie. `tk scaling` i `SetProcessDpiAwareness` muszą być ustawione przed tworzeniem widżetów. Szczegóły: `tkinter-ttk.md`.

### 2.2 sv-ttk (Sun Valley)

**Co daje.** Gotowy motyw w stylu Windows 11 w dwu trybach (`sv_ttk.set_theme("dark")`), zaokrąglone kontrolki (rysowane obrazkami), style dodatkowe takie jak przycisk akcentowy i przełącznik (nazwy stylów sprawdź w README). Wdrożenie to kilka linii.

**Czego nie daje.** Zmiany koloru akcentu bez edycji plików motywu (akcent domyślnie systemowy niebieski; sprawdź), kontroli nad wymiarami (kontrolki są wyższe niż w vista, co zmienia układ), stylowania klasycznych widżetów `tk.*` (pozostają do ręcznej obróbki, jak w opcji 1). Ciemny pasek tytułu wymaga osobnego wywołania DWM (jak w `theme_template.py`).

**Pułapki.** Nadpisuje bieżący motyw ttk w całości; własne style dodane wcześniej trzeba zdefiniować po `set_theme`. Bitmapowe elementy motywu mogą być lekko rozmyte przy 125 % (sprawdź na zrzucie). Zmiana motywu w locie działa, ale własne Canvasy trzeba odświeżyć ręcznie. Akcent bursztynowy aplikacji nie będzie spójny z niebieskim akcentem motywu, chyba że zmodyfikujesz motyw.

### 2.3 ttkbootstrap

**Co daje.** Kilkanaście motywów (jasne i ciemne) z semantycznymi kolorami (primary, secondary, success, info, warning, danger), własne widżety (m.in. przełącznik, wskaźniki postępu, tabela, przewijana ramka, powiadomienia toast), skróty stylów przez parametr `bootstyle="primary-outline"`. Możliwość zdefiniowania własnego motywu z akcentem #FFC400 przez plik użytkownika (sprawdź mechanizm w dokumentacji).

**Czego nie daje.** Wyglądu Fluent (estetyka Bootstrap: większe promienie, wyraźne kolory), pełnej zgodności z ręcznie napisanymi `ttk.Style().configure(...)`.

**Pułapki.** Własna klasa okna (`ttkbootstrap.Window`) zastępuje `tk.Tk()`, co jest zmianą w bootstrapie aplikacji. Style są generowane na żądanie po nazwach `bootstyle`; ręczna konfiguracja stylu o tej samej nazwie może zostać nadpisana lub nie zadziałać. Import `import ttkbootstrap as ttk` w miejsce `from tkinter import ttk` zmienia klasy widżetów (podklasy ttk), więc `isinstance` i `winfo_class()` mogą dać inne wyniki. Jeśli aplikacja używa `Style().theme_use()`, sprawdź konflikt.

### 2.4 CustomTkinter

**Co daje.** Nowoczesny wygląd (zaokrąglenia, płaskie kolory) w dark/light z motywami JSON, widżety takie jak CTkButton, CTkEntry, CTkComboBox, CTkOptionMenu, CTkSwitch, CTkSlider, CTkSegmentedButton, CTkTabview, CTkScrollableFrame, CTkProgressBar; własne skalowanie HiDPI.

**Czego nie daje.** Odpowiednika `ttk.Treeview` (lista/tabela), `ttk.Spinbox` (trzeba złożyć z Entry i dwu przycisków), stylowanego `tk.Menu`; nie jest to motyw dla ttk, tylko osobny zestaw widżetów.

**Pułapki.** Mieszanie widżetów CTk z ttk wygląda niespójnie (różne wysokości, promienie, fonty), więc migracja jest "wszystko albo nic" w obrębie okna. Widżety rysowane na Canvas: przy dużej liczbie (ponad ok. 100 w jednym oknie) odczuwalne spowolnienie odrysowania i zmiany rozmiaru. Własne skalowanie CTk może kolidować z `SetProcessDpiAwareness` ustawionym przez aplikację (CTk włącza DPI awareness samo; sprawdź `deactivate_automatic_dpi_awareness`). API zmieniało się między wersjami (np. nazwy parametrów kolorów), więc przypnij wersję.

### 2.5 PySide6 / PyQt6

**Co daje.** Pełny natywny toolkit: QPalette + QSS (styl Fusion jako baza), QMediaPlayer + QVideoWidget/QGraphicsVideoItem (odtwarzanie wideo w UI bez własnego dekodowania), QGraphicsView (nakładka jako przesuwalny element sceny), QDockWidget (dokowanie paneli), QFormLayout, QSplitter, QThread/QThreadPool z sygnałami, dostępność (UI Automation), ikony SVG, drukowanie, tabele (QTableView z modelem). Gotowe biblioteki motywów: qt-material (Material), PyQt-Fluent-Widgets (Fluent, sprawdź licencję), QDarkStyle. Szczegóły API w `qt-pyside6.md`.

**Czego nie daje.** Zachowania istniejącego kodu UI: każdy widżet, każde `bind`, każda zmienna Tk (`StringVar`) zostaje przepisana. Mały rozmiar pakietu.

**Pułapki.** Licencja (patrz macierz). Rozmiar dystrybucji i czas budowania PyInstaller (wyklucz nieużywane moduły Qt). Kodeki wideo w QMediaPlayer zależą od backendu (na Windows historycznie Media Foundation, w nowszych wersjach FFmpeg; sprawdź dla swojej wersji i formatów plików). Mieszanie QSS z QPalette bez planu prowadzi do niespójności (patrz `qt-pyside6.md`, pułapki QSS). Różnice PySide6 vs PyQt6 (nazwy sygnałów `Signal` vs `pyqtSignal`, w PyQt6 wymagane pełne nazwy enumów).

### 2.6 Flet

**Co daje.** Interfejs Flutter (Material 3) sterowany z Pythona, atrakcyjny wygląd, ten sam kod na desktop/web/mobile, animacje, responsywność.

**Czego nie daje.** Modelu widżetów Tk ani Qt; brak bezpośredniego dostępu do okna/Canvasu jak w Tk, integracja z OpenCV/PIL przez strumieniowanie obrazów do kontrolki `Image` (klatka po klatce jako base64 lub plik; kosztowne). Wygląd nie jest Fluent/Windows.

**Pułapki.** Inny model pakowania (`flet build windows` z Flutter SDK lub `flet pack` oparty o PyInstaller; sprawdź, który jest aktualnie zalecany), inny cykl życia (proces UI jako osobny silnik), API zmienia się między wersjami. Dla narzędzia z falą audio i podglądem wideo to raczej niewłaściwa technologia.

### 2.7 DearPyGui

**Co daje.** Renderowanie na GPU, bardzo szybkie wykresy i rysowanie (fala audio z milionów próbek, siatki, markery), własny system motywów, prosty model API (retained mode: tworzysz elementy, ustawiasz wartości).

**Czego nie daje.** Natywnego wyglądu Windows (estetyka narzędzi deweloperskich / gier), natywnych dialogów w pełni (własny dialog plików lub zewnętrzna biblioteka), dostępności, natywnego odtwarzania wideo (klatki jako tekstury aktualizowane co klatkę, co jest wykonalne i szybkie).

**Pułapki.** Inny model programowania (pętla renderowania, callbacki z tagami elementów), własne fonty (trzeba załadować pliki TTF, domyślny font nie ma polskich znaków bez dodania zakresu), skalowanie DPI ręczne. Dla zespołu znającego Tk to pełna zmiana paradygmatu.

## 3. Reguła decyzyjna

Drzewo (czytaj od góry, pierwszy pasujący warunek wygrywa):

1. **Wykryty framework to PySide6/PyQt6?** Opcje 1..4 (ttk i pochodne) nie mają zastosowania. Wybór jest inny: patrz sekcja 3.1.
2. **Wykryty framework to CustomTkinter, ttkbootstrap lub sv-ttk?** Zostań w tej bibliotece i popraw tokeny/motyw w jej mechanizmie (odpowiednio motyw JSON, motyw użytkownika, edycja motywu). Nie mieszaj drugiej biblioteki motywów.
3. **Aplikacja potrzebuje czegoś, czego Tk nie da:** natywnego odtwarzania wideo z dźwiękiem w UI, dokowania paneli, tabel z tysiącami wierszy i sortowaniem, dostępności dla czytników ekranu, animacji, lub ma być rozwijana latami przez większy zespół? -> migracja do Qt (opcja 5) według playbooka z sekcji 4. Warunek dodatkowy: licencja zweryfikowana dla sposobu dystrybucji.
4. **Potrzebny szybki efekt, akceptujesz estetykę i ograniczenia gotowego motywu** (niebieski akcent w sv-ttk, styl Bootstrap w ttkbootstrap), a aplikacja używa niemal wyłącznie ttk? -> opcja 2 lub 3. Doliczaj czas na klasyczne widżety `tk.*` i ciemny pasek tytułu.
5. **W pozostałych przypadkach (domyślnie):** opcja 1, ttk + własny motyw z `scripts/theme_template.py` i widżety z `scripts/widgets.py`. Najniższe ryzyko, pełna kontrola akcentu (#FFC400) i tokenów, zero nowych zależności.

Opcje 6 i 7 rozważaj tylko przy budowie nowej aplikacji od zera z wymaganiami, które do nich pasują (Flet: multiplatformowość web/mobile; DearPyGui: wizualizacja dużych danych na GPU). Jako cel migracji istniejącego narzędzia Tk są nieopłacalne.

### 3.1 Aplikacja już napisana w PySide6 / PyQt6

Gdy repozytorium zawiera `QMainWindow`, `QGroupBox`, `QThread` itd., pytanie "ttk czy migracja" znika. Decyzja dotyczy głębokości odświeżenia w obrębie Qt:

| Wariant | Nakład | Kiedy | Ryzyko |
|---|---|---|---|
| A. Odświeżenie w miejscu: `QApplication.setStyle("Fusion")` + QPalette z tokenów + arkusz QSS z tokenami + kilka własnych widżetów (nagłówek sekcji, swatch koloru, pole ścieżki, oś czasu na QPainter) | S..M | domyślnie; layout jest w zasadzie dobry, wygląd przestarzały (QGroupBox z ramkami, domyślny styl Windows) | niskie: te same widżety i sygnały; ryzyko to konflikty QSS z istniejącymi `setStyleSheet` na pojedynczych widżetach |
| B. Biblioteka motywu: PyQt-Fluent-Widgets (wygląd Windows 11, własne widżety) lub qt-material (Material) | M..L | chcesz Fluent "z pudełka" i akceptujesz podmianę klas widżetów na biblioteczne (Fluent-Widgets) albo tylko arkusz (qt-material) | średnie..wysokie dla Fluent-Widgets (podmiana klas, własne API, licencja GPL/komercyjna, sprawdź); niskie dla qt-material (sam QSS, ale estetyka Material, nie Fluent) |
| C. Przebudowa layoutu: nowy podział okna (QSplitter, QDockWidget, QScrollArea w inspektorze, pasek transportu, QStatusBar), zachowanie logiki i wątków | L | struktura okna jest źródłem problemów (brak przewijania, sekcje w złej kolejności, brak transportu), a nie tylko kolory | średnie: przeniesienie widżetów między layoutami bez zmiany sygnałów; wymaga oddzielenia logiki od budowy UI, jeśli `gui.py` miesza obie |

Zalecenie: zacznij od A (Fusion + QPalette + QSS z tokenów, jeden krok ze zrzutem), potem oceń, czy potrzebne jest C; B tylko gdy zespół chce zrezygnować z własnego arkusza na rzecz gotowego zestawu. QGroupBox z ramką zastępuj nagłówkiem sekcji (`component-patterns.md` §2) stopniowo, sekcja po sekcji. Wzorce z `component-patterns.md` obowiązują bez zmian; odpowiedniki Qt są wskazane w każdym wzorcu, a szczegóły API w przewodniku Qt skilla.

## 4. Playbook migracji (strangler)

Kolejność kroków jest ta sama dla opcji 1 (odświeżenie w miejscu) i opcji 5 (migracja); różni się tylko to, jak daleko idziesz. Każdy krok kończy się zrzutem przed/po i uruchomieniem aplikacji na tym samym pliku wejściowym.

1. **Inwentaryzacja.** Lista okien, sekcji, widżetów (klasa, zmienna, callback), wiązań klawiszy, miejsc zapisu ustawień. Zaznacz, gdzie logika siedzi w callbackach UI (kandydaci do wyciągnięcia). Wynik: tabela w `audit-example-*.md`.
2. **Oddziel model od widoków.** Wprowadź obiekt stanu (dataclass lub istniejący słownik ustawień) i funkcje logiki bez odwołań do widżetów. Widżety czytają/piszą stan przez cienką warstwę (zmienne Tk lub sygnały Qt). Nie zmieniaj formatu zapisu; testem jest porównanie pliku ustawień przed i po (`diff`).
3. **Motyw i fonty najpierw.** `enable_hidpi`, `apply_theme`, `set_windows_dark_titlebar`, fonty z tokenów. Zero zmian w layoutcie. Zrzut w 100 % i 150 %, dark i light, PL i EN.
4. **Warstwa widżetów.** Wprowadź fabryki/adaptery: `make_button(parent, text, kind="accent")`, `make_number_field(...)` itd., które zwracają widżety ze `scripts/widgets.py` lub zwykłe ttk. Podmieniaj wywołania w kodzie sekcja po sekcji; każda sekcja to osobny commit i zrzut. Przy migracji do Qt fabryki są miejscem, w którym implementacja Tk zostaje zastąpiona implementacją Qt bez ruszania kodu wywołującego (o ile interfejs adaptera jest neutralny: `get()/set()/on_change(callback)`).
5. **Layout.** PanedWindow/QSplitter, przewijany inspektor, pasek transportu, pasek stanu (`component-patterns.md` §1). Dopiero teraz, bo zmiany layoutu na starych widżetach nie dają się ocenić wizualnie.
6. **Feature flag.** Nowy UI włączany zmienną środowiskową lub argumentem (`--new-ui`), stary pozostaje domyślny do końca migracji. Flaga nie może zmieniać formatu ustawień. Przy odświeżeniu w miejscu (opcja 1) flaga może być tylko przełącznikiem motywu (stary/nowy), co i tak przydaje się do porównań.
7. **Zrzuty jako testy.** Skrypt uruchamia aplikację z tym samym plikiem wejściowym, ustawia stały rozmiar okna (`geometry("1280x800+0+0")`), czeka na `after_idle`, robi zrzut (np. `PIL.ImageGrab.grab(bbox)` z `winfo_rootx/rooty`), zapisuje do `screenshots/<krok>_<dpi>_<motyw>_<jezyk>.png`. Porównanie: ten sam rozmiar okna, ten sam DPI (uruchamiaj na tym samym monitorze lub wymuś skalowanie), ten sam plik wejściowy i te same ustawienia (kopia pliku ustawień w fixtures), wyłączone animacje/kursor migający (`insertofftime=0`), stała pozycja playheada. Różnice pikselowe oceniaj wzrokiem, nie progiem; próg ma sens tylko dla wykrywania "nic się nie zmieniło tam, gdzie nie powinno" (np. podgląd wideo po zmianie motywu).
8. **Usunięcie starego UI.** Po akceptacji wszystkich zrzutów i tygodniu użycia: usuń starą ścieżkę i flagę.

Sygnały ostrzegawcze podczas playbooka: callback UI wywołuje bezpośrednio ffmpeg/OpenCV (zasada 6: wynieś do wątku najpierw), wartość ustawienia parsowana z tekstu widżetu w wielu miejscach (wprowadź jedną funkcję parsowania), stany ukryte w `winfo_ismapped()` lub kolorze widżetu (przenieś do stanu modelu).

## 5. Szacowanie nakładu

Heurystyka, orientacyjna (zależy od jakości separacji logiki od UI i od doświadczenia z biblioteką). Jednostka: osobodni dla jednej osoby znającej Pythona i przynajmniej jedną z bibliotek.

| Element | Opcja 1 (ttk + motyw) | Opcja 2/3 (gotowy motyw) | Opcja 4 (CustomTkinter) | Opcja 5 (Qt, rewrite UI) |
|---|---|---|---|---|
| Fundament: HiDPI, motyw, fonty, pasek tytułu | 0,5..1 | 0,5 | 1 | 1..2 (Fusion + QPalette + QSS) |
| Inspektor z 30 kontrolkami w 4..5 sekcjach | 1,5..3 (adaptery, sekcje, formularze) | 1..2 (głównie poprawki wymiarów) | 3..5 (przepisanie każdego widżetu) | 4..8 (QFormLayout, walidatory, sygnały) |
| Podgląd wideo + tryb edycji pozycji | 0,5..1 (kolory, ramka, uchwyty) | 0,5 | 1 | 2..4 (QGraphicsView lub QVideoWidget; więcej, gdy odtwarzanie przez QMediaPlayer) |
| Oś czasu z falą i markerami | 1..2 (kolory, etykiety, snapping, zoom) | 1..2 | 1..2 | 2..4 (QPainter, cache, zdarzenia) |
| Pasek transportu + pasek stanu + skróty | 0,5..1 | 0,5..1 | 1 | 1..2 |
| Wątki i feedback (busy, postęp, anulowanie) | 0,5..1 (jeśli już są wątki) | 0,5..1 | 0,5..1 | 1..2 (QThread + sygnały; jeśli logika jest oddzielona) |
| i18n nowych tekstów, oba motywy, 4 DPI, zrzuty | 1 | 1 | 1 | 1,5..2 |
| Pakowanie i test na czystej maszynie | 0,5 | 0,5 | 0,5 | 1..2 (rozmiar, moduły Qt, kodeki) |
| **Razem** | **ok. 6..10** | **ok. 5..8** | **ok. 9..13** | **ok. 14..26** |

Mnożniki:

- Logika zmieszana z UI (callbacki zawierają obliczenia, brak obiektu stanu): +30..50 % dla opcji 1..3, +50..100 % dla opcji 4..5 (krok 2 playbooka staje się główną pracą).
- Więcej okien (dialogi ustawień, kreatory): +1..2 dni na okno dla opcji 1..3, +2..4 dla opcji 5.
- Brak doświadczenia zespołu z biblioteką docelową: +50 % dla opcji 4..5.
- Aplikacja już w PySide6 (sekcja 3.1): wariant A ok. 3..6 dni, wariant C ok. 8..15 dni, wariant B pomiędzy, zależnie od liczby podmienianych klas.

Liczby służą do porównania opcji między sobą, nie do zobowiązań terminowych. Po pierwszych dwóch krokach playbooka zweryfikuj tempo i przelicz.
