# RouteStats

RouteStats to propozycja aplikacji zbierającej i analizującej statystyki czasu dojazdu między punktem A i B w zależności od pory dnia, dnia tygodnia oraz kalendarza dni wolnych i świąt przypadających w tygodniu.

## Cel aplikacji

Aplikacja ma cyklicznie pobierać szacowany czas przejazdu dla zdefiniowanych tras, zapisywać obserwacje w repozytorium danych, a następnie prezentować statystyki pokazujące typowy, minimalny, maksymalny i percentylowy czas dojazdu dla wybranych przedziałów czasu.

Przykładowe pytania, na które aplikacja powinna odpowiadać:

- ile zwykle trwa dojazd z punktu A do B w poniedziałek między 7:00 a 8:00,
- czy piątkowe popołudnia są wolniejsze niż wtorkowe,
- jak święto wypadające w środku tygodnia wpływa na ruch,
- o której godzinie najlepiej wyruszyć, aby uniknąć największych opóźnień,
- jak zmienia się mediana i 90. percentyl czasu przejazdu w kolejnych tygodniach.

## Założenia funkcjonalne

- użytkownik definiuje jedną lub wiele tras jako pary punktów A-B,
- system pobiera czas przejazdu w regularnych interwałach, np. co 5, 10 lub 15 minut,
- każda obserwacja jest wzbogacana o cechy kalendarzowe: dzień tygodnia, godzinę, numer tygodnia, informację o weekendzie, święcie oraz dniu roboczym,
- aplikacja rozróżnia zwykłe dni robocze, weekendy, święta oraz dni nietypowe, np. święto przypadające we wtorek,
- panel raportowy prezentuje agregaty i trendy dla wybranych tras oraz zakresów dat,
- całość może działać w oparciu o GitHub bez konieczności utrzymywania własnego serwera aplikacyjnego.

## Proponowana architektura na GitHub

```mermaid
flowchart TD
    S[GitHub Actions Scheduler] --> C[Collector]
    C --> M[Maps / Routing API]
    C --> H[Holiday Calendar]
    C --> D[(Data Storage)]
    D --> A[Analytics Pipeline]
    H --> A
    A --> R[Generated Reports]
    R --> P[GitHub Pages Dashboard]
    D --> P
```

### 1. Repozytorium GitHub

Repozytorium pełni rolę centrum aplikacji i zawiera:

- kod kolektora danych,
- konfigurację monitorowanych tras,
- skrypty analityczne,
- definicje workflow GitHub Actions,
- dane historyczne lub metadane danych,
- wygenerowany statyczny dashboard publikowany przez GitHub Pages.

Proponowana struktura katalogów:

```text
.github/workflows/
  collect.yml          # cykliczne pobieranie danych
  aggregate.yml        # okresowe przeliczanie statystyk
  deploy-pages.yml     # publikacja dashboardu
config/
  routes.yml           # definicje tras A-B
  calendars.yml        # konfiguracja krajów/regionów świąt
data/
  raw/                 # surowe obserwacje, najlepiej partycjonowane po dacie
  processed/           # zagregowane tabele statystyczne
src/
  collector/           # klient API map i zapis obserwacji
  analytics/           # agregacje, cechy kalendarzowe, percentyle
  dashboard/           # statyczny frontend lub generator raportów
tests/
  unit/
  integration/
```

### 2. Warstwa zbierania danych

Kolektor uruchamiany przez GitHub Actions powinien:

1. odczytać listę tras z `config/routes.yml`,
2. pobrać szacowany czas przejazdu z wybranego API trasowania,
3. pobrać lub wyliczyć metadane kalendarzowe,
4. zapisać obserwację w formacie append-only,
5. opcjonalnie utworzyć Pull Request z nową porcją danych albo zapisać dane w zewnętrznym magazynie.

Potencjalne źródła czasu przejazdu:

- Google Maps Distance Matrix API,
- HERE Routing API,
- TomTom Routing API,
- GraphHopper,
- OpenRouteService,
- OSRM dla scenariuszy opartych o dane OpenStreetMap, choć bez rzeczywistego ruchu drogowego.

Dla statystyk zależnych od bieżącego natężenia ruchu najlepiej użyć API, które zwraca czas przejazdu z uwzględnieniem aktualnego lub historycznego ruchu.

### 3. Warstwa danych

Najprostszy wariant w pełni oparty o GitHub:

- surowe obserwacje jako pliki CSV, JSONL lub Parquet w repozytorium albo w GitHub Releases,
- dane partycjonowane według daty, np. `data/raw/year=2026/month=07/day=02/routes.jsonl`,
- statystyki zagregowane w `data/processed/`,
- dashboard statyczny czyta gotowe pliki JSON/CSV.

Przy większej skali lepszy będzie wariant hybrydowy:

- GitHub przechowuje kod, konfigurację i dashboard,
- dane trafiają do zewnętrznego magazynu, np. Supabase/PostgreSQL, DuckDB file w Release, S3-compatible storage, Neon, BigQuery lub Cloudflare R2,
- GitHub Actions nadal uruchamia kolektor i agregacje.

Rekomendacja początkowa: DuckDB lub Parquet jako pliki danych, ponieważ łatwo wersjonować zagregowane wyniki, uruchamiać analizy lokalnie i publikować statyczny dashboard.

### 4. Model danych obserwacji

Minimalny rekord surowej obserwacji:

| Pole | Opis |
| --- | --- |
| `observed_at_utc` | czas wykonania pomiaru w UTC |
| `route_id` | identyfikator trasy |
| `origin_lat`, `origin_lon` | współrzędne punktu A |
| `destination_lat`, `destination_lon` | współrzędne punktu B |
| `duration_seconds` | przewidywany czas przejazdu |
| `distance_meters` | dystans trasy |
| `provider` | źródło danych, np. Google, HERE, TomTom |
| `status` | status odpowiedzi API |

Cechy wyliczane dla analityki:

| Pole | Opis |
| --- | --- |
| `local_date` | lokalna data obserwacji |
| `local_time` | lokalna godzina obserwacji |
| `weekday` | dzień tygodnia |
| `time_bucket` | przedział czasu, np. 15-minutowy |
| `is_weekend` | czy dzień jest weekendem |
| `is_public_holiday` | czy dzień jest świętem |
| `holiday_name` | nazwa święta, jeżeli dotyczy |
| `is_workday` | czy dzień jest typowym dniem roboczym |
| `day_type` | `workday`, `weekend`, `holiday`, `bridge_day`, `special` |

### 5. Obsługa świąt i dni wolnych

Do klasyfikacji dni należy użyć biblioteki lub API kalendarzowego zależnego od kraju i regionu. Przykładowo:

- dla Polski: biblioteka `holidays` w Pythonie z krajem `PL`,
- dla wielu krajów: `python-holidays`, Nager.Date API albo własny plik `config/calendars.yml`,
- dla firmowych dni wolnych: dodatkowy plik `config/special_days.yml`.

Ważne jest, aby nie traktować świąt wypadających w tygodniu jako zwykłych dni roboczych. Agregacje powinny umożliwiać porównanie:

- zwykłych wtorków,
- wtorków będących świętem,
- dni przed świętem,
- dni po święcie,
- tzw. dni pomostowych.

### 6. Warstwa analityczna

Pipeline analityczny powinien okresowo tworzyć agregaty według:

- trasy,
- dnia tygodnia,
- typu dnia,
- przedziału czasu,
- miesiąca lub sezonu,
- zakresu dat.

Podstawowe metryki:

- liczba obserwacji,
- średni czas przejazdu,
- mediana,
- minimum i maksimum,
- 75., 90. i 95. percentyl,
- odchylenie standardowe,
- różnica względem bazowego czasu przejazdu,
- wskaźnik opóźnienia, np. `duration_seconds / free_flow_duration_seconds`.

