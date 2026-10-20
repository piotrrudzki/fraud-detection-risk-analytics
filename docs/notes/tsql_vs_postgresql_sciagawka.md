# T-SQL (SQL Server) vs PostgreSQL – ściągawka

Przykłady na tabelach z projektu: `customers`, `transactions` (id, customer_id, amount, currency, tx_time, country, merchant).

## 1. Najważniejsze różnice w skrócie

| Temat | SQL Server (T-SQL) | PostgreSQL |
|---|---|---|
| Ograniczenie wierszy | `SELECT TOP 10 ...` | `... LIMIT 10` |
| Stronicowanie | `OFFSET 20 ROWS FETCH NEXT 10 ROWS ONLY` | `LIMIT 10 OFFSET 20` (lub to samo co w T-SQL) |
| Cudzysłowy w nazwach | `[Nazwa Kolumny]` | `"Nazwa Kolumny"` |
| Wielkość liter nazw | bez znaczenia | nazwy bez cudzysłowów zamieniane na małe litery; używaj `snake_case` |
| Łączenie tekstów | `'a' + 'b'` | `'a' \|\| 'b'` lub `CONCAT('a','b')` |
| NULL zamiast wartości | `ISNULL(x, 0)` | `COALESCE(x, 0)` (działa też w T-SQL) |
| Bieżąca data/czas | `GETDATE()` | `NOW()` / `CURRENT_TIMESTAMP` |
| Dodanie czasu | `DATEADD(day, -30, GETDATE())` | `NOW() - INTERVAL '30 days'` |
| Różnica dat | `DATEDIFF(day, a, b)` | `b::date - a::date` lub `EXTRACT(EPOCH FROM b - a)` |
| Część daty | `DATEPART(hour, tx_time)` | `EXTRACT(HOUR FROM tx_time)` |
| Obcięcie do dnia/miesiąca | `CAST(tx_time AS date)` / `DATETRUNC` | `DATE_TRUNC('month', tx_time)` |
| Rzutowanie | `CAST(x AS INT)` / `CONVERT(INT, x)` | `CAST(x AS INT)` lub `x::int` |
| Warunek w jednej linii | `IIF(a > 0, 'T', 'N')` | `CASE WHEN a > 0 THEN 'T' ELSE 'N' END` |
| Typ logiczny | `BIT` (0/1) | `BOOLEAN` (`true`/`false`) |
| Autonumeracja | `INT IDENTITY(1,1)` | `INT GENERATED ALWAYS AS IDENTITY` (lub `SERIAL`) |
| Tekst | `NVARCHAR(100)`, `NVARCHAR(MAX)` | `VARCHAR(100)`, `TEXT` (Unicode domyślnie) |
| Data i czas | `DATETIME2` | `TIMESTAMP` / `TIMESTAMPTZ` |
| Kwoty | `DECIMAL(18,2)` / `MONEY` | `NUMERIC(18,2)` (unikaj `money`) |
| Tabela tymczasowa | `#tmp` | `CREATE TEMP TABLE tmp ...` |
| Wyszukiwanie bez wielkości liter | `LIKE` (zależy od collation) | `ILIKE` |
| Separator poleceń | `GO` | `;` (`GO` nie istnieje) |
| Zmienne w skrypcie | `DECLARE @x INT = 5;` | tylko w bloku `DO $$ ... $$` lub funkcji |
| Zwracanie id po INSERT | `OUTPUT inserted.id` | `RETURNING id` |
| Upsert | `MERGE` | `INSERT ... ON CONFLICT ... DO UPDATE` (od v15 też `MERGE`) |
| Schemat domyślny | `dbo` | `public` |

## 2. Przykłady obok siebie (kontekst fraudu)

### Top 10 największych transakcji z ostatnich 30 dni

```sql
-- T-SQL
SELECT TOP 10 id, customer_id, amount
FROM dbo.transactions
WHERE tx_time >= DATEADD(day, -30, GETDATE())
ORDER BY amount DESC;

-- PostgreSQL
SELECT id, customer_id, amount
FROM transactions
WHERE tx_time >= NOW() - INTERVAL '30 days'
ORDER BY amount DESC
LIMIT 10;
```

### Transakcje nocne (00:00–05:00) jako flaga

```sql
-- T-SQL
SELECT id, IIF(DATEPART(hour, tx_time) BETWEEN 0 AND 4, 1, 0) AS is_night
FROM dbo.transactions;

-- PostgreSQL
SELECT id, EXTRACT(HOUR FROM tx_time) BETWEEN 0 AND 4 AS is_night  -- zwraca boolean
FROM transactions;
```

