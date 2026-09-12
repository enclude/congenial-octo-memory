# Tokeny projektowe (design tokens)

Źródło prawdy dla kolorów, odstępów, promieni, fontów i stanów w skillu `python-desktop-ux`. Kod aplikacji odwołuje się do nazw tokenów (`TOKENS[theme]["surface"]`), nigdy do wartości hex. Blok Python na końcu tego pliku jest wzorcem dla `scripts/theme_template.py`; przy rozbieżności wygrywa ten dokument.

## Zasady

- Paleta neutralna (szarości o lekko chłodnym odcieniu) plus jeden akcent. Akcent pochodzi z nakładki aplikacji: bursztyn `#FFC400` (RGBA 255,196,0).
- Akcent służy wyłącznie do: przycisku primary, zaznaczenia, aktywnego markera, aktywnej zakładki i wskaźników postępu. Nie koloruje tła sekcji, nagłówków ani ikon dekoracyjnych.
- Kolory semantyczne (`danger`, `success`, `warning`, `info`) niosą znaczenie i zawsze występują z tekstem lub ikoną. Czerwień nie oznacza "końca zakresu", zieleń nie oznacza "początku".
- Motyw ciemny (DARK) jest domyślny: narzędzie pracuje z podglądem wideo i falą audio, ciemne otoczenie zmniejsza olśnienie i nie konkuruje z obrazem. Motyw jasny (LIGHT) jest pełnoprawną alternatywą i musi przechodzić te same testy kontrastu.
- Tk nie ma przezroczystości w kolorach widżetów, dlatego `accent_subtle`, `surface_alt` i stany hover są gotowymi, nieprzezroczystymi mieszankami.
- Wartości kontrastu w tym pliku są policzone, nie oszacowane. Zmieniając token, policz ponownie (§Weryfikacja kontrastu).

## Paleta DARK (domyślna)

| Token | Hex | Zastosowanie |
|---|---|---|
| bg | #1F1F1F | tło okna, letterbox podglądu, tło osi czasu, tło pod panelami |
| surface | #2A2A2C | panele (inspektor, pasek narzędzi, pasek stanu), karty, dialogi |
| surface_alt | #353538 | tło pól wprowadzania, wiersze naprzemienne, hover na elementach neutralnych, nagłówek tabeli |
| border | #3F3F43 | linie oddzielające sekcje, ramki paneli, siatka osi czasu |
| border_strong | #78787F | ramki pól wprowadzania i przycisków secondary (musi mieć 3:1 do surface) |
| text | #F2F2F2 | tekst podstawowy, wartości pól, etykiety |
| text_muted | #A0A0A8 | etykiety pomocnicze, jednostki, podpisy podziałki, fala audio |
| text_disabled | #6E6E76 | tekst i ikony kontrolek wyłączonych (celowo poniżej 4.5:1) |
| accent | #FFC400 | wypełnienie primary, aktywny marker T0, aktywna zakładka, postęp, ikony aktywne |
| accent_hover | #FFD033 | primary pod kursorem |
| accent_pressed | #E0AC00 | primary wciśnięty |
| accent_text | #1A1200 | tekst i ikony na wypełnieniu accent / accent_hover / accent_pressed |
| accent_subtle | #3F3821 | tło zaznaczonego wiersza bez fokusu, tło odznaki, podświetlenie zakresu Od-Do na osi |
| danger | #F87171 | tekst błędu, ramka pola z błędem, ikona błędu |
| success | #4ADE80 | potwierdzenie w pasku stanu, ikona OK |
| warning | #FB923C | ostrzeżenie (pomarańcz, celowo różny od bursztynowego akcentu) |
| info | #60A5FA | informacja, podpowiedź, link |
| focus | #FFFFFF | pierścień fokusu 2 px (konwencja Windows 11: biały w ciemnym motywie) |
| selection_bg | #FFC400 | zaznaczenie tekstu w polach, zaznaczony wiersz z fokusem |
| selection_text | #1A1200 | tekst na selection_bg |

## Paleta LIGHT

