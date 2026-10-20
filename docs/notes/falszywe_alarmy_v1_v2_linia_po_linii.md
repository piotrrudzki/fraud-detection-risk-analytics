# Fałszywe alarmy v1 vs v2: zapytanie wyjaśnione krok po kroku (PostgreSQL)

## Co robi zapytanie (w jednym zdaniu)

Bierze wszystkie **fałszywe alarmy**, czyli transakcje z wynikiem ≥ 60, które w rzeczywistości nie były fraudem. Dla każdego z 7 sygnałów liczy, w ilu z tych alarmów sygnał był włączony, osobno dla v1 i v2.

Wynik to 7 wierszy (jeden na sygnał) i 4 liczby: ile fałszywych alarmów i jaki procent, w v1 i v2.

## Dlaczego dwa razy CROSS JOIN LATERAL

Problem polega na tym, że dane leżą **w kolumnach**, a my chcemy je mieć **w wierszach**:

- Wynik v1 i v2 to dwie kolumny: `risk_score` i `risk_score_v2`. Chcemy jedną kolumnę `score` i obok etykietę `version`.
- 7 sygnałów to 7 kolumn: `s_fraud_history`, `s_new_device` itd. Chcemy jedną kolumnę `is_on` i obok nazwę `signal`.

Takie „obrócenie” kolumn w wiersze nazywa się **unpivot**. W PostgreSQL najprościej zrobić je przez `CROSS JOIN LATERAL (VALUES ...)`:

- **`VALUES (...), (...)`** tworzy małą tabelę „w locie”, np. 2 wiersze: `('v1', risk_score)` i `('v2', risk_score_v2)`.
- **`LATERAL`** pozwala tej małej tabeli korzystać z kolumn bieżącego wiersza (`r.risk_score`). Bez `LATERAL` nie byłoby wolno odwołać się do `r`.
- **`CROSS JOIN`** łączy każdy wiersz z każdym wierszem małej tabeli, więc jedna transakcja zamienia się w 2 wiersze (v1 i v2), a potem w 7 wierszy (po jednym na sygnał).

W T-SQL to samo robi `CROSS APPLY (VALUES ...)`, a `LATERAL` jest tam „wbudowany”. Można też użyć operatora `UNPIVOT`.

### Mały przykład

Jedna transakcja w `fact_transaction_risk`:

| transaction_id | risk_score | risk_score_v2 | is_fraud |
|---|---|---|---|
| 500 | 70 | 55 | false |

Po pierwszym `CROSS JOIN LATERAL` powstają 2 wiersze:

| transaction_id | version | score |
|---|---|---|
| 500 | v1 | 70 |
| 500 | v2 | 55 |

`WHERE v.score >= 60` zostawia tylko wiersz v1, bo w v2 ta transakcja nie dała alarmu. To dokładnie ten przypadek, który v2 „naprawiło”.

Po drugim `CROSS JOIN LATERAL` ten jeden wiersz zamienia się w 7, po jednym na sygnał:

| version | signal | is_on |
|---|---|---|
| v1 | fraud / chargeback history | true |
| v1 | risky category | true |
| v1 | amount > 3x customer avg | true |
| v1 | new country | false |
| … | … | … |

Teraz wystarczy `GROUP BY signal` i liczenie.

---

## Krok 1: CTE `false_alarms`, czyli lista fałszywych alarmów w obu wersjach

```sql
WITH false_alarms AS (
    SELECT v.version, r.*
```
`r.*` to wszystkie kolumny transakcji, w tym 7 sygnałów. `v.version` to etykieta 'v1' lub 'v2' z małej tabeli.

```sql
    FROM fact_transaction_risk r
    CROSS JOIN LATERAL (VALUES ('v1', r.risk_score),
                               ('v2', r.risk_score_v2)) AS v(version, score)
```
Każda transakcja zostaje skopiowana 2 razy: raz z wynikiem v1, raz z v2. `AS v(version, score)` nadaje małej tabeli nazwę `v` i nazwy kolumn.

```sql
    WHERE v.score >= 60
      AND NOT r.is_fraud
)
```
Zostawia tylko **alarmy** (wynik ≥ 60) i tylko **fałszywe** (`is_fraud = false`). `NOT r.is_fraud` to w PostgreSQL to samo co `r.is_fraud = false`. W T-SQL napisałbyś `is_fraud = 0`.

Po tym kroku mamy 1 009 wierszy v1 i 227 wierszy v2.

## Krok 2: rozbicie na sygnały

```sql
FROM false_alarms a
CROSS JOIN LATERAL (VALUES
    ('fraud / chargeback history', COALESCE(a.s_fraud_history, false)),
    ('risky category',             a.s_risky_category),
    ...
) AS s(signal, is_on)
```
Każdy fałszywy alarm zamienia się w 7 wierszy z nazwą sygnału i informacją, czy był włączony.

`COALESCE(..., false)` zamienia NULL na false. Dwa sygnały mogą być NULL:
- `s_fraud_history`, gdy klient nie ma wiersza w `fact_customer_risk`;
- `s_amount_3x_avg` przy pierwszej transakcji klienta, bo nie ma jeszcze średniej.

## Krok 3: liczenie z FILTER

```sql
SELECT
    s.signal,
    COUNT(*) FILTER (WHERE a.version = 'v1' AND s.is_on)  AS false_alarms_v1,
```
Ile fałszywych alarmów v1 miało włączony ten sygnał. `FILTER (WHERE ...)` liczy tylko wiersze spełniające warunek. W T-SQL: `SUM(CASE WHEN a.version = 'v1' AND s.is_on = 1 THEN 1 ELSE 0 END)`.

```sql
    ROUND(100.0 * COUNT(*) FILTER (WHERE a.version = 'v1' AND s.is_on)
                / COUNT(*) FILTER (WHERE a.version = 'v1'), 1)  AS pct_v1,
```
Jaki to procent wszystkich fałszywych alarmów v1. Mianownik to liczba wszystkich alarmów v1 w grupie danego sygnału, czyli 1 009, bo każdy alarm ma jeden wiersz na sygnał. `100.0` z kropką wymusza dzielenie z ułamkami. Samo `100` przy liczbach całkowitych dałoby dzielenie całkowite, i to zarówno w PostgreSQL, jak i w T-SQL.

Kolumny `false_alarms_v2` i `pct_v2` działają tak samo, tylko dla `'v2'`.

```sql
GROUP BY s.signal
ORDER BY false_alarms_v1 DESC;
```
Jeden wiersz na sygnał, a na górze ten, który w v1 dawał najwięcej fałszywych alarmów.

## Jak czytać wynik

| sygnał | false_alarms_v1 | pct_v1 | false_alarms_v2 | pct_v2 |
|---|---|---|---|---|
| fraud / chargeback history | 967 | 95,8 | 136 | 59,9 |

Z 1 009 fałszywych alarmów v1 aż 967 miało włączoną historię. W v2 takich alarmów zostało 136. Procenty v2 liczymy od mniejszej bazy (227), więc do porównania wersji patrz na **liczby**.
