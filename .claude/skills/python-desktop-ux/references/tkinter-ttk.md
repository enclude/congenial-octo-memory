# Tkinter/ttk: nowoczesny wygląd bez wymiany frameworka

Praktyczny przewodnik dla aplikacji takich jak Piro Overlay (inspektor po lewej, podgląd wideo i oś czasu po prawej). Wszystkie fragmenty kodu zakładają kontekst:

```python
import tkinter as tk
from tkinter import ttk
root = tk.Tk()
style = ttk.Style(root)
```

Gotowe implementacje: `scripts/theme_template.py` (funkcje `enable_hidpi`, `apply_theme`, `configure_named_fonts`, `set_windows_dark_titlebar`, `system_prefers_dark`, `bind_mousewheel`, `px`, `register_rounded_button_style`) oraz `scripts/widgets.py` (klasy `SectionHeader`, `FormGrid`, `Switch`, `SegmentedControl`, `ColorSwatchButton`, `NumberField`, `PathField`, `Tooltip`, `ScrollableFrame`, `StatusBar`, `InlineMessage`). Nazwy tokenów (kolory, odstępy, fonty) są wspólne dla całego skilla; wartości ustala `references/design-tokens.md`.

Zasady nadrzędne, których ten dokument nie łamie: odświeżenie UI nie zmienia logiki ani formatu zapisywanych ustawień; każdy krok da się zweryfikować zrzutem ekranu; teksty pozostają tłumaczalne (PL/EN); UI działa przy 100/125/150/200 % DPI; klawiatura i fokus działają; długie operacje nie blokują pętli zdarzeń.

## §1 Diagnoza: dlaczego domyślny Tkinter na Windows wygląda przestarzale

| Objaw na zrzucie | Przyczyna techniczna | Co z tym zrobić |
|---|---|---|
| Szare, płaskie tło i "wytłoczone" ramki sekcji | motyw `vista`/`winnative`/`xpnative` rysuje elementy natywnym API Windows i ignoruje większość opcji `Style.configure` (kolory tła przycisków, pól, strzałek) | przejść na `clam` jako bazę i ostylować wszystko z tokenów (§2, §3) |
| `LabelFrame` z obramowaniem i tytułem "na ramce" | domyślny `TLabelframe` ma `borderwidth` i relief | zamienić na `SectionHeader` z `scripts/widgets.py` lub zdjąć ramkę (§4) |
| Widżety w dwóch stylach (część "stara", część "nowa") | mieszanie `tk.Button`, `tk.Label`, `tk.Entry` z `ttk.*`; klasyczne widżety mają `bg=`, `relief=raised` itd. | ujednolicić do `ttk`, resztę (Menu, Listbox, Text, Canvas) kolorować przez `option_add` (§2, §4) |
| Rozmyte fonty i kontrolki przy 125/150 % | proces nie jest DPI aware, Windows skaluje bitmapę okna | `enable_hidpi()` przed `tk.Tk()` (§2, §6) |
| Mały, "systemowy" font, różne wielkości w różnych miejscach | fonty podawane krotkami `("Arial", 9)` w wielu miejscach; nienazwane fonty nie da się zmienić globalnie | nazwane fonty `TkDefaultFont`, `font_ui`, `font_section` (§2) |
| Jasny pasek tytułu przy ciemnym UI | Tk nie wie o trybie ciemnym systemu | `set_windows_dark_titlebar()` (§6) |
| Przycisk koloru z tekstem "RGBA 0,0,0,170" | brak wizualnej reprezentacji wartości | `ColorSwatchButton` (swatch + hex + alfa) |

Jak rozpoznać problemy w kodzie (uruchom w katalogu projektu):

```bash
grep -rn "from tkinter import \*" --include=*.py .
grep -rnE "tk\.(Button|Label|Entry|Checkbutton|Radiobutton|Frame|LabelFrame|Scale|Spinbox)\(" --include=*.py .
grep -rnE "\b(bg|fg|relief|highlightthickness|activebackground)=" --include=*.py .
grep -rn "LabelFrame" --include=*.py .
grep -rn "theme_use" --include=*.py .
grep -rnE "SetProcessDpiAwareness|SetProcessDPIAware|tk\.call\(['\"]tk['\"], *['\"]scaling" --include=*.py .
grep -rnE "font=\(" --include=*.py .          # fonty krotkami zamiast nazwanych
grep -rnE "\.(after|update|update_idletasks)\(" --include=*.py .   # zerknij, czy nie ma time.sleep w UI
grep -rn "time.sleep" --include=*.py .
grep -rnE "geometry\(|minsize\(" --include=*.py .
```

Wynik greps daje listę miejsc do przejrzenia; nie zmieniaj logiki, tylko warstwę prezentacji.

## §2 Fundament: kolejność startu aplikacji

Kolejność ma znaczenie. Poprawny start:

```python
import tkinter as tk
from tkinter import ttk
from theme_template import enable_hidpi, apply_theme, set_windows_dark_titlebar, system_prefers_dark

enable_hidpi()                                 # 1. DPI awareness PRZED utworzeniem Tk()
root = tk.Tk()
root.withdraw()                                # 2. nie pokazuj okna, dopóki nie jest ostylowane
mode = "dark" if system_prefers_dark() else "light"
tokens = apply_theme(root, mode)               # 3. fonty, clam, style, option_add, tło root
build_ui(root, tokens)                         # 4. budowa widżetów (wszystkie ttk)
root.update_idletasks()
set_windows_dark_titlebar(root, mode == "dark")  # 5. pasek tytułu (potrzebuje istniejącego HWND)
root.deiconify()
root.mainloop()
```

Co robi `apply_theme` pod spodem i co możesz zrobić ręcznie, jeśli nie chcesz kopiować modułu:

1. Skalowanie Tk zgodne z DPI, żeby rozmiary fontów w punktach były prawidłowe:

```python
dpi = root.winfo_fpixels("1i")           # rzeczywiste piksele na cal
root.tk.call("tk", "scaling", dpi / 72)  # Tk liczy punkty jako 1/72 cala
```