| Token | Hex | Zastosowanie |
|---|---|---|
| bg | #F3F3F3 | tło okna (odpowiednik Mica), letterbox, tło osi czasu |
| surface | #FFFFFF | panele, karty, dialogi, tło pól wprowadzania |
| surface_alt | #ECECEE | hover na elementach neutralnych, wiersze naprzemienne, pasek narzędzi, nagłówek tabeli |
| border | #D5D5D9 | linie oddzielające, ramki paneli, siatka osi |
| border_strong | #8A8A90 | ramki pól i przycisków secondary |
| text | #1B1B1F | tekst podstawowy |
| text_muted | #5C5C63 | etykiety pomocnicze, jednostki, podziałka, fala audio |
| text_disabled | #9A9AA1 | kontrolki wyłączone (celowo poniżej 4.5:1) |
| accent | #8A6100 | ciemny bursztyn: wypełnienie primary, tekst i ramki w kolorze akcentu, aktywny marker, postęp |
| accent_hover | #986A00 | primary pod kursorem |
| accent_pressed | #6B4B00 | primary wciśnięty |
| accent_text | #FFFFFF | tekst na accent / accent_hover / accent_pressed |
| accent_subtle | #FFF3CC | tło zaznaczonego wiersza bez fokusu, odznaki, podświetlenie zakresu na osi |
| danger | #C42B1C | błąd |
| success | #0F7B0F | potwierdzenie |
| warning | #B45309 | ostrzeżenie |
| info | #0F6CBD | informacja, link |
| focus | #1B1B1F | pierścień fokusu 2 px (konwencja Windows 11: czarny w jasnym motywie) |
| selection_bg | #FFC400 | zaznaczenie tekstu, zaznaczony wiersz z fokusem: jedyne miejsce, gdzie brandowy żółty występuje w jasnym UI |
| selection_text | #1A1200 | tekst na selection_bg |

### Dlaczego akcent w LIGHT nie jest żółty

`#FFC400` na białym tle ma kontrast ok. 1.6:1. Jako tekst, ramka, ikona czy wskaźnik jest nieczytelny i nie spełnia nawet progu 3:1 dla elementów UI. Dlatego w LIGHT token `accent` przyjmuje ciemniejszą odmianę `#8A6100` (5.5:1 na białym: przechodzi jako tekst i jako element UI), a brandowy `#FFC400` pozostaje tylko jako wypełnienie z ciemnym tekstem: w `selection_bg`/`selection_text` oraz oczywiście w samej nakładce na podglądzie (to treść, nie UI).

Wariant: jeśli w LIGHT przycisk primary ma pozostać żółty jak nakładka, użyj pary `selection_bg`/`selection_text` jako wypełnienia i tekstu stylu `Primary.TButton`, a `accent` zostaw ciemny dla tekstu, ramek i markerów. Nie wprowadzaj nowych nazw tokenów.

### Mapowanie tokenów na role widżetów

| Rola | DARK | LIGHT |
|---|---|---|
| Okno, letterbox, tło osi czasu | bg | bg |
| Panel, pasek narzędzi, pasek stanu, dialog | surface | surface |
| Tło pola (Entry, Spinbox, Combobox, Text) | surface_alt | surface |
| Ramka pola w spoczynku | border_strong | border_strong |
| Ramka pola z fokusem | focus (2 px) | focus (2 px) |
| Przycisk secondary: tło / ramka / tekst | surface / border_strong / text | surface / border_strong / text |
| Przycisk secondary hover | surface_alt | surface_alt |
| Przycisk primary: tło / tekst | accent / accent_text | accent / accent_text |
| Przycisk ghost: tło / tekst; hover | brak / text; surface_alt | brak / text; surface_alt |
| Nagłówek sekcji: tekst / linia | text / border | text / border |
| Fala audio / detekcje / marker T0 / zakres Od-Do | text_muted / accent (1 px) / accent / accent_subtle | text_muted / accent / accent / accent_subtle |
| Playhead | text | text |

Jedyna różnica między motywami w mapowaniu to tło pól: w DARK pola są jaśniejsze od panelu (`surface_alt`), w LIGHT białe jak panel (`surface`) i odróżnia je ramka.

## Weryfikacja kontrastu

Metoda: współczynnik kontrastu WCAG 2.x z luminancji względnej sRGB, policzony skryptem Python (nie jest częścią skilla; wynik poniżej). Progi: 4.5:1 dla tekstu, 3:1 dla elementów UI (ramki, ikony, fokus, markery). `text_disabled` i `border` są podane informacyjnie: celowo słabsze, bo mają schodzić na drugi plan; nie wolno nimi przekazywać informacji koniecznej do wykonania zadania.

