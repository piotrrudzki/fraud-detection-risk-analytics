-- 01_data_quality.sql  (PostgreSQL, database fraud_project)
-- Data quality checks, following section 7 of the plan.
-- Part 1 returns one summary table: each check is one row
-- with the number of records that fail it (0 = OK). Part 2 shows outlier candidates.

-- ============================================================
-- Part 1. Summary of checks
-- ============================================================
WITH tx_eur AS (
    -- transaction amount converted to EUR at the rate from the transaction day
    SELECT t.*, t.amount * fx.eur_rate AS amount_eur
    FROM fact_transaction t
    LEFT JOIN dim_fx_rate fx
           ON fx.rate_date = t.tx_datetime::date      -- T-SQL: CAST(t.tx_datetime AS date)
          AND fx.currency  = t.currency
),
checks AS (
    -- 1. Duplicate keys
    SELECT 1 AS check_no, 'Duplicate check' AS category, 'Duplicated transaction_id' AS check_name,
           (SELECT COUNT(*) - COUNT(DISTINCT transaction_id) FROM fact_transaction) AS failed_rows
    UNION ALL
    SELECT 2, 'Duplicate check', 'Duplicated customer_id',
           (SELECT COUNT(*) - COUNT(DISTINCT customer_id) FROM dim_customer)

    -- 2. Completeness of key fields
    UNION ALL
    SELECT 3, 'Null check', 'Transactions with empty customer_id / amount / tx_datetime / currency',
           (SELECT COUNT(*) FROM fact_transaction
            WHERE customer_id IS NULL OR amount IS NULL OR tx_datetime IS NULL OR currency IS NULL)
    UNION ALL
    SELECT 4, 'Null check', 'Transactions without merchant_id or device_id',
           (SELECT COUNT(*) FROM fact_transaction WHERE merchant_id IS NULL OR device_id IS NULL)
    UNION ALL
    SELECT 5, 'Null check', 'Customers without country, age or signup date',
           (SELECT COUNT(*) FROM dim_customer WHERE country IS NULL OR age IS NULL OR signup_date IS NULL)

    -- 3. Value ranges
    UNION ALL
    SELECT 6, 'Range check', 'Amount <= 0',
           (SELECT COUNT(*) FROM fact_transaction WHERE amount <= 0)
    UNION ALL
    SELECT 7, 'Range check', 'Age outside 18-100',
           (SELECT COUNT(*) FROM dim_customer WHERE age NOT BETWEEN 18 AND 100)
    UNION ALL
    SELECT 8, 'Range check', 'Transactions outside the period 2026-01-01 - 2026-06-30',
           (SELECT COUNT(*) FROM fact_transaction
            WHERE tx_datetime < DATE '2026-01-01' OR tx_datetime >= DATE '2026-07-01')
    UNION ALL
    SELECT 9, 'Range check', 'Transactions without an exchange rate for that day',
           (SELECT COUNT(*) FROM tx_eur WHERE amount_eur IS NULL)

    -- 4. Date consistency
    UNION ALL
    SELECT 10, 'Date consistency', 'Transaction before the customer signup date',
           (SELECT COUNT(*) FROM fact_transaction t
            JOIN dim_customer c USING (customer_id)
            WHERE t.tx_datetime::date < c.signup_date)
    UNION ALL
    SELECT 11, 'Date consistency', 'Transaction outside the device activity window (first_seen - last_seen)',
           (SELECT COUNT(*) FROM fact_transaction t
            JOIN dim_device d USING (device_id)
            WHERE t.tx_datetime NOT BETWEEN d.first_seen AND d.last_seen)
    UNION ALL
    SELECT 12, 'Date consistency', 'Device with first_seen later than last_seen',
           (SELECT COUNT(*) FROM dim_device WHERE first_seen > last_seen)

    -- 5. Referential integrity (orphan records)
    UNION ALL
    SELECT 13, 'Referential integrity', 'Transactions with a non-existent customer',
           (SELECT COUNT(*) FROM fact_transaction t
            WHERE NOT EXISTS (SELECT 1 FROM dim_customer c WHERE c.customer_id = t.customer_id))
    UNION ALL
    SELECT 14, 'Referential integrity', 'Transactions with a non-existent merchant',
           (SELECT COUNT(*) FROM fact_transaction t
            WHERE NOT EXISTS (SELECT 1 FROM dim_merchant m WHERE m.merchant_id = t.merchant_id))
    UNION ALL
    SELECT 15, 'Referential integrity', 'Transactions with a non-existent device',
           (SELECT COUNT(*) FROM fact_transaction t
            WHERE NOT EXISTS (SELECT 1 FROM dim_device d WHERE d.device_id = t.device_id))
    UNION ALL
    SELECT 16, 'Referential integrity', 'Transactions from a device belonging to another customer',
           (SELECT COUNT(*) FROM fact_transaction t
            JOIN dim_device d USING (device_id)
            WHERE d.customer_id <> t.customer_id)

    -- 6. Outliers (not an error, just candidates for further analysis)
    UNION ALL
    SELECT 17, 'Outlier check', 'Transactions above the 99.9th percentile of EUR amount (to review, not to delete)',
           (SELECT COUNT(*) FROM tx_eur
            WHERE amount_eur > (SELECT PERCENTILE_CONT(0.999) WITHIN GROUP (ORDER BY amount_eur) FROM tx_eur))
)
SELECT check_no, category, check_name, failed_rows,
       CASE WHEN failed_rows = 0 THEN 'OK'
            WHEN category = 'Outlier check' THEN 'REVIEW'
            ELSE 'ERROR' END AS status
FROM checks
ORDER BY check_no;


-- ============================================================
-- Part 2. Outliers: transactions many times higher than the customer's typical amount
-- (median of the customer's EUR amounts). Run separately: select only this query.
-- ============================================================
WITH tx_eur AS (
    SELECT t.transaction_id, t.customer_id, t.tx_datetime, t.amount, t.currency, t.is_fraud,
           ROUND(t.amount * fx.eur_rate, 2) AS amount_eur
    FROM fact_transaction t
    JOIN dim_fx_rate fx ON fx.rate_date = t.tx_datetime::date AND fx.currency = t.currency
),
customer_median AS (
    SELECT customer_id,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY amount_eur) AS median_eur,   -- T-SQL: PERCENTILE_CONT(...) OVER (PARTITION BY ...)
           COUNT(*) AS tx_count
    FROM tx_eur
    GROUP BY customer_id
)
SELECT e.transaction_id, e.customer_id, e.tx_datetime, e.amount, e.currency, e.amount_eur,
       ROUND(m.median_eur::numeric, 2)                 AS customer_median_eur,
       ROUND((e.amount_eur / m.median_eur)::numeric, 1) AS times_higher,
       e.is_fraud
FROM tx_eur e
JOIN customer_median m USING (customer_id)
WHERE m.tx_count >= 5                         -- only customers with history
  AND e.amount_eur > 10 * m.median_eur        -- at least 10x more than usual
ORDER BY times_higher DESC
LIMIT 50;                                     -- T-SQL: SELECT TOP 50