2. Nazwane fonty. Tk ma zestaw fontów systemowych, które widżety używają domyślnie; zmiana ich konfiguracji natychmiast zmienia wszystkie widżety:

```python
import tkinter.font as tkfont
for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont",
             "TkCaptionFont", "TkIconFont"):
    tkfont.nametofont(name).configure(family="Segoe UI", size=10)
for name in ("TkTooltipFont", "TkSmallCaptionFont"):
    tkfont.nametofont(name).configure(family="Segoe UI", size=9)
tkfont.nametofont("TkFixedFont").configure(family="Consolas", size=10)

# Własne nazwane fonty aplikacji (używaj po nazwie: font="font_section")
tkfont.Font(root, name="font_ui", family="Segoe UI", size=10)
tkfont.Font(root, name="font_section", family="Segoe UI", size=11, weight="bold")
```

Dostępność rodziny sprawdzaj przez `tkfont.families(root)` (porównanie bez wielkości liter); `pick_font_family` w `theme_template.py` robi to z listą kandydatów (Segoe UI Variable Text, Segoe UI, TkDefaultFont).

3. Motyw bazowy `clam`. Spośród motywów wbudowanych tylko `clam`, `alt` i `default` rysują wszystko własnymi elementami i respektują kolory z `Style.configure`. `clam` ma najbogatszy zestaw opcji (bordercolor, lightcolor, darkcolor, fieldbackground, arrowcolor, gripcount), dlatego jest bazą:

```python
style.theme_use("clam")
style.configure(".", background=tokens["bg"], foreground=tokens["text"], font="font_ui")
```

4. `option_add` dla widżetów klasycznych, których `Style` nie dotyka (Menu, Listbox, Text, Canvas, Toplevel oraz lista rozwijana Combobox). Działa tylko na widżety utworzone PO wywołaniu, dlatego wykonuj to na starcie:

```python
root.option_add("*Menu.background", tokens["surface"])
root.option_add("*Menu.foreground", tokens["text"])
root.option_add("*Menu.activeBackground", tokens["accent_subtle"])
root.option_add("*Menu.tearOff", 0)
root.option_add("*Text.background", tokens["surface"])
root.option_add("*Listbox.background", tokens["surface"])
root.option_add("*TCombobox*Listbox.background", tokens["surface"])
root.option_add("*TCombobox*Listbox.selectBackground", tokens["selection_bg"])
root.configure(bg=tokens["bg"])
```

## §3 ttk.Style od podszewki

### Trzy poziomy: configure, map, layout

- `style.configure(name, **opts)` ustawia wartości opcji dla stanu domyślnego. Nieznane opcje są zapisywane i ignorowane, więc literówka nie zgłosi błędu (sprawdzaj wynik zrzutem).
- `style.map(name, option=[(state_spec, value), ...])` ustawia wartości zależne od stanu. Lista jest przeglądana od początku i wygrywa PIERWSZE dopasowanie, dlatego stany bardziej szczegółowe (`disabled`, `pressed`) muszą być przed ogólnymi (`active`).
- `style.layout(name)` zwraca drzewo elementów, a `style.layout(name, spec)` je nadpisuje.

Stany, które warto znać: `disabled`, `active` (kursor nad widżetem), `pressed`, `focus`, `readonly`, `selected` (Checkbutton, Radiobutton, zakładka Notebook, Toolbutton), `invalid`, `hover`, `alternate`, `background` (okno nieaktywne). Negacja przez `!`, np. `("!disabled", "active")` oznacza oba warunki naraz.

```python
style.configure("TButton", background=tokens["surface_alt"], foreground=tokens["text"],
                borderwidth=1, relief="flat", padding=(12, 6))
style.map("TButton",
          background=[("disabled", tokens["surface"]),
                      ("pressed", tokens["border_strong"]),
                      ("active", tokens["border"])],
          foreground=[("disabled", tokens["text_disabled"])])
```

### Konwencja nazw stylów

Nazwa stylu MUSI kończyć się nazwą klasy widżetu, bo po niej ttk znajduje layout i wartości domyślne: `Accent.TButton`, `Muted.TLabel`, `Thin.Vertical.TScrollbar`, `Card.TFrame`. Styl `Accent.TButton` dziedziczy z `TButton` wszystko, czego sam nie ustawia. Zły przykład: `style.configure("AccentButton", ...)` zadziała bez błędu, ale `ttk.Button(style="AccentButton")` nie ma layoutu i nic nie narysuje.

### Podglądanie i modyfikacja layoutu

```python
print(style.layout("TButton"))
# clam: [('Button.border', {'sticky': 'nswe', 'border': '1', 'children':
#          [('Button.focus', {'sticky': 'nswe', 'children':
#            [('Button.padding', {'sticky': 'nswe', 'children':
#              [('Button.label', {'sticky': 'nswe'})]})]})]})]
print(style.element_options("Button.border"))   # jakie opcje rozumie element
```

Usunięcie elementu (np. ramki fokusa, bo rysujesz własny przez `bordercolor`):

```python
style.layout("Flat.TButton", [
    ("Button.border", {"sticky": "nswe", "border": 1, "children": [
        ("Button.padding", {"sticky": "nswe", "children": [
            ("Button.label", {"sticky": "nswe"})]})]})])
```

Cienki pasek przewijania bez strzałek to ten sam mechanizm (patrz `Thin.Vertical.TScrollbar` w `apply_theme`).

### element_create

Dwa użyteczne warianty:

- `style.element_create("Custom.Field", "from", "default")` kopiuje element z innego motywu (np. prostsze pole z `default`, gdy `clam` rysuje coś nie po Twojej myśli).
- `style.element_create(name, "image", img_normal, ("disabled", img_dis), ("pressed", img_pressed), ("active", img_hover), border=8, sticky="nswe", padding=(12, 6))` rysuje element z obrazka z rozciąganiem środka (9-slice przez `border`). To jedyna droga do prawdziwie zaokrąglonych przycisków w ttk. Obrazki trzymaj w zmiennej modułu, inaczej znikną (Garbage Collector). Elementu nie da się utworzyć dwa razy pod tą samą nazwą (`TclError: Duplicate element`), więc przy przełączaniu motywu nadawaj nazwy z sufiksem trybu. Implementacja: `register_rounded_button_style` w `theme_template.py`.