### DARK

| Para | Kolory | Wynik | Wymóg | Status |
|---|---|---|---|---|
| text / bg | #F2F2F2 / #1F1F1F | 14.72:1 | 4.5:1 | OK |
| text / surface | #F2F2F2 / #2A2A2C | 12.80:1 | 4.5:1 | OK |
| text_muted / surface | #A0A0A8 / #2A2A2C | 5.52:1 | 4.5:1 | OK |
| text_disabled / surface | #6E6E76 / #2A2A2C | 2.83:1 | informacyjnie | celowo poniżej |
| accent_text / accent | #1A1200 / #FFC400 | 11.63:1 | 4.5:1 | OK |
| accent / surface | #FFC400 / #2A2A2C | 8.97:1 | 3.0:1 (element UI) | OK |
| danger / surface | #F87171 / #2A2A2C | 5.18:1 | 4.5:1 | OK |
| success / surface | #4ADE80 / #2A2A2C | 8.22:1 | 4.5:1 | OK |
| warning / surface | #FB923C / #2A2A2C | 6.33:1 | 4.5:1 | OK |
| info / surface | #60A5FA / #2A2A2C | 5.63:1 | 4.5:1 | OK |
| selection_text / selection_bg | #1A1200 / #FFC400 | 11.63:1 | 4.5:1 | OK |
| focus / surface | #FFFFFF / #2A2A2C | 14.32:1 | 3.0:1 (element UI) | OK |
| border_strong / surface | #78787F / #2A2A2C | 3.27:1 | 3.0:1 (element UI) | OK (po korekcie) |
| border / surface | #3F3F43 / #2A2A2C | 1.37:1 | informacyjnie | linia dekoracyjna |

### LIGHT

| Para | Kolory | Wynik | Wymóg | Status |
|---|---|---|---|---|
| text / bg | #1B1B1F / #F3F3F3 | 15.47:1 | 4.5:1 | OK |
| text / surface | #1B1B1F / #FFFFFF | 17.17:1 | 4.5:1 | OK |
| text_muted / surface | #5C5C63 / #FFFFFF | 6.63:1 | 4.5:1 | OK |
| text_disabled / surface | #9A9AA1 / #FFFFFF | 2.80:1 | informacyjnie | celowo poniżej |
| accent_text / accent | #FFFFFF / #8A6100 | 5.54:1 | 4.5:1 | OK |
| accent / surface | #8A6100 / #FFFFFF | 5.54:1 | 3.0:1 (element UI) | OK (także jako tekst) |
| danger / surface | #C42B1C / #FFFFFF | 5.66:1 | 4.5:1 | OK |
| success / surface | #0F7B0F / #FFFFFF | 5.44:1 | 4.5:1 | OK |
| warning / surface | #B45309 / #FFFFFF | 5.02:1 | 4.5:1 | OK |
| info / surface | #0F6CBD / #FFFFFF | 5.38:1 | 4.5:1 | OK |
| selection_text / selection_bg | #1A1200 / #FFC400 | 11.63:1 | 4.5:1 | OK |
| focus / surface | #1B1B1F / #FFFFFF | 17.17:1 | 3.0:1 (element UI) | OK |
| border_strong / surface | #8A8A90 / #FFFFFF | 3.43:1 | 3.0:1 (element UI) | OK |
| border / surface | #D5D5D9 / #FFFFFF | 1.46:1 | informacyjnie | linia dekoracyjna |

Pary dodatkowe (stany): `accent_text / accent_hover` DARK 12.67:1, LIGHT 4.78:1; `accent_text / accent_pressed` DARK 8.91:1, LIGHT 7.98:1; `text / accent_subtle` DARK 10.43:1, LIGHT 15.49:1; `text / surface_alt` DARK 10.92:1, LIGHT 14.55:1.

### Korekty wprowadzone po pomiarze

- DARK `border_strong`: pierwsza propozycja `#626268` dała 2.36:1 do `surface`, poniżej progu 3:1 dla ramek pól. Zmieniono na `#78787F` (3.27:1).
- LIGHT `accent_hover`: pierwsza propozycja `#9C6E00` dała 4.52:1 z białym tekstem, na granicy AA. Zmieniono na `#986A00` (4.78:1), żeby zachować margines na antyaliasing i ClearType.
- LIGHT `accent`: brandowy `#FFC400` (1.6:1 na białym) zastąpiono `#8A6100`; uzasadnienie w §Dlaczego akcent w LIGHT nie jest żółty.

