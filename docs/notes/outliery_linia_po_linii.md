# Outliery: zapytanie wyjaśnione linijka po linijce (PostgreSQL)

**Cel zapytania:** znaleźć transakcje, w których klient zapłacił co najmniej 10 razy więcej niż zwykle. „Zwykle” oznacza medianę jego kwot. Kwoty są w różnych walutach, więc najpierw przeliczamy wszystko na EUR.

Zapytanie ma trzy części:

1. **`tx_eur`:** każda transakcja z kwotą przeliczoną na EUR.
2. **`customer_median`:** typowa kwota każdego klienta (mediana) i liczba jego transakcji.
3. **Końcowy `SELECT`:** łączy części 1 i 2 i zostawia tylko transakcje dużo wyższe niż typowa kwota klienta.

`WITH ... AS (...)` to **CTE** (Common Table Expression), czyli tymczasowa, nazwana tabela, która istnieje tylko w czasie wykonania tego zapytania. Działa tak samo jak w T-SQL.

---

## Część 1: `tx_eur`, czyli kwoty w EUR

```sql
WITH tx_eur AS (
```
Tworzy pierwszą tymczasową tabelę o nazwie `tx_eur`.

```sql
    SELECT t.transaction_id, t.customer_id, t.tx_datetime, t.amount, t.currency, t.is_fraud,
```
Bierze potrzebne kolumny z transakcji. `t` to alias (skrót) tabeli `fact_transaction`, nadany niżej.

```sql
           ROUND(t.amount * fx.eur_rate, 2) AS amount_eur
```
Przelicza kwotę na EUR: kwota razy kurs. Na przykład 6210,93 PLN × 0,2385 = 1481,30 EUR. `ROUND(..., 2)` zaokrągla wynik do groszy.

```sql
    FROM fact_transaction t
```
Źródłem są transakcje, z aliasem `t`.

```sql
    JOIN dim_fx_rate fx ON fx.rate_date = t.tx_datetime::date AND fx.currency = t.currency
```
Dołącza kurs waluty z **dnia transakcji** i **w walucie transakcji**.
- `t.tx_datetime::date` obcina datę z godziną do samej daty, np. `2026-06-08 15:40:16` zmienia się w `2026-06-08`. `::` to rzutowanie w PostgreSQL. W T-SQL napisałbyś `CAST(t.tx_datetime AS date)`.
- Warunek ma dwie części, bo kursy są zapisane osobno dla każdego dnia i każdej waluty.

```sql
),
```
Koniec pierwszego CTE. Przecinek oznacza, że zaraz będzie następne.

---

## Część 2: `customer_median`, czyli typowa kwota klienta

```sql
customer_median AS (
```
Druga tymczasowa tabela. Może korzystać z `tx_eur`, bo ta jest już zdefiniowana wyżej.

```sql
    SELECT customer_id,
```
Jeden wiersz na klienta.

```sql
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY amount_eur) AS median_eur,
```
**Mediana** kwot klienta w EUR, czyli wartość środkowa po posortowaniu kwot.
- `0.5` oznacza 50. percentyl, czyli medianę. `0.9` dałoby 90. percentyl.
- `WITHIN GROUP (ORDER BY amount_eur)` mówi, według czego sortować przed wybraniem środka.
- **Dlaczego mediana, a nie średnia (`AVG`)?** Średnią łatwo zawyżyć jedną dużą kwotą, a właśnie takich kwot szukamy. Mediana jest na nie odporna. Przykład: kwoty 20, 25, 30, 35 i 2000 dają średnią 422, a medianę 30.
- **Różnica względem T-SQL:** w SQL Server `PERCENTILE_CONT` działa tylko jako funkcja okna i nie da się jej użyć z `GROUP BY`. Trzeba napisać `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY amount_eur) OVER (PARTITION BY customer_id)` i potem usunąć duplikaty przez `DISTINCT`. W PostgreSQL to zwykła funkcja agregująca, więc wystarczy `GROUP BY`.

```sql
           COUNT(*) AS tx_count
```
Liczba transakcji klienta. Przyda się, bo mediana z 1–2 transakcji niewiele mówi.

```sql
    FROM tx_eur
    GROUP BY customer_id
)
```
Liczy wszystko osobno dla każdego klienta, a `)` zamyka drugie CTE.

---

## Część 3: wynik końcowy

```sql
SELECT e.transaction_id, e.customer_id, e.tx_datetime, e.amount, e.currency, e.amount_eur,
```
Kolumny z `tx_eur`, które ma alias `e`: dane transakcji oraz kwota w oryginalnej walucie i w EUR.

```sql
       ROUND(m.median_eur::numeric, 2)                 AS mediana_klienta_eur,
```
Mediana klienta zaokrąglona do 2 miejsc. `PERCENTILE_CONT` zwraca typ `double precision`, a w PostgreSQL `ROUND(x, 2)` działa tylko na typie `numeric`, stąd rzutowanie `::numeric`. W T-SQL to rzutowanie nie jest potrzebne.

```sql
       ROUND((e.amount_eur / m.median_eur)::numeric, 1) AS ile_razy_wiecej,
```
Mówi, ile razy ta transakcja jest wyższa niż typowa kwota klienta. Na przykład 1481,30 / 2,64 = 561,1.

```sql
       e.is_fraud
```
Informacja, czy transakcja była fraudem. Dzięki niej widać, ile z tych podejrzanych transakcji to fraud, a ile fałszywy alarm.

```sql
FROM tx_eur e
JOIN customer_median m USING (customer_id)
```
Do każdej transakcji dołącza medianę jej klienta. `USING (customer_id)` to skrót od `ON e.customer_id = m.customer_id` i działa, gdy kolumna nazywa się tak samo w obu tabelach. **W T-SQL nie ma `USING`**, trzeba pisać pełne `ON`.

```sql
WHERE m.tx_count >= 5
```
Bierze tylko klientów z co najmniej 5 transakcjami, żeby mediana była wiarygodna.

```sql
  AND e.amount_eur > 10 * m.median_eur
```
To jest **reguła wykrywania**: zostają transakcje ponad 10 razy wyższe niż mediana klienta. Próg 10 jest umowny. Niższy złapie więcej fraudów, ale też więcej fałszywych alarmów. Ten kompromis zbadamy przy scoringu.

```sql
ORDER BY ile_razy_wiecej DESC
```
Sortuje od najbardziej odstających transakcji.

```sql
LIMIT 50;
```
Pokazuje tylko 50 pierwszych wierszy. W T-SQL zamiast tego piszesz `SELECT TOP 50` na początku zapytania.

---

## Co wynika z Twojego wyniku

- W top 50 jest 31 fraudów i 19 uczciwych transakcji. Reguła „10 razy więcej niż zwykle” działa, ale **38% jej alarmów jest fałszywych**.
- Mediany 2–5 EUR to klienci, u których oszuści robili wcześniej card testing, czyli dużo płatności po 1–5 EUR. Te drobne płatności zaniżyły medianę. To przykład, że fraud „psuje” też statystyki opisujące normalne zachowanie klienta.