### theme_create czy stylowanie clam

`style.theme_create("piro", parent="clam", settings={...})` daje izolowany motyw, ale nie ma realnej przewagi nad konfigurowaniem `clam` w jednej funkcji, a utrudnia przełączanie dark/light (motyw można utworzyć raz). Rekomendacja: `theme_use("clam")` + funkcja `apply_theme(root, mode)` wołana ponownie przy zmianie trybu.

## §4 Receptury per widżet

Każda receptura zakłada `t = tokens` (słownik aktywnego motywu) i `clam`. Kompletny zestaw jest w `apply_theme`; tu opis celu, minimalny kod i pułapki. Wartości pikselowe skaluj przez `px(root, 8)` (§6), w przykładach podane dla 96 dpi.

### TFrame i TLabel

Cel: płaskie powierzchnie i trzy warianty tekstu (tytuł, nagłówek sekcji, opis wyciszony).

```python
style.configure("TFrame", background=t["bg"])
style.configure("Card.TFrame", background=t["surface"], bordercolor=t["border"],
                relief="solid", borderwidth=1)
style.configure("Sidebar.TFrame", background=t["surface"])
style.configure("TLabel", background=t["bg"], foreground=t["text"])
style.configure("Title.TLabel", font="font_title")
style.configure("Section.TLabel", font="font_section")
style.configure("Muted.TLabel", foreground=t["text_muted"], font="font_ui_small")
```

Pułapki: etykieta wewnątrz `Card.TFrame` ma tło `bg`, nie `surface`; potrzebny wariant `Card.TLabel` z `background=t["surface"]`. `ttk.Label(..., background=...)` też działa, ale wtedy kolor nie przełączy się z motywem.

### TButton (Accent, Ghost, Danger)

Cel: płaskie przyciski bez 3D, akcent tylko dla akcji głównej, hover i pressed widoczne, fokus widoczny.

```python
style.configure("TButton", background=t["surface_alt"], foreground=t["text"],
                bordercolor=t["border"], lightcolor=t["surface_alt"], darkcolor=t["surface_alt"],
                focuscolor=t["surface_alt"], focusthickness=1, borderwidth=1, relief="flat",
                padding=(12, 6), anchor="center")
style.map("TButton",
          background=[("disabled", t["surface"]), ("pressed", t["border_strong"]), ("active", t["border"])],
          lightcolor=[("pressed", t["border_strong"]), ("active", t["border"])],
          darkcolor=[("pressed", t["border_strong"]), ("active", t["border"])],
          bordercolor=[("focus", t["focus"])],
          focuscolor=[("focus", t["focus"])])
style.configure("Accent.TButton", background=t["accent"], foreground=t["accent_text"],
                bordercolor=t["accent"], lightcolor=t["accent"], darkcolor=t["accent"])
style.map("Accent.TButton",
          background=[("disabled", t["surface_alt"]), ("pressed", t["accent_pressed"]), ("active", t["accent_hover"])],
          lightcolor=[("pressed", t["accent_pressed"]), ("active", t["accent_hover"])],
          darkcolor=[("pressed", t["accent_pressed"]), ("active", t["accent_hover"])])
```

W `clam` ramka przycisku składa się z `bordercolor` (zewnętrzna linia) oraz `lightcolor`/`darkcolor` (wewnętrzne linie 3D). Płaski wygląd wymaga ustawienia obu na kolor tła przycisku, także w `map` dla `active`/`pressed`, inaczej po najechaniu pojawia się jasna obwódka. `focuscolor` to kolor przerywanej ramki fokusa rysowanej wewnątrz; ustaw ją na kolor tła w stanie normalnym i na `focus` w stanie `focus`. `Ghost.TButton` ma tło równe `bg` (przycisk "tekstowy"), `Danger.TButton` ma obrys i tekst w `danger`, wypełnienie dopiero przy hover. Zaokrąglone rogi: tylko przez obrazki (§3, §7).

### TEntry i TSpinbox

Cel: pole z cienką ramką, ramka w akcencie przy fokusie, czerwona w stanie `invalid`, spinbox ze strzałkami w kolorze tekstu wyciszonego.

```python
for name in ("TEntry", "TSpinbox"):
    style.configure(name, fieldbackground=t["surface"], foreground=t["text"],
                    bordercolor=t["border"], lightcolor=t["surface"], darkcolor=t["surface"],
                    insertcolor=t["text"], padding=(8, 5),
                    selectbackground=t["selection_bg"], selectforeground=t["selection_text"],
                    arrowcolor=t["text_muted"], arrowsize=14, background=t["surface"])
    style.map(name,
              fieldbackground=[("disabled", t["bg"]), ("readonly", t["surface_alt"])],
              bordercolor=[("invalid", t["danger"]), ("focus", t["focus"])],
              lightcolor=[("focus", t["focus"])], darkcolor=[("focus", t["focus"])],
              arrowcolor=[("disabled", t["text_disabled"]), ("pressed", t["accent"])])
style.configure("Invalid.TEntry", bordercolor=t["danger"], lightcolor=t["danger"], darkcolor=t["danger"])
```

Pułapki: w `clam` widoczna "ramka fokusa" to `lightcolor`/`darkcolor`, nie `bordercolor`, dlatego oba trzeba mapować. `background` w Spinbox to tło przycisków strzałek. Stan `invalid` ustawia sam widżet, gdy `validatecommand` zwróci `False`, można go też ustawić ręcznie: `entry.state(["invalid"])`. Motyw `vista` ignoruje wszystkie te kolory. Zamiennik dla liczb z jednostką i przyciskami -/+: `NumberField` z `scripts/widgets.py`.

### TCombobox

Cel: wygląd spójny z Entry; lista rozwijana to klasyczny `tk.Listbox` w osobnym Toplevel, więc kolorujesz ją przez `option_add`.

