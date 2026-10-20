# Część 1. Tabele i kolumny w projekcie (PostgreSQL, baza fraud_project)

## Jak zbudowana jest baza

Baza ma układ **gwiazdy** (*star schema*), czyli standardowy układ hurtowni danych:

- **Tabele faktów** (`fact_...`) zapisują zdarzenia, tutaj transakcje i wyniki ryzyka. Mają dużo wierszy.
- **Tabele wymiarów** (`dim_...`) opisują to, czego dotyczy zdarzenie: kto płacił (klient), gdzie (merchant), czym (urządzenie), w jakiej walucie (kurs). Mają mniej wierszy.

W środku gwiazdy jest `fact_transaction`, a wymiary są dookoła. Łączą się przez klucze:

- **PRIMARY KEY (PK)**: unikalny identyfikator wiersza w tabeli, np. `customer_id` w `dim_customer`.
- **FOREIGN KEY (FK)**: kolumna wskazująca na PK innej tabeli, np. `customer_id` w `fact_transaction`. Baza pilnuje, żeby nie dało się wpisać transakcji klienta, który nie istnieje.

```
                 dim_customer ── fact_customer_risk
                      │
dim_merchant ── fact_transaction ── dim_device
                      │
                 dim_fx_rate (łączona po dacie i walucie)
                      │
              fact_transaction_risk (wynik scoringu, 1 wiersz = 1 transakcja)
```

Wszystkie dane są **syntetyczne**: wygenerowaliśmy je w Pythonie (skrypty 01–05 i 07), z ziarnem losowania 42, więc za każdym razem wychodzą identyczne. Okres transakcji to **1.01.2026–30.06.2026**.

Kolejność tworzenia: `00_create_tables.sql` tworzy 6 pustych tabel, skrypty Python generują pliki CSV, `06_load_to_postgres.py` ładuje je do bazy, a `03_risk_scoring.sql` i `05_risk_score_v2.sql` dobudowują siódmą tabelę z wynikami ryzyka.

---

## 1. `dim_customer`: klienci (10 000 wierszy)

Kto ma konto w banku. Tworzy ją skrypt `01_generate_customers.py`.

| Kolumna | Typ | Co oznacza |
|---|---|---|
| `customer_id` | INT, **PK** | Numer klienta, od 1 do 10 000. |
| `country` | CHAR(2) | Kraj zamieszkania klienta, kod ISO (PL, GB, DE, FR, ES, IT, RO, LT, IE, NL). Najwięcej jest klientów z Polski (25%). |
| `age` | SMALLINT | Wiek, od 18 do 80. `CHECK (age BETWEEN 18 AND 100)` w tabeli nie pozwoli wpisać innej wartości. |
| `signup_date` | DATE | Data założenia konta, od 2020 roku. Około 8% klientów założyło konto w trakcie okresu (2026). To ważne, bo nowe konta są bardziej ryzykowne. |
| `plan` | VARCHAR(20) | Plan konta jak w Revolucie: standard (60%), plus, premium, metal. |
| `account_age_days` | INT | Wiek konta w dniach na 30.06.2026. |

**Typy w PostgreSQL:** `CHAR(2)` to tekst o stałej długości 2 znaków, `SMALLINT` to mała liczba całkowita, `VARCHAR(20)` to tekst do 20 znaków (tak samo jak w T-SQL).

---

## 2. `dim_merchant`: sprzedawcy (500 wierszy)

Gdzie klient płacił: sklep, serwis, bankomat. Tworzy ją skrypt `02_generate_merchants.py`.

| Kolumna | Typ | Co oznacza |
|---|---|---|
| `merchant_id` | INT, **PK** | Numer sprzedawcy, od 1 do 500. |
| `merchant_category` | VARCHAR(50) | Kategoria (10 rodzajów): grocery, restaurants, transport, online_shopping, travel, gaming, cash_withdrawal, electronics, gift_cards, crypto. |
| `country` | CHAR(2) | Kraj sprzedawcy. Około 17% jest spoza Europy (US, CN, AE, SG, TR). |
| `merchant_risk_category` | VARCHAR(10) | Ryzyko sprzedawcy: low / medium / high. Wynika z kategorii (crypto, gift_cards, electronics = high), a sprzedawca spoza UE dostaje stopień wyżej. |

Waluta transakcji wynika z kraju sprzedawcy, np. sprzedawca z PL to PLN, a z DE to EUR.