### 7. Dashboard

Dashboard może być w pełni statyczny i publikowany przez GitHub Pages. Najprostsze opcje:

- MkDocs + wykresy generowane jako statyczne HTML,
- Quarto,
- Observable Framework,
- Astro/React z plikami JSON jako źródłem danych,
- Streamlit tylko w wariancie poza GitHub Pages, np. na Streamlit Community Cloud.

Widoki dashboardu:

- heatmapa: dzień tygodnia × godzina,
- wykres mediany i percentyli w czasie,
- porównanie typów dni: roboczy, weekend, święto,
- tabela najlepszych i najgorszych okien wyjazdu,
- szczegóły pojedynczej trasy,
- alerty dla nietypowo długich przejazdów.

### 8. GitHub Actions

Proponowane workflow:

- `collect.yml` uruchamiany cronem co 5-15 minut w godzinach istotnych dla dojazdów,
- `aggregate.yml` uruchamiany po zapisaniu danych lub raz dziennie,
- `deploy-pages.yml` publikujący dashboard po przeliczeniu raportów,
- opcjonalny `quality.yml` uruchamiający testy, linting i walidację konfiguracji.

Sekrety, takie jak klucze API map, powinny być przechowywane w GitHub Actions Secrets, np. `ROUTING_API_KEY`.

### 9. Rekomendowany stos technologiczny

Wariant startowy:

- Python dla kolektora i analityki,
- `requests` lub `httpx` dla integracji z API,
- `pandas`, `polars` albo DuckDB dla agregacji,
- `python-holidays` dla świąt,
- Parquet lub DuckDB dla danych,
- Observable Framework, Quarto albo prosty React/Vite dla dashboardu,
- GitHub Actions jako scheduler,
- GitHub Pages jako hosting raportów.

Wariant bardziej produkcyjny:

- Python lub TypeScript dla kolektora,
- PostgreSQL/Supabase/Neon jako baza,
- dbt albo SQLMesh dla transformacji,
- Cloudflare Pages lub GitHub Pages dla dashboardu,
- monitoring kosztów API i limitów zapytań.

## Proponowany plan wdrożenia MVP

1. Zdefiniować format `config/routes.yml` dla jednej trasy A-B.
2. Dodać kolektor pobierający czas przejazdu z jednego dostawcy API.
3. Zapisywać surowe obserwacje w dziennych plikach JSONL lub Parquet.
4. Dodać wzbogacanie obserwacji o dzień tygodnia, typ dnia i święta.
5. Utworzyć agregacje po 15-minutowych bucketach czasu.
6. Wygenerować pierwszy statyczny raport HTML.
7. Opublikować raport przez GitHub Pages.
8. Dodać testy walidujące konfigurację tras i klasyfikację dni wolnych.
9. Rozszerzyć obsługę o wiele tras i porównania między trasami.

## Ryzyka i ograniczenia

- Koszt API map może rosnąć przy dużej liczbie tras i krótkim interwale pomiarów.
- GitHub Actions ma limity czasu i liczby minut, dlatego częstotliwość pomiarów trzeba dobrać ostrożnie.
- Commitowanie każdej obserwacji do repozytorium może szybko zwiększyć jego rozmiar; przy większej skali warto przenieść surowe dane poza Git.
- Dane o ruchu zależą od dostawcy API i mogą różnić się metodologią.
- Dojazdy w święta i dni pomostowe mogą mieć mało obserwacji, więc warto oznaczać niską liczebność próby w raportach.

## Docelowa definicja sukcesu

MVP można uznać za gotowe, gdy aplikacja automatycznie zbiera pomiary dla co najmniej jednej trasy przez GitHub Actions, klasyfikuje obserwacje według dnia tygodnia i świąt, generuje agregaty mediany oraz percentyli i publikuje czytelny dashboard w GitHub Pages.
