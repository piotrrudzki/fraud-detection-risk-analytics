# Część 2. Co robi każdy skrypt, po kolei

Projekt ma 5 etapów: **dane → baza → jakość i analiza (SQL) → scoring (SQL) → Python**. Poniżej każdy skrypt w kolejności uruchamiania: co bierze na wejściu, co robi, co z niego wychodzi i jaki ma najważniejszy wynik.

Wszystkie liczby pochodzą z Twoich danych (ziarno 42, okres 1.01–30.06.2026).

```
Python 01–05, 07  →  pliki CSV w data\
Python 06         →  CSV ładowane do PostgreSQL
SQL 00            →  (wcześniej) puste tabele
SQL 01            →  jakość danych
SQL 02_sql_analysis\01–04  →  analiza fraudu
SQL 03 → 04 → 05  →  scoring v1, ocena błędów, scoring v2
Python 08, 09     →  EDA, anomalie, CSV pod Power BI
```

---

## Etap 1. Generowanie danych (Python)

Prawdziwych danych bankowych nie da się pobrać, więc tworzymy **syntetyczne**, ale realistyczne. Każdy skrypt zapisuje plik CSV do folderu `data\`.

| Skrypt | Co tworzy | Najważniejsze |
|---|---|---|
| `01_generate_customers.py` | `dim_customer.csv`: 10 000 klientów | kraje (najwięcej PL), wiek, plan, data założenia konta. Ok. 8% kont założono w 2026, a nowe konta są ryzykowne. |
| `02_generate_merchants.py` | `dim_merchant.csv`: 500 sprzedawców | 10 kategorii; ryzykowne kategorie częściej spoza Europy. |
| `03_generate_devices.py` | `dim_device.csv`: urządzenia klientów | większość ma 1 telefon, część 2–3. |
| `04_generate_fx_rates.py` | `dim_fx_rate.csv`: kursy 9 walut × 181 dni | kurs zmienia się codziennie (losowy spacer). |
| `05_generate_transactions.py` | `fact_transaction.csv`: 257 947 transakcji | normalne zakupy + 4 scenariusze oszustw + legalne „podejrzane” transakcje (podróże, duże zakupy). Dopisuje też urządzenia oszustów do `dim_device.csv`. |
| `07_generate_customer_history.py` | `fact_customer_risk.csv`: historia 10 000 klientów | `previous_fraud` i `chargebacks` sprzed 2026. |

**Ziarno losowania (`SEED = 42`)** sprawia, że każde uruchomienie daje identyczne dane. Dzięki temu Twoje wyniki i moje testy zgadzają się co do sztuki.

## Etap 2. Baza danych

| Skrypt | Co robi |
|---|---|
| `00_create_tables.sql` | Tworzy 6 pustych tabel z kluczami (PK, FK) i typami kolumn. |
| `06_load_to_postgres.py` | Czyści tabele (`TRUNCATE`) i ładuje do nich pliki CSV poleceniem `COPY`, najszybszym sposobem wczytania dużego pliku do PostgreSQL. Na końcu wypisuje liczbę wierszy w każdej tabeli. Kolejność ładowania wynika z kluczy obcych: najpierw wymiary, potem transakcje. |

## Etap 3. Jakość danych i analiza (SQL)

### `01_data_quality.sql`: czy dane są czyste?
- **Część 1** to 17 kontroli w jednej tabeli: duplikaty, puste pola, zakresy (kwota > 0, wiek 18–100), spójność dat (transakcja po założeniu konta, w czasie życia urządzenia), osierocone rekordy (transakcja z nieistniejącym klientem) i outliery.
- **Wynik:** 16 kontroli OK, jedna REVIEW, czyli 258 transakcji powyżej 99,9 percentyla kwoty. To nie błąd, tylko kandydaci do analizy.
- **Część 2** to 50 transakcji co najmniej 10× wyższych niż mediana klienta: 31 to fraudy, 19 to legalne duże zakupy. To pierwszy przykład, że „nietypowe” nie znaczy „oszustwo”.

### `02_sql_analysis\01_fraud_rate.sql`: ile jest fraudu i gdzie?
- **Ogółem:** 1,64% transakcji to fraud, ale to aż **14,65% wartości** (3,43 mln z 23,4 mln EUR), bo oszuści wydają dużo naraz.
- **Kategorie:** crypto 18,97%, electronics 10,21%, gift_cards 8,40%.
- **Kraje:** spoza Europy dużo wyżej (CN 42,59%) niż w Europie (poniżej 1,2%).
- **Za granicą vs kraj klienta:** 10,14% vs 0,11%.

### `02_sql_analysis\02_fraud_trend.sql`: jak fraud zmienia się w czasie?
- Trend miesięczny, tygodniowy i dzienny ze średnią kroczącą z 7 dni (wygładza skoki).
- Styczeń 1,33%, potem 1,65–1,81%.
- Godzina 3:00 w nocy ma najwyższy fraud rate.

### `02_sql_analysis\03_customer_behaviour.sql`: jak zachowują się klienci?
- Top 20 klientów według wartości i liczby transakcji.
- **Klienci z fraudem** (849) mają średnią transakcję 255,69 EUR, a bez fraudu 83,15 EUR.
- **Liczba urządzeń:** przy 1 urządzeniu fraud dotyczy 5,81% klientów, przy 3 już 18,98%.

### `02_sql_analysis\04_window_functions.sql`: sygnały ryzyka
- **Funkcje okna** (`ROW_NUMBER`, `LAG`, `AVG/COUNT/SUM OVER`) liczą dla każdej transakcji jej kontekst: średnią klienta **przed** tą transakcją, liczbę transakcji w ostatnich 10 minutach, pierwsze użycie urządzenia i pierwszą transakcję w danym kraju.
- Z tego powstaje 6 sygnałów (CASE). Dla każdego sprawdzamy fraud rate, gdy jest włączony:

| sygnał | fraud rate gdy włączony | % wszystkich fraudów, które łapie |
|---|---|---|
| 5+ tx w 10 min | 100% | 45,2% |
| nowe urządzenie | 43,45% | 65,8% |
| ryzykowna kategoria | 11,59% | 80,7% |
| kwota > 3x średnia | 9,55% | 36,0% |
| nowy kraj | 8,01% | 49,2% |
| nocna godzina | 3,04% | 3,9% |

Żaden sygnał sam nie wystarcza: jedne są precyzyjne, ale rzadkie, inne częste, ale nieprecyzyjne. Dlatego łączymy je w punkty.

## Etap 4. Scoring (SQL)

### `03_risk_scoring.sql`: risk score v1 (wagi z planu)
- Liczy 7 sygnałów (6 powyżej + historia fraud/chargeback) dla każdej transakcji, sumuje punkty i nadaje poziom.
- Zapisuje wynik do nowej tabeli `fact_transaction_risk`.
- Wynik klienta to najwyższy wynik z ostatnich 30 dni, zapisany w `fact_customer_risk`.
- **Wynik:** fraud rate rośnie z poziomem: LOW 0,26%, MEDIUM 5,32%, HIGH 56%, CRITICAL 90,39%.

### `04_false_positives.sql`: gdzie scoring się myli?
- **Macierz pomyłek** przy progu 60: 1 821 trafionych fraudów, 1 009 fałszywych alarmów, 2 421 przepuszczonych fraudów.
- **Progi 30/50/60/70/80:** im wyższy próg, tym mniej fałszywych alarmów, ale więcej przepuszczonych fraudów.
- **Które reguły dają fałszywe alarmy:** historia fraud/chargeback jest w 95,8% z nich, więc reguła +30 jest przeważona.

### `05_risk_score_v2.sql`: poprawione wagi
- Historia +30 → +15, nowe urządzenie +15 → +25.
- Dodaje kolumny `risk_score_v2` / `risk_level_v2` w obu tabelach ryzyka i pokazuje porównanie „przed i po”.
- **Wynik przy progu 60:** fałszywe alarmy 1 009 → 227, precision 64,3% → 88,5%, recall prawie bez zmian (42,9% → 41,1%).

## Etap 5. Python: EDA i anomalie

### `08_eda.py`: eksploracja danych
- Czyta dane z PostgreSQL do pandas.
- Sprawdza kształt, typy, braki i duplikaty: wszystko czyste.
- Porównuje normalne i fraudowe transakcje: średnio 79 vs 808 EUR, za granicą 14% vs 94%.
- Liczy fraud rate per kraj, kategoria i plan. Plan prawie nie ma znaczenia (1,38–1,97%).
- Zapisuje 5 wykresów do `charts\`. Najciekawszy pokazuje dwa „garby” fraudu: drobne kwoty (card testing) i duże (czyszczenie konta).

### `09_anomaly_detection.py`: statystyka kontra reguły
- **IQR** (jeden próg kwoty dla wszystkich: 191,57 EUR): łapie 77,8% fraudów, ale tylko 14,8% alarmów jest trafnych.
- **z-score** (kwota względem średniej klienta): słaby, 12,8% fraudów, bo fraudy same zawyżają średnią klienta.
- **Scoring v2 ≥ 60:** 88,5% alarmów trafnych.
- **Lift** każdej reguły i korelacja scoringu z `is_fraud`: v1 0,403, v2 0,492.
- Eksportuje `powerbi_data\transactions_scored.csv` i `customers_risk.csv`, czyli gotowe dane do Power BI.

---

## Kolejność uruchamiania od zera

1. `00_create_tables.sql`
2. Python: `01` → `02` → `03` → `04` → `05` → `07` → `06`
3. SQL: `01_data_quality.sql`, a potem pliki z `02_sql_analysis\` (w dowolnej kolejności, tylko czytają dane)
4. SQL: `03_risk_scoring.sql` → `04_false_positives.sql` → `05_risk_score_v2.sql`
5. Python: `08_eda.py` → `09_anomaly_detection.py`

Jeśli ponownie uruchomisz `03`, zawsze uruchom po nim `05`, a potem `09`.

---

**Następna część:** podsumowanie biznesowe, czyli co te wszystkie wyniki znaczą dla banku i jak o nich opowiedzieć na rozmowie.