```python
style.configure("TCombobox", fieldbackground=t["surface"], background=t["surface"],
                foreground=t["text"], bordercolor=t["border"], lightcolor=t["surface"],
                darkcolor=t["surface"], arrowcolor=t["text_muted"], arrowsize=14, padding=(8, 5))
style.map("TCombobox",
          fieldbackground=[("readonly", t["surface"]), ("disabled", t["bg"])],
          bordercolor=[("focus", t["focus"])], lightcolor=[("focus", t["focus"])],
          darkcolor=[("focus", t["focus"])],
          foreground=[("disabled", t["text_disabled"])])
root.option_add("*TCombobox*Listbox.background", t["surface"])
root.option_add("*TCombobox*Listbox.foreground", t["text"])
root.option_add("*TCombobox*Listbox.selectBackground", t["selection_bg"])
root.option_add("*TCombobox*Listbox.selectForeground", t["selection_text"])
root.option_add("*TCombobox*Listbox.font", "font_ui")
```

Pułapka: `state="readonly"` domyślnie w `clam` daje szare pole; jeśli chcesz wygląd jak zwykłe pole, mapuj `fieldbackground` dla `readonly` na `surface`. Po wyborze pozycji Combobox zaznacza tekst; `cb.selection_clear()` w handlerze `<<ComboboxSelected>>` usuwa to.

### TCheckbutton i TRadiobutton

Cel: wskaźnik (kwadrat/kółko) w kolorze `surface` z obwódką `border_strong`, po zaznaczeniu wypełniony `accent`.

```python
for name in ("TCheckbutton", "TRadiobutton"):
    style.configure(name, background=t["bg"], foreground=t["text"], padding=(0, 4),
                    indicatorbackground=t["surface"], indicatorforeground=t["accent_text"],
                    indicatormargin=(0, 0, 8, 0), upperbordercolor=t["border_strong"],
                    lowerbordercolor=t["border_strong"], focuscolor=t["bg"])
    style.map(name,
              indicatorbackground=[("disabled", t["bg"]), ("selected", t["accent"]), ("active", t["surface_alt"])],
              upperbordercolor=[("selected", t["accent"])], lowerbordercolor=[("selected", t["accent"])],
              focuscolor=[("focus", t["focus"])])
```

Zestaw opcji wskaźnika różni się między motywami (`clam` ma `indicatorbackground`, `indicatorforeground`, `upperbordercolor`, `lowerbordercolor`; motyw `default` używa `indicatorcolor`). Ustawienie nadmiarowych opcji jest bezpieczne. Jeśli wskaźnik z `clam` wygląda zbyt "retro", zamień: pojedynczy checkbox na `Switch`, grupę radio na `SegmentedControl` (oba w `scripts/widgets.py`, oba obsługują klawiaturę i zmienną w dwie strony).

### TLabelframe

Cel: zdjąć ramkę, zachować tytuł jako nagłówek sekcji. To ścieżka minimalna dla istniejącego kodu, który ma dziesiątki `LabelFrame`:

```python
style.configure("TLabelframe", background=t["bg"], borderwidth=0, relief="flat",
                labelmargins=(0, 0, 0, 4), padding=(0, 4, 0, 8))
style.configure("TLabelframe.Label", background=t["bg"], foreground=t["text"], font="font_section")
```

Docelowo lepsza jest zamiana na `SectionHeader(parent, "Wejście", collapsible=True, content=frame)`: nagłówek z linią, opcjonalne zwijanie, ta sama siatka co reszta inspektora. Zamiana nie dotyka logiki: `LabelFrame` był tylko kontenerem.

### TNotebook

```python
style.configure("TNotebook", background=t["bg"], borderwidth=0, tabmargins=(0, 0, 0, 0))
style.configure("TNotebook.Tab", background=t["bg"], foreground=t["text_muted"],
                padding=(12, 8), borderwidth=0, bordercolor=t["bg"], lightcolor=t["bg"], darkcolor=t["bg"])
style.map("TNotebook.Tab",
          background=[("selected", t["surface"]), ("active", t["surface_alt"])],
          foreground=[("selected", t["text"])],
          expand=[("selected", (0, 0, 0, 0))])
```

`expand` dla `selected` domyślnie powiększa aktywną zakładkę o kilka pikseli (efekt "wysuniętej" karty); zerowanie daje płaskie zakładki. Fokus na zakładce rysuje przerywaną ramkę: `focuscolor=t["bg"]` ją ukrywa, ale wtedy zadbaj o inny wskaźnik (kolor tekstu w stanie `focus`).

### Treeview

```python
row_h = px(root, 26)
style.configure("Treeview", background=t["surface"], fieldbackground=t["surface"],
                foreground=t["text"], borderwidth=0, rowheight=row_h, font="font_ui")
style.configure("Treeview.Heading", background=t["surface_alt"], foreground=t["text_muted"],
                relief="flat", padding=(8, 6), font="font_ui_small", borderwidth=0)
style.map("Treeview.Heading", background=[("active", t["border"])])

def fixed_map(option):
    # W niektórych wersjach Tk 8.6 domyślna mapa ma wpis ('!disabled', '!selected'),
    # który nadpisuje kolory z tag_configure. Ten filtr go usuwa.
    return [e for e in style.map("Treeview", query_opt=option) if e[:2] != ("!disabled", "!selected")]

style.map("Treeview",
          background=[("selected", t["selection_bg"])] + fixed_map("background"),
          foreground=[("selected", t["selection_text"])] + fixed_map("foreground"))
tree.tag_configure("odd", background=t["surface_alt"])   # naprzemienne wiersze
```

`rowheight` nie skaluje się z DPI automatycznie, licz go z `px()`. Kolory wierszy ustawiasz przez tagi, nie przez styl. Usunięcie ramki wokół drzewa: `borderwidth=0` w stylu i umieszczenie widżetu w `Card.TFrame`, jeśli potrzebna jest linia.

### TScrollbar

```python
style.configure("Vertical.TScrollbar", background=t["border_strong"], troughcolor=t["bg"],
                bordercolor=t["bg"], lightcolor=t["border_strong"], darkcolor=t["border_strong"],
                arrowcolor=t["text_muted"], arrowsize=12, gripcount=0, relief="flat")
style.map("Vertical.TScrollbar", background=[("pressed", t["accent"]), ("active", t["text_muted"])])
# Wariant bez strzałek: sam korytko + suwak
style.layout("Thin.Vertical.TScrollbar", [
    ("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
        ("Vertical.Scrollbar.thumb", {"expand": 1, "sticky": "nswe"})]})])
style.configure("Thin.Vertical.TScrollbar", arrowsize=8)
```