## Skala odstępów

Wartości w px przy 96 dpi (100 %). W Tk podawaj je bezpośrednio w `padding`, `padx`, `pady`; przy DPI awareness Tk skaluje geometrię przez `tk scaling` tylko dla jednostek punktowych, więc dla px użyj `scale_px(v) = round(v * tk_scaling / (96/72))` lub trzymaj wartości w px i akceptuj, że przy 150 % odstępy są proporcjonalnie ciaśniejsze (zalecane: skaluj).

| Token | px | Użycie |
|---|---|---|
| sp_1 | 4 | odstęp ikona-tekst, wewnętrzny odstęp między próbką koloru i hex, odstęp między przyciskami w grupie segmentowej |
| sp_2 | 8 | odstęp między etykietą i kontrolką, między kontrolkami w jednym wierszu, między wierszami formularza, padding pionowy w polach |
| sp_3 | 12 | padding poziomy przycisków, odstęp między przyciskami w pasku, odstęp nagłówka sekcji od pierwszego wiersza |
| sp_4 | 16 | padding sekcji (lewo/prawo), margines wewnętrzny paneli, odstęp między grupami przycisków |
| sp_5 | 20 | margines dialogów, odstęp między kolumnami paneli |
| sp_6 | 24 | odstęp między sekcjami inspektora, margines okna od krawędzi do treści |
| sp_8 | 32 | odstęp między blokami na pustym stanie, nad przyciskiem primary w dialogu |

Zasady użycia:

- Wysokość kontrolki 28-32 px (przy 10 pt font wiersz tekstu ma ok. 17 px; `padding=(sp_3, 5)` na TButton i `padding=(sp_2, 5)` na TEntry daje ok. 28-30 px). Spinbox i Combobox wyrównaj do tej samej wysokości.
- Wiersz formularza: kontrolka 28-32 px + `pady=(0, sp_2)`. Etykieta wyrównana do lewej (`sticky="w"`), do linii bazowej kontrolki.
- Kolumna etykiet: jedna szerokość dla całego inspektora (`columnconfigure(0, minsize=150)` przy 100 %), etykieta i kontrolka rozdzielone `sp_2`.
- Sekcja: nagłówek, `sp_3`, wiersze, `sp_6` do następnej sekcji. Padding sekcji `sp_4` po bokach; zawartość nie dotyka krawędzi panelu.
- Okno: treść odsunięta od krawędzi o `sp_4` (panele) lub `sp_6` (dialogi).
- Pasek narzędzi i pasek stanu: wysokość 36-40 px, padding poziomy `sp_3`, elementy rozdzielone `sp_2`, grupy `sp_4`.
- Nie używaj wartości spoza skali. Jeśli "brakuje" 6 px, poprawny jest zwykle inny podział siatki, nie nowy token.

## Typografia

| Nazwany font | Rodzina i fallback | Rozmiar (pt) | Waga | Użycie |
|---|---|---|---|---|
| font_ui | Segoe UI Variable Text -> Segoe UI -> TkDefaultFont | 10 | normal | etykiety, wartości, przyciski, menu, tooltipy |
| font_ui_small | jak font_ui | 9 | normal | jednostki, podpisy podziałki osi, tekst pomocniczy pod polem, pasek stanu |
| font_section | jak font_ui | 11 | bold | nagłówki sekcji inspektora, tytuły grup w dialogach |
| font_title | jak font_ui | 13 | bold | tytuł dialogu, tytuł pustego stanu, nazwa pliku w nagłówku obszaru roboczego |
| font_mono | Cascadia Mono -> Consolas -> TkFixedFont | 10 | normal | wartości czasu, współrzędne, hex kolorów, log, tabela strzałów |

Fallbacki dla innych platform (kolejność dopisana za fallbackami Windows): Linux: Noto Sans, DejaVu Sans (mono: Noto Sans Mono, DejaVu Sans Mono); macOS: TkDefaultFont wskazuje na font systemowy (mono: Menlo). Wybieraj pierwszą rodzinę obecną w `tkinter.font.families()`; nazwy nieobecne Tk cicho zastępuje domyślnym fontem, więc sprawdzaj obecność jawnie.

