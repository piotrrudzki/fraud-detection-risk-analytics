-- 02_sql_analysis/03_customer_behaviour.sql  (PostgreSQL, database fraud_project)
-- Section 8 of the plan: top customers, average customer transaction value, number of customer devices.
-- Run each query separately (select it and run).
-- Differences vs T-SQL:
--   LIMIT 20                        instead of  SELECT TOP 20
--   COUNT(DISTINCT ...) FILTER (...) - in T-SQL: COUNT(DISTINCT CASE WHEN ... THEN ... END)
--   BOOL_OR(is_fraud)               - in T-SQL: MAX(CAST(is_fraud AS int)) = 1  ("was there at least one fraud")


-- 1. Top 20 customers by transaction value in EUR
--    (are the biggest customers regular customers or accounts with fraud?)
SELECT
    t.customer_id,
    c.country,
    c.plan,
    COUNT(*)                                            AS transactions,
    ROUND(SUM(t.amount * fx.eur_rate), 0)               AS value_eur,
    ROUND(AVG(t.amount * fx.eur_rate), 2)               AS avg_transaction_eur,
    COUNT(*) FILTER (WHERE t.is_fraud)                  AS fraud_transactions
FROM fact_transaction t
JOIN dim_customer c USING (customer_id)
JOIN dim_fx_rate fx ON fx.rate_date = t.tx_datetime::date AND fx.currency = t.currency
GROUP BY t.customer_id, c.country, c.plan
ORDER BY value_eur DESC
LIMIT 20;


-- 2. Top 20 customers by number of transactions
SELECT
    t.customer_id,
    COUNT(*)                                            AS transactions,
    COUNT(DISTINCT t.tx_datetime::date)                 AS active_days,
    ROUND(COUNT(*)::numeric / COUNT(DISTINCT t.tx_datetime::date), 1) AS tx_per_active_day,
    COUNT(*) FILTER (WHERE t.is_fraud)                  AS fraud_transactions
FROM fact_transaction t
GROUP BY t.customer_id
ORDER BY transactions DESC
LIMIT 20;


-- 3. Average transaction value: customers with fraud vs without fraud
WITH per_customer AS (
    SELECT
        t.customer_id,
        AVG(t.amount * fx.eur_rate)                     AS avg_eur,
        COUNT(*)                                        AS transactions,
        BOOL_OR(t.is_fraud)                             AS had_fraud      -- true if at least one transaction was fraud
    FROM fact_transaction t
    JOIN dim_fx_rate fx ON fx.rate_date = t.tx_datetime::date AND fx.currency = t.currency
    GROUP BY t.customer_id
)
SELECT
    CASE WHEN had_fraud THEN 'customer with fraud' ELSE 'customer without fraud' END AS customer_group,
    COUNT(*)                                            AS customers,
    ROUND(AVG(transactions), 1)                         AS avg_transactions,
    ROUND(AVG(avg_eur), 2)                              AS avg_transaction_eur,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY avg_eur)::numeric, 2) AS median_avg_eur
FROM per_customer
GROUP BY 1;


-- 4. Number of devices used by the customer vs risk
--    (counts devices actually used in transactions, not all devices from dim_device)
WITH per_customer AS (
    SELECT
        customer_id,
        COUNT(DISTINCT device_id)                       AS devices,
        BOOL_OR(is_fraud)                               AS had_fraud
    FROM fact_transaction
    GROUP BY customer_id
)
SELECT
    CASE WHEN devices >= 4 THEN '4+' ELSE devices::text END AS devices_used,
    COUNT(*)                                            AS customers,
    COUNT(*) FILTER (WHERE had_fraud)                   AS customers_with_fraud,
    ROUND(100.0 * AVG(had_fraud::int), 2)               AS pct_customers_with_fraud
FROM per_customer
GROUP BY 1
ORDER BY 1;