Szerokość paska w `clam` wynika z `arrowsize`, więc `Thin` z `arrowsize=8` daje pasek ok. 8 px. `gripcount=0` usuwa "uchwyt" z kresek na suwaku.

### TProgressbar, TScale, TSeparator

```python
style.configure("Horizontal.TProgressbar", background=t["accent"], troughcolor=t["surface_alt"],
                bordercolor=t["surface_alt"], lightcolor=t["accent"], darkcolor=t["accent"],
                borderwidth=0, thickness=6)
style.configure("Horizontal.TScale", background=t["accent"], troughcolor=t["surface_alt"],
                bordercolor=t["surface_alt"], lightcolor=t["accent"], darkcolor=t["accent"],
                sliderlength=18, borderwidth=0)
style.configure("TSeparator", background=t["border"])
```

W Progressbar `background` to kolor paska postępu, w Scale to kolor suwaka. Dla trybu `indeterminate` (operacja w tle, §9) wywołuj `pb.start(15)` i `pb.stop()`.

### TPanedwindow

```python
style.configure("TPanedwindow", background=t["bg"])
style.configure("Sash", sashthickness=6, gripcount=0, handlesize=0, sashpad=0)
paned = ttk.PanedWindow(root, orient="horizontal")
paned.add(inspector, weight=0)
paned.add(preview, weight=1)
```

`Sash` to nazwa stylu elementu separatora w `clam`; jeśli w Twojej wersji Tk nie reaguje, sprawdź w dokumentacji `ttk::panedwindow`, a jako obejście użyj klasycznego `tk.PanedWindow(sashwidth=6, bg=t["bg"], bd=0)`.

### Menu (tylko tk)

Menu nie ma odpowiednika ttk; jedyna droga to `option_add` (§2) przed utworzeniem menu albo `menu.configure(background=..., foreground=..., activebackground=..., activeforeground=..., borderwidth=0, relief="flat", tearoff=0)` dla każdego już istniejącego. Pasek menu głównego okna na Windows rysuje system i nie przyjmuje kolorów; jeśli ciemny pasek menu jest wymagany, zastąp go rzędem `Ghost.TButton` z rozwijanymi `tk.Menu` (`menu.post(x, y)`).

## §5 Layout: dyscyplina grid i wzorzec inspektora

### Zasady grid

- Jeden menedżer na kontener: w danym `Frame` używaj albo `grid`, albo `pack`, nigdy obu.
- Rozciąganie deklaruj świadomie: `columnconfigure(i, weight=1)` dla kolumny, która ma rosnąć, `minsize` dla kolumny etykiet, `uniform="x"` dla kolumn o równej szerokości (przyciski w rzędzie).
- `sticky="ew"` na kontrolkach w kolumnie rozciąganej, `sticky="w"` na etykietach.
- Odstępy tylko z tokenów: `padx=SPACING["sp_2"]`, `pady=(0, SPACING["sp_4"])`. Zero "magicznych" liczb.
- Sekcje oddzielaj odstępem `sp_4` do `sp_6`, pola w sekcji odstępem `sp_1` do `sp_2`.

### Inspektor dwukolumnowy

Etykiety w kolumnie 0 o stałej minimalnej szerokości, kontrolki w kolumnie 1 rozciągane, jednostka w kolumnie 2. Tak zachowuje się `FormGrid` z `scripts/widgets.py`:

```python
from widgets import FormGrid, SectionHeader, NumberField

body = ttk.Frame(inspector)
body.columnconfigure(0, weight=1)
grid = FormGrid(body, label_width=130)
SectionHeader(body, "Synchronizacja i przycięcie", collapsible=True, content=grid).grid(
    row=0, column=0, sticky="ew", pady=(0, SPACING["sp_2"]))
grid.grid(row=1, column=0, sticky="ew", pady=(0, SPACING["sp_4"]))
grid.row("Przesunięcie", lambda p: NumberField(p, offset_var, -10, 10, 0.05, unit="s"),
         help_text="Ujemne = nakładka wcześniej niż dźwięk.")
```

`row()` przyjmuje fabrykę `lambda parent: widget` albo gotowy widżet (wtedy musi być dzieckiem `grid`).

### ScrollableFrame

Inspektor jest dłuższy niż okno, więc potrzebuje przewijania. Wzorzec: `Canvas` + wewnętrzny `Frame` wstawiony przez `create_window` + `Scrollbar`.

```python
canvas = tk.Canvas(parent, background=t["bg"], highlightthickness=0)
inner = ttk.Frame(canvas)
win = canvas.create_window((0, 0), window=inner, anchor="nw")
vsb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview, style="Thin.Vertical.TScrollbar")
canvas.configure(yscrollcommand=vsb.set)
inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))   # inner tak szeroki jak canvas
```

Kółko myszy: Windows i macOS wysyłają `<MouseWheel>` z `event.delta` (na Windows wielokrotność 120, na macOS małe liczby), X11 wysyła `<Button-4>`/`<Button-5>`. Wiązanie przez `bind_all` przy `<Enter>` i zdjęcie przy `<Leave>`, aby zagnieżdżone obszary nie przewijały się jednocześnie. Gotowe: `bind_mousewheel(widget, canvas)` w `theme_template.py` oraz klasa `ScrollableFrame` (atrybut `.inner`).

### Podział inspektor / podgląd

`ttk.PanedWindow(orient="horizontal")` z `add(inspector, weight=0)` i `add(preview, weight=1)`: podgląd rośnie, inspektor trzyma szerokość. Nadaj inspektorowi `width` startowe (np. `px(root, 360)`) i `minsize` okna, żeby przy małym oknie kontrolki nie zapadały się:

```python
root.minsize(px(root, 960), px(root, 600))
```

### Geometria okna: zapis i odczyt

