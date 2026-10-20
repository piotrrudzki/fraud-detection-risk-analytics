-- 02_sql_analysis/01_fraud_rate.sql  (PostgreSQL, database fraud_project)
-- Section 8 of the plan: overall fraud rate, per merchant category, per country, fraud amount and loss in EUR.
-- Run each query separately (select it and run).
-- Differences vs T-SQL:
--   COUNT(*) FILTER (WHERE is_fraud)    instead of  SUM(CASE WHEN is_fraud = 1 THEN 1 ELSE 0 END)
--   AVG(is_fraud::int)                  instead of  AVG(CAST(is_fraud AS float))
--   ROUND(x, 2) works on the numeric type, hence the ::numeric casts where needed


-- 1. Overall fraud rate (by count and by amount, in EUR)
SELECT
    COUNT(*)                                                    AS transactions,
    COUNT(*) FILTER (WHERE t.is_fraud)                          AS fraud_transactions,
    ROUND(100.0 * AVG(t.is_fraud::int), 2)                      AS fraud_rate_pct,
    ROUND(SUM(t.amount * fx.eur_rate), 0)                       AS total_eur,
    ROUND(SUM(t.amount * fx.eur_rate) FILTER (WHERE t.is_fraud), 0) AS fraud_loss_eur,
    ROUND(100.0 * SUM(t.amount * fx.eur_rate) FILTER (WHERE t.is_fraud)
                / SUM(t.amount * fx.eur_rate), 2)               AS fraud_rate_by_amount_pct
FROM fact_transaction t
JOIN dim_fx_rate fx ON fx.rate_date = t.tx_datetime::date AND fx.currency = t.currency;


-- 2. Fraud rate per merchant category
SELECT
    m.merchant_category,
    COUNT(*)                                            AS transactions,
    COUNT(*) FILTER (WHERE t.is_fraud)                  AS fraud_transactions,
    ROUND(100.0 * AVG(t.is_fraud::int), 2)              AS fraud_rate_pct,
    COALESCE(ROUND(SUM(t.amount * fx.eur_rate) FILTER (WHERE t.is_fraud), 0), 0) AS fraud_loss_eur   -- T-SQL: ISNULL(...)
FROM fact_transaction t
JOIN dim_merchant m USING (merchant_id)
JOIN dim_fx_rate fx ON fx.rate_date = t.tx_datetime::date AND fx.currency = t.currency
GROUP BY m.merchant_category
ORDER BY fraud_rate_pct DESC;


-- 3. Fraud rate per transaction country (only countries with at least 500 transactions)
SELECT
    t.country,
    COUNT(*)                                            AS transactions,
    COUNT(*) FILTER (WHERE t.is_fraud)                  AS fraud_transactions,
    ROUND(100.0 * AVG(t.is_fraud::int), 2)              AS fraud_rate_pct
FROM fact_transaction t
GROUP BY t.country
HAVING COUNT(*) >= 500
ORDER BY fraud_rate_pct DESC;


-- 4. Transaction in a different country than the customer's: does it increase risk?
SELECT
    CASE WHEN t.country = c.country THEN 'home country' ELSE 'abroad' END AS location,
    COUNT(*)                                            AS transactions,
    COUNT(*) FILTER (WHERE t.is_fraud)                  AS fraud_transactions,
    ROUND(100.0 * AVG(t.is_fraud::int), 2)              AS fraud_rate_pct
FROM fact_transaction t
JOIN dim_customer c USING (customer_id)
GROUP BY 1                                            -- T-SQL: GROUP BY needs the full CASE expression
ORDER BY fraud_rate_pct DESC;