---

## 3. `dim_device`: urządzenia (14 511 wierszy)

Telefony i komputery, z których klienci logują się do aplikacji. Tworzy ją skrypt `03_generate_devices.py`, a `05` dopisuje urządzenia oszustów.

| Kolumna | Typ | Co oznacza |
|---|---|---|
| `device_id` | INT, **PK** | Numer urządzenia. |
| `customer_id` | INT, **FK** → `dim_customer` | Do którego klienta należy urządzenie. |
| `device_country` | CHAR(2) | Kraj, w którym urządzenie zostało zarejestrowane. |
| `first_seen` | TIMESTAMP | Kiedy urządzenie pojawiło się pierwszy raz. |
| `last_seen` | TIMESTAMP | Kiedy było użyte ostatni raz. |

Większość klientów ma 1 urządzenie (65%), część 2 lub 3. Urządzenie o najniższym `device_id` to główny telefon klienta. **Nowe urządzenie** jest jednym z najmocniejszych sygnałów oszustwa: przy przejęciu konta (*account takeover*) oszust loguje się ze swojego telefonu.

---

## 4. `dim_fx_rate`: kursy walut (1 629 wierszy)

9 walut × 181 dni. Tworzy ją skrypt `04_generate_fx_rates.py`.

| Kolumna | Typ | Co oznacza |
|---|---|---|
| `rate_date` | DATE, część **PK** | Dzień kursu. |
| `currency` | CHAR(3), część **PK** | Waluta: EUR, PLN, GBP, RON, USD, CNY, AED, SGD, TRY. |
| `eur_rate` | NUMERIC(12,6) | Ile EUR kosztuje 1 jednostka waluty, np. PLN ≈ 0,235. |

Klucz główny składa się z **dwóch kolumn** (`rate_date` + `currency`), bo dopiero ich para jest unikalna. Służy do przeliczenia każdej kwoty na EUR: `amount × eur_rate`. Bez tego nie dałoby się porównać 100 PLN ze 100 GBP. `NUMERIC(12,6)` to liczba dokładna z 6 miejscami po przecinku (w T-SQL: `DECIMAL(12,6)`).

---

## 5. `fact_transaction`: transakcje (257 947 wierszy), serce projektu

Każda płatność kartą klienta. Tworzy ją skrypt `05_generate_transactions.py`.

| Kolumna | Typ | Co oznacza |
|---|---|---|
| `transaction_id` | BIGINT, **PK** | Numer transakcji. BIGINT, bo w prawdziwym banku byłyby ich miliardy. |
| `customer_id` | INT, **FK** → `dim_customer` | Kto płacił. |
| `tx_datetime` | TIMESTAMP | Data i godzina płatności. |
| `amount` | NUMERIC(12,2) | Kwota w walucie transakcji, z groszami. |
| `currency` | CHAR(3) | Waluta transakcji. |
| `merchant_id` | INT, **FK** → `dim_merchant` | Gdzie płacił. |
| `device_id` | INT, **FK** → `dim_device` | Z jakiego urządzenia. |
| `country` | CHAR(2) | Kraj, w którym odbyła się transakcja. |
| `is_fraud` | BOOLEAN | **Etykieta**: `true` = oszustwo, `false` = normalna transakcja. W T-SQL byłby to typ `BIT` (1/0). |

Fraudów jest **4 242, czyli 1,64%**. Wstrzyknęliśmy 4 scenariusze oszustw:

1. **Przejęcie konta (ATO):** nowe urządzenie, często inny kraj, seria dużych płatności.
2. **Card testing:** dużo drobnych kwot (1–5 EUR) w kilka minut, żeby sprawdzić, czy karta działa.
3. **Wysoka kwota:** pojedyncza płatność dużo wyższa niż zwykle u klienta.
4. **Nowe konto:** świeżo założone konto użyte od razu do oszustwa.

Celowo dodaliśmy też **legalne transakcje, które wyglądają podejrzanie**: podróże za granicę i duże zakupy. Bez nich każdy alarm byłby trafiony, a to nierealne.

W prawdziwym banku `is_fraud` pochodzi z potwierdzonych zgłoszeń, często po tygodniach. Używamy go **tylko do oceny** scoringu, nigdy do jego liczenia.

---

## 6. `fact_customer_risk`: ryzyko klienta (10 000 wierszy)