```python
def save_geometry(root, settings):
    settings["window_geometry"] = root.geometry()          # "1280x800+100+60"
    settings["window_state"] = root.state()                # "normal" / "zoomed"

def restore_geometry(root, settings):
    geo = settings.get("window_geometry")
    if geo:
        root.geometry(geo)
        root.update_idletasks()
        # okno poza ekranem (odłączony monitor): wróć na środek
        if root.winfo_x() < -100 or root.winfo_y() < -100:
            root.geometry("+80+60")
    if settings.get("window_state") == "zoomed":
        root.state("zoomed")
```

Nowe klucze w ustawieniach dodawaj z wartością domyślną przy odczycie; nie zmieniaj istniejących kluczy ani ich formatu.

## §6 Windows: pasek tytułu, DPI, ikona, tryb ciemny systemu

### Ciemny pasek tytułu

```python
import ctypes

def set_dark_titlebar(root, enabled=True):
    root.update_idletasks()                                  # HWND musi istnieć
    hwnd = ctypes.windll.user32.GetParent(root.winfo_id())   # winfo_id to okno-dziecko Tk
    value = ctypes.c_int(1 if enabled else 0)
    for attr in (20, 19):   # DWMWA_USE_IMMERSIVE_DARK_MODE: 20, na starszych buildach 19
        if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
            break
    # wymuś przerysowanie ramki: zmiana rozmiaru o 1 px i powrót (albo withdraw/deiconify)
    w, h = root.winfo_width(), root.winfo_height()
    root.geometry("%dx%d" % (w + 1, h)); root.update_idletasks(); root.geometry("%dx%d" % (w, h))
```

Cała funkcja z obsługą wyjątków: `set_windows_dark_titlebar` w `theme_template.py`. Dla każdego `Toplevel` (dialogi) wywołaj ją osobno. Poza Windows funkcja zwraca `False` i nic nie robi.

### DPI

```python
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor
except Exception:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # system
    except Exception:
        ctypes.windll.user32.SetProcessDPIAware()
root = tk.Tk()
dpi = root.winfo_fpixels("1i")     # alternatywa: ctypes.windll.user32.GetDpiForSystem()
scale = dpi / 96.0
```

Konsekwencje DPI awareness: wszystko, co podajesz w pikselach (Canvas, `rowheight`, `padding`, `width` okna, obrazki), trzeba pomnożyć przez `scale`. Pomocnik `px(root, value)` w `theme_template.py`. Wartości w punktach (fonty) przelicza Tk sam po ustawieniu `tk scaling` (§2). Testuj przy 100/125/150/200 %: ustawienie Windows "Skala" zmienia DPI bez restartu, ale Tk odczytuje DPI przy starcie, więc aplikację restartuj.

### Ikona okna

```python
root.iconbitmap("assets/piro.ico")           # Windows: plik .ico z kilkoma rozmiarami (16, 32, 48, 256)
icon = tk.PhotoImage(file="assets/piro.png")  # inne systemy lub fallback
root.iconphoto(True, icon)                    # True = także dla przyszłych Toplevel
root._icon_ref = icon                         # referencja, inaczej obrazek znika
```

W PyInstaller ścieżkę do zasobów buduj względem `sys._MEIPASS` (gdy istnieje) albo katalogu modułu.

### Tryb ciemny systemu

```python
def system_prefers_dark():
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return int(value) == 0
    except Exception:
        return False   # inne systemy, brak klucza, brak uprawnień
```

Działa tylko na Windows. Ustawienie użytkownika w aplikacji (Ciemny / Jasny / Systemowy) zapisuj jako nowy klucz z domyślną wartością "system".

## §7 Canvas i rysowanie

Tk Canvas nie ma antyaliasingu: ukośne linie i łuki są "schodkowe". Dla UI (przyciski, przełączniki) wystarczą prostokąty i owale; dla ładnych zaokrągleń rysuj w PIL z supersamplingiem i wstawiaj jako `PhotoImage`.

### Zaokrąglone kształty

```python
# 1. Tylko Tk: prostokąt z zaokrąglonymi rogami jako polygon smooth
def rounded_rect(canvas, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
           x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)

# 2. PIL: rysuj 4x większy i zmniejsz (gładkie krawędzie)
from PIL import Image, ImageDraw, ImageTk
def rounded_image(w, h, r, fill, scale=4):
    img = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((0, 0, w * scale - 1, h * scale - 1), radius=r * scale, fill=fill)
    return ImageTk.PhotoImage(img.resize((w, h), Image.LANCZOS))
```

Przyciski z obrazkami dla stanów: cztery obrazki (normal, hover=`active`, pressed, disabled) i `style.element_create(..., "image", ...)` jak w §3; przykład kompletny: `register_rounded_button_style`. Obrazki generuj po `apply_theme`, bo zależą od tokenów, i trzymaj referencje w słowniku modułu.

### Oś czasu i fala audio

- Falę rysuj raz (po wczytaniu pliku lub zmianie rozmiaru), markery i kursor przesuwaj przez `canvas.coords(item, ...)` lub `canvas.move(tag, dx, 0)`, nie przez `delete` i ponowne rysowanie.
- Taguj elementy: `tags=("wave",)`, `tags=("marker", "marker_start")`; `canvas.delete("wave")` czyści tylko falę.
- `<Configure>` przychodzi seriami podczas zmiany rozmiaru okna; odkładaj przerysowanie:

```python
_redraw_job = None
def on_configure(event):
    global _redraw_job
    if _redraw_job:
        canvas.after_cancel(_redraw_job)
    _redraw_job = canvas.after(50, redraw_waveform)
canvas.bind("<Configure>", on_configure)
```

- Kolory z tokenów: fala `text_muted`, marker START `accent`, tło `surface`, zaznaczenie `selection_bg`.
- Fala dla długiego pliku: licz próbki min/max per piksel raz (w wątku, §9) i rysuj jedną `create_line` z listą punktów albo listę pionowych kresek; nie rysuj każdej próbki.

### Podgląd wideo