### Liczenie z warunkiem (np. ile transakcji zagranicznych ma klient)

```sql
-- T-SQL
SELECT customer_id, SUM(CASE WHEN country <> 'PL' THEN 1 ELSE 0 END) AS foreign_tx
FROM dbo.transactions GROUP BY customer_id;

-- PostgreSQL (krócej, dzięki FILTER)
SELECT customer_id, COUNT(*) FILTER (WHERE country <> 'PL') AS foreign_tx
FROM transactions GROUP BY customer_id;
```

### Funkcje okna (prawie identyczne)

```sql
-- Oba dialekty: kwota vs średnia klienta, czas od poprzedniej transakcji
SELECT id, customer_id, amount,
       amount / NULLIF(AVG(amount) OVER (PARTITION BY customer_id), 0) AS amount_vs_avg,
       tx_time - LAG(tx_time) OVER (PARTITION BY customer_id ORDER BY tx_time) AS since_prev
FROM transactions;
-- Różnica: w T-SQL "since_prev" liczysz przez DATEDIFF(second, LAG(...), tx_time),
-- w PostgreSQL odejmowanie timestampów daje typ INTERVAL.
```

### Okno czasowe "ostatnia godzina" (velocity check)

```sql
-- PostgreSQL potrafi okna po czasie (RANGE z INTERVAL); T-SQL tego nie ma
SELECT id, customer_id,
       COUNT(*) OVER (PARTITION BY customer_id ORDER BY tx_time
                      RANGE BETWEEN INTERVAL '1 hour' PRECEDING AND CURRENT ROW) AS tx_last_hour
FROM transactions;
```

### Ostatnia transakcja każdego klienta

```sql
-- T-SQL: ROW_NUMBER() w CTE + WHERE rn = 1  (działa też w PostgreSQL)

-- PostgreSQL: skrót DISTINCT ON
SELECT DISTINCT ON (customer_id) customer_id, id, amount, tx_time
FROM transactions
ORDER BY customer_id, tx_time DESC;
```

### CROSS APPLY → LATERAL

```sql
-- T-SQL
SELECT c.id, t.amount
FROM dbo.customers c
CROSS APPLY (SELECT TOP 3 amount FROM dbo.transactions t
             WHERE t.customer_id = c.id ORDER BY amount DESC) t;

-- PostgreSQL
SELECT c.id, t.amount
FROM customers c
CROSS JOIN LATERAL (SELECT amount FROM transactions t
                    WHERE t.customer_id = c.id ORDER BY amount DESC LIMIT 3) t;
-- OUTER APPLY → LEFT JOIN LATERAL (...) t ON true
```

### Tworzenie tabeli

```sql
-- T-SQL
CREATE TABLE dbo.transactions (
  id INT IDENTITY(1,1) PRIMARY KEY,
  customer_id INT NOT NULL,
  amount DECIMAL(18,2),
  merchant NVARCHAR(200),
  is_flagged BIT DEFAULT 0,
  tx_time DATETIME2
);

-- PostgreSQL
CREATE TABLE transactions (
  id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  customer_id INT NOT NULL,
  amount NUMERIC(18,2),
  merchant VARCHAR(200),
  is_flagged BOOLEAN DEFAULT false,
  tx_time TIMESTAMP
);
```

## 3. Pułapki na start

- **Dzielenie liczb całkowitych**: `5/2` daje `2` w obu, ale w PostgreSQL łatwiej o to wpaść przy wskaźnikach typu `fraud_count / total`. Pisz `fraud_count::numeric / total`.
- **Wielkie litery w nazwach**: `CREATE TABLE "Transactions"` wymusza potem cudzysłowy przy każdym zapytaniu. Trzymaj się małych liter.
- **Pojedyncze vs podwójne cudzysłowy**: `'tekst'` to wartość, `"kolumna"` to nazwa. `WHERE country = "PL"` zwróci błąd.
- **Błąd w transakcji**: po błędzie w otwartej transakcji PostgreSQL odrzuca kolejne polecenia, aż zrobisz `ROLLBACK`.
- **Procedury**: T-SQL-owe skrypty z `DECLARE @x`, `IF`, `WHILE` trzeba przepisać na PL/pgSQL (`DO $$ BEGIN ... END $$;`). W tym projekcie i tak większość logiki zrobisz zwykłymi zapytaniami i widokami, więc rzadko będzie to potrzebne.
- **Narzędzia**: zamiast SSMS używa się pgAdmin lub DBeaver; Power BI łączy się z PostgreSQL wbudowanym konektorem, Python przez `psycopg` lub `SQLAlchemy`.