Uwagi o Tk:

- Dodatni rozmiar fontu to punkty przeliczane na piksele przez `tk scaling` (px na pt; przy 96 dpi ok. 1.33). Ujemny rozmiar to piksele bez skalowania. Dla tekstu UI używaj punktów, wtedy fonty rosną z DPI. Piksele wolno użyć tylko do glifów ikon dopasowanych do bitmap.
- Zamiast tworzyć font przy każdym widżecie, zdefiniuj nazwane fonty raz (`tkinter.font.Font(name="font_ui", family=..., size=10)`) i podawaj `font="font_ui"`; nadpisz też `TkDefaultFont`, `TkTextFont`, `TkMenuFont`, `TkHeadingFont`, `TkTooltipFont`, żeby widżety bez jawnego fontu przejęły nową rodzinę i rozmiar.
- Segoe UI Variable to font Windows 11 z instancjami "Display", "Text", "Small". Jeśli `tkinter.font.families()` nie zawiera "Segoe UI Variable Text", użyj "Segoe UI". Cascadia Mono może nie być zainstalowana na Windows 10: sprawdź obecność.
- Wartości liczbowe wyrównuj do prawej (`justify="right"`) lub używaj `font_mono`, żeby cyfry tworzyły kolumny.
- Przeliczenie px -> pt dla glifów ikon: `pt = px * 72 / 96` przy 100 % (16 px = 12 pt, 20 px = 15 pt, 24 px = 18 pt).

## Promienie i obramowania

| Token | px | Użycie |
|---|---|---|
| r_sm | 4 | pola wprowadzania, odznaki, próbki koloru, przyciski segmentowe |
| r_md | 6 | przyciski, karty w inspektorze, tooltipy |
| r_lg | 8 | dialogi, panele podglądu, menu kontekstowe |

Ograniczenia frameworków:

- Klasyczne ttk (motyw `clam` jako baza) nie rysuje zaokrągleń ani cieni. Promienie realizuj tylko tam, gdzie framework pozwala (CustomTkinter, ttkbootstrap z własnymi obrazami elementów, Qt przez QSS `border-radius`). W czystym ttk zaokrąglenie da się uzyskać przez `style.element_create(..., "image", ...)` z prerenderowanymi bitmapami dla każdego stanu; rób to tylko dla przycisków primary, jeśli w ogóle.
- Cieni nie ma: "elevation" buduj kontrastem powierzchni (`surface` na `bg`) i linią 1 px w kolorze `border`. Dialog: `surface` z ramką `border`, na tle okna `bg`.
- Ramki pól 1 px w `border_strong` (3:1 do powierzchni), ramki dekoracyjne (separatory, obwódki paneli) 1 px w `border`.
- Separator sekcji: linia 1 px `border` na całą szerokość pod nagłówkiem; nie ramka wokół sekcji.
- Fokus: pierścień 2 px w `focus` na zewnątrz lub w miejscu ramki 1 px (wtedy ramka rośnie do 2 px, geometria się nie zmienia, jeśli rezerwujesz 2 px od początku).

## Stany

| Stan | Tło | Tekst / ikona | Ramka | Uwagi |
|---|---|---|---|---|
| primary spoczynek | accent | accent_text | brak | jeden na widok |
| primary hover | accent_hover | accent_text | brak | |
| primary pressed | accent_pressed | accent_text | brak | |
| secondary spoczynek | surface | text | border_strong 1 px | |
| secondary hover | surface_alt | text | border_strong | |
| secondary pressed | surface_alt | text | border_strong | dodatkowo lekkie przyciemnienie tła, jeśli framework pozwala |
| ghost spoczynek | brak | text (lub text_muted) | brak | akcje pomocnicze, linki, przyciski ikonowe |
| ghost hover | surface_alt | text | brak | |
| pole spoczynek | surface_alt (DARK) / surface (LIGHT) | text | border_strong 1 px | placeholder w text_muted |
| pole hover | jak spoczynek | text | border_strong | opcjonalnie border jaśniejszy o jeden krok |
| pole fokus | jak spoczynek | text | focus 2 px | kursor w kolorze text (`insertbackground`) |
| pole readonly | surface_alt | text | border 1 px | bez kursora, tekst zaznaczalny |
| pole invalid | jak spoczynek | text | danger 2 px | komunikat pod polem w danger, font_ui_small |
| disabled (każda kontrolka) | surface | text_disabled | border | ikony także w text_disabled; brak hover |
| zaznaczenie z fokusem (lista, tekst) | selection_bg | selection_text | brak | |
| zaznaczenie bez fokusu | accent_subtle | text | brak | |
| przełącznik aktywny (Toolbutton, zakładka) | accent_subtle | text | accent 2 px na dolnej lub lewej krawędzi | tekst bez zmiany koloru, żeby nie tracić kontrastu |
| fokus na przycisku primary | accent | accent_text | focus 2 px z odstępem 1 px w surface | podwójny pierścień, jak w Windows 11 |
| fokus na Canvas (oś czasu) | bez zmian | bez zmian | focus 2 px (`highlightthickness=2`, `highlightcolor`) | `highlightbackground` = surface, żeby ramka znikała bez fokusu |