```python
from PIL import Image, ImageTk

def show_frame(canvas, pil_image, bg="#000000"):
    cw, ch = canvas.winfo_width(), canvas.winfo_height()
    if cw < 2 or ch < 2:
        return
    iw, ih = pil_image.size
    k = min(cw / iw, ch / ih)                       # zachowaj proporcje
    w, h = max(1, int(iw * k)), max(1, int(ih * k))
    frame = pil_image.resize((w, h), Image.BILINEAR)
    photo = ImageTk.PhotoImage(frame)
    canvas.delete("frame")
    canvas.create_rectangle(0, 0, cw, ch, fill=bg, width=0, tags="frame")   # letterbox
    canvas.create_image(cw // 2, ch // 2, image=photo, anchor="center", tags="frame")
    canvas.photo = photo                             # referencja, inaczej obraz znika
    canvas.tag_raise("overlay")                      # nakładka START zawsze nad klatką
```

Skalowanie klatki `BILINEAR` jest wystarczające dla podglądu i szybkie; `LANCZOS` zostaw dla eksportu. Nakładkę (START, czas) rysuj jako osobne elementy z tagiem `overlay` i tylko aktualizuj `itemconfigure(text=...)`.

## §8 Interakcje: hover, fokus, klawiatura, tooltipy, walidacja

### Hover i fokus

W ttk hover to stan `active`, fokus to stan `focus`; obsługujesz je w `style.map` (§4), bez własnych bindów. Dla widżetów na Canvas (Switch, swatch) wiąż `<Enter>`/`<Leave>` i `<FocusIn>`/`<FocusOut>` i przerysowuj. Fokus musi być widoczny na każdym elemencie, który przyjmuje klawiaturę: ramka w kolorze `focus` (przyciski, pola) albo przerywany obrys (Canvas).

```python
canvas.configure(takefocus=1)
canvas.bind("<FocusIn>", lambda e: draw(focused=True))
canvas.bind("<FocusOut>", lambda e: draw(focused=False))
canvas.bind("<space>", toggle)
canvas.bind("<Return>", toggle)
```

### Kolejność Tab

Tab idzie w kolejności tworzenia widżetów w obrębie rodzica. Gdy trzeba ją zmienić bez przestawiania kodu: `widget.lift(sibling)` ustawia widżet po `sibling` w kolejności stosu (i fokusa), `widget.lower(sibling)` przed. Elementy dekoracyjne wyłączaj z Tab: `takefocus=0` (przyciski -/+ przy polu liczbowym, przycisk "..." zostaw dostępny).

### Skróty klawiszowe

```python
root.bind_all("<Control-o>", lambda e: open_file())
root.bind_all("<Control-s>", lambda e: save_project())
root.bind_all("<F5>", lambda e: render())
file_menu.add_command(label="Otwórz...", accelerator="Ctrl+O", command=open_file)   # accelerator to tylko napis
```

`accelerator=` niczego nie wiąże, tylko wyświetla tekst; bind dodaj osobno. Zwracaj `"break"` z handlera, gdy chcesz zatrzymać domyślną akcję (np. `<Return>` w Entry).

### Tooltipy

`Tooltip(widget, "Pełny opis", delay=500)` z `scripts/widgets.py`: `Toplevel` z `overrideredirect(True)`, pokazywany po opóźnieniu z `after`, ukrywany przy `<Leave>` i kliknięciu. Pozycja względem wskaźnika (`winfo_pointerx/y`), kolory `surface_alt`/`text`, font `TkTooltipFont`. Dla skróconych ścieżek (`PathField`) tooltip pokazuje pełną wartość.

### Enter i Escape w dialogach

```python
dlg = tk.Toplevel(root)
dlg.transient(root)
dlg.grab_set()
dlg.bind("<Return>", lambda e: on_ok())
dlg.bind("<Escape>", lambda e: dlg.destroy())
ok = ttk.Button(dlg, text="OK", style="Accent.TButton", command=on_ok, default="active")
ok.focus_set()
dlg.wait_window()
```

`transient` trzyma dialog nad oknem głównym, `grab_set` blokuje resztę UI (modalność), `default="active"` oznacza przycisk domyślny wizualnie.

### Walidacja pola

```python
def only_number(proposed):
    return proposed in ("", "-") or proposed.replace(",", ".").replace("-", "", 1).replace(".", "", 1).isdigit()

vcmd = (root.register(only_number), "%P")           # %P = tekst po zmianie
entry = ttk.Entry(root, validate="key", validatecommand=vcmd)
```

Gdy `validatecommand` zwróci `False`, ttk odrzuca zmianę i ustawia stan `invalid`, na który reaguje `style.map(..., bordercolor=[("invalid", danger)])`. Do błędów semantycznych (poza zakresem, nieistniejący plik) ustaw ręcznie `entry.state(["invalid"])` i pokaż komunikat `InlineMessage.show("...", "danger")`; czyszczenie przez `entry.state(["!invalid"])`. Uwaga: jeśli podczas ustawiania `textvariable` z kodu walidacja zwróci `False`, Tk może wyłączyć walidację (`validate` wraca do `none`), dlatego funkcja walidująca powinna akceptować każdy tekst, który sam formatujesz. `NumberField` łączy to wszystko z clampowaniem i krokiem strzałkami.

## §9 Responsywność: UI nie zamiera

- Nigdy `time.sleep` w wątku UI. Odliczanie i animacje przez `after`:

```python
def tick():
    label.configure(text=fmt_time(player.position()))
    root.after(100, tick)
```

- Długie operacje (analiza audio, render wideo, ffmpeg) w `threading.Thread(daemon=True)`. Wątek NIE dotyka widżetów; wyniki wkłada do `queue.Queue`, a UI odpytuje kolejkę przez `after`:

```python
import threading, queue

q = queue.Queue()
cancel = threading.Event()

def worker(path):
    try:
        for i, chunk in enumerate(analyze(path)):
            if cancel.is_set():
                q.put(("cancelled", None)); return
            q.put(("progress", i))
        q.put(("done", result))
    except Exception as exc:          # wyjątek też przez kolejkę, nie print w wątku
        q.put(("error", exc))

def poll():
    try:
        while True:
            kind, payload = q.get_nowait()
            if kind == "progress":
                progress.configure(value=payload)
            elif kind in ("done", "error", "cancelled"):
                finish(kind, payload); return
    except queue.Empty:
        pass
    root.after(50, poll)

def start():
    cancel.clear()
    set_busy(True)                    # Progressbar indeterminate + blokada przycisków
    threading.Thread(target=worker, args=(path_var.get(),), daemon=True).start()
    root.after(50, poll)
```