Jeden wiersz na klienta. Historię tworzy skrypt `07_generate_customer_history.py`, a wyniki ryzyka dopisuje SQL (v1 plik 03, v2 plik 05).

| Kolumna | Typ | Co oznacza |
|---|---|---|
| `customer_id` | INT, **PK** i **FK** → `dim_customer` | Klient. |
| `previous_fraud` | BOOLEAN | Czy klient miał potwierdzony fraud **przed** 2026 rokiem (285 klientów). |
| `chargebacks` | INT | Ile chargebacków miał w 12 miesiącach przed 2026 (807 klientów ma co najmniej 1). |
| `risk_score` | NUMERIC(5,2) | Wynik ryzyka klienta na 30.06.2026 według **wag z planu (v1)**: najwyższy wynik jego transakcji z ostatnich 30 dni. Wpisuje go `03_risk_scoring.sql`. |
| `risk_level` | VARCHAR(10) | Poziom według v1: LOW / MEDIUM / HIGH / CRITICAL. |
| `risk_score_v2` | NUMERIC(5,2) | To samo, ale według **poprawionych wag (v2)**, czyli wynik końcowy. Kolumnę dodaje i wypełnia `05_risk_score_v2.sql`. |
| `risk_level_v2` | VARCHAR(10) | Poziom według v2. |

Ta tabela jest „migawką” (*snapshot*): odpowiada na pytanie, jak ryzykowny jest klient dziś. Z niej korzysta strona Power BI do przeglądania klientów.

---

## 7. `fact_transaction_risk`: scoring każdej transakcji (257 947 wierszy)

Nie ma jej w `00_create_tables.sql`. Tworzy ją `03_risk_scoring.sql` (wersja v1), a `05_risk_score_v2.sql` dopisuje kolumny v2. Każdy wiersz to jedna transakcja i odpowiedź na pytanie: które sygnały się zapaliły i ile punktów dostała.

| Kolumna | Co oznacza |
|---|---|
| `transaction_id`, `customer_id`, `tx_datetime` | Która transakcja, czyja i kiedy. |
| `amount_eur` | Kwota przeliczona na EUR. |
| `is_fraud` | Etykieta, przepisana tylko do oceny wyników. |
| `s_amount_3x_avg` | Sygnał: kwota ponad 3× wyższa niż dotychczasowa średnia klienta. |
| `s_new_device` | Sygnał: pierwsze 24 godziny nowego (nie pierwszego) urządzenia klienta. |
| `s_new_country` | Sygnał: pierwsza transakcja klienta w tym kraju. |
| `s_5_tx_in_10_min` | Sygnał: 5 lub więcej transakcji klienta w ciągu 10 minut. |
| `s_risky_category` | Sygnał: crypto, gift_cards albo electronics. |
| `s_fraud_history` | Sygnał: klient miał wcześniej fraud lub chargeback (z `fact_customer_risk`). |
| `s_night_hour` | Sygnał: godzina 0:00–4:59. |
| `risk_score`, `risk_level` | Wynik i poziom według **wag z planu (v1)**. |
| `risk_score_v2`, `risk_level_v2` | Wynik i poziom według **poprawionych wag (v2)**: historia +15 zamiast +30, nowe urządzenie +25 zamiast +15. |

Kolumny `s_...` są typu BOOLEAN (true/false). Prefiks `s_` znaczy *signal*. Progi poziomów: 0–29 LOW, 30–59 MEDIUM, 60–79 HIGH, 80+ CRITICAL.

---

## Pliki pod Power BI (folder `powerbi_data\`)

Tworzy je `09_anomaly_detection.py`. To nie są tabele w bazie, tylko gotowe eksporty:

- `transactions_scored.csv`: `fact_transaction_risk` z kategorią, krajem i walutą, plus trzy kolumny z analizy statystycznej:
  - `iqr_outlier`: czy kwota przekracza 191,57 EUR (próg IQR dla wszystkich).
  - `z_score`: o ile odchyleń standardowych kwota odbiega od średniej klienta.
  - `z_outlier`: czy `z_score` jest powyżej 3.
- `customers_risk.csv`: `dim_customer` połączone z `fact_customer_risk`.

---

**Następna część:** co robią po kolei skrypty SQL (jakość danych, analiza, funkcje okna, scoring), a potem podsumowanie biznesowe wyników.