W ttk stany mapuje się przez `style.map("Primary.TButton", background=[("pressed", accent_pressed), ("active", accent_hover), ("disabled", surface)], ...)`; kolejność krotek ma znaczenie (pierwsze dopasowanie wygrywa), więc `disabled` daj na początku listy, a `pressed` przed `active`. Szczegóły w `tkinter-ttk.md`.

## Ikony

Podejście lekkie i zalecane na Windows: glify z fontu systemowego "Segoe Fluent Icons" (Windows 11) lub "Segoe MDL2 Assets" (Windows 10 i 11) w `ttk.Label`/`ttk.Button` z parametrem `font=("Segoe Fluent Icons", 12)`. Glify skalują się z DPI jak tekst, przyjmują kolor `foreground` (więc dark/light za darmo) i nie wymagają plików. Sprawdź obecność fontu w `tkinter.font.families()` i wybierz Fluent, a w razie braku MDL2; oba fonty używają tych samych kodów dla poniższych glifów. Rozmiary: 16 px (12 pt) inline i w menu, 20 px (15 pt) w pasku narzędzi, 24 px (18 pt) dla dużych akcji.

| Użycie | Nazwa glifu | Kod |
|---|---|---|
| Otwórz plik / folder | FolderOpen | U+E838 |
| Folder (zamknięty) | Folder | U+E8B7 |
| Odtwarzaj | Play | U+E768 |
| Pauza | Pause | U+E769 |
| Stop | Stop | U+E71A |
| Poprzedni / następny marker | Previous / Next | U+E892 / U+E893 |
| Odśwież, wykryj ponownie | Refresh | U+E72C |
| Synchronizuj | Sync | U+E895 |
| Pobierz (API) | Download | U+E896 |
| Eksport / wyślij | Upload | U+E898 |
| Ustawienia | Setting | U+E713 |
| Rozwiń / zwiń sekcję | ChevronDown / ChevronUp | U+E70D / U+E70E |
| W lewo / w prawo | ChevronLeft / ChevronRight | U+E76B / U+E76C |
| Zamknij | Cancel (X) lub ChromeClose | U+E711 / U+E8BB |
| Potwierdzenie | CheckMark | U+E73E |
| Ostrzeżenie | Warning | U+E7BA |
| Informacja | Info | U+E946 |
| Błąd | Error | U+E783 |
| Kolor (pipeta / paleta) | Color | U+E790 |
| Przycięcie | Crop | U+E7A8 |
| Wideo | Video | U+E714 |
| Dźwięk / fala | Audio | U+E8D6 |
| Powiększ / pomniejsz oś | Zoom / ZoomOut | U+E71E / U+E71F |
| Pełny ekran / wyjście | FullScreen / BackToWindow | U+E740 / U+E73F |
| Głośność / wycisz | Volume / Mute | U+E767 / U+E74F |
| Zapisz | Save | U+E74E |
| Usuń | Delete | U+E74D |
| Edytuj | Edit | U+E70F |
| Dodaj / usuń z listy | Add / Remove | U+E710 / U+E738 |
| Cofnij / powtórz | Undo / Redo | U+E7A7 / U+E7A6 |
| Więcej (menu "...") | More | U+E712 |
| Pomoc | Help | U+E897 |
| Historia / czas | Recent (zegar ze strzałką) | U+E823 |
| Prosty zegar | Clock | sprawdź kod w Character Map |
| Stoper (timer strzelecki) | Stopwatch | sprawdź kod w Character Map |
| Przesuwanie (tryb przeciągania) | Move | sprawdź kod w Character Map |
| Marker / pinezka | Pin | U+E718 |