- Stan "zajęty": `progress.configure(mode="indeterminate"); progress.start(15)`, przyciski akcji `state(["disabled"])`, przycisk "Anuluj" aktywny i podpięty do `cancel.set()`. Po zakończeniu przywróć stan, pokaż wynik w `StatusBar.set("Gotowe", "success", timeout_ms=4000)`.
- Podprocesy (ffmpeg) czytaj w wątku linia po linii (`subprocess.Popen(..., stdout=PIPE, text=True)`), parsuj postęp i przekazuj do kolejki.
- `root.update()` wewnątrz pętli obliczeniowej to obejście, które prowadzi do rekurencyjnych zdarzeń; nie używaj.

## §10 Pułapki i lista kontrolna wdrożenia

### Pułapki

| Pułapka | Objaw | Rozwiązanie |
|---|---|---|
| `bg=` / `fg=` / `relief=` na widżecie ttk | `TclError: unknown option "-bg"` | kolory przez `Style`, warianty stylów (`Card.TLabel`) |
| Nazwa stylu bez klasy widżetu (`"Accent"`) | widżet niewidoczny lub domyślny | `"Accent.TButton"` |
| `theme_use("clam")` po zbudowaniu części okien | dwa wyglądy w jednej aplikacji | motyw na starcie, przed pierwszym widżetem; przejrzyj wszystkie Toplevel i dialogi |
| Fonty krotkami `("Segoe UI", 9)` | brak reakcji na zmianę motywu i DPI | nazwane fonty (§2) |
| `PhotoImage` bez referencji | pusty obszar zamiast obrazka | przypisz do atrybutu widżetu lub słownika modułu |
| `Style` jest globalny dla interpretera | zmiana w jednym oknie zmienia wszystkie | traktuj jako zamierzone; konfiguracja tylko w `apply_theme` |
| Mieszanie `tk.Button` i `ttk.Button` | różne wysokości i kolory w jednym rzędzie | jeden rodzaj w całym UI |
| Lista rozwijana Combobox ignoruje `Style` | jasna lista przy ciemnym UI | `option_add("*TCombobox*Listbox.*")` przed utworzeniem |
| Spinbox / Entry w motywie `vista` ignorują kolory | białe pola w ciemnym UI | baza `clam` |
| `option_add` po utworzeniu widżetów | brak efektu | wywołaj wcześniej; dla istniejących `configure` ręcznie |
| `Treeview` ignoruje kolory tagów | jednolite wiersze | `fixed_map` (§4) |
| `element_create` przy ponownym `apply_theme` | `TclError: Duplicate element` | nazwa elementu z sufiksem trybu lub try/except |
| `rowheight`, `padding`, rozmiary Canvas bez skalowania | ucięty tekst przy 150 % | `px(root, v)` |
| PyInstaller i motywy z plików `.tcl` (np. zewnętrzne) | `TclError: can't find theme` | dodaj katalog motywu w `datas` i ładuj przez `root.tk.call("source", path)` |
| `grab_set` bez `transient` | dialog za oknem głównym | oba razem (§8) |
| `after` bez `after_cancel` przy zamykaniu | `TclError: invalid command name` po zamknięciu okna | pamiętaj identyfikatory i anuluj w `<Destroy>` |
| Widżety dotykane z wątku | losowe zawieszenia, `RuntimeError: main thread is not in main loop` | kolejka + `after` (§9) |

### Lista kontrolna wdrożenia (krok = jeden zrzut ekranu do porównania)

1. `enable_hidpi()` przed `tk.Tk()`, `tk scaling` z DPI. Zrzut przy 100 % i 150 %: tekst ostry, nic nie ucięte.
2. `configure_named_fonts`: cały tekst w Segoe UI (lub fallback), trzy rozmiary (ui, section, title).
3. `theme_use("clam")` + `apply_theme`: tło `bg`, powierzchnie `surface`, brak białych pól i 3D.
4. Zamiana `LabelFrame` na `SectionHeader` + `FormGrid`: etykiety wyrównane w jednej kolumnie, kontrolki rozciągnięte.
5. Przyciski: jedna akcja główna `Accent.TButton` na widok, reszta domyślne/Ghost, akcje destrukcyjne `Danger`.
6. Pola: Entry/Spinbox/Combobox z ramką `border`, fokus `focus`, `invalid` w `danger`. Combobox z ciemną listą.
7. Checkbox/radio: `Switch`/`SegmentedControl` tam, gdzie ma to sens (włącz/wyłącz, 2-4 opcje), reszta ostylowane ttk.
8. Kolory RGBA: `ColorSwatchButton` zamiast napisu; format zapisu w ustawieniach niezmieniony.
9. Ścieżki: `PathField` (skrócenie od lewej, tooltip z pełną ścieżką).
10. Przewijanie inspektora: `ScrollableFrame`, kółko działa w całym panelu, cienki pasek.
11. Podgląd i oś czasu: kolory z tokenów, marker START w `accent`, przerysowanie z debounce.
12. Windows: ciemny pasek tytułu, ikona, wybór motywu z systemu z możliwością nadpisania.
13. Klawiatura: Tab przechodzi przez wszystkie kontrolki w sensownej kolejności, fokus widoczny, Enter/Escape w dialogach, skróty w menu.
14. Długie operacje: wątek + kolejka, wskaźnik zajętości, anulowanie; UI reaguje w trakcie.
15. i18n: żaden nowy napis nie jest wpisany na sztywno poza słownikiem tłumaczeń; szerokości kolumn etykiet sprawdzone dla PL i EN.
16. Ustawienia: plik ustawień zapisany starą wersją aplikacji wczytuje się bez błędów; nowe klucze mają wartości domyślne.
17. Regresja: każda funkcja z listy "co robi aplikacja" działa jak przed zmianą (ten sam plik wejściowy, ten sam wynik renderu).
