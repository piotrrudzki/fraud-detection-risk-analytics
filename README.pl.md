# Fraud Detection & Customer Risk Analytics

[English](README.md) | **Polski**

Analiza oszustw i przejrzysty, regułowy scoring ryzyka zbudowany na **257 947 syntetycznych transakcjach kartowych** (10 000 klientów, 500 sprzedawców, styczeń–czerwiec 2026).
Cel: wykryć jak najwięcej fraudu przy jak najmniejszej liczbie **fałszywych alarmów** i umieć wytłumaczyć każdą decyzję.

**Technologie:** PostgreSQL 18 · Python (pandas, NumPy, matplotlib, psycopg) · Power BI

---

## Najważniejsze wyniki

| | |
|---|---|
| Udział fraudu w liczbie transakcji | **1,64%** (4 242 z 257 947) |
| Udział fraudu w wartości | **14,65%** (3,43 mln z 23,4 mln EUR) |
| Średnia transakcja: fraud vs normalna | 808 EUR vs 79 EUR |
| Fraud rate: za granicą vs w kraju klienta | 10,14% vs 0,11% |
| Najbardziej ryzykowne kategorie | crypto 18,97%, elektronika 10,21%, karty podarunkowe 8,40% |

**Scoring ryzyka v1 → v2 (próg 60)**

| | v1 | v2 | zmiana |
|---|---|---|---|
| Fałszywe alarmy | 1 009 | **227** | **−78%** |
| Wykryte fraudy | 1 821 | 1 742 | −4% |
| Precision | 64,3% | **88,5%** | +24 pp |

Dla porównania: prosta reguła „kwota powyżej 191,57 EUR” (IQR) daje 22 276 alarmów, z których tylko **14,8%** to fraud.

**Rekomendacja:** dwa poziomy reakcji zamiast jednego progu:
- **wynik 80+**: automatyczna blokada (466 transakcji w 6 miesięcy, 99,1% to fraud);
- **wynik 50–79**: kolejka do ręcznej weryfikacji (ok. 21 spraw dziennie, ok. 62% to fraud).

Razem wychwytują **66,8%** wszystkich fraudów.

## Najmocniejsze sygnały oszustwa

| Sygnał | Fraud rate, gdy sygnał się zapali | Lift |
|---|---|---|
| 5+ transakcji w 10 minut | 100%* | ×60,8 |
| Nowe urządzenie (pierwsze 24 h) | 43,45% | ×26,4 |
| Ryzykowna kategoria sprzedawcy | 11,59% | ×7,0 |
| Kwota > 3× średnia klienta | 9,55% | ×5,8 |
| Pierwsza transakcja w nowym kraju | 8,01% | ×4,9 |
| Wcześniejszy fraud / chargeback | 5,41% | ×3,3 |
| Godziny nocne | 3,04% | ×1,9 |

\* Efekt danych syntetycznych, patrz ograniczenia.

Najważniejszy wniosek z analizy fałszywych alarmów: reguła „historia klienta” odpowiadała za **96% fałszywych alarmów** w v1. Zmniejszenie jej wagi i zwiększenie wagi „nowego urządzenia” usunęło prawie 4 na 5 fałszywych alarmów.

![Fraud rate według wyniku scoringu](charts/06_fraud_rate_by_risk_score.png)

## Struktura projektu

```
python/
  01-05, 07_generate_*.py    generatory danych syntetycznych (seed 42) -> data/*.csv
  06_load_to_postgres.py      ładowanie CSV do PostgreSQL (COPY)
  08_eda.py                   analiza eksploracyjna, wykresy
  09_anomaly_detection.py     IQR / z-score vs scoring, eksport do Power BI
sql/
  00_create_tables.sql        schemat gwiazdy: 4 wymiary + 2 tabele faktów
  01_data_quality.sql         17 kontroli jakości danych
  02_sql_analysis/            fraud rate, trendy, zachowania klientów, sygnały z funkcji okna
  03_risk_scoring.sql         scoring v1 (7 sygnałów, poziom transakcji i klienta)
  04_false_positives.sql      macierz pomyłek, progi, które reguły dają fałszywe alarmy
  05_risk_score_v2.sql        scoring v2 z poprawionymi wagami, porównanie przed i po
charts/                       wykresy ze skryptów Python
docs/                         podsumowanie projektu (PDF), notatki SQL, ściągawka PostgreSQL vs T-SQL
```

**Model danych (schemat gwiazdy):** `fact_transaction` z wymiarami `dim_customer`, `dim_merchant`, `dim_device`, `dim_fx_rate` (dzienne kursy EUR dla 9 walut) oraz `fact_customer_risk`.

**Użyte techniki SQL:** CTE, funkcje okna (`LAG`, `ROW_NUMBER`, `RANGE BETWEEN INTERVAL ... PRECEDING`), `FILTER`, `CROSS JOIN LATERAL`, złączenia po kilku kolumnach przy przeliczaniu walut, scoring oparty na `CASE`.

## Jak uruchomić

1. Utwórz bazę PostgreSQL `fraud_project` i uruchom `sql/00_create_tables.sql`.
2. Zainstaluj biblioteki: `pip install -r requirements.txt`.
3. Wygeneruj i załaduj dane (z głównego folderu projektu):
   `python/01` → `02` → `03` → `04` → `05` → `07` → `06_load_to_postgres.py`.
   Danych nie ma w repozytorium. Dzięki seed 42 odtwarzają się identycznie.
4. SQL: `01_data_quality.sql`, pliki z `02_sql_analysis/`, potem `03_risk_scoring.sql` → `04_false_positives.sql` → `05_risk_score_v2.sql`.
5. Python: `08_eda.py` → `09_anomaly_detection.py` (tworzy też `powerbi_data/` pod dashboard).

Skrypty pytają o hasło do PostgreSQL w terminalu. W kodzie nie ma zapisanych haseł.

## Ograniczenia

- Dane są **syntetyczne**. W prawdziwym banku etykieta fraudu jest opóźniona i niepełna.
- Niektóre sygnały są „zbyt czyste” (5+ transakcji w 10 minut = 100% fraudu; 5 kategorii z 0% fraudu). To efekt generatora.
- Wagi v2 dobrano i oceniono na tym samym okresie. Produkcyjnie sprawdzono by je na nowym, niewidzianym okresie.
- Okno 30 dni i progi poziomów 30/60/80 to założenia demonstracyjne.

## Kolejne kroki

- Nowe sygnały: zmiana hasła lub numeru telefonu przed płatnością, nowy odbiorca przelewu, niemożliwa podróż między krajami.
- Porównanie scoringu regułowego z modelem ML (regresja logistyczna, drzewa decyzyjne).
- Dashboard w Power BI na danych z `powerbi_data/`.

---

Autor: Piotr Rudzki