Zasady: nie mieszaj glifów z emoji ani ze znakami z innych fontów; ikona bez tekstu ma tooltip; ikony stanu (Warning, Error, Info, CheckMark) zawsze towarzyszą tekstowi, kolor semantyczny jest dodatkiem. Kod użyj w Pythonie jako `""`.

Alternatywa bitmapowa (Linux/macOS lub własny zestaw): PNG w rozmiarach 16/20/24 px z wariantami @1.25x, @1.5x, @2x (lub render z SVG przez Pillow z `cairosvg` przy starcie, do docelowego rozmiaru px po przeliczeniu DPI), osobne wersje dla dark (jasne glify) i light (ciemne glify), ładowane przez `ImageTk.PhotoImage` i trzymane w referencjach, żeby garbage collector ich nie usunął. Nie skaluj `PhotoImage.zoom/subsample` ułamkowo.

## Blok Python (źródło prawdy dla scripts/theme_template.py)

```python
TOKENS = {
    "dark": {
        "bg": "#1F1F1F",
        "surface": "#2A2A2C",
        "surface_alt": "#353538",
        "border": "#3F3F43",
        "border_strong": "#78787F",
        "text": "#F2F2F2",
        "text_muted": "#A0A0A8",
        "text_disabled": "#6E6E76",
        "accent": "#FFC400",
        "accent_hover": "#FFD033",
        "accent_pressed": "#E0AC00",
        "accent_text": "#1A1200",
        "accent_subtle": "#3F3821",
        "danger": "#F87171",
        "success": "#4ADE80",
        "warning": "#FB923C",
        "info": "#60A5FA",
        "focus": "#FFFFFF",
        "selection_bg": "#FFC400",
        "selection_text": "#1A1200",
    },
    "light": {
        "bg": "#F3F3F3",
        "surface": "#FFFFFF",
        "surface_alt": "#ECECEE",
        "border": "#D5D5D9",
        "border_strong": "#8A8A90",
        "text": "#1B1B1F",
        "text_muted": "#5C5C63",
        "text_disabled": "#9A9AA1",
        "accent": "#8A6100",
        "accent_hover": "#986A00",
        "accent_pressed": "#6B4B00",
        "accent_text": "#FFFFFF",
        "accent_subtle": "#FFF3CC",
        "danger": "#C42B1C",
        "success": "#0F7B0F",
        "warning": "#B45309",
        "info": "#0F6CBD",
        "focus": "#1B1B1F",
        "selection_bg": "#FFC400",
        "selection_text": "#1A1200",
    },
}

# Pixels at 96 dpi (100 %). Scale with tk scaling for HiDPI.
SPACING = {
    "sp_1": 4,
    "sp_2": 8,
    "sp_3": 12,
    "sp_4": 16,
    "sp_5": 20,
    "sp_6": 24,
    "sp_8": 32,
}

RADIUS = {
    "r_sm": 4,
    "r_md": 6,
    "r_lg": 8,
}

# Sizes are Tk points (positive = scaled by `tk scaling`). Pick the first
# family present in tkinter.font.families(); the last entry always exists.
FONTS = {
    "font_ui": {
        "families": ["Segoe UI Variable Text", "Segoe UI", "Noto Sans", "DejaVu Sans", "TkDefaultFont"],
        "size": 10,
        "weight": "normal",
    },
    "font_ui_small": {
        "families": ["Segoe UI Variable Text", "Segoe UI", "Noto Sans", "DejaVu Sans", "TkDefaultFont"],
        "size": 9,
        "weight": "normal",
    },
    "font_section": {
        "families": ["Segoe UI Variable Text", "Segoe UI", "Noto Sans", "DejaVu Sans", "TkDefaultFont"],
        "size": 11,
        "weight": "bold",
    },
    "font_title": {
        "families": ["Segoe UI Variable Text", "Segoe UI", "Noto Sans", "DejaVu Sans", "TkDefaultFont"],
        "size": 13,
        "weight": "bold",
    },
    "font_mono": {
        "families": ["Cascadia Mono", "Consolas", "Menlo", "Noto Sans Mono", "DejaVu Sans Mono", "TkFixedFont"],
        "size": 10,
        "weight": "normal",
    },
}
```
